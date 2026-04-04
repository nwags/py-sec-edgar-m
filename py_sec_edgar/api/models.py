from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class FilingMetadataResponse(BaseModel):
    accession_number: str
    filing_cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    filename: str | None = None
    submission_path: str | None = None
    local_content_available: bool
    metadata_source: str | None = None
    metadata_surface: str | None = None
    augmentations: list["FilingAugmentationItemResponse"] | None = None


class AugmentationSubmissionItemRequest(BaseModel):
    accession_number: str
    augmentation_type: str
    payload: dict[str, object]
    payload_schema_version: str | None = None
    filename: str | None = None
    filing_cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None


class AugmentationSubmissionRequest(BaseModel):
    producer_id: str
    layer_type: str
    schema_version: str
    producer_run_id: str | None = None
    pipeline_id: str | None = None
    model_id: str | None = None
    producer_version: str | None = None
    items: list[AugmentationSubmissionItemRequest] = Field(default_factory=list)


class AugmentationSubmissionResponse(BaseModel):
    submission_id: str
    received_at: str
    item_count: int
    submissions_path: str
    items_path: str
    raw_request_path: str


class AugmentationSubmissionLifecycleTransitionRequest(BaseModel):
    to_state: Literal["active", "superseded", "withdrawn", "disabled"]
    reason: str | None = None
    changed_by: str | None = None
    source: str | None = None


class AugmentationSubmissionLifecycleTransitionResponse(BaseModel):
    event_time: str
    lifecycle_event_id: str
    submission_id: str
    from_state: Literal["active", "superseded", "withdrawn", "disabled"]
    to_state: Literal["active", "superseded", "withdrawn", "disabled"]
    reason: str | None = None
    changed_by: str | None = None
    source: str | None = None


class FilingAugmentationItemResponse(BaseModel):
    submission_id: str
    item_index: int
    received_at: str
    accession_number: str
    filename: str | None = None
    filing_cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    producer_id: str
    layer_type: str
    schema_version: str
    augmentation_type: str
    payload_schema_version: str | None = None
    payload: dict[str, object]
    producer_run_id: str | None = None
    pipeline_id: str | None = None
    model_id: str | None = None
    producer_version: str | None = None
    raw_request_path: str | None = None


class FilingAugmentationsResponse(BaseModel):
    accession_number: str
    augmentations: list[FilingAugmentationItemResponse]


class FilingOverlaySelectedSubmissionKeyResponse(BaseModel):
    producer_id: str
    layer_type: str
    submission_id: str
    received_at: str


class FilingResolvedOverlayResponse(BaseModel):
    accession_number: str
    selection_policy: Literal["latest_per_producer_layer_v1"]
    selected_submission_keys: list[FilingOverlaySelectedSubmissionKeyResponse]
    augmentations: list[FilingAugmentationItemResponse]


class FilingAugmentationSubmissionSummaryResponse(BaseModel):
    submission_id: str
    received_at: str
    producer_id: str
    layer_type: str
    schema_version: str
    producer_run_id: str | None = None
    pipeline_id: str | None = None
    model_id: str | None = None
    producer_version: str | None = None
    raw_request_path: str | None = None
    item_count_for_accession: int
    lifecycle_state: Literal["active", "superseded", "withdrawn", "disabled"] = "active"


class FilingAugmentationSubmissionsResponse(BaseModel):
    accession_number: str
    submissions: list[FilingAugmentationSubmissionSummaryResponse]


class GovernanceEventResponse(BaseModel):
    event_time: str
    contract_version_id: str
    submission_id: str
    item_index: int
    accession_number: str
    producer_id: str
    layer_type: str
    augmentation_type: str
    schema_version: str
    family_id: str | None = None
    family_inferred: bool
    match_status: Literal["match", "warning", "unknown"]
    warning_codes: list[str]
    warning_messages: list[str]


class GovernanceEventsResponse(BaseModel):
    events: list[GovernanceEventResponse]


class GovernanceSummaryRowResponse(BaseModel):
    warning_code: str
    family_id: str | None = None
    match_status: Literal["match", "warning", "unknown"]
    event_count: int
    submission_count: int
    accession_count: int


class GovernanceSummaryResponse(BaseModel):
    rows: list[GovernanceSummaryRowResponse]


class CrossAccessionAugmentationSubmissionSummaryResponse(BaseModel):
    submission_id: str
    received_at: str
    producer_id: str
    layer_type: str
    schema_version: str
    producer_run_id: str | None = None
    pipeline_id: str | None = None
    model_id: str | None = None
    producer_version: str | None = None
    raw_request_path: str | None = None
    item_count_total: int
    accession_count: int
    warning_item_count: int
    lifecycle_state: Literal["active", "superseded", "withdrawn", "disabled"]


class CrossAccessionAugmentationSubmissionsResponse(BaseModel):
    submissions: list[CrossAccessionAugmentationSubmissionSummaryResponse]


class AugmentationSubmissionDetailResponse(BaseModel):
    submission: CrossAccessionAugmentationSubmissionSummaryResponse


