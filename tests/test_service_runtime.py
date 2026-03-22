from __future__ import annotations

from contextlib import contextmanager
import time
import signal

from py_sec_edgar.config import AppConfig
import py_sec_edgar.service_runtime as runtime


def _runtime_settings(**overrides):
    settings = {
        "api_host": "0.0.0.0",
        "api_port": 8000,
        "monitor_interval_seconds": 30.0,
        "monitor_warm": True,
        "monitor_refresh_lookup": True,
        "monitor_form_types": None,
        "monitor_form_families": None,
        "monitor_execute_extraction": False,
        "monitor_persist_filing_parties": False,
        "monitor_single_instance": True,
    }
    settings.update(overrides)
    return settings


def test_load_runtime_settings_defaults(monkeypatch):
    for name in [
        "PY_SEC_EDGAR_API_HOST",
        "PY_SEC_EDGAR_API_PORT",
        "PY_SEC_EDGAR_MONITOR_INTERVAL_SECONDS",
        "PY_SEC_EDGAR_MONITOR_WARM",
        "PY_SEC_EDGAR_MONITOR_REFRESH_LOOKUP",
        "PY_SEC_EDGAR_MONITOR_FORM_TYPES",
        "PY_SEC_EDGAR_MONITOR_FORM_FAMILIES",
        "PY_SEC_EDGAR_MONITOR_EXECUTE_EXTRACTION",
        "PY_SEC_EDGAR_MONITOR_PERSIST_FILING_PARTIES",
        "PY_SEC_EDGAR_MONITOR_SINGLE_INSTANCE",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = runtime.load_runtime_settings()
    assert settings["api_host"] == "0.0.0.0"
    assert settings["api_port"] == 8000
    assert settings["monitor_interval_seconds"] == 30.0
    assert settings["monitor_warm"] is True
    assert settings["monitor_refresh_lookup"] is True
    assert settings["monitor_form_types"] is None
    assert settings["monitor_form_families"] is None
    assert settings["monitor_execute_extraction"] is False
    assert settings["monitor_persist_filing_parties"] is False
    assert settings["monitor_single_instance"] is True


def test_load_runtime_settings_overrides(monkeypatch):
    monkeypatch.setenv("PY_SEC_EDGAR_API_HOST", "127.0.0.1")
    monkeypatch.setenv("PY_SEC_EDGAR_API_PORT", "9000")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_WARM", "false")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_REFRESH_LOOKUP", "no")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_FORM_TYPES", "8-K,SC 13D")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_FORM_FAMILIES", "current_reports,beneficial_ownership")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_EXECUTE_EXTRACTION", "true")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_PERSIST_FILING_PARTIES", "1")
    monkeypatch.setenv("PY_SEC_EDGAR_MONITOR_SINGLE_INSTANCE", "false")

    settings = runtime.load_runtime_settings()
    assert settings["api_host"] == "127.0.0.1"
    assert settings["api_port"] == 9000
    assert settings["monitor_interval_seconds"] == 5.0
    assert settings["monitor_warm"] is False
    assert settings["monitor_refresh_lookup"] is False
    assert settings["monitor_form_types"] == ["8-K", "SC 13D"]
    assert settings["monitor_form_families"] == ["current_reports", "beneficial_ownership"]
    assert settings["monitor_execute_extraction"] is True
    assert settings["monitor_persist_filing_parties"] is True
    assert settings["monitor_single_instance"] is False


def test_runtime_snapshot_reflects_project_root_override(monkeypatch, tmp_path):
    project_root = tmp_path / "workspace"
    project_root.mkdir(parents=True)
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(project_root))

    config = runtime.load_config()
    payload = runtime._runtime_snapshot("api", config, _runtime_settings())

    assert payload["resolved_project_root"] == str(project_root.resolve())
    assert payload["resolved_download_root"] == str((project_root / ".sec_cache" / "Archives").resolve())
    assert payload["resolved_normalized_refdata_root"] == str((project_root / "refdata" / "normalized").resolve())


