from __future__ import annotations

from typing import Any

from m_cache_shared.augmentation.schema_loaders import (
    load_json_schema,
    load_shared_schema,
    load_wave4_schema,
    load_wave5_schema,
)
from m_cache_shared.augmentation.validators import (
    validate_artifact_submission_envelope,
    validate_events_view_row,
    validate_producer_artifact_submission,
    validate_producer_run_submission,
    validate_producer_target_descriptor,
    validate_run_status_view,
    validate_run_submission_envelope,
    validate_target_descriptor_envelope,
)

# Compatibility alias retained for the Wave 5.1 normalization cycle.
def load_json_schema_compat(*, wave: int, schema_filename: str) -> dict[str, Any]:
    return load_json_schema(wave=wave, schema_filename=schema_filename)


__all__ = [
    "load_json_schema",
    "load_json_schema_compat",
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
