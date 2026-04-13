from __future__ import annotations

from m_cache_shared.augmentation.cli_helpers import (
    load_json_object_input,
    parse_json_input_payload,
)
from m_cache_shared.augmentation.enums import (
    AugmentationType,
    ProducerKind,
    RunStatus,
)
from m_cache_shared.augmentation.models import (
    ApiAugmentationMeta,
    EventsViewRow,
    EventsViewRowModel,
    ProducerArtifactSubmission,
    ProducerArtifactSubmissionModel,
    ProducerRunSubmission,
    ProducerRunSubmissionModel,
    ProducerTargetDescriptor,
    ProducerTargetDescriptorModel,
    RunStatusView,
    RunStatusViewModel,
)
from m_cache_shared.augmentation.packers import (
    pack_additive_augmentation_meta,
    pack_events_view,
    pack_run_status_view,
)
from m_cache_shared.augmentation.schema_loaders import (
    load_json_schema,
)
from m_cache_shared.augmentation.validators import (
    validate_artifact_submission_envelope,
    validate_producer_artifact_submission,
    validate_producer_run_submission,
    validate_producer_target_descriptor,
    validate_run_submission_envelope,
)

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
    "validate_producer_target_descriptor",
    "validate_producer_run_submission",
    "validate_producer_artifact_submission",
    "validate_run_submission_envelope",
    "validate_artifact_submission_envelope",
    "load_json_schema",
    "pack_run_status_view",
    "pack_events_view",
    "pack_additive_augmentation_meta",
    "parse_json_input_payload",
    "load_json_object_input",
    # Compatibility aliases retained for the Wave 5.1 normalization cycle.
    "ProducerTargetDescriptorModel",
    "ProducerRunSubmissionModel",
    "ProducerArtifactSubmissionModel",
    "RunStatusViewModel",
    "EventsViewRowModel",
]