def test_run_api_service_dispatches_create_app_and_uvicorn(monkeypatch, tmp_path):
    config = AppConfig.from_project_root(tmp_path)
    calls = {}
    payloads = []

    monkeypatch.setattr(runtime, "load_config", lambda: config)
    monkeypatch.setattr(runtime, "create_app", lambda cfg: "app-instance")
    monkeypatch.setattr(runtime, "_emit_json", lambda payload: payloads.append(payload))

    def fake_uvicorn_run(app, host, port):
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(runtime.uvicorn, "run", fake_uvicorn_run)
    runtime.run_api_service(settings=_runtime_settings(api_host="127.0.0.1", api_port=8123))

    assert calls == {"app": "app-instance", "host": "127.0.0.1", "port": 8123}
    assert payloads[0]["event"] == "service_startup"
    assert payloads[0]["mode"] == "api"


def test_run_monitor_once_emits_startup_and_summary(monkeypatch, tmp_path):
    config = AppConfig.from_project_root(tmp_path)
    payloads = []

    monkeypatch.setattr(runtime, "load_config", lambda: config)
    monkeypatch.setattr(runtime, "_emit_json", lambda payload: payloads.append(payload))

    def fake_poll(config_arg, **kwargs):
        assert config_arg == config
        assert kwargs["form_types"] == ["8-K"]
        return {
            "detected_candidate_count": 3,
            "filtered_candidate_count": 1,
            "warm_attempted_count": 1,
            "warm_succeeded_count": 1,
            "warm_failed_count": 0,
            "lookup_refresh_performed": True,
            "lookup_refresh_skipped_reason": None,
            "total_elapsed_seconds": 0.25,
        }

    monkeypatch.setattr(runtime, "run_monitor_poll", fake_poll)
    out = runtime.run_monitor_once(
        settings=_runtime_settings(
            monitor_form_types=["8-K"],
            monitor_form_families=["current_reports"],
        )
    )

    assert out["warm_succeeded_count"] == 1
    assert payloads[0]["event"] == "service_startup"
    assert payloads[0]["mode"] == "monitor-once"
    assert payloads[1]["event"] == "monitor_run_summary"
    assert payloads[1]["mode"] == "monitor-once"


def test_run_monitor_loop_dispatches_poll_and_stops(monkeypatch, tmp_path):
    config = AppConfig.from_project_root(tmp_path)
    calls = {"poll_count": 0, "sleep_values": []}
    payloads = []

    monkeypatch.setattr(runtime, "load_config", lambda: config)
    monkeypatch.setattr(runtime, "_emit_json", lambda payload: payloads.append(payload))
    monkeypatch.setattr(runtime.signal, "getsignal", lambda sig: signal.SIG_DFL)
    monkeypatch.setattr(runtime.signal, "signal", lambda sig, handler: None)

    def fake_poll(config_arg, **kwargs):
        assert config_arg == config
        calls["poll_count"] += 1
        return {
            "detected_candidate_count": 2,
            "filtered_candidate_count": 1,
            "warm_attempted_count": 0,
            "warm_succeeded_count": 0,
            "warm_failed_count": 0,
            "lookup_refresh_performed": False,
            "lookup_refresh_skipped_reason": "no_local_visibility_change",
            "total_elapsed_seconds": 0.1,
        }

    monkeypatch.setattr(runtime, "run_monitor_poll", fake_poll)

    def fake_sleep(seconds):
        calls["sleep_values"].append(seconds)

    result = runtime.run_monitor_loop_service(
        settings=_runtime_settings(
            monitor_interval_seconds=0.5,
            monitor_single_instance=False,
        ),
        sleep_fn=fake_sleep,
        stop_after_iterations=2,
    )

    assert result["status"] == "completed"
    assert result["iterations"] == 2
    assert calls["poll_count"] == 2
    assert calls["sleep_values"] == [0.5]
    assert any(p.get("event") == "monitor_iteration_summary" for p in payloads)


