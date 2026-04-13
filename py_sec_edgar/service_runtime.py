from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Callable, Sequence

import uvicorn

from py_sec_edgar.api.app import create_app
from py_sec_edgar.config import AppConfig, load_config
from py_sec_edgar.m_cache_config import load_m_cache_effective_config
from py_sec_edgar.monitoring import run_monitor_poll
from py_sec_edgar.progress import ProgressHeartbeat, progress_enabled, progress_machine_enabled, progress_payload_from_result

try:  # pragma: no cover - Linux path is exercised in tests
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None


_STOP_REQUESTED = False
_LOCK_FILENAME = "monitor_loop.lock"


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _parse_csv_env(name: str) -> list[str] | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or None


def load_runtime_settings() -> dict[str, object]:
    return {
        "api_host": os.getenv("PY_SEC_EDGAR_API_HOST", "0.0.0.0").strip() or "0.0.0.0",
        "api_port": _parse_int_env("PY_SEC_EDGAR_API_PORT", 8000),
        "monitor_interval_seconds": _parse_float_env("PY_SEC_EDGAR_MONITOR_INTERVAL_SECONDS", 30.0),
        "monitor_warm": _parse_bool_env("PY_SEC_EDGAR_MONITOR_WARM", True),
        "monitor_refresh_lookup": _parse_bool_env("PY_SEC_EDGAR_MONITOR_REFRESH_LOOKUP", True),
        "monitor_form_types": _parse_csv_env("PY_SEC_EDGAR_MONITOR_FORM_TYPES"),
        "monitor_form_families": _parse_csv_env("PY_SEC_EDGAR_MONITOR_FORM_FAMILIES"),
        "monitor_execute_extraction": _parse_bool_env("PY_SEC_EDGAR_MONITOR_EXECUTE_EXTRACTION", False),
        "monitor_persist_filing_parties": _parse_bool_env("PY_SEC_EDGAR_MONITOR_PERSIST_FILING_PARTIES", False),
        "monitor_single_instance": _parse_bool_env("PY_SEC_EDGAR_MONITOR_SINGLE_INSTANCE", True),
    }


def _monitor_kwargs(settings: dict[str, object]) -> dict[str, object]:
    return {
        "warm": bool(settings["monitor_warm"]),
        "refresh_lookup": bool(settings["monitor_refresh_lookup"]),
        "form_types": settings["monitor_form_types"],
        "form_families": settings["monitor_form_families"],
        "execute_extraction": bool(settings["monitor_execute_extraction"]),
        "persist_filing_parties": bool(settings["monitor_persist_filing_parties"]),
    }


def _runtime_snapshot(mode: str, config: AppConfig, settings: dict[str, object]) -> dict[str, object]:
    try:
        effective_cfg = load_m_cache_effective_config(project_root=config.project_root)
        effective_cfg_payload = {
            "global": asdict(effective_cfg.global_config),
            "domains": {
                key: {
                    **{
                        "enabled": value.enabled,
                        "cache_root": value.cache_root,
                        "normalized_refdata_root": value.normalized_refdata_root,
                        "lookup_root": value.lookup_root,
                        "default_resolution_mode": value.default_resolution_mode,
                        "runtime": value.runtime,
                    },
                    "providers": {provider_key: asdict(provider_value) for provider_key, provider_value in value.providers.items()},
                }
                for key, value in effective_cfg.domains.items()
            },
            "source_path": effective_cfg.source_path,
        }
    except Exception:
        effective_cfg_payload = None
    return {
        "event": "service_startup",
        "mode": mode,
        "resolved_project_root": str(config.project_root),
        "resolved_download_root": str(config.download_root),
        "resolved_normalized_refdata_root": str(config.normalized_refdata_root),
        "api_host": str(settings["api_host"]),
        "api_port": int(settings["api_port"]),
        "monitor_interval_seconds": float(settings["monitor_interval_seconds"]),
        "monitor_warm": bool(settings["monitor_warm"]),
        "monitor_refresh_lookup": bool(settings["monitor_refresh_lookup"]),
        "monitor_form_types": settings["monitor_form_types"],
        "monitor_form_families": settings["monitor_form_families"],
        "monitor_execute_extraction": bool(settings["monitor_execute_extraction"]),
        "monitor_persist_filing_parties": bool(settings["monitor_persist_filing_parties"]),
        "monitor_single_instance": bool(settings["monitor_single_instance"]),
        "effective_config": effective_cfg_payload,
    }


