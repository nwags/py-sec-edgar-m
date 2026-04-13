from __future__ import annotations

import importlib
import json
from pathlib import Path

from m_cache_shared.augmentation import (
    ApiAugmentationMeta,
    EventsViewRow,
    ProducerArtifactSubmission,
    ProducerRunSubmission,
    ProducerTargetDescriptor,
    RunStatusView,
    load_json_schema,
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
from m_cache_shared.packers import (
    build_augmentation_meta_additive,
    build_events_view_row,
    build_run_status_view,
)
from m_cache_shared.validators import (
    load_wave4_schema,
    load_wave5_schema,
)
from py_sec_edgar.wave4_shared import _shared_backend


def test_m_cache_shared_schema_loaders_support_wave4_and_wave5() -> None:
    wave4 = load_wave4_schema("producer-target-descriptor.schema.json")
    wave5 = load_wave5_schema("run-status-view.schema.json")
    canonical = load_json_schema(wave=5, schema_filename="run-status-view.schema.json")
    assert "required" in wave4
    assert "canonical_key" in wave4["required"]
    assert "required" in wave5
    assert "run_id" in wave5["required"]
    assert canonical["required"] == wave5["required"]


def test_m_cache_shared_canonical_model_construction() -> None:
    target = ProducerTargetDescriptor(
        domain="sec",
        resource_family="filing",
        canonical_key="0000320193-25-000010",
        text_source="api:/filings/0000320193-25-000010/content",
        source_text_version="sha256:abc",
    )
    run = ProducerRunSubmission(
        run_id="run-1",
        domain="sec",
        resource_family="filing",
        canonical_key="0000320193-25-000010",
        augmentation_type="entity_tagging",
        source_text_version="sha256:abc",
        producer_kind="hybrid",
        producer_name="producer-x",
        producer_version="1.0.0",
        payload_schema_name="com.example.entity",
        payload_schema_version="2026-04-10",
        status="completed",
        success=True,
        reason_code="completed",
    )
    artifact = ProducerArtifactSubmission(
        domain="sec",
        resource_family="filing",
        canonical_key="0000320193-25-000010",
        augmentation_type="entity_tagging",
        source_text_version="sha256:abc",
        producer_name="producer-x",
        producer_version="1.0.0",
        payload_schema_name="com.example.entity",
        payload_schema_version="2026-04-10",
        payload={"annotations": [{"span_start": 0, "span_end": 5}]},
    )
    status = RunStatusView(
        run_id="run-1",
        augmentation_type="entity_tagging",
        canonical_key="0000320193-25-000010",
        source_text_version="sha256:abc",
        producer_name="producer-x",
        producer_version="1.0.0",
        status="completed",
        success=True,
        reason_code="completed",
        persisted_locally=True,
    )
    event = EventsViewRow(
        event_at="2026-04-10T12:00:00Z",
        event_code="event_recorded",
        canonical_key="0000320193-25-000010",
    )
    meta = ApiAugmentationMeta(
        augmentation_available=True,
        augmentation_types_present=["entity_tagging"],
        source_text_version="sha256:abc",
    )
    assert target.canonical_key == "0000320193-25-000010"
    assert run.run_id == "run-1"
    assert artifact.success is True
    assert status.persisted_locally is True
    assert event.event_code == "event_recorded"
    assert meta.augmentation_available is True


def test_m_cache_shared_validator_and_wave4_facade_parity(monkeypatch) -> None:
    monkeypatch.setenv("M_CACHE_SHARED_SOURCE", "local")
    _shared_backend.reset_shared_backend_for_tests()
    import py_sec_edgar.wave4_shared.validators as wave4_validators

    importlib.reload(wave4_validators)

    target_payload = {
        "domain": "sec",
        "resource_family": "filing",
        "canonical_key": "0000320193-25-000010",
        "text_source": "api:/filings/0000320193-25-000010/content",
        "source_text_version": "sha256:abc",
    }
    run_payload = {
        "run_id": "run-1",
        "domain": "sec",
        "resource_family": "filing",
        "canonical_key": "0000320193-25-000010",
        "augmentation_type": "entity_tagging",
        "source_text_version": "sha256:abc",
        "producer_kind": "hybrid",
        "producer_name": "producer-x",
        "producer_version": "1.0.0",
        "payload_schema_name": "com.example.entity",
        "payload_schema_version": "2026-04-10",
        "status": "completed",
        "success": True,
        "reason_code": "completed",
    }
    artifact_payload = {
        "domain": "sec",
        "resource_family": "filing",
        "canonical_key": "0000320193-25-000010",
        "augmentation_type": "entity_tagging",
        "source_text_version": "sha256:abc",
        "producer_name": "producer-x",
        "producer_version": "1.0.0",
        "payload_schema_name": "com.example.entity",
        "payload_schema_version": "2026-04-10",
        "payload": {"annotations": [{"span_start": 0, "span_end": 5}]},
        "success": True,
    }
    assert validate_producer_target_descriptor(
        target_payload
    ) == wave4_validators.validate_producer_target_descriptor(target_payload)
    assert validate_producer_run_submission(
        run_payload
    ) == wave4_validators.validate_producer_run_submission(run_payload)
    assert validate_producer_artifact_submission(
        artifact_payload
    ) == wave4_validators.validate_producer_artifact_submission(artifact_payload)
    assert validate_run_submission_envelope(run_payload) == validate_producer_run_submission(run_payload)
    assert validate_artifact_submission_envelope(
        artifact_payload
    ) == validate_producer_artifact_submission(artifact_payload)


def test_m_cache_shared_packers_and_compat_aliases_are_shape_equivalent() -> None:
    canonical_meta = pack_additive_augmentation_meta(
        augmentation_available=True,
        augmentation_types_present=["entity_tagging"],
        last_augmented_at="2026-04-10T12:00:00Z",
        augmentation_stale=False,
        inspect_path="/filings/0000320193-25-000010/augmentations",
        source_text_version="sha256:abc",
        target_descriptor={"canonical_key": "0000320193-25-000010"},
    )
    compat_meta = build_augmentation_meta_additive(
        augmentation_available=True,
        augmentation_types_present=["entity_tagging"],
        last_augmented_at="2026-04-10T12:00:00Z",
        augmentation_stale=False,
        inspect_path="/filings/0000320193-25-000010/augmentations",
        source_text_version="sha256:abc",
        target_descriptor={"canonical_key": "0000320193-25-000010"},
    )
    assert canonical_meta == compat_meta

    canonical_status = pack_run_status_view(
        run_id="run-1",
        idempotency_key="run-1",
        augmentation_type="entity_tagging",
        canonical_key="0000320193-25-000010",
        source_text_version="sha256:abc",
        producer_name="producer-x",
        producer_version="1.0.0",
        status="completed",
        success=True,
        reason_code="completed",
        persisted_locally=True,
        augmentation_stale=False,
        last_updated_at="2026-04-10T12:00:00Z",
    )
    compat_status = build_run_status_view(
        run_id="run-1",
        idempotency_key="run-1",
        augmentation_type="entity_tagging",
        canonical_key="0000320193-25-000010",
        source_text_version="sha256:abc",
        producer_name="producer-x",
        producer_version="1.0.0",
        status="completed",
        success=True,
        reason_code="completed",
        persisted_locally=True,
        augmentation_stale=False,
        last_updated_at="2026-04-10T12:00:00Z",
    )
    assert canonical_status == compat_status

    canonical_event = pack_events_view(
        event_at="2026-04-10T12:00:00Z",
        event_code="event_recorded",
        canonical_key="0000320193-25-000010",
        run_id="run-1",
        success=True,
    )
    compat_event = build_events_view_row(
        event_at="2026-04-10T12:00:00Z",
        event_code="event_recorded",
        canonical_key="0000320193-25-000010",
        run_id="run-1",
        success=True,
    )
    assert canonical_event == compat_event


def test_m_cache_shared_cli_helper_canonical_and_alias_parse_identically(tmp_path: Path) -> None:
    payload = {"run_id": "run-1", "status": "completed"}
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    from m_cache_shared.cli_helpers import load_json_object_input

    by_json = parse_json_input_payload(payload_json=json.dumps(payload), payload_file=None)
    by_file = parse_json_input_payload(payload_json=None, payload_file=payload_file)
    alias_json = load_json_object_input(payload_json=json.dumps(payload), payload_file=None)
    assert by_json == payload
    assert by_file == payload
    assert alias_json == payload
