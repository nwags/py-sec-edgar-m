from __future__ import annotations

from m_cache_shared.augmentation.enums import AugmentationType, ProducerKind, RunStatus
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
]
