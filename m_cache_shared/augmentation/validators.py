from __future__ import annotations

from typing import Any

from m_cache_shared.augmentation.models import (
    EventsViewRow,
    ProducerArtifactSubmission,
    ProducerRunSubmission,
    ProducerTargetDescriptor,
    RunStatusView,
)


def validate_producer_target_descriptor(payload: dict[str, Any]) -> dict[str, Any]:
    return ProducerTargetDescriptor.model_validate(payload).model_dump()


def validate_producer_run_submission(payload: dict[str, Any]) -> dict[str, Any]:
    return ProducerRunSubmission.model_validate(payload).model_dump()


def validate_producer_artifact_submission(payload: dict[str, Any]) -> dict[str, Any]:
    return ProducerArtifactSubmission.model_validate(payload).model_dump()


def validate_run_submission_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_producer_run_submission(payload)


def validate_artifact_submission_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_producer_artifact_submission(payload)


def validate_run_status_view(payload: dict[str, Any]) -> dict[str, Any]:
    return RunStatusView.model_validate(payload).model_dump()


def validate_events_view_row(payload: dict[str, Any]) -> dict[str, Any]:
    return EventsViewRow.model_validate(payload).model_dump()


def validate_target_descriptor_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_producer_target_descriptor(payload)


__all__ = [
    "validate_producer_target_descriptor",
    "validate_producer_run_submission",
    "validate_producer_artifact_submission",
    "validate_run_submission_envelope",
    "validate_artifact_submission_envelope",
    "validate_run_status_view",
    "validate_events_view_row",
    "validate_target_descriptor_envelope",
]
