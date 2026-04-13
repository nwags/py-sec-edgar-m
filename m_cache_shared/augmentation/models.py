from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from m_cache_shared.augmentation.enums import AugmentationType, ProducerKind, RunStatus


class ProducerTargetDescriptor(BaseModel):
    domain: str
    resource_family: str
    canonical_key: str
    text_source: str
    source_text_version: str
    language: str | None = None
    document_time_reference: str | None = None
    producer_hints: dict[str, Any] = Field(default_factory=dict)


class ProducerRunSubmission(BaseModel):
    run_id: str
    domain: str
    resource_family: str
    canonical_key: str
    augmentation_type: AugmentationType
    source_text_version: str
    producer_kind: ProducerKind
    producer_name: str
    producer_version: str
    payload_schema_name: str
    payload_schema_version: str
    status: RunStatus
    success: bool
    reason_code: str
    persisted_locally: bool = False


class ProducerArtifactSubmission(BaseModel):
    domain: str
    resource_family: str
    canonical_key: str
    augmentation_type: AugmentationType
    source_text_version: str
    producer_name: str
    producer_version: str
    payload_schema_name: str
    payload_schema_version: str
    artifact_locator: str | None = None
    payload: dict[str, Any] | None = None
    success: bool = True


class RunStatusView(BaseModel):
    run_id: str
    augmentation_type: str
    canonical_key: str
    source_text_version: str
    producer_name: str
    producer_version: str
    status: str
    success: bool
    reason_code: str
    persisted_locally: bool
    idempotency_key: str | None = None
    augmentation_stale: bool | None = None
    last_updated_at: str | None = None


class EventsViewRow(BaseModel):
    event_at: str
    event_code: str
    canonical_key: str
    augmentation_type: str | None = None
    run_id: str | None = None
    producer_name: str | None = None
    producer_version: str | None = None
    reason_code: str | None = None
    success: bool | None = None


class ApiAugmentationMeta(BaseModel):
    augmentation_available: bool
    augmentation_types_present: list[str] = Field(default_factory=list)
    last_augmented_at: str | None = None
    augmentation_stale: bool | None = None
    inspect_path: str | None = None
    source_text_version: str | None = None
    target_descriptor: dict[str, object] | None = None


# Compatibility aliases retained for the Wave 5.1 normalization cycle.
ProducerTargetDescriptorModel = ProducerTargetDescriptor
ProducerRunSubmissionModel = ProducerRunSubmission
ProducerArtifactSubmissionModel = ProducerArtifactSubmission
RunStatusViewModel = RunStatusView
EventsViewRowModel = EventsViewRow

__all__ = [
    "ProducerTargetDescriptor",
    "ProducerRunSubmission",
    "ProducerArtifactSubmission",
    "RunStatusView",
    "EventsViewRow",
    "ApiAugmentationMeta",
    "ProducerTargetDescriptorModel",
    "ProducerRunSubmissionModel",
    "ProducerArtifactSubmissionModel",
    "RunStatusViewModel",
    "EventsViewRowModel",
]
