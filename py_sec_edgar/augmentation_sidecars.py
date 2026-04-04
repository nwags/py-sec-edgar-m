from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.refdata.normalize import normalize_cik
from py_sec_edgar.resolution_provenance import now_utc_iso


class SidecarContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SidecarNotFoundError(LookupError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_MAX_SUBMISSIONS_ROWS = 100000
_MAX_ITEMS_ROWS = 1000000
_MAX_GOVERNANCE_EVENT_ROWS = 1000000
_MAX_LIFECYCLE_EVENT_ROWS = 1000000

AUGMENTATION_FAMILY_CONTRACT_VERSION_ID = "augmentation_family_conventions_v1"

AUGMENTATION_SUBMISSIONS_COLUMNS = [
    "submission_id",
    "received_at",
    "producer_id",
    "layer_type",
    "schema_version",
    "producer_run_id",
    "pipeline_id",
    "model_id",
    "producer_version",
    "item_count",
    "raw_request_path",
]

AUGMENTATION_ITEMS_COLUMNS = [
    "submission_id",
    "item_index",
    "received_at",
    "accession_number",
    "filename",
    "filing_cik",
    "form_type",
    "filing_date",
    "producer_id",
    "layer_type",
    "schema_version",
    "augmentation_type",
    "payload_schema_version",
    "payload_json",
]

AUGMENTATION_GOVERNANCE_EVENT_COLUMNS = [
    "event_time",
    "contract_version_id",
    "submission_id",
    "item_index",
    "accession_number",
    "producer_id",
    "layer_type",
    "augmentation_type",
    "schema_version",
    "family_id",
    "family_inferred",
    "match_status",
    "warning_codes_json",
    "warning_messages_json",
]

AUGMENTATION_SUBMISSION_LIFECYCLE_EVENT_COLUMNS = [
    "event_time",
    "lifecycle_event_id",
    "submission_id",
    "from_state",
    "to_state",
    "reason",
    "changed_by",
    "source",
]

AUGMENTATION_ENTITY_INDEX_COLUMNS = [
    "accession_number",
    "submission_id",
    "producer_id",
    "layer_type",
    "augmentation_type",
    "entity_text",
    "entity_type",
    "entity_id",
    "entity_normalized",
    "received_at",
    "filing_cik",
    "form_type",
    "filing_date",
]

SUBMISSION_METADATA_FIELDS = [
    "producer_run_id",
    "pipeline_id",
    "model_id",
    "producer_version",
    "raw_request_path",
]


@dataclass(frozen=True)
class AugmentationSubmissionPersistResult:
    submission_id: str
    received_at: str
    item_count: int
    submissions_path: str
    items_path: str
    raw_request_path: str


@dataclass(frozen=True)
class ResolvedOverlaySelectionResult:
    selection_policy: str
    selected_submission_keys: list[dict[str, object]]
    augmentations: list[dict[str, object]]


RESOLVED_OVERLAY_SELECTION_POLICY = "latest_per_producer_layer_v1"

LIFECYCLE_STATE_ACTIVE = "active"
LIFECYCLE_STATE_SUPERSEDED = "superseded"
LIFECYCLE_STATE_WITHDRAWN = "withdrawn"
LIFECYCLE_STATE_DISABLED = "disabled"
LIFECYCLE_STATES = {
    LIFECYCLE_STATE_ACTIVE,
    LIFECYCLE_STATE_SUPERSEDED,
    LIFECYCLE_STATE_WITHDRAWN,
    LIFECYCLE_STATE_DISABLED,
}
LIFECYCLE_ELIGIBLE_FOR_OVERLAY = {LIFECYCLE_STATE_ACTIVE}

ALLOWED_LIFECYCLE_TRANSITIONS = {
    LIFECYCLE_STATE_ACTIVE: {
        LIFECYCLE_STATE_SUPERSEDED,
        LIFECYCLE_STATE_WITHDRAWN,
        LIFECYCLE_STATE_DISABLED,
    },
    LIFECYCLE_STATE_SUPERSEDED: {
        LIFECYCLE_STATE_ACTIVE,
        LIFECYCLE_STATE_WITHDRAWN,
        LIFECYCLE_STATE_DISABLED,
    },
    LIFECYCLE_STATE_WITHDRAWN: {
        LIFECYCLE_STATE_ACTIVE,
        LIFECYCLE_STATE_DISABLED,
    },
    LIFECYCLE_STATE_DISABLED: {
        LIFECYCLE_STATE_ACTIVE,
    },
}

SIDECAR_AUGMENTATION_FAMILY_CONVENTIONS = {
    "entity_mentions": {
        "default_layer_type": "entities",
        "default_augmentation_type": "entity_mentions",
        "recommended_payload_keys": ["mentions"],
        "description": "Text span mentions with entity labels and optional confidence.",
    },
    "entity_links": {
        "default_layer_type": "entities",
        "default_augmentation_type": "entity_links",
        "recommended_payload_keys": ["links"],
        "description": "Resolved links from mentions to canonical entities.",
    },
    "temporal_expressions": {
        "default_layer_type": "temporal",
        "default_augmentation_type": "temporal_expressions",
        "recommended_payload_keys": ["expressions"],
        "description": "Normalized temporal mentions and source spans.",
    },
    "event_spans": {
        "default_layer_type": "events",
        "default_augmentation_type": "event_spans",
        "recommended_payload_keys": ["events"],
        "description": "Event trigger/argument spans with labels.",
    },
    "document_labels": {
        "default_layer_type": "labels",
        "default_augmentation_type": "document_labels",
        "recommended_payload_keys": ["labels"],
        "description": "Document-level tags, classes, or scores.",
    },
}

GOV_WARNING_UNKNOWN_FAMILY = "gov_unknown_family"
GOV_WARNING_LAYER_TYPE_MISMATCH = "gov_layer_type_mismatch"
GOV_WARNING_AUGMENTATION_TYPE_MISMATCH = "gov_augmentation_type_mismatch"
GOV_WARNING_MISSING_RECOMMENDED_PAYLOAD_KEYS = "gov_missing_recommended_payload_keys"

_KNOWN_GOV_WARNING_CODES = {
    GOV_WARNING_UNKNOWN_FAMILY,
    GOV_WARNING_LAYER_TYPE_MISMATCH,
    GOV_WARNING_AUGMENTATION_TYPE_MISMATCH,
    GOV_WARNING_MISSING_RECOMMENDED_PAYLOAD_KEYS,
}

SIDE_CAR_ERROR_INVALID_TIMESTAMP = "invalid_timestamp"
SIDE_CAR_ERROR_INVALID_TIME_RANGE = "invalid_time_range"
SIDE_CAR_ERROR_INVALID_MATCH_STATUS = "invalid_match_status"
SIDE_CAR_ERROR_INVALID_EVENT_FAMILY = "invalid_event_family"
SIDE_CAR_ERROR_INVALID_EVENT_TYPE = "invalid_event_type"
SIDE_CAR_ERROR_INVALID_GROUP_BY = "invalid_group_by"
SIDE_CAR_ERROR_INVALID_LIFECYCLE_STATE = "invalid_lifecycle_state"
SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND = "submission_not_found"
SIDE_CAR_ERROR_INVALID_LIFECYCLE_TRANSITION = "invalid_lifecycle_transition"
SIDE_CAR_ERROR_DUPLICATE_LIFECYCLE_STATE = "duplicate_lifecycle_state"

EVENT_FAMILY_GOVERNANCE = "governance"
EVENT_FAMILY_LIFECYCLE = "lifecycle"
EVENT_FAMILIES = {
    EVENT_FAMILY_GOVERNANCE,
    EVENT_FAMILY_LIFECYCLE,
}
EVENT_TYPE_GOVERNANCE_DIAGNOSTIC = "governance_diagnostic"
EVENT_TYPE_SUBMISSION_LIFECYCLE_TRANSITION = "submission_lifecycle_transition"
EVENT_TYPES = {
    EVENT_TYPE_GOVERNANCE_DIAGNOSTIC,
    EVENT_TYPE_SUBMISSION_LIFECYCLE_TRANSITION,
}
EVENT_SOURCE_AUGMENTATION_GOVERNANCE_EVENTS_V1 = "augmentation_governance_events_v1"
EVENT_SOURCE_AUGMENTATION_SUBMISSION_LIFECYCLE_EVENTS_V1 = "augmentation_submission_lifecycle_events_v1"
EVENT_SOURCES = {
    EVENT_SOURCE_AUGMENTATION_GOVERNANCE_EVENTS_V1,
    EVENT_SOURCE_AUGMENTATION_SUBMISSION_LIFECYCLE_EVENTS_V1,
}
EVENT_SUMMARY_GROUP_DIMENSIONS = {
    "event_family",
    "event_type",
    "event_source",
    "producer_id",
    "layer_type",
    "warning_code",
    "match_status",
    "to_state",
}

OVERLAY_IMPACT_REASON_SELECTED = "selected"
OVERLAY_IMPACT_REASON_LIFECYCLE_INELIGIBLE = "lifecycle_ineligible"
OVERLAY_IMPACT_REASON_SUPERSEDED_BY_WINNER = "superseded_by_winner"
OVERLAY_IMPACT_REASON_NO_ELIGIBLE_ROWS = "no_eligible_rows"

_LAYER_TYPE_TO_FAMILY: dict[str, list[str]] = {}
for _family_id, _contract in SIDECAR_AUGMENTATION_FAMILY_CONVENTIONS.items():
    _layer = str(_contract.get("default_layer_type") or "").strip()
    if _layer:
        _LAYER_TYPE_TO_FAMILY.setdefault(_layer, []).append(_family_id)


@dataclass(frozen=True)
class GovernanceEvaluation:
    family_id: str | None
    family_inferred: bool
    match_status: str
    warning_codes: list[str]
    warning_messages: list[str]


@dataclass(frozen=True)
class AugmentationSubmissionSummary:
    submission_id: str
    received_at: str
    producer_id: str
    layer_type: str
    schema_version: str
    producer_run_id: str | None
    pipeline_id: str | None
    model_id: str | None
    producer_version: str | None
    raw_request_path: str | None
    item_count_for_accession: int
    lifecycle_state: str


@dataclass(frozen=True)
class GovernanceEventRow:
    event_time: str
    contract_version_id: str
    submission_id: str
    item_index: int
    accession_number: str
    producer_id: str
    layer_type: str
    augmentation_type: str
    schema_version: str
    family_id: str | None
    family_inferred: bool
    match_status: str
    warning_codes: list[str]
    warning_messages: list[str]


@dataclass(frozen=True)
class GovernanceSummaryRow:
    warning_code: str
    family_id: str | None
    match_status: str
    event_count: int
    submission_count: int
    accession_count: int


@dataclass(frozen=True)
class AugmentationUnifiedEventRow:
    event_family: str
    event_type: str
    event_source: str
    event_time: str
    event_id: str
    submission_id: str
    accession_numbers: list[str]
    producer_id: str | None
    layer_type: str | None
    warning_codes: list[str] | None = None
    match_status: str | None = None
    family_id: str | None = None
    family_inferred: bool | None = None
    augmentation_type: str | None = None
    schema_version: str | None = None
    contract_version_id: str | None = None
    warning_messages: list[str] | None = None
    from_state: str | None = None
    to_state: str | None = None
    reason: str | None = None
    changed_by: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class CrossAccessionSubmissionSummary:
    submission_id: str
    received_at: str
    producer_id: str
    layer_type: str
    schema_version: str
    producer_run_id: str | None
    pipeline_id: str | None
    model_id: str | None
    producer_version: str | None
    raw_request_path: str | None
    item_count_total: int
    accession_count: int
    warning_item_count: int
    lifecycle_state: str


@dataclass(frozen=True)
class SubmissionLifecycleEventRow:
    event_time: str
    lifecycle_event_id: str
    submission_id: str
    from_state: str
    to_state: str
    reason: str | None
    changed_by: str | None
    source: str | None


@dataclass(frozen=True)
class SubmissionOverlayImpactRow:
    accession_number: str
    producer_id: str
    layer_type: str
    submission_id: str
    lifecycle_state: str
    contributes_to_resolved_overlay: bool
    winning_submission_id: str | None
    reason_code: str
    reason_message: str


@dataclass(frozen=True)
class SubmissionEntityImpactRow:
    accession_number: str
    entity_text: str
    entity_normalized: str
    entity_type: str | None
    entity_id: str | None
    filing_cik: str | None
    form_type: str | None
    filing_date: str | None


def augmentation_governance_events_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_governance_events.parquet"


def augmentation_submission_lifecycle_events_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_submission_lifecycle_events.parquet"


def augmentation_entity_index_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_entity_index.parquet"


def _sorted_governance_events(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["event_time", "submission_id", "item_index"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _sorted_lifecycle_events(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["event_time", "submission_id", "lifecycle_event_id"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _parse_filter_timestamp(name: str, value: str | None) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_TIMESTAMP,
            f"{name} must be an RFC3339/ISO-8601 timestamp.",
        )
    return parsed.to_pydatetime().astimezone(UTC)


def _resolve_event_time_filter_bounds(
    *,
    received_at_from: str | None,
    received_at_to: str | None,
    event_time_from: str | None,
    event_time_to: str | None,
) -> tuple[datetime | None, datetime | None]:
    from_value = event_time_from if event_time_from is not None else received_at_from
    to_value = event_time_to if event_time_to is not None else received_at_to
    from_bound = _parse_filter_timestamp("event_time_from", from_value)
    to_bound = _parse_filter_timestamp("event_time_to", to_value)
    if from_bound is not None and to_bound is not None and from_bound > to_bound:
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_TIME_RANGE,
            "event_time_from must be less than or equal to event_time_to.",
        )
    return from_bound, to_bound


def _normalize_received_at(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().astimezone(UTC)


def _apply_received_at_filters(
    df: pd.DataFrame,
    *,
    received_at_from: datetime | None,
    received_at_to: datetime | None,
) -> pd.DataFrame:
    if df.empty:
        return df
    if received_at_from is None and received_at_to is None:
        return df
    normalized = df.copy()
    normalized["_received_at_ts"] = normalized["received_at"].apply(_normalize_received_at)
    if received_at_from is not None:
        normalized = normalized[normalized["_received_at_ts"].notna() & (normalized["_received_at_ts"] >= received_at_from)]
    if received_at_to is not None:
        normalized = normalized[normalized["_received_at_ts"].notna() & (normalized["_received_at_ts"] <= received_at_to)]
    return normalized.drop(columns=["_received_at_ts"], errors="ignore")


def _evaluate_governance_for_item(
    *,
    layer_type: str | None,
    augmentation_type: str | None,
    payload: object,
) -> GovernanceEvaluation:
    layer_value = str(layer_type or "").strip()
    augmentation_value = str(augmentation_type or "").strip()
    family_id: str | None = None
    family_inferred = False

    if augmentation_value in SIDECAR_AUGMENTATION_FAMILY_CONVENTIONS:
        family_id = augmentation_value
    else:
        layer_matches = _LAYER_TYPE_TO_FAMILY.get(layer_value, [])
        if len(layer_matches) == 1:
            family_id = layer_matches[0]
            family_inferred = True

    warning_codes: list[str] = []
    warning_messages: list[str] = []
    if family_id is None:
        warning_codes.append(GOV_WARNING_UNKNOWN_FAMILY)
        warning_messages.append("Unable to classify augmentation family from augmentation_type/layer_type.")
        return GovernanceEvaluation(
            family_id=None,
            family_inferred=False,
            match_status="unknown",
            warning_codes=warning_codes,
            warning_messages=warning_messages,
        )

    contract = SIDECAR_AUGMENTATION_FAMILY_CONVENTIONS[family_id]
    expected_layer = str(contract.get("default_layer_type") or "").strip()
    expected_type = str(contract.get("default_augmentation_type") or "").strip()
    if layer_value != expected_layer:
        warning_codes.append(GOV_WARNING_LAYER_TYPE_MISMATCH)
        warning_messages.append(f"Expected layer_type '{expected_layer}' for family '{family_id}'.")
    if augmentation_value != expected_type:
        warning_codes.append(GOV_WARNING_AUGMENTATION_TYPE_MISMATCH)
        warning_messages.append(f"Expected augmentation_type '{expected_type}' for family '{family_id}'.")

    payload_dict = payload if isinstance(payload, dict) else {}
    recommended_keys = [str(k) for k in contract.get("recommended_payload_keys", []) if str(k).strip()]
    missing = [k for k in recommended_keys if k not in payload_dict]
    if missing:
        warning_codes.append(GOV_WARNING_MISSING_RECOMMENDED_PAYLOAD_KEYS)
        warning_messages.append("Missing recommended payload keys: " + ", ".join(sorted(missing)))

    match_status = "match" if not warning_codes else "warning"
    return GovernanceEvaluation(
        family_id=family_id,
        family_inferred=family_inferred,
        match_status=match_status,
        warning_codes=warning_codes,
        warning_messages=warning_messages,
    )


def _append_governance_events(config: AppConfig, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    out_path = augmentation_governance_events_path(config)
    df = _load_or_empty(out_path, AUGMENTATION_GOVERNANCE_EVENT_COLUMNS)
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    df = _sorted_governance_events(df)
    if len(df.index) > _MAX_GOVERNANCE_EVENT_ROWS:
        df = df.head(_MAX_GOVERNANCE_EVENT_ROWS).reset_index(drop=True)
    df.to_parquet(out_path, index=False)


def _append_lifecycle_events(config: AppConfig, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    out_path = augmentation_submission_lifecycle_events_path(config)
    df = _load_or_empty(out_path, AUGMENTATION_SUBMISSION_LIFECYCLE_EVENT_COLUMNS)
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    df = _sorted_lifecycle_events(df)
    if len(df.index) > _MAX_LIFECYCLE_EVENT_ROWS:
        df = df.head(_MAX_LIFECYCLE_EVENT_ROWS).reset_index(drop=True)
    df.to_parquet(out_path, index=False)


def _serialize_codes(codes: list[str]) -> str:
    deduped = [c for c in dict.fromkeys(codes) if c in _KNOWN_GOV_WARNING_CODES]
    return json.dumps(deduped, sort_keys=False, separators=(",", ":"))


def _serialize_messages(messages: list[str]) -> str:
    deduped = [m for m in dict.fromkeys(messages) if str(m).strip()]
    return json.dumps(deduped, sort_keys=False, separators=(",", ":"))


def _deserialize_list_json(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(x) for x in loaded]


def _submission_exists(config: AppConfig, submission_id: str) -> bool:
    submissions_df = _load_or_empty(augmentation_submissions_path(config), AUGMENTATION_SUBMISSIONS_COLUMNS)
    if submissions_df.empty:
        return False
    out = submissions_df[submissions_df["submission_id"].astype(str) == str(submission_id)]
    return not out.empty


def _current_lifecycle_state_map_for_submissions(
    config: AppConfig,
    submission_ids: list[str] | None = None,
) -> dict[str, str]:
    lifecycle_df = _load_or_empty(
        augmentation_submission_lifecycle_events_path(config),
        AUGMENTATION_SUBMISSION_LIFECYCLE_EVENT_COLUMNS,
    )
    if lifecycle_df.empty:
        return {}
    if submission_ids is not None:
        wanted = {str(x) for x in submission_ids}
        lifecycle_df = lifecycle_df[lifecycle_df["submission_id"].astype(str).isin(wanted)]
    if lifecycle_df.empty:
        return {}
    sorted_df = _sorted_lifecycle_events(lifecycle_df)
    latest = sorted_df.drop_duplicates(subset=["submission_id"], keep="first")
    return {
        str(row.get("submission_id")): str(row.get("to_state") or LIFECYCLE_STATE_ACTIVE)
        for row in latest.to_dict(orient="records")
    }


def current_submission_lifecycle_state(config: AppConfig, submission_id: str) -> str:
    state_map = _current_lifecycle_state_map_for_submissions(config, [submission_id])
    return state_map.get(str(submission_id), LIFECYCLE_STATE_ACTIVE)


def record_submission_lifecycle_transition(
    config: AppConfig,
    *,
    submission_id: str,
    to_state: str,
    reason: str | None = None,
    changed_by: str | None = None,
    source: str | None = None,
) -> dict[str, object]:
    target_state = str(to_state or "").strip().lower()
    if target_state not in LIFECYCLE_STATES:
        allowed = ", ".join(sorted(LIFECYCLE_STATES))
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_LIFECYCLE_STATE,
            f"to_state must be one of: {allowed}.",
        )
    if not _submission_exists(config, submission_id):
        raise SidecarNotFoundError(
            SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND,
            f"Submission {submission_id} was not found.",
        )

    current_state = current_submission_lifecycle_state(config, submission_id)
    if current_state == target_state:
        raise SidecarContractError(
            SIDE_CAR_ERROR_DUPLICATE_LIFECYCLE_STATE,
            f"Submission {submission_id} is already in lifecycle state '{target_state}'.",
        )
    allowed_next = ALLOWED_LIFECYCLE_TRANSITIONS.get(current_state, set())
    if target_state not in allowed_next:
        allowed = ", ".join(sorted(allowed_next))
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_LIFECYCLE_TRANSITION,
            f"Invalid lifecycle transition from '{current_state}' to '{target_state}'. "
            f"Allowed next states: {allowed}."
        )

    event = {
        "event_time": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "lifecycle_event_id": str(uuid4()),
        "submission_id": str(submission_id),
        "from_state": current_state,
        "to_state": target_state,
        "reason": reason,
        "changed_by": changed_by,
        "source": source or "api_admin",
    }
    _append_lifecycle_events(config, [event])
    return event


def _enrich_item_rows_with_submission_metadata(config: AppConfig, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not rows:
        return rows
    submissions_df = _load_or_empty(augmentation_submissions_path(config), AUGMENTATION_SUBMISSIONS_COLUMNS)
    if submissions_df.empty:
        for row in rows:
            for field in SUBMISSION_METADATA_FIELDS:
                row[field] = None
        return rows
    submissions_by_id = {
        str(rec.get("submission_id")): rec
        for rec in submissions_df.to_dict(orient="records")
    }
    for row in rows:
        submission = submissions_by_id.get(str(row.get("submission_id")))
        for field in SUBMISSION_METADATA_FIELDS:
            row[field] = submission.get(field) if submission is not None else None
    return rows


def list_augmentation_submissions_for_accession(
    config: AppConfig,
    *,
    accession_number: str,
    producer_id: str | None = None,
    layer_type: str | None = None,
    schema_version: str | None = None,
    lifecycle_state: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    limit: int | None = None,
) -> list[AugmentationSubmissionSummary]:
    from_bound = _parse_filter_timestamp("received_at_from", received_at_from)
    to_bound = _parse_filter_timestamp("received_at_to", received_at_to)
    if from_bound is not None and to_bound is not None and from_bound > to_bound:
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_TIME_RANGE,
            "received_at_from must be less than or equal to received_at_to.",
        )

    filtered_items = _filtered_items_df(
        config,
        accession_number=accession_number,
        producer_id=producer_id,
        layer_type=layer_type,
        schema_version=schema_version,
        received_at_from=from_bound,
        received_at_to=to_bound,
    )
    if filtered_items.empty:
        return []

    counts = (
        filtered_items.groupby("submission_id", as_index=False)
        .size()
        .rename(columns={"size": "item_count_for_accession"})
    )
    submissions = _load_or_empty(augmentation_submissions_path(config), AUGMENTATION_SUBMISSIONS_COLUMNS)
    merged = counts.merge(submissions, on="submission_id", how="left")
    if schema_version:
        merged = merged[merged["schema_version"].astype(str) == str(schema_version)]
    merged = _apply_received_at_filters(merged, received_at_from=from_bound, received_at_to=to_bound)
    merged = merged.sort_values(["received_at", "submission_id"], ascending=[False, True], na_position="last").reset_index(drop=True)
    if limit is not None:
        merged = merged.head(int(limit)).reset_index(drop=True)
    submission_ids = [str(x) for x in merged["submission_id"].dropna().astype(str).unique().tolist()]
    state_map = _current_lifecycle_state_map_for_submissions(config, submission_ids=submission_ids)
    merged["lifecycle_state"] = merged["submission_id"].astype(str).map(lambda sid: state_map.get(str(sid), LIFECYCLE_STATE_ACTIVE))
    if lifecycle_state:
        state = str(lifecycle_state).strip().lower()
        if state not in LIFECYCLE_STATES:
            allowed = ", ".join(sorted(LIFECYCLE_STATES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_LIFECYCLE_STATE,
                f"lifecycle_state must be one of: {allowed}.",
            )
        merged = merged[merged["lifecycle_state"].astype(str) == state]
    rows: list[AugmentationSubmissionSummary] = []
    for row in merged.to_dict(orient="records"):
        rows.append(
            AugmentationSubmissionSummary(
                submission_id=str(row.get("submission_id") or ""),
                received_at=str(row.get("received_at") or ""),
                producer_id=str(row.get("producer_id") or ""),
                layer_type=str(row.get("layer_type") or ""),
                schema_version=str(row.get("schema_version") or ""),
                producer_run_id=row.get("producer_run_id"),
                pipeline_id=row.get("pipeline_id"),
                model_id=row.get("model_id"),
                producer_version=row.get("producer_version"),
                raw_request_path=row.get("raw_request_path"),
                item_count_for_accession=int(row.get("item_count_for_accession") or 0),
                lifecycle_state=str(row.get("lifecycle_state") or LIFECYCLE_STATE_ACTIVE),
            )
        )
    return rows


def augmentation_submissions_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_submissions.parquet"


def augmentation_items_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_items.parquet"


def augmentation_raw_requests_dir(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "augmentation_raw_requests"


def _load_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_parquet(path)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _sorted_submissions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(["received_at", "submission_id"], ascending=[False, True], na_position="last").reset_index(drop=True)


def _sorted_items(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["accession_number", "received_at", "submission_id", "item_index"],
        ascending=[True, False, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _sorted_entity_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        [
            "accession_number",
            "producer_id",
            "layer_type",
            "received_at",
            "submission_id",
            "entity_normalized",
            "entity_text",
            "entity_id",
        ],
        ascending=[True, True, True, False, True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _write_parquet_atomic(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _payload_to_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _payload_from_json(value: object) -> dict[str, object]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"_raw_payload": text}
    if isinstance(loaded, dict):
        return loaded
    return {"_value": loaded}


def _first_text(value: object, keys: list[str]) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        raw = value.get(key)
        text = str(raw or "").strip()
        if text:
            return text
    return None


def extract_entities_from_payload(payload_json: object, family_id: str) -> list[dict[str, object]]:
    payload = payload_json if isinstance(payload_json, dict) else {}
    family = str(family_id or "").strip()
    if family not in {"entity_mentions", "entity_links"}:
        return []

    if family == "entity_mentions":
        candidates = payload.get("mentions")
        if not isinstance(candidates, list):
            candidates = payload.get("entities")
        if not isinstance(candidates, list):
            return []
    else:
        candidates = payload.get("links")
        if not isinstance(candidates, list):
            candidates = payload.get("entity_links")
        if not isinstance(candidates, list):
            candidates = payload.get("entities")
        if not isinstance(candidates, list):
            return []

    rows: list[dict[str, object]] = []
    for item in candidates:
        try:
            if isinstance(item, str):
                entity_text = item.strip()
                entity_type = None
                entity_id = None
            elif isinstance(item, dict):
                entity_text = (
                    _first_text(item, ["text", "entity_text", "mention_text", "mention", "value", "name"]) or ""
                ).strip()
                entity_type = _first_text(item, ["entity_type", "type", "label"])
                entity_id = _first_text(item, ["entity_id", "id", "identifier", "target_id", "canonical_id", "kb_id"])
            else:
                continue
            if not entity_text:
                continue
            rows.append(
                {
                    "entity_text": entity_text,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "entity_normalized": entity_text.strip().lower(),
                }
            )
        except Exception:
            # Extraction is intentionally tolerant; malformed payload entries are skipped.
            continue
    return rows


def _filtered_items_df(
    config: AppConfig,
    *,
    accession_number: str,
    producer_id: str | None = None,
    layer_type: str | None = None,
    augmentation_type: str | None = None,
    schema_version: str | None = None,
    received_at_from: datetime | None = None,
    received_at_to: datetime | None = None,
    lifecycle_state: str | None = None,
    submission_id: str | None = None,
) -> pd.DataFrame:
    items_path = augmentation_items_path(config)
    items_df = _load_or_empty(items_path, AUGMENTATION_ITEMS_COLUMNS)

    if items_df.empty:
        return items_df

    out = items_df[items_df["accession_number"].astype(str) == str(accession_number)].copy()
    if producer_id:
        out = out[out["producer_id"].astype(str) == str(producer_id)]
    if layer_type:
        out = out[out["layer_type"].astype(str) == str(layer_type)]
    if augmentation_type:
        out = out[out["augmentation_type"].astype(str) == str(augmentation_type)]
    if schema_version:
        out = out[out["schema_version"].astype(str) == str(schema_version)]
    out = _apply_received_at_filters(out, received_at_from=received_at_from, received_at_to=received_at_to)
    if lifecycle_state:
        state = str(lifecycle_state).strip().lower()
        if state not in LIFECYCLE_STATES:
            allowed = ", ".join(sorted(LIFECYCLE_STATES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_LIFECYCLE_STATE,
                f"lifecycle_state must be one of: {allowed}.",
            )
        submission_ids = [str(x) for x in out["submission_id"].dropna().astype(str).unique().tolist()]
        state_map = _current_lifecycle_state_map_for_submissions(config, submission_ids=submission_ids)
        out = out[out["submission_id"].astype(str).map(lambda sid: state_map.get(str(sid), LIFECYCLE_STATE_ACTIVE) == state)]
    if submission_id:
        out = out[out["submission_id"].astype(str) == str(submission_id)]
    return out


def _rows_from_items_df(df: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in df.to_dict(orient="records"):
        rows.append(
            {
                "submission_id": row.get("submission_id"),
                "item_index": int(row.get("item_index") or 0),
                "received_at": row.get("received_at"),
                "accession_number": row.get("accession_number"),
                "filename": row.get("filename"),
                "filing_cik": row.get("filing_cik"),
                "form_type": row.get("form_type"),
                "filing_date": row.get("filing_date"),
                "producer_id": row.get("producer_id"),
                "layer_type": row.get("layer_type"),
                "schema_version": row.get("schema_version"),
                "augmentation_type": row.get("augmentation_type"),
                "payload_schema_version": row.get("payload_schema_version"),
                "payload": _payload_from_json(row.get("payload_json")),
            }
        )
    return rows


def persist_augmentation_submission(
    config: AppConfig,
    *,
    producer_id: str,
    layer_type: str,
    schema_version: str,
    producer_run_id: str | None,
    pipeline_id: str | None,
    model_id: str | None,
    producer_version: str | None,
    items: list[dict[str, object]],
    raw_request: dict[str, object],
) -> AugmentationSubmissionPersistResult:
    config.ensure_runtime_dirs()

    submission_id = str(uuid4())
    received_at = now_utc_iso()
    governance_event_time = now_utc_iso()

    raw_dir = augmentation_raw_requests_dir(config)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{submission_id}.json"
    raw_path.write_text(json.dumps(raw_request, sort_keys=True, indent=2), encoding="utf-8")

    submissions_path = augmentation_submissions_path(config)
    items_path = augmentation_items_path(config)

    submission_row = {
        "submission_id": submission_id,
        "received_at": received_at,
        "producer_id": producer_id,
        "layer_type": layer_type,
        "schema_version": schema_version,
        "producer_run_id": producer_run_id,
        "pipeline_id": pipeline_id,
        "model_id": model_id,
        "producer_version": producer_version,
        "item_count": int(len(items)),
        "raw_request_path": str(raw_path),
    }

    item_rows: list[dict[str, object]] = []
    governance_rows: list[dict[str, object]] = []
    for item_index, item in enumerate(items):
        payload = item.get("payload") or {}
        governance = _evaluate_governance_for_item(
            layer_type=layer_type,
            augmentation_type=item.get("augmentation_type"),
            payload=payload,
        )
        item_rows.append(
            {
                "submission_id": submission_id,
                "item_index": int(item_index),
                "received_at": received_at,
                "accession_number": item.get("accession_number"),
                "filename": item.get("filename"),
                "filing_cik": item.get("filing_cik"),
                "form_type": item.get("form_type"),
                "filing_date": item.get("filing_date"),
                "producer_id": producer_id,
                "layer_type": layer_type,
                "schema_version": schema_version,
                "augmentation_type": item.get("augmentation_type"),
                "payload_schema_version": item.get("payload_schema_version"),
                "payload_json": _payload_to_json(payload),
            }
        )
        governance_rows.append(
            {
                "event_time": governance_event_time,
                "contract_version_id": AUGMENTATION_FAMILY_CONTRACT_VERSION_ID,
                "submission_id": submission_id,
                "item_index": int(item_index),
                "accession_number": item.get("accession_number"),
                "producer_id": producer_id,
                "layer_type": layer_type,
                "augmentation_type": item.get("augmentation_type"),
                "schema_version": schema_version,
                "family_id": governance.family_id,
                "family_inferred": bool(governance.family_inferred),
                "match_status": governance.match_status,
                "warning_codes_json": _serialize_codes(governance.warning_codes),
                "warning_messages_json": _serialize_messages(governance.warning_messages),
            }
        )

    submissions_df = _load_or_empty(submissions_path, AUGMENTATION_SUBMISSIONS_COLUMNS)
    submissions_df = pd.concat([submissions_df, pd.DataFrame([submission_row])], ignore_index=True)
    submissions_df = _sorted_submissions(submissions_df)
    if len(submissions_df.index) > _MAX_SUBMISSIONS_ROWS:
        submissions_df = submissions_df.head(_MAX_SUBMISSIONS_ROWS).reset_index(drop=True)
    submissions_df.to_parquet(submissions_path, index=False)

    items_df = _load_or_empty(items_path, AUGMENTATION_ITEMS_COLUMNS)
    if item_rows:
        items_df = pd.concat([items_df, pd.DataFrame(item_rows)], ignore_index=True)
    items_df = _sorted_items(items_df)
    if len(items_df.index) > _MAX_ITEMS_ROWS:
        items_df = items_df.head(_MAX_ITEMS_ROWS).reset_index(drop=True)
    items_df.to_parquet(items_path, index=False)
    _append_governance_events(config, governance_rows)

    return AugmentationSubmissionPersistResult(
        submission_id=submission_id,
        received_at=received_at,
        item_count=int(len(item_rows)),
        submissions_path=str(submissions_path),
        items_path=str(items_path),
        raw_request_path=str(raw_path),
    )


def list_augmentations_for_accession(
    config: AppConfig,
    *,
    accession_number: str,
    producer_id: str | None = None,
    layer_type: str | None = None,
    augmentation_type: str | None = None,
    schema_version: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    include_submission_metadata: bool = False,
    lifecycle_state: str | None = None,
    submission_id: str | None = None,
    latest_submission_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, object]]:
    from_bound = _parse_filter_timestamp("received_at_from", received_at_from)
    to_bound = _parse_filter_timestamp("received_at_to", received_at_to)
    if from_bound is not None and to_bound is not None and from_bound > to_bound:
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_TIME_RANGE,
            "received_at_from must be less than or equal to received_at_to.",
        )
    out = _filtered_items_df(
        config,
        accession_number=accession_number,
        producer_id=producer_id,
        layer_type=layer_type,
        augmentation_type=augmentation_type,
        schema_version=schema_version,
        received_at_from=from_bound,
        received_at_to=to_bound,
        lifecycle_state=lifecycle_state,
        submission_id=submission_id,
    )
    if out.empty:
        return []

    out = _sorted_items(out)

    if latest_submission_only and not out.empty:
        latest_submission_id = str(out.iloc[0]["submission_id"])
        out = out[out["submission_id"].astype(str) == latest_submission_id]
        out = _sorted_items(out)

    if limit is not None:
        out = out.head(int(limit))
    rows = _rows_from_items_df(out)
    if include_submission_metadata:
        rows = _enrich_item_rows_with_submission_metadata(config, rows)
    return rows


def resolve_overlay_for_accession(
    config: AppConfig,
    *,
    accession_number: str,
    producer_id: str | None = None,
    layer_type: str | None = None,
    augmentation_type: str | None = None,
    schema_version: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    include_submission_metadata: bool = False,
    lifecycle_state: str | None = None,
    limit: int | None = None,
) -> ResolvedOverlaySelectionResult:
    from_bound = _parse_filter_timestamp("received_at_from", received_at_from)
    to_bound = _parse_filter_timestamp("received_at_to", received_at_to)
    if from_bound is not None and to_bound is not None and from_bound > to_bound:
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_TIME_RANGE,
            "received_at_from must be less than or equal to received_at_to.",
        )
    out = _filtered_items_df(
        config,
        accession_number=accession_number,
        producer_id=producer_id,
        layer_type=layer_type,
        augmentation_type=augmentation_type,
        schema_version=schema_version,
        received_at_from=from_bound,
        received_at_to=to_bound,
        lifecycle_state=lifecycle_state,
    )
    # Overlay selection is lifecycle-aware: only active submissions are eligible winners.
    if not out.empty:
        submission_ids = [str(x) for x in out["submission_id"].dropna().astype(str).unique().tolist()]
        state_map = _current_lifecycle_state_map_for_submissions(config, submission_ids=submission_ids)
        out = out[
            out["submission_id"].astype(str).map(
                lambda sid: state_map.get(str(sid), LIFECYCLE_STATE_ACTIVE) in LIFECYCLE_ELIGIBLE_FOR_OVERLAY
            )
        ]
    if out.empty:
        return ResolvedOverlaySelectionResult(
            selection_policy=RESOLVED_OVERLAY_SELECTION_POLICY,
            selected_submission_keys=[],
            augmentations=[],
        )

    unique_submissions = (
        out[["producer_id", "layer_type", "submission_id", "received_at"]]
        .drop_duplicates()
        .sort_values(
            ["producer_id", "layer_type", "received_at", "submission_id"],
            ascending=[True, True, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )
    winners = (
        unique_submissions.groupby(["producer_id", "layer_type"], sort=False, as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    winner_keys = winners[["producer_id", "layer_type", "submission_id"]]

    selected = (
        out.merge(winner_keys, on=["producer_id", "layer_type", "submission_id"], how="inner")
        .sort_values(
            ["producer_id", "layer_type", "received_at", "submission_id", "item_index"],
            ascending=[True, True, False, True, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )
    if limit is not None:
        selected = selected.head(int(limit)).reset_index(drop=True)

    selected_submission_keys = (
        winners.sort_values(
            ["producer_id", "layer_type", "received_at", "submission_id"],
            ascending=[True, True, False, True],
            na_position="last",
        )
        .to_dict(orient="records")
    )
    augmentations = _rows_from_items_df(selected)
    if include_submission_metadata:
        augmentations = _enrich_item_rows_with_submission_metadata(config, augmentations)
    return ResolvedOverlaySelectionResult(
        selection_policy=RESOLVED_OVERLAY_SELECTION_POLICY,
        selected_submission_keys=[
            {
                "producer_id": row.get("producer_id"),
                "layer_type": row.get("layer_type"),
                "submission_id": row.get("submission_id"),
                "received_at": row.get("received_at"),
            }
            for row in selected_submission_keys
        ],
        augmentations=augmentations,
    )


def _resolved_overlay_winner_items_df(config: AppConfig) -> pd.DataFrame:
    items_df = _load_or_empty(augmentation_items_path(config), AUGMENTATION_ITEMS_COLUMNS)
    if items_df.empty:
        return items_df
    submission_ids = [str(x) for x in items_df["submission_id"].dropna().astype(str).unique().tolist()]
    state_map = _current_lifecycle_state_map_for_submissions(config, submission_ids=submission_ids)
    eligible = items_df[
        items_df["submission_id"].astype(str).map(
            lambda sid: state_map.get(str(sid), LIFECYCLE_STATE_ACTIVE) in LIFECYCLE_ELIGIBLE_FOR_OVERLAY
        )
    ]
    if eligible.empty:
        return eligible
    unique_submissions = (
        eligible[["accession_number", "producer_id", "layer_type", "submission_id", "received_at"]]
        .drop_duplicates()
        .sort_values(
            ["accession_number", "producer_id", "layer_type", "received_at", "submission_id"],
            ascending=[True, True, True, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )
    winners = (
        unique_submissions.groupby(["accession_number", "producer_id", "layer_type"], sort=False, as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    winner_keys = winners[["accession_number", "producer_id", "layer_type", "submission_id"]]
    return (
        eligible.merge(winner_keys, on=["accession_number", "producer_id", "layer_type", "submission_id"], how="inner")
        .sort_values(
            ["accession_number", "producer_id", "layer_type", "received_at", "submission_id", "item_index"],
            ascending=[True, True, True, False, True, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )


def build_augmentation_entity_index(config: AppConfig) -> dict[str, object]:
    winners = _resolved_overlay_winner_items_df(config)
    rows: list[dict[str, object]] = []
    for item in winners.to_dict(orient="records"):
        family_id = str(item.get("augmentation_type") or "")
        if family_id not in {"entity_mentions", "entity_links"}:
            continue
        payload = _payload_from_json(item.get("payload_json"))
        for entity in extract_entities_from_payload(payload, family_id):
            rows.append(
                {
                    "accession_number": str(item.get("accession_number") or ""),
                    "submission_id": str(item.get("submission_id") or ""),
                    "producer_id": str(item.get("producer_id") or ""),
                    "layer_type": str(item.get("layer_type") or ""),
                    "augmentation_type": str(item.get("augmentation_type") or ""),
                    "entity_text": entity.get("entity_text"),
                    "entity_type": entity.get("entity_type"),
                    "entity_id": entity.get("entity_id"),
                    "entity_normalized": entity.get("entity_normalized"),
                    "received_at": item.get("received_at"),
                    "filing_cik": item.get("filing_cik"),
                    "form_type": item.get("form_type"),
                    "filing_date": item.get("filing_date"),
                }
            )
    out_df = pd.DataFrame(rows, columns=AUGMENTATION_ENTITY_INDEX_COLUMNS)
    out_df = _sorted_entity_index(out_df)
    out_path = augmentation_entity_index_path(config)
    _write_parquet_atomic(out_path, out_df)
    return {
        "index_path": str(out_path),
        "resolved_overlay_item_count": int(len(winners.index)),
        "entity_row_count": int(len(out_df.index)),
    }


def search_filings_by_entity_index(
    config: AppConfig,
    *,
    entity_text: str | None = None,
    entity_normalized: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    cik: str | None = None,
    form_type: str | None = None,
    filing_date_from: str | None = None,
    filing_date_to: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    path = augmentation_entity_index_path(config)
    if not path.exists():
        build_augmentation_entity_index(config)
    df = _load_or_empty(path, AUGMENTATION_ENTITY_INDEX_COLUMNS)
    if df.empty:
        return []

    out = df.copy()
    if entity_normalized:
        needle = str(entity_normalized).strip().lower()
        out = out[out["entity_normalized"].astype(str) == needle]
    if entity_text:
        needle = str(entity_text).strip().lower()
        out = out[out["entity_normalized"].astype(str).str.contains(needle, regex=False)]
    if entity_type:
        out = out[out["entity_type"].astype(str) == str(entity_type)]
    if entity_id:
        out = out[out["entity_id"].astype(str) == str(entity_id)]
    if cik:
        normalized_cik = normalize_cik(cik)
        if normalized_cik is None:
            raise ValueError("cik must be a valid CIK value.")
        out["filing_cik"] = out["filing_cik"].map(normalize_cik)
        out = out[out["filing_cik"] == normalized_cik]
    if form_type:
        out = out[out["form_type"].astype(str).str.upper() == str(form_type).strip().upper()]

    filing_dates = pd.to_datetime(out["filing_date"], errors="coerce")
    if filing_date_from is not None:
        from_ts = pd.to_datetime(str(filing_date_from).strip(), errors="coerce")
        if pd.isna(from_ts):
            raise ValueError("filing_date_from must be a valid date.")
        out = out[filing_dates >= from_ts]
        filing_dates = pd.to_datetime(out["filing_date"], errors="coerce")
    if filing_date_to is not None:
        to_ts = pd.to_datetime(str(filing_date_to).strip(), errors="coerce")
        if pd.isna(to_ts):
            raise ValueError("filing_date_to must be a valid date.")
        out = out[filing_dates <= to_ts]
    if out.empty:
        return []

    grouped = (
        out.groupby(["accession_number", "filing_cik", "form_type", "filing_date"], dropna=False, as_index=False)
        .size()
        .rename(columns={"size": "entity_match_count"})
    )
    grouped["_filing_date_sort"] = pd.to_datetime(grouped["filing_date"], errors="coerce")
    grouped = grouped.sort_values(
        ["_filing_date_sort", "accession_number"],
        ascending=[False, True],
        na_position="last",
    ).drop(columns=["_filing_date_sort"])
    if limit is not None:
        grouped = grouped.head(int(limit)).reset_index(drop=True)
    return grouped.to_dict(orient="records")


def _sorted_deduped_accession_numbers(values: list[object]) -> list[str]:
    normalized = [str(value).strip() for value in values if str(value or "").strip()]
    return sorted(set(normalized))


def _governance_event_id_from_row(row: dict[str, object]) -> str:
    fields = [
        str(row.get("event_time") or ""),
        str(row.get("submission_id") or ""),
        str(int(row.get("item_index") or 0)),
        str(row.get("accession_number") or ""),
        str(row.get("producer_id") or ""),
        str(row.get("layer_type") or ""),
        str(row.get("augmentation_type") or ""),
        str(row.get("schema_version") or ""),
        str(row.get("contract_version_id") or ""),
    ]
    return "|".join(fields)


def _event_sort_timestamp_value(event_time: str) -> int:
    ts = pd.to_datetime(str(event_time or "").strip(), utc=True, errors="coerce")
    if pd.isna(ts):
        return 0
    return int(ts.value)


def _sorted_unified_events(rows: list[AugmentationUnifiedEventRow]) -> list[AugmentationUnifiedEventRow]:
    return sorted(
        rows,
        key=lambda row: (
            -_event_sort_timestamp_value(row.event_time),
            str(row.event_family),
            str(row.event_id),
        ),
    )


def _submission_accession_map(config: AppConfig) -> dict[str, list[str]]:
    items_df = _load_or_empty(augmentation_items_path(config), AUGMENTATION_ITEMS_COLUMNS)
    if items_df.empty:
        return {}
    by_submission: dict[str, list[str]] = {}
    for submission_id, frame in items_df.groupby("submission_id", sort=False):
        by_submission[str(submission_id)] = _sorted_deduped_accession_numbers(
            frame["accession_number"].tolist()
        )
    return by_submission


def _submission_producer_layer_map(config: AppConfig) -> dict[str, tuple[str | None, str | None]]:
    items_df = _load_or_empty(augmentation_items_path(config), AUGMENTATION_ITEMS_COLUMNS)
    if items_df.empty:
        return {}
    out: dict[str, tuple[str | None, str | None]] = {}
    first_rows = (
        items_df[["submission_id", "producer_id", "layer_type"]]
        .drop_duplicates(subset=["submission_id"], keep="first")
        .reset_index(drop=True)
    )
    for row in first_rows.to_dict(orient="records"):
        out[str(row.get("submission_id") or "")] = (
            None if pd.isna(row.get("producer_id")) else str(row.get("producer_id") or ""),
            None if pd.isna(row.get("layer_type")) else str(row.get("layer_type") or ""),
        )
    return out


def _validate_event_filters(
    *,
    event_family: str | None,
    event_type: str | None,
    event_source: str | None,
    match_status: str | None,
) -> None:
    if event_family is not None:
        family = str(event_family).strip()
        if family not in EVENT_FAMILIES:
            allowed = ", ".join(sorted(EVENT_FAMILIES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_EVENT_FAMILY,
                f"event_family must be one of: {allowed}.",
            )
    if event_type is not None:
        ev_type = str(event_type).strip()
        if ev_type not in EVENT_TYPES:
            allowed = ", ".join(sorted(EVENT_TYPES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_EVENT_TYPE,
                f"event_type must be one of: {allowed}.",
            )
    if event_source is not None:
        source = str(event_source).strip()
        if source not in EVENT_SOURCES:
            allowed = ", ".join(sorted(EVENT_SOURCES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_EVENT_TYPE,
                f"event_source must be one of: {allowed}.",
            )
    if match_status is not None and str(match_status).strip() not in {"match", "warning", "unknown"}:
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_MATCH_STATUS,
            "match_status must be one of: match, warning, unknown.",
        )


def list_augmentation_events(
    config: AppConfig,
    *,
    accession_numbers: list[str] | None = None,
    submission_id: str | None = None,
    producer_id: str | None = None,
    layer_type: str | None = None,
    event_family: str | None = None,
    event_type: str | None = None,
    event_source: str | None = None,
    warning_code: str | None = None,
    match_status: str | None = None,
    to_state: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    event_time_from: str | None = None,
    event_time_to: str | None = None,
    limit: int | None = None,
) -> list[AugmentationUnifiedEventRow]:
    _validate_event_filters(
        event_family=event_family,
        event_type=event_type,
        event_source=event_source,
        match_status=match_status,
    )
    if to_state is not None:
        normalized_to_state = str(to_state).strip().lower()
        if normalized_to_state not in LIFECYCLE_STATES:
            allowed = ", ".join(sorted(LIFECYCLE_STATES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_LIFECYCLE_STATE,
                f"to_state must be one of: {allowed}.",
            )
    else:
        normalized_to_state = None

    if submission_id is not None and not _submission_exists(config, submission_id):
        raise SidecarNotFoundError(
            SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND,
            f"Submission {submission_id} was not found.",
        )

    from_bound, to_bound = _resolve_event_time_filter_bounds(
        received_at_from=received_at_from,
        received_at_to=received_at_to,
        event_time_from=event_time_from,
        event_time_to=event_time_to,
    )
    accession_filter = {str(value) for value in accession_numbers or [] if str(value).strip()}

    submission_accessions = _submission_accession_map(config)
    submission_producer_layer = _submission_producer_layer_map(config)
    unified_rows: list[AugmentationUnifiedEventRow] = []

    governance_df = _load_or_empty(augmentation_governance_events_path(config), AUGMENTATION_GOVERNANCE_EVENT_COLUMNS)
    for row in governance_df.to_dict(orient="records"):
        event_accessions = _sorted_deduped_accession_numbers([row.get("accession_number")])
        submission_value = str(row.get("submission_id") or "")
        producer_value = None if pd.isna(row.get("producer_id")) else str(row.get("producer_id") or "")
        layer_value = None if pd.isna(row.get("layer_type")) else str(row.get("layer_type") or "")
        unified_rows.append(
            AugmentationUnifiedEventRow(
                event_family=EVENT_FAMILY_GOVERNANCE,
                event_type=EVENT_TYPE_GOVERNANCE_DIAGNOSTIC,
                event_source=EVENT_SOURCE_AUGMENTATION_GOVERNANCE_EVENTS_V1,
                event_time=str(row.get("event_time") or ""),
                event_id=_governance_event_id_from_row(row),
                submission_id=submission_value,
                accession_numbers=event_accessions,
                producer_id=producer_value,
                layer_type=layer_value,
                warning_codes=_deserialize_list_json(row.get("warning_codes_json")),
                match_status=str(row.get("match_status") or ""),
                family_id=None if pd.isna(row.get("family_id")) else row.get("family_id"),
                family_inferred=bool(row.get("family_inferred")),
                augmentation_type=str(row.get("augmentation_type") or ""),
                schema_version=str(row.get("schema_version") or ""),
                contract_version_id=str(row.get("contract_version_id") or ""),
                warning_messages=_deserialize_list_json(row.get("warning_messages_json")),
            )
        )

    lifecycle_df = _load_or_empty(
        augmentation_submission_lifecycle_events_path(config),
        AUGMENTATION_SUBMISSION_LIFECYCLE_EVENT_COLUMNS,
    )
    for row in lifecycle_df.to_dict(orient="records"):
        submission_value = str(row.get("submission_id") or "")
        producer_value, layer_value = submission_producer_layer.get(submission_value, (None, None))
        unified_rows.append(
            AugmentationUnifiedEventRow(
                event_family=EVENT_FAMILY_LIFECYCLE,
                event_type=EVENT_TYPE_SUBMISSION_LIFECYCLE_TRANSITION,
                event_source=EVENT_SOURCE_AUGMENTATION_SUBMISSION_LIFECYCLE_EVENTS_V1,
                event_time=str(row.get("event_time") or ""),
                event_id=str(row.get("lifecycle_event_id") or ""),
                submission_id=submission_value,
                accession_numbers=submission_accessions.get(submission_value, []),
                producer_id=producer_value,
                layer_type=layer_value,
                from_state=str(row.get("from_state") or ""),
                to_state=str(row.get("to_state") or ""),
                reason=None if pd.isna(row.get("reason")) else row.get("reason"),
                changed_by=None if pd.isna(row.get("changed_by")) else row.get("changed_by"),
                source=None if pd.isna(row.get("source")) else row.get("source"),
            )
        )

    filtered: list[AugmentationUnifiedEventRow] = []
    for row in unified_rows:
        if accession_filter and not set(row.accession_numbers).intersection(accession_filter):
            continue
        if submission_id is not None and row.submission_id != str(submission_id):
            continue
        if producer_id is not None and str(row.producer_id or "") != str(producer_id):
            continue
        if layer_type is not None and str(row.layer_type or "") != str(layer_type):
            continue
        if event_family is not None and row.event_family != str(event_family):
            continue
        if event_type is not None and row.event_type != str(event_type):
            continue
        if event_source is not None and row.event_source != str(event_source):
            continue
        if warning_code is not None:
            if row.warning_codes is None or str(warning_code) not in row.warning_codes:
                continue
        if match_status is not None and row.match_status != str(match_status):
            continue
        if normalized_to_state is not None and str(row.to_state or "") != normalized_to_state:
            continue
        event_ts = _parse_filter_timestamp("event_time", row.event_time)
        if from_bound is not None and (event_ts is None or event_ts < from_bound):
            continue
        if to_bound is not None and (event_ts is None or event_ts > to_bound):
            continue
        filtered.append(row)

    filtered = _sorted_unified_events(filtered)
    if limit is not None:
        filtered = filtered[: int(limit)]
    return filtered


def summarize_augmentation_events(
    config: AppConfig,
    *,
    accession_numbers: list[str] | None = None,
    submission_id: str | None = None,
    producer_id: str | None = None,
    layer_type: str | None = None,
    event_family: str | None = None,
    event_type: str | None = None,
    event_source: str | None = None,
    warning_code: str | None = None,
    match_status: str | None = None,
    to_state: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    event_time_from: str | None = None,
    event_time_to: str | None = None,
    group_by: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    dimensions = group_by or ["event_family", "event_type"]
    invalid = [value for value in dimensions if str(value) not in EVENT_SUMMARY_GROUP_DIMENSIONS]
    if invalid:
        allowed = ", ".join(sorted(EVENT_SUMMARY_GROUP_DIMENSIONS))
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_GROUP_BY,
            f"group_by must be one of: {allowed}.",
        )

    events = list_augmentation_events(
        config,
        accession_numbers=accession_numbers,
        submission_id=submission_id,
        producer_id=producer_id,
        layer_type=layer_type,
        event_family=event_family,
        event_type=event_type,
        event_source=event_source,
        warning_code=warning_code,
        match_status=match_status,
        to_state=to_state,
        received_at_from=received_at_from,
        received_at_to=received_at_to,
        event_time_from=event_time_from,
        event_time_to=event_time_to,
        limit=None,
    )
    if not events:
        return []

    aggregates: dict[tuple[object, ...], dict[str, object]] = {}
    for event in events:
        dimension_rows: list[dict[str, object]] = [{}]
        for dim in dimensions:
            dim_name = str(dim)
            if dim_name == "warning_code":
                values = event.warning_codes or [None]
            elif dim_name == "match_status":
                values = [event.match_status]
            elif dim_name == "to_state":
                values = [event.to_state]
            else:
                values = [getattr(event, dim_name)]
            next_rows: list[dict[str, object]] = []
            for base in dimension_rows:
                for value in values:
                    merged = dict(base)
                    merged[dim_name] = value
                    next_rows.append(merged)
            dimension_rows = next_rows

        for dimension_values in dimension_rows:
            key = tuple(dimension_values.get(str(dim)) for dim in dimensions)
            if key not in aggregates:
                aggregates[key] = {
                    "dimensions": dimension_values,
                    "event_ids": set(),
                    "submission_ids": set(),
                    "accession_numbers": set(),
                }
            agg = aggregates[key]
            agg["event_ids"].add(event.event_id)
            agg["submission_ids"].add(event.submission_id)
            agg["accession_numbers"].update(event.accession_numbers)

    sorted_keys = sorted(
        aggregates.keys(),
        key=lambda key: tuple(
            (value is None, "" if value is None else str(value))
            for value in key
        ),
    )
    rows: list[dict[str, object]] = []
    for key in sorted_keys:
        agg = aggregates[key]
        row = {str(dim): agg["dimensions"].get(str(dim)) for dim in dimensions}
        row["event_count"] = int(len(agg["event_ids"]))
        row["submission_count"] = int(len(agg["submission_ids"]))
        row["accession_count"] = int(len(agg["accession_numbers"]))
        rows.append(row)
    if limit is not None:
        rows = rows[: int(limit)]
    return rows


def list_governance_events(
    config: AppConfig,
    *,
    accession_number: str | None = None,
    submission_id: str | None = None,
    producer_id: str | None = None,
    layer_type: str | None = None,
    warning_code: str | None = None,
    family_id: str | None = None,
    match_status: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    event_time_from: str | None = None,
    event_time_to: str | None = None,
    limit: int | None = None,
) -> list[GovernanceEventRow]:
    from_bound, to_bound = _resolve_event_time_filter_bounds(
        received_at_from=received_at_from,
        received_at_to=received_at_to,
        event_time_from=event_time_from,
        event_time_to=event_time_to,
    )

    df = _load_or_empty(augmentation_governance_events_path(config), AUGMENTATION_GOVERNANCE_EVENT_COLUMNS)
    if df.empty:
        return []
    if accession_number:
        df = df[df["accession_number"].astype(str) == str(accession_number)]
    if submission_id:
        df = df[df["submission_id"].astype(str) == str(submission_id)]
    if producer_id:
        df = df[df["producer_id"].astype(str) == str(producer_id)]
    if layer_type:
        df = df[df["layer_type"].astype(str) == str(layer_type)]
    if family_id:
        df = df[df["family_id"].astype(str) == str(family_id)]
    if match_status:
        valid = {"match", "warning", "unknown"}
        if str(match_status) not in valid:
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_MATCH_STATUS,
                "match_status must be one of: match, warning, unknown.",
            )
        df = df[df["match_status"].astype(str) == str(match_status)]
    if warning_code:
        code = str(warning_code)
        df = df[
            df["warning_codes_json"].apply(lambda v: code in _deserialize_list_json(v))
        ]
    df = _apply_received_at_filters(df.rename(columns={"event_time": "received_at"}), received_at_from=from_bound, received_at_to=to_bound)
    df = df.rename(columns={"received_at": "event_time"})
    df = _sorted_governance_events(df)
    if limit is not None:
        df = df.head(int(limit)).reset_index(drop=True)

    rows: list[GovernanceEventRow] = []
    for row in df.to_dict(orient="records"):
        rows.append(
            GovernanceEventRow(
                event_time=str(row.get("event_time") or ""),
                contract_version_id=str(row.get("contract_version_id") or ""),
                submission_id=str(row.get("submission_id") or ""),
                item_index=int(row.get("item_index") or 0),
                accession_number=str(row.get("accession_number") or ""),
                producer_id=str(row.get("producer_id") or ""),
                layer_type=str(row.get("layer_type") or ""),
                augmentation_type=str(row.get("augmentation_type") or ""),
                schema_version=str(row.get("schema_version") or ""),
                family_id=None if pd.isna(row.get("family_id")) else row.get("family_id"),
                family_inferred=bool(row.get("family_inferred")),
                match_status=str(row.get("match_status") or ""),
                warning_codes=_deserialize_list_json(row.get("warning_codes_json")),
                warning_messages=_deserialize_list_json(row.get("warning_messages_json")),
            )
        )
    return rows


def summarize_governance_events(
    config: AppConfig,
    *,
    accession_number: str | None = None,
    submission_id: str | None = None,
    producer_id: str | None = None,
    layer_type: str | None = None,
    warning_code: str | None = None,
    family_id: str | None = None,
    match_status: str | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    event_time_from: str | None = None,
    event_time_to: str | None = None,
    limit: int | None = None,
) -> list[GovernanceSummaryRow]:
    from_bound, to_bound = _resolve_event_time_filter_bounds(
        received_at_from=received_at_from,
        received_at_to=received_at_to,
        event_time_from=event_time_from,
        event_time_to=event_time_to,
    )

    df = _load_or_empty(augmentation_governance_events_path(config), AUGMENTATION_GOVERNANCE_EVENT_COLUMNS)
    if df.empty:
        return []
    if accession_number:
        df = df[df["accession_number"].astype(str) == str(accession_number)]
    if submission_id:
        df = df[df["submission_id"].astype(str) == str(submission_id)]
    if producer_id:
        df = df[df["producer_id"].astype(str) == str(producer_id)]
    if layer_type:
        df = df[df["layer_type"].astype(str) == str(layer_type)]
    if family_id:
        df = df[df["family_id"].astype(str) == str(family_id)]
    if match_status:
        valid = {"match", "warning", "unknown"}
        if str(match_status) not in valid:
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_MATCH_STATUS,
                "match_status must be one of: match, warning, unknown.",
            )
        df = df[df["match_status"].astype(str) == str(match_status)]
    if warning_code:
        code = str(warning_code)
        df = df[df["warning_codes_json"].apply(lambda v: code in _deserialize_list_json(v))]

    df = _apply_received_at_filters(
        df.rename(columns={"event_time": "received_at"}),
        received_at_from=from_bound,
        received_at_to=to_bound,
    ).rename(columns={"received_at": "event_time"})
    if df.empty:
        return []

    summary_rows: list[dict[str, object]] = []
    for row in df.to_dict(orient="records"):
        codes = _deserialize_list_json(row.get("warning_codes_json"))
        if not codes:
            codes = [""]
        for code in codes:
            summary_rows.append(
                {
                    "warning_code": str(code),
                    "family_id": None if pd.isna(row.get("family_id")) else row.get("family_id"),
                    "match_status": str(row.get("match_status") or ""),
                    "submission_id": str(row.get("submission_id") or ""),
                    "accession_number": str(row.get("accession_number") or ""),
                }
            )

    if not summary_rows:
        return []
    summary_df = pd.DataFrame(summary_rows)
    grouped = (
        summary_df.groupby(["warning_code", "family_id", "match_status"], dropna=False, as_index=False)
        .agg(
            event_count=("submission_id", "count"),
            submission_count=("submission_id", "nunique"),
            accession_count=("accession_number", "nunique"),
        )
        .sort_values(["warning_code", "family_id", "match_status"], ascending=[True, True, True], na_position="last")
        .reset_index(drop=True)
    )
    if limit is not None:
        grouped = grouped.head(int(limit)).reset_index(drop=True)

    out: list[GovernanceSummaryRow] = []
    for row in grouped.to_dict(orient="records"):
        out.append(
            GovernanceSummaryRow(
                warning_code=str(row.get("warning_code") or ""),
                family_id=None if pd.isna(row.get("family_id")) else row.get("family_id"),
                match_status=str(row.get("match_status") or ""),
                event_count=int(row.get("event_count") or 0),
                submission_count=int(row.get("submission_count") or 0),
                accession_count=int(row.get("accession_count") or 0),
            )
        )
    return out


def get_augmentation_submission_detail(
    config: AppConfig,
    *,
    submission_id: str,
) -> CrossAccessionSubmissionSummary:
    rows = list_augmentation_submissions_cross_accession(
        config,
        submission_id=submission_id,
        limit=1,
    )
    if not rows:
        raise SidecarNotFoundError(
            SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND,
            f"Submission {submission_id} was not found.",
        )
    return rows[0]


def list_submission_lifecycle_events(
    config: AppConfig,
    *,
    submission_id: str,
    limit: int | None = None,
) -> list[SubmissionLifecycleEventRow]:
    if not _submission_exists(config, submission_id):
        raise SidecarNotFoundError(
            SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND,
            f"Submission {submission_id} was not found.",
        )
    df = _load_or_empty(
        augmentation_submission_lifecycle_events_path(config),
        AUGMENTATION_SUBMISSION_LIFECYCLE_EVENT_COLUMNS,
    )
    if df.empty:
        return []
    df = df[df["submission_id"].astype(str) == str(submission_id)]
    if df.empty:
        return []
    df = _sorted_lifecycle_events(df)
    if limit is not None:
        df = df.head(int(limit)).reset_index(drop=True)

    out: list[SubmissionLifecycleEventRow] = []
    for row in df.to_dict(orient="records"):
        out.append(
            SubmissionLifecycleEventRow(
                event_time=str(row.get("event_time") or ""),
                lifecycle_event_id=str(row.get("lifecycle_event_id") or ""),
                submission_id=str(row.get("submission_id") or ""),
                from_state=str(row.get("from_state") or ""),
                to_state=str(row.get("to_state") or ""),
                reason=row.get("reason"),
                changed_by=row.get("changed_by"),
                source=row.get("source"),
            )
        )
    return out


def _overlay_winner_map_for_bucket(
    config: AppConfig,
    *,
    producer_id: str,
    layer_type: str,
) -> dict[str, str]:
    items_df = _load_or_empty(augmentation_items_path(config), AUGMENTATION_ITEMS_COLUMNS)
    if items_df.empty:
        return {}
    bucket = items_df[
        (items_df["producer_id"].astype(str) == str(producer_id))
        & (items_df["layer_type"].astype(str) == str(layer_type))
    ]
    if bucket.empty:
        return {}
    submission_ids = [str(x) for x in bucket["submission_id"].dropna().astype(str).unique().tolist()]
    state_map = _current_lifecycle_state_map_for_submissions(config, submission_ids=submission_ids)
    eligible = bucket[
        bucket["submission_id"].astype(str).map(
            lambda sid: state_map.get(str(sid), LIFECYCLE_STATE_ACTIVE) in LIFECYCLE_ELIGIBLE_FOR_OVERLAY
        )
    ]
    if eligible.empty:
        return {}
    unique_submissions = (
        eligible[["accession_number", "submission_id", "received_at"]]
        .drop_duplicates()
        .sort_values(
            ["accession_number", "received_at", "submission_id"],
            ascending=[True, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )
    winners = (
        unique_submissions.groupby(["accession_number"], sort=False, as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    return {
        str(row.get("accession_number") or ""): str(row.get("submission_id") or "")
        for row in winners.to_dict(orient="records")
    }


def list_submission_overlay_impact(
    config: AppConfig,
    *,
    submission_id: str,
    accession_numbers: list[str] | None = None,
    limit: int | None = None,
) -> list[SubmissionOverlayImpactRow]:
    submission = get_augmentation_submission_detail(config, submission_id=submission_id)
    items_df = _load_or_empty(augmentation_items_path(config), AUGMENTATION_ITEMS_COLUMNS)
    if items_df.empty:
        return []
    submission_items = items_df[items_df["submission_id"].astype(str) == str(submission_id)]
    if submission_items.empty:
        return []
    if accession_numbers:
        allowed = {str(value) for value in accession_numbers}
        submission_items = submission_items[submission_items["accession_number"].astype(str).isin(allowed)]
    if submission_items.empty:
        return []
    accessions = sorted(
        submission_items["accession_number"].dropna().astype(str).unique().tolist()
    )
    winner_map = _overlay_winner_map_for_bucket(
        config,
        producer_id=submission.producer_id,
        layer_type=submission.layer_type,
    )
    lifecycle_state = str(submission.lifecycle_state or LIFECYCLE_STATE_ACTIVE)

    rows: list[SubmissionOverlayImpactRow] = []
    for accession_number in accessions:
        winning_submission_id = winner_map.get(accession_number)
        if lifecycle_state not in LIFECYCLE_ELIGIBLE_FOR_OVERLAY:
            reason_code = OVERLAY_IMPACT_REASON_LIFECYCLE_INELIGIBLE
            contributes = False
            reason_message = "Submission lifecycle state is not eligible for resolved overlay selection."
        elif winning_submission_id is None:
            reason_code = OVERLAY_IMPACT_REASON_NO_ELIGIBLE_ROWS
            contributes = False
            reason_message = "No lifecycle-eligible rows were available for resolved overlay selection."
        elif str(winning_submission_id) == str(submission_id):
            reason_code = OVERLAY_IMPACT_REASON_SELECTED
            contributes = True
            reason_message = "Submission currently contributes to resolved overlay for this accession bucket."
        else:
            reason_code = OVERLAY_IMPACT_REASON_SUPERSEDED_BY_WINNER
            contributes = False
            reason_message = "A later eligible submission currently wins this accession bucket."
        rows.append(
            SubmissionOverlayImpactRow(
                accession_number=str(accession_number),
                producer_id=str(submission.producer_id),
                layer_type=str(submission.layer_type),
                submission_id=str(submission_id),
                lifecycle_state=lifecycle_state,
                contributes_to_resolved_overlay=bool(contributes),
                winning_submission_id=None if winning_submission_id is None else str(winning_submission_id),
                reason_code=reason_code,
                reason_message=reason_message,
            )
        )
    rows = sorted(
        rows,
        key=lambda row: (
            row.accession_number,
            row.producer_id,
            row.layer_type,
            row.submission_id,
        ),
    )
    if limit is not None:
        rows = rows[: int(limit)]
    return rows


def list_submission_entity_impact(
    config: AppConfig,
    *,
    submission_id: str,
    accession_numbers: list[str] | None = None,
    limit: int | None = None,
) -> tuple[bool, list[SubmissionEntityImpactRow]]:
    _ = get_augmentation_submission_detail(config, submission_id=submission_id)
    build_augmentation_entity_index(config)
    overlay_rows = list_submission_overlay_impact(
        config,
        submission_id=submission_id,
        accession_numbers=accession_numbers,
        limit=None,
    )
    contributing_accessions = {
        row.accession_number
        for row in overlay_rows
        if row.contributes_to_resolved_overlay
    }
    if not contributing_accessions:
        return augmentation_entity_index_path(config).exists(), []
    path = augmentation_entity_index_path(config)
    if not path.exists():
        return False, []
    df = _load_or_empty(path, AUGMENTATION_ENTITY_INDEX_COLUMNS)
    if df.empty:
        return True, []
    out = df[df["submission_id"].astype(str) == str(submission_id)]
    out = out[out["accession_number"].astype(str).isin(contributing_accessions)]
    if accession_numbers:
        allowed = {str(value) for value in accession_numbers}
        out = out[out["accession_number"].astype(str).isin(allowed)]
    if out.empty:
        return True, []
    out = out.sort_values(
        ["accession_number", "entity_normalized", "entity_text", "entity_id"],
        ascending=[True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)
    if limit is not None:
        out = out.head(int(limit)).reset_index(drop=True)
    rows: list[SubmissionEntityImpactRow] = []
    for row in out.to_dict(orient="records"):
        rows.append(
            SubmissionEntityImpactRow(
                accession_number=str(row.get("accession_number") or ""),
                entity_text=str(row.get("entity_text") or ""),
                entity_normalized=str(row.get("entity_normalized") or ""),
                entity_type=None if pd.isna(row.get("entity_type")) else row.get("entity_type"),
                entity_id=None if pd.isna(row.get("entity_id")) else row.get("entity_id"),
                filing_cik=None if pd.isna(row.get("filing_cik")) else row.get("filing_cik"),
                form_type=None if pd.isna(row.get("form_type")) else row.get("form_type"),
                filing_date=None if pd.isna(row.get("filing_date")) else row.get("filing_date"),
            )
        )
    return True, rows


def get_submission_review_bundle(
    config: AppConfig,
    *,
    submission_id: str,
    overlay_limit: int = 50,
    entity_limit: int = 50,
    lifecycle_limit: int = 50,
    governance_limit: int = 50,
) -> dict[str, object]:
    submission = get_augmentation_submission_detail(config, submission_id=submission_id)
    all_lifecycle = list_submission_lifecycle_events(config, submission_id=submission_id, limit=None)
    lifecycle_rows = all_lifecycle[: int(lifecycle_limit)]
    governance_all = summarize_governance_events(config, submission_id=submission_id, limit=None)
    governance_rows = governance_all[: int(governance_limit)]
    overlay_all = list_submission_overlay_impact(config, submission_id=submission_id, limit=None)
    overlay_rows = overlay_all[: int(overlay_limit)]
    entity_index_present, entity_all = list_submission_entity_impact(config, submission_id=submission_id, limit=None)
    entity_rows = entity_all[: int(entity_limit)]
    contributing = len([row for row in overlay_all if row.contributes_to_resolved_overlay])

    return {
        "submission": {
            "submission_id": submission.submission_id,
            "received_at": submission.received_at,
            "producer_id": submission.producer_id,
            "layer_type": submission.layer_type,
            "schema_version": submission.schema_version,
            "producer_run_id": submission.producer_run_id,
            "pipeline_id": submission.pipeline_id,
            "model_id": submission.model_id,
            "producer_version": submission.producer_version,
            "raw_request_path": submission.raw_request_path,
            "item_count_total": submission.item_count_total,
            "accession_count": submission.accession_count,
            "warning_item_count": submission.warning_item_count,
            "lifecycle_state": submission.lifecycle_state,
        },
        "lifecycle_events": {
            "total_count": int(len(all_lifecycle)),
            "returned_count": int(len(lifecycle_rows)),
            "truncated": bool(len(all_lifecycle) > len(lifecycle_rows)),
            "rows": [
                {
                    "event_time": row.event_time,
                    "lifecycle_event_id": row.lifecycle_event_id,
                    "submission_id": row.submission_id,
                    "from_state": row.from_state,
                    "to_state": row.to_state,
                    "reason": row.reason,
                    "changed_by": row.changed_by,
                    "source": row.source,
                }
                for row in lifecycle_rows
            ],
        },
        "governance_summary": {
            "total_count": int(len(governance_all)),
            "returned_count": int(len(governance_rows)),
            "truncated": bool(len(governance_all) > len(governance_rows)),
            "rows": [
                {
                    "warning_code": row.warning_code,
                    "family_id": row.family_id,
                    "match_status": row.match_status,
                    "event_count": row.event_count,
                    "submission_count": row.submission_count,
                    "accession_count": row.accession_count,
                }
                for row in governance_rows
            ],
        },
        "overlay_impact": {
            "selection_policy": RESOLVED_OVERLAY_SELECTION_POLICY,
            "total_count": int(len(overlay_all)),
            "returned_count": int(len(overlay_rows)),
            "truncated": bool(len(overlay_all) > len(overlay_rows)),
            "contributing_count": int(contributing),
            "non_contributing_count": int(len(overlay_all) - contributing),
            "rows": [
                {
                    "accession_number": row.accession_number,
                    "producer_id": row.producer_id,
                    "layer_type": row.layer_type,
                    "submission_id": row.submission_id,
                    "lifecycle_state": row.lifecycle_state,
                    "contributes_to_resolved_overlay": row.contributes_to_resolved_overlay,
                    "winning_submission_id": row.winning_submission_id,
                    "reason_code": row.reason_code,
                    "reason_message": row.reason_message,
                }
                for row in overlay_rows
            ],
        },
        "entity_impact": {
            "entity_index_present": bool(entity_index_present),
            "total_count": int(len(entity_all)),
            "returned_count": int(len(entity_rows)),
            "truncated": bool(len(entity_all) > len(entity_rows)),
            "rows": [
                {
                    "accession_number": row.accession_number,
                    "entity_text": row.entity_text,
                    "entity_normalized": row.entity_normalized,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "filing_cik": row.filing_cik,
                    "form_type": row.form_type,
                    "filing_date": row.filing_date,
                }
                for row in entity_rows
            ],
        },
    }


def list_augmentation_submissions_cross_accession(
    config: AppConfig,
    *,
    submission_id: str | None = None,
    accession_number: str | None = None,
    producer_id: str | None = None,
    layer_type: str | None = None,
    schema_version: str | None = None,
    lifecycle_state: str | None = None,
    has_governance_warnings: bool | None = None,
    received_at_from: str | None = None,
    received_at_to: str | None = None,
    limit: int | None = None,
) -> list[CrossAccessionSubmissionSummary]:
    from_bound = _parse_filter_timestamp("received_at_from", received_at_from)
    to_bound = _parse_filter_timestamp("received_at_to", received_at_to)
    if from_bound is not None and to_bound is not None and from_bound > to_bound:
        raise SidecarContractError(
            SIDE_CAR_ERROR_INVALID_TIME_RANGE,
            "received_at_from must be less than or equal to received_at_to.",
        )

    submissions = _load_or_empty(augmentation_submissions_path(config), AUGMENTATION_SUBMISSIONS_COLUMNS)
    if submissions.empty:
        return []
    if submission_id:
        submissions = submissions[submissions["submission_id"].astype(str) == str(submission_id)]
    if submissions.empty:
        return []

    items = _load_or_empty(augmentation_items_path(config), AUGMENTATION_ITEMS_COLUMNS)
    if accession_number:
        matching_submission_ids = set(
            items[items["accession_number"].astype(str) == str(accession_number)]["submission_id"].astype(str).tolist()
        )
        submissions = submissions[submissions["submission_id"].astype(str).isin(matching_submission_ids)]
        if submissions.empty:
            return []
    if producer_id:
        submissions = submissions[submissions["producer_id"].astype(str) == str(producer_id)]
    if layer_type:
        submissions = submissions[submissions["layer_type"].astype(str) == str(layer_type)]
    if schema_version:
        submissions = submissions[submissions["schema_version"].astype(str) == str(schema_version)]
    submissions = _apply_received_at_filters(submissions, received_at_from=from_bound, received_at_to=to_bound)
    if submissions.empty:
        return []
    item_counts = (
        items.groupby("submission_id", as_index=False)
        .agg(item_count_total=("item_index", "count"), accession_count=("accession_number", "nunique"))
        if not items.empty
        else pd.DataFrame(columns=["submission_id", "item_count_total", "accession_count"])
    )
    governance = _load_or_empty(augmentation_governance_events_path(config), AUGMENTATION_GOVERNANCE_EVENT_COLUMNS)
    warning_counts = (
        governance[governance["match_status"].astype(str).isin(["warning", "unknown"])]
        .groupby("submission_id", as_index=False)
        .agg(warning_item_count=("item_index", "count"))
        if not governance.empty
        else pd.DataFrame(columns=["submission_id", "warning_item_count"])
    )

    merged = submissions.merge(item_counts, on="submission_id", how="left").merge(warning_counts, on="submission_id", how="left")
    merged["item_count_total"] = merged["item_count_total"].fillna(0).astype(int)
    merged["accession_count"] = merged["accession_count"].fillna(0).astype(int)
    merged["warning_item_count"] = merged["warning_item_count"].fillna(0).astype(int)

    submission_ids = [str(x) for x in merged["submission_id"].dropna().astype(str).unique().tolist()]
    state_map = _current_lifecycle_state_map_for_submissions(config, submission_ids=submission_ids)
    merged["lifecycle_state"] = merged["submission_id"].astype(str).map(lambda sid: state_map.get(str(sid), LIFECYCLE_STATE_ACTIVE))

    if lifecycle_state:
        state = str(lifecycle_state).strip().lower()
        if state not in LIFECYCLE_STATES:
            allowed = ", ".join(sorted(LIFECYCLE_STATES))
            raise SidecarContractError(
                SIDE_CAR_ERROR_INVALID_LIFECYCLE_STATE,
                f"lifecycle_state must be one of: {allowed}.",
            )
        merged = merged[merged["lifecycle_state"].astype(str) == state]
    if has_governance_warnings is not None:
        if has_governance_warnings:
            merged = merged[merged["warning_item_count"].astype(int) > 0]
        else:
            merged = merged[merged["warning_item_count"].astype(int) == 0]

    merged = merged.sort_values(["received_at", "submission_id"], ascending=[False, True], na_position="last").reset_index(drop=True)
    if limit is not None:
        merged = merged.head(int(limit)).reset_index(drop=True)

    out: list[CrossAccessionSubmissionSummary] = []
    for row in merged.to_dict(orient="records"):
        out.append(
            CrossAccessionSubmissionSummary(
                submission_id=str(row.get("submission_id") or ""),
                received_at=str(row.get("received_at") or ""),
                producer_id=str(row.get("producer_id") or ""),
                layer_type=str(row.get("layer_type") or ""),
                schema_version=str(row.get("schema_version") or ""),
                producer_run_id=row.get("producer_run_id"),
                pipeline_id=row.get("pipeline_id"),
                model_id=row.get("model_id"),
                producer_version=row.get("producer_version"),
                raw_request_path=row.get("raw_request_path"),
                item_count_total=int(row.get("item_count_total") or 0),
                accession_count=int(row.get("accession_count") or 0),
                warning_item_count=int(row.get("warning_item_count") or 0),
                lifecycle_state=str(row.get("lifecycle_state") or LIFECYCLE_STATE_ACTIVE),
            )
        )
    return out