def test_monitor_loop_lock_refusal_emits_stable_json(monkeypatch, tmp_path):
    config = AppConfig.from_project_root(tmp_path)
    payloads = []

    monkeypatch.setattr(runtime, "load_config", lambda: config)
    monkeypatch.setattr(runtime, "_emit_json", lambda payload: payloads.append(payload))
    monkeypatch.setattr(runtime.signal, "getsignal", lambda sig: signal.SIG_DFL)
    monkeypatch.setattr(runtime.signal, "signal", lambda sig, handler: None)

    @contextmanager
    def fake_lock(config_arg, enabled: bool):
        assert enabled is True
        raise BlockingIOError("locked")
        yield None

    monkeypatch.setattr(runtime, "_acquire_monitor_loop_lock", fake_lock)

    result = runtime.run_monitor_loop_service(
        settings=_runtime_settings(monitor_single_instance=True),
        stop_after_iterations=1,
    )

    assert result["status"] == "lock_refused"
    refusal = next(payload for payload in payloads if payload.get("event") == "monitor_lock_refused")
    assert refusal["mode"] == "monitor-loop"
    assert refusal["lock_path"].endswith(".sec_runtime/monitor_loop.lock")


def test_exception_backoff_applies_only_on_poll_exceptions(monkeypatch, tmp_path):
    config = AppConfig.from_project_root(tmp_path)
    payloads = []
    sleeps = []
    state = {"calls": 0}

    monkeypatch.setattr(runtime, "load_config", lambda: config)
    monkeypatch.setattr(runtime, "_emit_json", lambda payload: payloads.append(payload))
    monkeypatch.setattr(runtime.signal, "getsignal", lambda sig: signal.SIG_DFL)
    monkeypatch.setattr(runtime.signal, "signal", lambda sig, handler: None)

    def fake_poll(config_arg, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("transient failure")
        return {
            "detected_candidate_count": 1,
            "filtered_candidate_count": 1,
            "warm_attempted_count": 0,
            "warm_succeeded_count": 0,
            "warm_failed_count": 0,
            "lookup_refresh_performed": False,
            "lookup_refresh_skipped_reason": "no_local_visibility_change",
            "total_elapsed_seconds": 0.02,
        }

    monkeypatch.setattr(runtime, "run_monitor_poll", fake_poll)

    result = runtime.run_monitor_loop_service(
        settings=_runtime_settings(
            monitor_interval_seconds=0.0,
            monitor_single_instance=False,
        ),
        sleep_fn=lambda seconds: sleeps.append(seconds),
        stop_after_iterations=1,
        backoff_fn=lambda failures: 7.0,
    )

    assert result["status"] == "completed"
    assert result["iterations"] == 1
    assert sleeps == [7.0]
    assert any(p.get("event") == "monitor_iteration_exception" for p in payloads)


def test_advisory_lock_context_manager_uses_flock_and_releases(monkeypatch, tmp_path):
    config = AppConfig.from_project_root(tmp_path)
    ops = []
    locked_fds = set()

    class FakeFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        @staticmethod
        def flock(fd, mode):
            ops.append((fd, mode))
            if mode == (FakeFcntl.LOCK_EX | FakeFcntl.LOCK_NB):
                if fd in locked_fds:
                    raise BlockingIOError("already locked")
                locked_fds.add(fd)
                return
            if mode == FakeFcntl.LOCK_UN:
                locked_fds.discard(fd)
                return
            raise AssertionError(f"unexpected lock mode: {mode}")

    monkeypatch.setattr(runtime, "fcntl", FakeFcntl)

    with runtime._acquire_monitor_loop_lock(config, enabled=True) as lock_path:
        assert str(lock_path).endswith(".sec_runtime/monitor_loop.lock")
        assert len(locked_fds) == 1

    assert len(locked_fds) == 0
    assert any(mode == (FakeFcntl.LOCK_EX | FakeFcntl.LOCK_NB) for _, mode in ops)
    assert any(mode == FakeFcntl.LOCK_UN for _, mode in ops)


def test_main_dispatches_subcommands(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "run_api_service", lambda: calls.append("api"))
    monkeypatch.setattr(runtime, "run_monitor_once", lambda **kwargs: calls.append(("once", kwargs.get("progress_json", False))))
    monkeypatch.setattr(runtime, "run_monitor_loop_service", lambda: calls.append("loop") or {"status": "completed"})

    assert runtime.main(["api"]) == 0
    assert runtime.main(["monitor-once"]) == 0
    assert runtime.main(["monitor-loop"]) == 0
    assert calls == ["api", ("once", False), "loop"]


def test_main_monitor_once_keyboard_interrupt_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(runtime, "run_monitor_once", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    exit_code = runtime.main(["monitor-once"])
    captured = capsys.readouterr()
    assert exit_code == 130
    assert "Interrupted by user." in captured.err


def test_run_monitor_once_progress_json_emits_stderr_progress(monkeypatch, tmp_path, capsys):
    config = AppConfig.from_project_root(tmp_path)

    monkeypatch.setattr(runtime, "load_config", lambda: config)

    def fake_poll(config_arg, **kwargs):
        return {
            "detected_candidate_count": 3,
            "filtered_candidate_count": 1,
            "warm_attempted_count": 1,
            "warm_succeeded_count": 1,
            "warm_failed_count": 0,
            "lookup_refresh_performed": True,
            "lookup_refresh_skipped_reason": None,
            "total_elapsed_seconds": 0.25,
        }

    monkeypatch.setattr(runtime, "run_monitor_poll", fake_poll)
    out = runtime.run_monitor_once(settings=_runtime_settings(), progress_json=True)
    captured = capsys.readouterr()

    assert out["warm_succeeded_count"] == 1
    stdout_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert stdout_lines
    assert '"event": "service_startup"' in stdout_lines[0]
    assert any('"event": "monitor_run_summary"' in line for line in stdout_lines)

    stderr_lines = [line for line in captured.err.splitlines() if line.strip()]
    assert stderr_lines
    assert len(stderr_lines) == 2
    assert all('"event": "progress"' in line for line in stderr_lines)


def test_main_monitor_once_progress_json_passes_flag(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime, "run_monitor_once", lambda **kwargs: calls.append(kwargs) or {})
    exit_code = runtime.main(["monitor-once", "--progress-json"])

    assert exit_code == 0
    assert calls
    assert calls[0]["progress_json"] is True
    assert calls[0]["progress_heartbeat_seconds"] == 0.0


def test_run_monitor_once_progress_json_heartbeat_is_opt_in(monkeypatch, tmp_path, capsys):
    config = AppConfig.from_project_root(tmp_path)

    monkeypatch.setattr(runtime, "load_config", lambda: config)

    def fake_poll(config_arg, **kwargs):
        time.sleep(0.25)
        return {
            "detected_candidate_count": 3,
            "filtered_candidate_count": 1,
            "warm_attempted_count": 1,
            "warm_succeeded_count": 1,
            "warm_failed_count": 0,
            "lookup_refresh_performed": True,
            "lookup_refresh_skipped_reason": None,
            "total_elapsed_seconds": 0.25,
        }

    monkeypatch.setattr(runtime, "run_monitor_poll", fake_poll)
    out = runtime.run_monitor_once(
        settings=_runtime_settings(),
        progress_json=True,
        progress_heartbeat_seconds=0.05,
    )
    captured = capsys.readouterr()

    assert out["warm_succeeded_count"] == 1
    stderr_lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(stderr_lines) > 2
    assert all('"event": "progress"' in line for line in stderr_lines)


def test_main_monitor_once_progress_heartbeat_seconds_passes_flag(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime, "run_monitor_once", lambda **kwargs: calls.append(kwargs) or {})
    exit_code = runtime.main(["monitor-once", "--progress-json", "--progress-heartbeat-seconds", "1.5"])

    assert exit_code == 0
    assert calls
    assert calls[0]["progress_json"] is True
    assert calls[0]["progress_heartbeat_seconds"] == 1.5
