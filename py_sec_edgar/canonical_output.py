from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_canonical_summary(
    *,
    domain: str,
    command_path: list[str],
    started_at: str,
    finished_at: str,
    elapsed_seconds: float,
    counters: dict[str, int | float],
    resolution_mode: str | None = None,
    remote_attempted: bool = False,
    provider_requested: str | None = None,
    provider_used: str | None = None,
    rate_limited: bool = False,
    retry_count: int = 0,
    persisted_locally: bool | None = None,
    deferred: bool | None = None,
    deferred_until: str | None = None,
    defer_reason: str | None = None,
    selection_outcome: str | None = None,
    served_from: str | None = None,
    reason_code: str | None = None,
    provider_skip_reasons: list[dict[str, object]] | None = None,
    rate_limit_state: dict[str, object] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    status: str = "ok",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": str(status),
        "domain": str(domain),
        "command_path": [str(item) for item in command_path],
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": float(round(elapsed_seconds, 3)),
        "resolution_mode": resolution_mode,
        "remote_attempted": bool(remote_attempted),
        "provider_requested": provider_requested,
        "provider_used": provider_used,
        "rate_limited": bool(rate_limited),
        "retry_count": int(retry_count),
        "persisted_locally": persisted_locally,
        "counters": {str(k): v for k, v in counters.items()},
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }
    if deferred is not None:
        payload["deferred"] = bool(deferred)
    if deferred_until is not None:
        payload["deferred_until"] = deferred_until
    if defer_reason is not None:
        payload["defer_reason"] = defer_reason
    if selection_outcome is not None:
        payload["selection_outcome"] = selection_outcome
    if served_from is not None:
        payload["served_from"] = served_from
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if provider_skip_reasons is not None:
        payload["provider_skip_reasons"] = provider_skip_reasons
    if rate_limit_state is not None:
        payload["rate_limit_state"] = rate_limit_state
    return payload


def counters_from_result(
    result: dict[str, object],
    *,
    key_map: dict[str, str],
) -> dict[str, int | float]:
    out: dict[str, int | float] = {}
    for source_key, canonical_key in key_map.items():
        value = result.get(source_key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            out[canonical_key] = value
    return out
