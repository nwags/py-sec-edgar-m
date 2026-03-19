from __future__ import annotations

from py_sec_edgar.runtime_output import (
    bounded_recent_activity,
    render_activity_block,
    render_summary_block,
)


def test_bounded_recent_activity_keeps_last_items() -> None:
    events = [{"item": f"e{i}", "stage": "s", "status": "ok"} for i in range(6)]
    recent = bounded_recent_activity(events, window=3)
    assert [item["item"] for item in recent] == ["e3", "e4", "e5"]


def test_render_summary_block_is_stable() -> None:
    text = render_summary_block("Title", {"a": 1, "b": 2})
    assert "Title" in text
    assert "- a: 1" in text
    assert "- b: 2" in text


def test_render_activity_block_handles_empty_and_non_empty() -> None:
    assert "none" in render_activity_block([])
    text = render_activity_block(
        [{"stage": "download", "status": "success", "item": "x.txt", "detail": "ok"}],
        window=10,
    )
    assert "Recent activity:" in text
    assert "[download] success: x.txt (ok)" in text
