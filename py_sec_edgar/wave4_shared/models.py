from __future__ import annotations

from py_sec_edgar.wave4_shared._shared_backend import import_shared_submodule

_enums = import_shared_submodule("enums")
_models = import_shared_submodule("models")

AugmentationType = _enums.AugmentationType
ProducerKind = _enums.ProducerKind
RunStatus = _enums.RunStatus

ProducerTargetDescriptorModel = getattr(
    _models, "ProducerTargetDescriptorModel", _models.ProducerTargetDescriptor
)
ProducerRunSubmissionModel = getattr(
    _models, "ProducerRunSubmissionModel", _models.ProducerRunSubmission
)
ProducerArtifactSubmissionModel = getattr(
    _models, "ProducerArtifactSubmissionModel", _models.ProducerArtifactSubmission
)
TargetDescriptorEnvelopeModel = ProducerTargetDescriptorModel
RunSubmissionEnvelopeModel = ProducerRunSubmissionModel
ArtifactSubmissionEnvelopeModel = ProducerArtifactSubmissionModel

__all__ = [
    "AugmentationType",
    "ProducerKind",
    "RunStatus",
    "ProducerTargetDescriptorModel",
    "ProducerRunSubmissionModel",
    "ProducerArtifactSubmissionModel",
    "TargetDescriptorEnvelopeModel",
    "RunSubmissionEnvelopeModel",
    "ArtifactSubmissionEnvelopeModel",
]
