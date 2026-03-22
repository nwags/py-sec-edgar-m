from __future__ import annotations

from contextlib import AbstractContextManager
import io
import json
import sys
import threading
import time
from typing import Mapping


class ProgressHeartbeat(AbstractContextManager["ProgressHeartbeat"]):
    """Threaded stderr heartbeat for long-running operator commands."""

    def __init__(
        self,
        *,
        enabled: bool,
        phase: str,
        interval_seconds: float = 2.0,
        stream: io.TextIOBase | None = None,
        machine_json: bool = False,
        machine_liveness_seconds: float | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.phase = str(phase)
        self.interval_seconds = max(0.2, float(interval_seconds))
        self.stream = stream or sys.stderr
        self.machine_json = bool(machine_json)
        if machine_liveness_seconds is None:
            self.machine_liveness_seconds: float | None = None
        else:
            requested_liveness = float(machine_liveness_seconds)
            self.machine_liveness_seconds = requested_liveness if requested_liveness > 0 else None

        self._started_at = time.monotonic()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._counters: dict[str, object] = {}
        self._detail: str | None = None
        self._window_date: str | None = None
        self._window_index: int | None = None
        self._window_total: int | None = None
        self._last_machine_signature: tuple[object, ...] | None = None
        self._last_machine_emitted_at = self._started_at
        self._last_substantive_event_at = self._started_at

    def __enter__(self) -> "ProgressHeartbeat":
        if self.enabled:
            if self.machine_json:
                self.emit_event()
            else:
                self._emit_once(prefix="progress_start")
            thread_required = (not self.machine_json) or (self.machine_liveness_seconds is not None)
            if thread_required:
                self._thread = threading.Thread(target=self._run, name="progress-heartbeat", daemon=True)
                self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop(final_status="interrupted" if exc_type is KeyboardInterrupt else "done")
        return None

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = str(phase)

    def set_counters(self, **counters: object) -> None:
        with self._lock:
            self._counters = {str(k): v for k, v in counters.items()}

    def set_detail(
        self,
        detail: str | None = None,
        *,
        window_date: str | None = None,
        window_index: int | None = None,
        window_total: int | None = None,
    ) -> None:
        with self._lock:
            self._detail = str(detail) if detail else None
            self._window_date = str(window_date) if window_date else None
            self._window_index = int(window_index) if window_index is not None else None
            self._window_total = int(window_total) if window_total is not None else None

    def emit_event(
        self,
        *,
        phase: str | None = None,
        counters: Mapping[str, object] | None = None,
        detail: str | None = None,
        window_date: str | None = None,
        window_index: int | None = None,
        window_total: int | None = None,
    ) -> None:
        if not self.enabled or not self.machine_json:
            return
        if phase is not None:
            self.set_phase(phase)
        if counters is not None:
            self.set_counters(**{str(k): v for k, v in counters.items()})
        if detail is not None or window_date is not None or window_index is not None or window_total is not None:
            self.set_detail(
                detail,
                window_date=window_date,
                window_index=window_index,
                window_total=window_total,
            )
        self._emit_machine_event(is_substantive=True)

    def stop(self, *, final_status: str = "done") -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 0.5))
            self._thread = None
        if self.machine_json:
            detail = "interrupted" if final_status == "interrupted" else "done"
            self.emit_event(detail=detail)
        else:
            self._emit_once(prefix=f"progress_{final_status}")

    def _run(self) -> None:
        wait_seconds = self.interval_seconds
        if self.machine_json and self.machine_liveness_seconds is not None:
            wait_seconds = min(wait_seconds, self.machine_liveness_seconds)
        while not self._stop_event.wait(wait_seconds):
            if self.machine_json:
                self._emit_machine_event(is_substantive=False)
            else:
                self._emit_once(prefix="progress_heartbeat")

    def _emit_once(self, *, prefix: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            phase = self.phase
            counters = dict(self._counters)
        elapsed = round(time.monotonic() - self._started_at, 1)
        counters_text = " ".join(f"{k}={v}" for k, v in sorted(counters.items()))
        line = f"[{prefix}] phase={phase} elapsed_s={elapsed}"
        if counters_text:
            line = f"{line} {counters_text}"
        print(line, file=self.stream, flush=True)

    def _emit_machine_event(self, *, is_substantive: bool) -> None:
        if not self.enabled:
            return

        now = time.monotonic()
        with self._lock:
            signature = (
                self.phase,
                json.dumps(self._counters, sort_keys=True, default=str),
                self._detail,
                self._window_date,
                self._window_index,
                self._window_total,
            )

            if not is_substantive:
                if self.machine_liveness_seconds is None:
                    return
                if now - self._last_substantive_event_at < self.machine_liveness_seconds:
                    return
                if now - self._last_machine_emitted_at < self.machine_liveness_seconds:
                    return

            if is_substantive and signature == self._last_machine_signature:
                return

            payload: dict[str, object] = {
                "event": "progress",
                "phase": self.phase,
                "elapsed_seconds": round(now - self._started_at, 1),
                "counters": dict(self._counters),
            }
            if self._detail:
                payload["detail"] = self._detail
            if self._window_date:
                payload["window_date"] = self._window_date
            if self._window_index is not None:
                payload["window_index"] = self._window_index
            if self._window_total is not None:
                payload["window_total"] = self._window_total

            self._last_machine_signature = signature
            self._last_machine_emitted_at = now
            if is_substantive:
                self._last_substantive_event_at = now

        print(json.dumps(payload, sort_keys=True), file=self.stream, flush=True)


def progress_enabled(*, summary_json: bool, stderr: io.TextIOBase | None = None) -> bool:
    if summary_json:
        return False
    stream = stderr or sys.stderr
    is_tty = getattr(stream, "isatty", lambda: False)
    try:
        return bool(is_tty())
    except Exception:
        return False


def progress_machine_enabled(*, progress_json: bool) -> bool:
    return bool(progress_json)


def progress_payload_from_result(result: Mapping[str, object], *, keys: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key in keys:
        value = result.get(key)
        if value is not None:
            out[key] = value
    return out
