from __future__ import annotations

from collections import deque
from typing import Iterable


DEFAULT_ACTIVITY_WINDOW = 10


def bounded_recent_activity(
    events: Iterable[dict],
    *,
    window: int = DEFAULT_ACTIVITY_WINDOW,
) -> list[dict]:
    size = max(1, int(window))
    return list(deque(events, maxlen=size))


def render_summary_block(title: str, metrics: dict[str, object]) -> str:
    lines = [title]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def render_activity_block(events: Iterable[dict], *, window: int = DEFAULT_ACTIVITY_WINDOW) -> str:
    recent = bounded_recent_activity(events, window=window)
    if not recent:
        return "Recent activity:\n- none"

    lines = ["Recent activity:"]
    for event in recent:
        stage = event.get("stage", "unknown")
        status = event.get("status", "info")
        item = event.get("item") or event.get("url") or event.get("filename") or "n/a"
        detail = event.get("detail")
        suffix = f" ({detail})" if detail else ""
        lines.append(f"- [{stage}] {status}: {item}{suffix}")
    return "\n".join(lines)
