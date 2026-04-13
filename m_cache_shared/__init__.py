from __future__ import annotations

from m_cache_shared.augmentation import (
    ApiAugmentationMeta,
    AugmentationType,
    EventsViewRow,
    EventsViewRowModel,
    ProducerArtifactSubmission,
    ProducerArtifactSubmissionModel,
    ProducerKind,
    ProducerRunSubmission,
    ProducerRunSubmissionModel,
    ProducerTargetDescriptor,
    ProducerTargetDescriptorModel,
    RunStatus,
    RunStatusView,
    RunStatusViewModel,
    load_json_schema,
    load_json_object_input,
    pack_additive_augmentation_meta,
    pack_events_view,
    pack_run_status_view,
    parse_json_input_payload,
    validate_artifact_submission_envelope,
    validate_producer_artifact_submission,
    validate_producer_run_submission,
    validate_producer_target_descriptor,
    validate_run_submission_envelope,
)
from m_cache_shared.augmentation.packers import (
    build_augmentation_meta_additive,
    build_events_view_row,
    build_run_status_view,
)
from m_cache_shared.augmentation.schema_loaders import (
    load_shared_schema,
    load_wave4_schema,
    load_wave5_schema,
)
from m_cache_shared.augmentation.validators import (
    validate_events_view_row,
    validate_run_status_view,
    validate_target_descriptor_envelope,
)

# Compatibility aliases retained for the Wave 5.1 normalization cycle.
TargetDescriptorEnvelopeModel = ProducerTargetDescriptorModel
RunSubmissionEnvelopeModel = ProducerRunSubmissionModel
ArtifactSubmissionEnvelopeModel = ProducerArtifactSubmissionModel

__all__ = [
    "AugmentationType",
    "ProducerKind",
    "RunStatus",
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
    "TargetDescriptorEnvelopeModel",
    "RunSubmissionEnvelopeModel",
    "ArtifactSubmissionEnvelopeModel",
    "build_augmentation_meta_additive",
    "build_run_status_view",
    "build_events_view_row",
    "pack_additive_augmentation_meta",
    "pack_run_status_view",
    "pack_events_view",
    "parse_json_input_payload",
    "load_json_object_input",
    "load_json_schema",
    "load_shared_schema",
    "load_wave4_schema",
    "load_wave5_schema",
    "validate_producer_target_descriptor",
    "validate_producer_run_submission",
    "validate_producer_artifact_submission",
    "validate_target_descriptor_envelope",
    "validate_run_submission_envelope",
    "validate_artifact_submission_envelope",
    "validate_run_status_view",
    "validate_events_view_row",
]
