from __future__ import annotations

from pathlib import Path

import pandas as pd

from py_sec_edgar.augmentation_sidecars import (
    EVENT_FAMILY_LIFECYCLE,
    LIFECYCLE_STATE_ACTIVE,
    augmentation_items_path,
    augmentation_submissions_path,
    current_submission_lifecycle_state,
    list_augmentation_events,
)
from py_sec_edgar.config import AppConfig
from py_sec_edgar.wave4_shared.helpers import (
    build_filing_target_descriptor,
    deterministic_source_text_version,
)
from py_sec_edgar.wave4_shared.packers import build_augmentation_meta_additive


SHARED_AUGMENTATION_TYPE_ENTITY_TAGGING = "entity_tagging"
SHARED_AUGMENTATION_TYPE_TEMPORAL_EXPRESSION_TAGGING = "temporal_expression_tagging"

SHARED_AUGMENTATION_TYPES = (
    SHARED_AUGMENTATION_TYPE_ENTITY_TAGGING,
    SHARED_AUGMENTATION_TYPE_TEMPORAL_EXPRESSION_TAGGING,
)

SHARED_PRODUCER_KIND_HYBRID = "hybrid"
SHARED_STATUS_COMPLETED = "completed"
SHARED_STATUS_SKIPPED = "skipped"


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value)


def augmentation_runs_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_runs.parquet"


def augmentation_events_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_events.parquet"


def map_to_shared_augmentation_type(
    *,
    augmentation_type: str | None,
    layer_type: str | None,
) -> str | None:
    candidate = str(augmentation_type or "").strip().lower()
    if candidate in {"entity_mentions", "entity_links", "entity_tagging"}:
        return SHARED_AUGMENTATION_TYPE_ENTITY_TAGGING
    if candidate in {"temporal_expressions", "temporal_expression_tagging"}:
        return SHARED_AUGMENTATION_TYPE_TEMPORAL_EXPRESSION_TAGGING

    layer = str(layer_type or "").strip().lower()
    if layer == "entities":
        return SHARED_AUGMENTATION_TYPE_ENTITY_TAGGING
    if layer == "temporal":
        return SHARED_AUGMENTATION_TYPE_TEMPORAL_EXPRESSION_TAGGING
    return None


def materialize_shared_augmentation_metadata(config: AppConfig) -> tuple[Path, int, Path, int]:
    config.ensure_runtime_dirs()
    runs_df = _build_runs_df(config)
    events_df = _build_events_df(config)

    runs_out = augmentation_runs_path(config)
    events_out = augmentation_events_path(config)
    runs_out.parent.mkdir(parents=True, exist_ok=True)
    events_out.parent.mkdir(parents=True, exist_ok=True)
    runs_df.to_parquet(runs_out, index=False)
    events_df.to_parquet(events_out, index=False)
    return runs_out, int(len(runs_df.index)), events_out, int(len(events_df.index))


def load_shared_augmentation_runs(config: AppConfig) -> pd.DataFrame:
    out_path = augmentation_runs_path(config)
    if not out_path.exists():
        materialize_shared_augmentation_metadata(config)
    return pd.read_parquet(out_path)


def load_shared_augmentation_events(config: AppConfig) -> pd.DataFrame:
    out_path = augmentation_events_path(config)
    if not out_path.exists():
        materialize_shared_augmentation_metadata(config)
    return pd.read_parquet(out_path)