def _emit_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _monitor_loop_iteration_payload(result: dict[str, object], *, iteration: int) -> dict[str, object]:
    lookup_refresh_performed = bool(result.get("lookup_refresh_performed"))
    return {
        "event": "monitor_iteration_summary",
        "mode": "monitor-loop",
        "iteration": int(iteration),
        "detected_candidate_count": int(result.get("detected_candidate_count", 0)),
        "filtered_candidate_count": int(result.get("filtered_candidate_count", 0)),
        "warm_attempted_count": int(result.get("warm_attempted_count", 0)),
        "warm_succeeded_count": int(result.get("warm_succeeded_count", 0)),
        "warm_failed_count": int(result.get("warm_failed_count", 0)),
        "lookup_refresh_performed": lookup_refresh_performed,
        "lookup_refresh_skipped": not lookup_refresh_performed,
        "lookup_refresh_skipped_reason": result.get("lookup_refresh_skipped_reason"),
        "total_elapsed_seconds": float(result.get("total_elapsed_seconds", 0.0)),
    }


def _monitor_once_summary_payload(result: dict[str, object]) -> dict[str, object]:
    payload = _monitor_loop_iteration_payload(result, iteration=1)
    payload["event"] = "monitor_run_summary"
    payload["mode"] = "monitor-once"
    return payload


def run_api_service(*, settings: dict[str, object] | None = None) -> None:
    runtime = settings or load_runtime_settings()
    config = load_config()
    _emit_json(_runtime_snapshot("api", config, runtime))
    app = create_app(config)
    uvicorn.run(app, host=str(runtime["api_host"]), port=int(runtime["api_port"]))


def run_monitor_once(
    *,
    settings: dict[str, object] | None = None,
    progress_json: bool = False,
    progress_heartbeat_seconds: float = 0.0,
) -> dict[str, object]:
    runtime = settings or load_runtime_settings()
    config = load_config()
    _emit_json(_runtime_snapshot("monitor-once", config, runtime))
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=False),
        phase="service_runtime.monitor_once",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
    )
    with progress:
        result = run_monitor_poll(
            config,
            **_monitor_kwargs(runtime),
            progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
        )
        progress.set_counters(
            **progress_payload_from_result(
                result,
                keys=[
                    "detected_candidate_count",
                    "filtered_candidate_count",
                    "warm_attempted_count",
                    "warm_succeeded_count",
                    "warm_failed_count",
                ],
            )
        )
    _emit_json(_monitor_once_summary_payload(result))
    return result


def _handle_stop_signal(signum, frame) -> None:  # pragma: no cover - signal path is injected in tests
    del signum, frame
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def _monitor_lock_path(config: AppConfig) -> Path:
    return config.project_root / ".sec_runtime" / _LOCK_FILENAME


@contextmanager
def _acquire_monitor_loop_lock(config: AppConfig, *, enabled: bool):
    if not enabled:
        yield None
        return

    if fcntl is None:
        raise RuntimeError("Advisory locking is unavailable on this platform.")

    lock_path = _monitor_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate(0)
        handle.write(str(os.getpid()))
        handle.flush()
        yield lock_path
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _compute_exception_backoff(
    consecutive_failures: int,
    *,
    base_seconds: float = 5.0,
    max_seconds: float = 60.0,
    jitter_fn: Callable[[float], float] | None = None,
) -> float:
    bounded_failures = max(1, int(consecutive_failures))
    backoff_seconds = min(max_seconds, base_seconds * (2 ** (bounded_failures - 1)))
    if jitter_fn is None:
        return float(backoff_seconds)
    return float(max(0.0, min(max_seconds, jitter_fn(float(backoff_seconds)))))


