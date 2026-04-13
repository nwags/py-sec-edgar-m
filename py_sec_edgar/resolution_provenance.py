from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from py_sec_edgar.config import AppConfig


_MAX_PROVENANCE_ROWS = 200000

RESOLUTION_PROVENANCE_COLUMNS = [
    "event_time",
    "flow",
    "provider_id",
    "accession_number",
    "filename",
    "filing_cik",
    "form_type",
    "filing_date",
    "metadata_surface",
    "content_surface",
    "decision",
    "remote_url",
    "local_path",
    "persisted_locally",
    "status_code",
    "reason",
    "error",
    "error_class",
    "resolution_mode",
    "provider_requested",
    "served_from",
    "remote_attempted",
    "success",
    "retry_count",
    "rate_limited",
    "deferred",
    "deferred_until",
    "selection_outcome",
    "provider_skip_reasons",
    "reason_code",
    "message",
]

RESOLUTION_EVENTS_COLUMNS = [
    "event_at",
    "domain",
    "content_domain",
    "canonical_key",
    "resolution_mode",
    "provider_requested",
    "provider_used",
    "method_used",
    "served_from",
    "remote_attempted",
    "success",
    "reason_code",
    "message",
    "persisted_locally",
    "http_status",
    "retry_count",
    "rate_limited",
    "deferred_until",
    "latency_ms",
    "deferred",
    "selection_outcome",
    "provider_skip_reasons",
]


def filing_resolution_provenance_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "filing_resolution_provenance.parquet"


def resolution_events_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "resolution_events.parquet"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=RESOLUTION_PROVENANCE_COLUMNS)
    df = pd.read_parquet(path)
    for col in RESOLUTION_PROVENANCE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RESOLUTION_PROVENANCE_COLUMNS]


def append_resolution_provenance_events(config: AppConfig, rows: list[dict[str, object]]) -> int:
    path = filing_resolution_provenance_path(config)
    current = _load_or_empty(path)
    if rows:
        current = pd.concat([current, pd.DataFrame(rows)], ignore_index=True)
    if len(current.index) > _MAX_PROVENANCE_ROWS:
        current = current.tail(_MAX_PROVENANCE_ROWS).reset_index(drop=True)
    current.to_parquet(path, index=False)
    _append_resolution_events_compat(config, rows)
    return int(len(current.index))


def _append_resolution_events_compat(config: AppConfig, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    out_rows = [_canonical_resolution_event_from_legacy_row(row) for row in rows]
    path = resolution_events_path(config)
    current = _load_or_empty_with_columns(path, RESOLUTION_EVENTS_COLUMNS)
    current = pd.concat([current, pd.DataFrame(out_rows)], ignore_index=True)
    if len(current.index) > _MAX_PROVENANCE_ROWS:
        current = current.tail(_MAX_PROVENANCE_ROWS).reset_index(drop=True)
    current.to_parquet(path, index=False)


def _load_or_empty_with_columns(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_parquet(path)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _canonical_resolution_event_from_legacy_row(row: dict[str, object]) -> dict[str, object]:
    reason = _as_text(row.get("reason")) or _as_text(row.get("decision")) or "resolution_event"
    decision = _as_text(row.get("decision")) or ""
    remote_url = _as_text(row.get("remote_url"))
    status_code = _as_int(row.get("status_code"))
    success = bool(row.get("persisted_locally")) and "failed" not in decision

    if decision in {"local_hit"}:
        served_from = "local_cache"
    elif decision in {"remote_fetched_and_persisted", "catch_up_succeeded", "warm_succeeded"}:
        served_from = "remote_then_persisted"
    elif remote_url:
        served_from = "none"
    else:
        served_from = "local_normalized"

    remote_attempted = bool(row.get("remote_attempted")) or bool(remote_url) or ("remote" in decision) or ("warm" in decision) or ("catch_up" in decision) or status_code is not None
    message = _as_text(row.get("error")) or _as_text(row.get("reason"))
    canonical_key = _as_text(row.get("accession_number")) or _as_text(row.get("filename")) or "unknown"
    provider = _as_text(row.get("provider_used")) or _as_text(row.get("provider_id"))
    provider_requested = _as_text(row.get("provider_requested")) or provider
    method_used = _as_text(row.get("flow")) or "unknown"
    resolution_mode = _as_text(row.get("resolution_mode")) or ("resolve_if_missing" if remote_attempted else "local_only")
    retry_count = _as_int(row.get("retry_count")) or 0
    rate_limited = _as_bool(row.get("rate_limited"))
    deferred_until = _as_text(row.get("deferred_until"))
    deferred = _as_bool(row.get("deferred")) or (deferred_until is not None)
    selection_outcome = _as_text(row.get("selection_outcome"))
    provider_skip_reasons = _as_json_text(row.get("provider_skip_reasons"))
    served_from = _as_text(row.get("served_from")) or (
        "remote_then_persisted" if bool(row.get("persisted_locally")) and remote_attempted else served_from
    )
    reason_code = _as_text(row.get("reason_code")) or reason

    return {
        "event_at": _as_text(row.get("event_time")) or now_utc_iso(),
        "domain": "sec",
        "content_domain": "filing",
        "canonical_key": canonical_key,
        "resolution_mode": resolution_mode,
        "provider_requested": provider_requested,
        "provider_used": provider,
        "method_used": method_used,
        "served_from": served_from,
        "remote_attempted": bool(remote_attempted),
        "success": bool(success),
        "reason_code": reason_code,
        "message": message,
        "persisted_locally": bool(row.get("persisted_locally")),
        "http_status": status_code,
        "retry_count": retry_count,
        "rate_limited": bool(rate_limited),
        "deferred_until": deferred_until,
        "latency_ms": None,
        "deferred": bool(deferred),
        "selection_outcome": selection_outcome,
        "provider_skip_reasons": provider_skip_reasons,
    }


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _as_text(value)
    if text is None:
        return False
    return text.lower() in {"1", "true", "yes", "y", "on"}


def _as_json_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    try:
        import json

        return json.dumps(value, sort_keys=True)
    except Exception:
        return _as_text(value)