class SubmissionLifecycleEventResponse(BaseModel):
    event_time: str
    lifecycle_event_id: str
    submission_id: str
    from_state: Literal["active", "superseded", "withdrawn", "disabled"]
    to_state: Literal["active", "superseded", "withdrawn", "disabled"]
    reason: str | None = None
    changed_by: str | None = None
    source: str | None = None


class SubmissionLifecycleEventsResponse(BaseModel):
    submission_id: str
    events: list[SubmissionLifecycleEventResponse]


class AugmentationUnifiedEventResponse(BaseModel):
    event_family: Literal["governance", "lifecycle"]
    event_type: Literal["governance_diagnostic", "submission_lifecycle_transition"]
    event_source: Literal[
        "augmentation_governance_events_v1",
        "augmentation_submission_lifecycle_events_v1",
    ]
    event_time: str
    event_id: str
    submission_id: str
    accession_numbers: list[str]
    producer_id: str | None = None
    layer_type: str | None = None
    item_index: int | None = None
    contract_version_id: str | None = None
    augmentation_type: str | None = None
    schema_version: str | None = None
    family_id: str | None = None
    family_inferred: bool | None = None
    warning_codes: list[str] = Field(default_factory=list)
    match_status: Literal["match", "warning", "unknown"] | None = None
    warning_messages: list[str] = Field(default_factory=list)
    from_state: Literal["active", "superseded", "withdrawn", "disabled"] | None = None
    to_state: Literal["active", "superseded", "withdrawn", "disabled"] | None = None
    reason: str | None = None
    changed_by: str | None = None
    source: str | None = None


class AugmentationUnifiedEventsResponse(BaseModel):
    events: list[AugmentationUnifiedEventResponse]


class AugmentationUnifiedEventsSummaryRowResponse(BaseModel):
    event_family: Literal["governance", "lifecycle"] | None = None
    event_type: Literal["governance_diagnostic", "submission_lifecycle_transition"] | None = None
    event_source: Literal[
        "augmentation_governance_events_v1",
        "augmentation_submission_lifecycle_events_v1",
    ] | None = None
    producer_id: str | None = None
    layer_type: str | None = None
    warning_code: str | None = None
    match_status: Literal["match", "warning", "unknown"] | None = None
    to_state: Literal["active", "superseded", "withdrawn", "disabled"] | None = None
    event_count: int
    submission_count: int
    accession_count: int


class AugmentationUnifiedEventsSummaryResponse(BaseModel):
    rows: list[AugmentationUnifiedEventsSummaryRowResponse]


class SubmissionOverlayImpactRowResponse(BaseModel):
    accession_number: str
    producer_id: str
    layer_type: str
    submission_id: str
    lifecycle_state: Literal["active", "superseded", "withdrawn", "disabled"]
    contributes_to_resolved_overlay: bool
    winning_submission_id: str | None = None
    reason_code: Literal[
        "selected",
        "lifecycle_ineligible",
        "superseded_by_winner",
        "no_eligible_rows",
    ]
    reason_message: str


class SubmissionOverlayImpactResponse(BaseModel):
    submission_id: str
    selection_policy: Literal["latest_per_producer_layer_v1"]
    affected_accession_count: int
    contributing_accession_count: int
    non_contributing_accession_count: int
    rows: list[SubmissionOverlayImpactRowResponse]


class SubmissionEntityImpactRowResponse(BaseModel):
    accession_number: str
    entity_text: str
    entity_normalized: str
    entity_type: str | None = None
    entity_id: str | None = None
    filing_cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None


class SubmissionEntityImpactResponse(BaseModel):
    submission_id: str
    entity_index_present: bool
    row_count: int
    accession_count: int
    rows: list[SubmissionEntityImpactRowResponse]


class SubmissionReviewBundleSectionLifecycle(BaseModel):
    total_count: int
    returned_count: int
    truncated: bool
    rows: list[SubmissionLifecycleEventResponse]


class SubmissionReviewBundleSectionGovernance(BaseModel):
    total_count: int
    returned_count: int
    truncated: bool
    rows: list[GovernanceSummaryRowResponse]


class SubmissionReviewBundleSectionOverlay(BaseModel):
    selection_policy: Literal["latest_per_producer_layer_v1"]
    total_count: int
    returned_count: int
    truncated: bool
    contributing_count: int
    non_contributing_count: int
    rows: list[SubmissionOverlayImpactRowResponse]


class SubmissionReviewBundleSectionEntity(BaseModel):
    entity_index_present: bool
    total_count: int
    returned_count: int
    truncated: bool
    rows: list[SubmissionEntityImpactRowResponse]


class SubmissionReviewBundleResponse(BaseModel):
    submission: CrossAccessionAugmentationSubmissionSummaryResponse
    lifecycle_events: SubmissionReviewBundleSectionLifecycle
    governance_summary: SubmissionReviewBundleSectionGovernance
    overlay_impact: SubmissionReviewBundleSectionOverlay
    entity_impact: SubmissionReviewBundleSectionEntity


class FilingSearchResultResponse(BaseModel):
    accession_number: str
    filing_cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    entity_match_count: int


class FilingSearchResponse(BaseModel):
    results: list[FilingSearchResultResponse]
