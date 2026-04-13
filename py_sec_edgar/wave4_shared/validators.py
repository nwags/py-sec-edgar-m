from __future__ import annotations

from typing import Any

from py_sec_edgar.wave4_shared._shared_backend import import_shared_submodule

_schema_loaders = import_shared_submodule("schema_loaders")
_validators = import_shared_submodule("validators")


def load_wave4_schema(schema_filename: str) -> dict[str, Any]:
    compat_loader = getattr(_schema_loaders, "load_wave4_schema", None)
    if callable(compat_loader):
        return compat_loader(schema_filename)
    return _schema_loaders.load_json_schema(wave=4, schema_filename=schema_filename)


def validate_producer_target_descriptor(payload: dict[str, Any]) -> dict[str, Any]:
    return _validators.validate_producer_target_descriptor(payload)


def validate_producer_run_submission(payload: dict[str, Any]) -> dict[str, Any]:
    return _validators.validate_producer_run_submission(payload)


def validate_producer_artifact_submission(payload: dict[str, Any]) -> dict[str, Any]:
    return _validators.validate_producer_artifact_submission(payload)


def validate_target_descriptor_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    compat = getattr(_validators, "validate_target_descriptor_envelope", None)
    if callable(compat):
        return compat(payload)
    return validate_producer_target_descriptor(payload)


def validate_run_submission_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return _validators.validate_run_submission_envelope(payload)


def validate_artifact_submission_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return _validators.validate_artifact_submission_envelope(payload)

__all__ = [
    "load_wave4_schema",
    "validate_producer_target_descriptor",
    "validate_producer_run_submission",
    "validate_producer_artifact_submission",
    "validate_target_descriptor_envelope",
    "validate_run_submission_envelope",
    "validate_artifact_submission_envelope",
]
