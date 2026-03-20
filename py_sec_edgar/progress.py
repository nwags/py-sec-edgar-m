from __future__ import annotations

from contextlib import AbstractContextManager
import io
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
    ) -> None:
        self.enabled = bool(enabled)
        self.phase = str(phase)
        self.interval_seconds = max(0.2, float(interval_seconds))
        self.stream = stream or sys.stderr

        self._started_at = time.monotonic()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._counters: dict[str, object] = {}

    def __enter__(self) -> "ProgressHeartbeat":
        if self.enabled:
            self._emit_once(prefix="progress_start")
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

    def stop(self, *, final_status: str = "done") -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 0.5))
            self._thread = None
        self._emit_once(prefix=f"progress_{final_status}")

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
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


def progress_enabled(*, summary_json: bool, stderr: io.TextIOBase | None = None) -> bool:
    if summary_json:
        return False
    stream = stderr or sys.stderr
    is_tty = getattr(stream, "isatty", lambda: False)
    try:
        return bool(is_tty())
    except Exception:
        return False


def progress_payload_from_result(result: Mapping[str, object], *, keys: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key in keys:
        value = result.get(key)
        if value is not None:
            out[key] = value
    return out