def list_shared_augmentation_artifacts(
    config: AppConfig,
    *,
    accession_number: str | None = None,
    submission_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    items_path = augmentation_items_path(config)
    submissions_path = augmentation_submissions_path(config)
    if not items_path.exists():
        return []
    items = pd.read_parquet(items_path)
    if items.empty:
        return []
    items = items.copy()
    submissions_by_id: dict[str, dict[str, object]] = {}
    if submissions_path.exists():
        submissions = pd.read_parquet(submissions_path)
        submissions_by_id = {
            str(row.get("submission_id") or ""): row
            for row in submissions.to_dict(orient="records")
        }

    if accession_number:
        items = items[items["accession_number"].astype(str) == str(accession_number)]
    if submission_id:
        items = items[items["submission_id"].astype(str) == str(submission_id)]
    if items.empty:
        return []

    rows: list[dict[str, object]] = []
    for row in items.to_dict(orient="records"):
        submission = submissions_by_id.get(str(row.get("submission_id") or ""), {})
        shared_type = map_to_shared_augmentation_type(
            augmentation_type=str(row.get("augmentation_type") or ""),
            layer_type=str(row.get("layer_type") or ""),
        )
        if shared_type is None:
            continue
        rows.append(
            {
                "domain": "sec",
                "resource_family": "filing",
                "canonical_key": str(row.get("accession_number") or ""),
                "augmentation_type": shared_type,
                "artifact_locator": (
                    f"{augmentation_items_path(config)}"
                    f"#submission_id={row.get('submission_id')}&item_index={row.get('item_index')}"
                ),
                "source_text_version": _clean_text(row.get("source_text_version")),
                "producer_name": str(row.get("producer_id") or ""),
                "producer_version": _clean_text(submission.get("producer_version")),
                "producer_run_id": _clean_text(submission.get("producer_run_id")),
                "pipeline_id": _clean_text(submission.get("pipeline_id")),
                "model_id": _clean_text(submission.get("model_id")),
                "payload_schema_version": _clean_text(row.get("payload_schema_version")),
                "event_at": str(row.get("received_at") or ""),
                "success": True,
                "source_submission_id": str(row.get("submission_id") or ""),
                "item_index": int(row.get("item_index") or 0),
                "augmentation_type_local": str(row.get("augmentation_type") or ""),
            }
        )
    rows = sorted(rows, key=lambda x: (str(x.get("event_at") or ""), str(x.get("source_submission_id") or "")), reverse=True)
    if limit is not None:
        rows = rows[: int(limit)]
    return rows


def build_api_augmentation_meta(config: AppConfig, accession_number: str) -> dict[str, object]:
    source_text_version = deterministic_source_text_version(config, accession_number)
    target_descriptor = build_filing_target_descriptor(config, accession_number)
    items_path = augmentation_items_path(config)
    if not items_path.exists():
        return build_augmentation_meta_additive(
            augmentation_available=False,
            augmentation_types_present=[],
            last_augmented_at=None,
            augmentation_stale=None,
            inspect_path=f"/filings/{accession_number}/augmentations",
            source_text_version=source_text_version,
            target_descriptor=target_descriptor,
        )
    items = pd.read_parquet(items_path)
    if items.empty:
        return build_augmentation_meta_additive(
            augmentation_available=False,
            augmentation_types_present=[],
            last_augmented_at=None,
            augmentation_stale=None,
            inspect_path=f"/filings/{accession_number}/augmentations",
            source_text_version=source_text_version,
            target_descriptor=target_descriptor,
        )
    items = items[items["accession_number"].astype(str) == str(accession_number)]
    if items.empty:
        return build_augmentation_meta_additive(
            augmentation_available=False,
            augmentation_types_present=[],
            last_augmented_at=None,
            augmentation_stale=None,
            inspect_path=f"/filings/{accession_number}/augmentations",
            source_text_version=source_text_version,
            target_descriptor=target_descriptor,
        )

    shared_types: set[str] = set()
    for row in items.to_dict(orient="records"):
        shared = map_to_shared_augmentation_type(
            augmentation_type=str(row.get("augmentation_type") or ""),
            layer_type=str(row.get("layer_type") or ""),
        )
        if shared is not None:
            shared_types.add(shared)
    if not shared_types:
        for local_type in items["augmentation_type"].dropna().astype(str).tolist():
            shared_types.add(f"domain_local:{local_type}")

    latest_row = (
        items.sort_values(["received_at", "submission_id", "item_index"], ascending=[False, True, True], na_position="last")
        .iloc[0]
    )
    last_augmented_at = str(latest_row.get("received_at") or "")
    latest_version_value = str(latest_row.get("source_text_version") or "").strip()
    latest_source_text_version = latest_version_value or None
    augmentation_stale = (
        bool(latest_source_text_version != source_text_version)
        if latest_source_text_version is not None
        else None
    )
    return build_augmentation_meta_additive(
        augmentation_available=True,
        augmentation_types_present=sorted(shared_types),
        last_augmented_at=last_augmented_at or None,
        augmentation_stale=augmentation_stale,
        inspect_path=f"/filings/{accession_number}/augmentations",
        source_text_version=source_text_version,
        target_descriptor=target_descriptor,
    )


def _build_runs_df(config: AppConfig) -> pd.DataFrame:
    items_path = augmentation_items_path(config)
    submissions_path = augmentation_submissions_path(config)
    if not items_path.exists() or not submissions_path.exists():
        return pd.DataFrame(
            columns=[
                "run_id",
                "event_at",
                "domain",
                "resource_family",
                "canonical_key",
                "augmentation_type",
                "source_text_version",
                "producer_kind",
                "producer_name",
                "status",
                "success",
                "reason_code",
                "message",
                "persisted_locally",
                "latency_ms",
                "rate_limited",
                "retry_count",
                "deferred_until",
                "source_submission_id",
                "schema_version",
                "producer_version",
                "producer_run_id",
                "pipeline_id",
                "model_id",
                "payload_schema_version",
                "layer_type",
                "augmentation_type_local",
                "lifecycle_state",
            ]
        )

    items = pd.read_parquet(items_path)
    submissions = pd.read_parquet(submissions_path)
    if items.empty or submissions.empty:
        return _build_runs_df_empty()

    submissions_by_id = {
        str(row.get("submission_id")): row
        for row in submissions.to_dict(orient="records")
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in items.to_dict(orient="records"):
        submission_id = str(row.get("submission_id") or "")
        accession_number = str(row.get("accession_number") or "")
        shared_type = map_to_shared_augmentation_type(
            augmentation_type=str(row.get("augmentation_type") or ""),
            layer_type=str(row.get("layer_type") or ""),
        )
        if not submission_id or not accession_number or shared_type is None:
            continue
        dedupe_key = (submission_id, accession_number, shared_type)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        lifecycle_state = current_submission_lifecycle_state(config, submission_id)
        submission = submissions_by_id.get(submission_id, {})
        lifecycle_is_active = lifecycle_state == LIFECYCLE_STATE_ACTIVE
        rows.append(
            {
                "run_id": f"{submission_id}:{accession_number}:{shared_type}",
                "event_at": str(row.get("received_at") or ""),
                "domain": "sec",
                "resource_family": "filing",
                "canonical_key": accession_number,
                "augmentation_type": shared_type,
                "source_text_version": _clean_text(row.get("source_text_version")) or deterministic_source_text_version(config, accession_number),
                "producer_kind": SHARED_PRODUCER_KIND_HYBRID,
                "producer_name": str(row.get("producer_id") or ""),
                "status": SHARED_STATUS_COMPLETED if lifecycle_is_active else SHARED_STATUS_SKIPPED,
                "success": bool(lifecycle_is_active),
                "reason_code": "ingested" if lifecycle_is_active else f"lifecycle_state_{lifecycle_state}",
                "message": None,
                "persisted_locally": True,
                "latency_ms": None,
                "rate_limited": False,
                "retry_count": 0,
                "deferred_until": None,
                "source_submission_id": submission_id,
                "schema_version": _clean_text(submission.get("schema_version")),
                "producer_version": _clean_text(submission.get("producer_version")),
                "producer_run_id": _clean_text(submission.get("producer_run_id")),
                "pipeline_id": _clean_text(submission.get("pipeline_id")),
                "model_id": _clean_text(submission.get("model_id")),
                "payload_schema_version": _clean_text(row.get("payload_schema_version")),
                "layer_type": str(row.get("layer_type") or ""),
                "augmentation_type_local": str(row.get("augmentation_type") or ""),
                "lifecycle_state": lifecycle_state,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return _build_runs_df_empty()
    return out.sort_values(["event_at", "run_id"], ascending=[False, True], na_position="last").reset_index(drop=True)


def _build_events_df(config: AppConfig) -> pd.DataFrame:
    rows = list_augmentation_events(config, limit=100000)
    out_rows: list[dict[str, object]] = []
    for row_obj in rows:
        row = row_obj if isinstance(row_obj, dict) else vars(row_obj)
        accession_numbers = [str(item) for item in row.get("accession_numbers") or [] if str(item or "").strip()]
        canonical_key = accession_numbers[0] if accession_numbers else None
        shared_type = map_to_shared_augmentation_type(
            augmentation_type=str(row.get("augmentation_type") or ""),
            layer_type=str(row.get("layer_type") or ""),
        )
        if shared_type is None or canonical_key is None:
            continue
        success = True
        if str(row.get("event_family") or "") == EVENT_FAMILY_LIFECYCLE:
            success = str(row.get("to_state") or "") == LIFECYCLE_STATE_ACTIVE
        out_rows.append(
            {
                "run_id": str(row.get("submission_id") or ""),
                "event_at": str(row.get("event_time") or ""),
                "domain": "sec",
                "resource_family": "filing",
                "canonical_key": canonical_key,
                "augmentation_type": shared_type,
                "source_text_version": deterministic_source_text_version(config, canonical_key),
                "producer_kind": SHARED_PRODUCER_KIND_HYBRID,
                "producer_name": str(row.get("producer_id") or ""),
                "status": SHARED_STATUS_COMPLETED if success else SHARED_STATUS_SKIPPED,
                "success": bool(success),
                "reason_code": str(row.get("event_type") or "event_recorded"),
                "message": None,
                "persisted_locally": True,
                "latency_ms": None,
                "rate_limited": False,
                "retry_count": 0,
                "deferred_until": None,
                "event_id": str(row.get("event_id") or ""),
                "event_family": str(row.get("event_family") or ""),
                "event_type": str(row.get("event_type") or ""),
                "event_source": str(row.get("event_source") or ""),
                "source_submission_id": str(row.get("submission_id") or ""),
                "augmentation_type_local": str(row.get("augmentation_type") or ""),
            }
        )
    out = pd.DataFrame(out_rows)
    if out.empty:
        return pd.DataFrame(
            columns=[
                "run_id",
                "event_at",
                "domain",
                "resource_family",
                "canonical_key",
                "augmentation_type",
                "source_text_version",
                "producer_kind",
                "producer_name",
                "status",
                "success",
                "reason_code",
                "message",
                "persisted_locally",
                "latency_ms",
                "rate_limited",
                "retry_count",
                "deferred_until",
                "event_id",
                "event_family",
                "event_type",
                "event_source",
                "source_submission_id",
                "augmentation_type_local",
            ]
        )
    return out.sort_values(["event_at", "event_id"], ascending=[False, True], na_position="last").reset_index(drop=True)


def _build_runs_df_empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "run_id",
            "event_at",
            "domain",
            "resource_family",
            "canonical_key",
            "augmentation_type",
            "source_text_version",
            "producer_kind",
            "producer_name",
            "status",
            "success",
            "reason_code",
            "message",
            "persisted_locally",
            "latency_ms",
            "rate_limited",
            "retry_count",
            "deferred_until",
            "source_submission_id",
            "schema_version",
            "producer_version",
            "producer_run_id",
            "pipeline_id",
            "model_id",
            "payload_schema_version",
            "layer_type",
            "augmentation_type_local",
            "lifecycle_state",
        ]
    )
