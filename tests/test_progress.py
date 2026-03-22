from __future__ import annotations

import io
import json
import time

from py_sec_edgar.progress import ProgressHeartbeat, progress_enabled, progress_machine_enabled


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


def test_progress_machine_enabled_is_opt_in() -> None:
    assert progress_machine_enabled(progress_json=False) is False
    assert progress_machine_enabled(progress_json=True) is True


def test_progress_heartbeat_emits_periodically_while_blocked() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(enabled=True, phase="test.phase", interval_seconds=0.05, stream=stream):
        time.sleep(0.35)

    output = stream.getvalue()
    assert "progress_start" in output
    assert "progress_heartbeat" in output
    assert "phase=test.phase" in output


def test_machine_progress_is_event_driven_by_default_no_periodic_heartbeat() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(
        enabled=True,
        machine_json=True,
        phase="test.machine",
        interval_seconds=0.05,
        stream=stream,
    ):
        time.sleep(0.25)

    payloads = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert len(payloads) == 2
    assert payloads[0]["event"] == "progress"
    assert payloads[1].get("detail") == "done"


def test_machine_progress_liveness_heartbeat_is_opt_in() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(
        enabled=True,
        machine_json=True,
        phase="test.machine",
        interval_seconds=0.05,
        machine_liveness_seconds=0.06,
        stream=stream,
    ):
        time.sleep(0.25)

    payloads = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert len(payloads) > 2
    assert payloads[-1].get("detail") == "done"


def test_machine_progress_emits_compact_json_lines() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(
        enabled=True,
        machine_json=True,
        phase="test.machine",
        interval_seconds=0.05,
        stream=stream,
    ) as progress:
        progress.set_counters(done=1, total=2)
        progress.emit_event(detail="rows_processed", window_date="2025-01-15", window_index=1, window_total=3)

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    payload = json.loads(lines[0])
    assert payload["event"] == "progress"
    assert payload["phase"] == "test.machine"
    assert "elapsed_seconds" in payload
    assert payload["counters"] == {}

    detailed = [json.loads(line) for line in lines if "rows_processed" in line][0]
    assert detailed["counters"] == {"done": 1, "total": 2}
    assert detailed["detail"] == "rows_processed"
    assert detailed["window_date"] == "2025-01-15"
    assert detailed["window_index"] == 1
    assert detailed["window_total"] == 3


def test_machine_progress_omits_empty_optional_fields() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(
        enabled=True,
        machine_json=True,
        phase="test.machine",
        interval_seconds=0.05,
        stream=stream,
    ) as progress:
        progress.set_counters(done=1)
        progress.emit_event()

    payloads = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert payloads
    for payload in payloads:
        assert "event" in payload
        assert "phase" in payload
        assert "elapsed_seconds" in payload
        assert "counters" in payload

    no_optional = [
        payload
        for payload in payloads
        if "detail" not in payload
        and "window_date" not in payload
        and "window_index" not in payload
        and "window_total" not in payload
    ]
    assert no_optional


def test_progress_disabled_emits_nothing() -> None:
    stream = _TtyBuffer()
    with ProgressHeartbeat(enabled=False, phase="test.phase", interval_seconds=0.05, stream=stream):
        time.sleep(0.05)

    assert stream.getvalue() == ""
