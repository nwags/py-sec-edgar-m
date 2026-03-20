from __future__ import annotations

import io
import time

from py_sec_edgar.progress import ProgressHeartbeat, progress_enabled


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:  # pragma: no cover - simple shim
        return True


class _NonTtyBuffer(io.StringIO):
    def isatty(self) -> bool:  # pragma: no cover - simple shim
        return False


def test_progress_enabled_respects_summary_json_and_tty() -> None:
    assert progress_enabled(summary_json=True, stderr=_TtyBuffer()) is False
    assert progress_enabled(summary_json=False, stderr=_NonTtyBuffer()) is False
    assert progress_enabled(summary_json=False, stderr=_TtyBuffer()) is True


def test_progress_heartbeat_emits_periodically_while_blocked() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(enabled=True, phase="test.phase", interval_seconds=0.05, stream=stream):
        time.sleep(0.35)

    output = stream.getvalue()
    assert "progress_start" in output
    assert "progress_heartbeat" in output
    assert "phase=test.phase" in output


def test_progress_disabled_emits_nothing() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(enabled=False, phase="test.phase", interval_seconds=0.05, stream=stream):
        time.sleep(0.05)

    assert stream.getvalue() == ""