def run_monitor_loop_service(
    *,
    settings: dict[str, object] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop_after_iterations: int | None = None,
    backoff_fn: Callable[[int], float] | None = None,
) -> dict[str, object]:
    global _STOP_REQUESTED
    _STOP_REQUESTED = False

    runtime = settings or load_runtime_settings()
    config = load_config()
    interval = max(0.0, float(runtime["monitor_interval_seconds"]))

    _emit_json(_runtime_snapshot("monitor-loop", config, runtime))

    iterations = 0
    last_result: dict[str, object] | None = None
    consecutive_failures = 0
    lock_path = str(_monitor_lock_path(config))
    compute_backoff = backoff_fn or (lambda failures: _compute_exception_backoff(failures))

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_stop_signal)
    signal.signal(signal.SIGTERM, _handle_stop_signal)

    try:
        with _acquire_monitor_loop_lock(config, enabled=bool(runtime["monitor_single_instance"])):
            _emit_json(
                {
                    "event": "monitor_lock_acquired",
                    "mode": "monitor-loop",
                    "lock_path": lock_path,
                }
            )
            while not _STOP_REQUESTED:
                try:
                    last_result = run_monitor_poll(config, **_monitor_kwargs(runtime))
                    consecutive_failures = 0
                    iterations += 1
                    _emit_json(_monitor_loop_iteration_payload(last_result, iteration=iterations))

                    if stop_after_iterations is not None and iterations >= int(stop_after_iterations):
                        break

                    if interval > 0 and not _STOP_REQUESTED:
                        sleep_fn(interval)
                except Exception as exc:
                    consecutive_failures += 1
                    backoff_seconds = max(0.0, float(compute_backoff(consecutive_failures)))
                    _emit_json(
                        {
                            "event": "monitor_iteration_exception",
                            "mode": "monitor-loop",
                            "iteration": iterations + 1,
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                            "backoff_seconds": backoff_seconds,
                        }
                    )
                    if _STOP_REQUESTED:
                        break
                    sleep_fn(backoff_seconds)
    except BlockingIOError:
        _emit_json(
            {
                "event": "monitor_lock_refused",
                "mode": "monitor-loop",
                "lock_path": lock_path,
                "message": "monitor-loop lock is already held by another process",
            }
        )
        return {
            "status": "lock_refused",
            "iterations": 0,
            "last_result": {},
        }
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)

    return {
        "status": "completed",
        "iterations": iterations,
        "last_result": last_result or {},
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py_sec_edgar.service_runtime",
        description="Portable runtime wrapper for py-sec-edgar API and monitor services.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("api", help="Run FastAPI service.")
    monitor_once = sub.add_parser("monitor-once", help="Run one monitor poll and exit.")
    monitor_once.add_argument("--progress-json", action="store_true", help="Emit machine-readable NDJSON progress events to stderr.")
    monitor_once.add_argument(
        "--progress-heartbeat-seconds",
        type=float,
        default=0.0,
        help="Emit machine liveness heartbeat events to stderr only when idle for this many seconds (0 disables).",
    )
    sub.add_parser("monitor-loop", help="Run continuous monitor loop service.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "api":
        run_api_service()
        return 0
    if args.command == "monitor-once":
        try:
            run_monitor_once(
                progress_json=bool(getattr(args, "progress_json", False)),
                progress_heartbeat_seconds=max(0.0, float(getattr(args, "progress_heartbeat_seconds", 0.0))),
            )
            return 0
        except KeyboardInterrupt:
            print("Interrupted by user.", file=sys.stderr, flush=True)
            return 130
    if args.command == "monitor-loop":
        result = run_monitor_loop_service()
        return 1 if result.get("status") == "lock_refused" else 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
