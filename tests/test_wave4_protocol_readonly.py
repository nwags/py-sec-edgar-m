from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from httpx import ASGITransport, AsyncClient

from py_sec_edgar.api.app import create_app
from py_sec_edgar.augmentation_sidecars import persist_augmentation_submission
from py_sec_edgar.augmentation_wave3 import build_api_augmentation_meta
from py_sec_edgar.config import load_config
from py_sec_edgar.wave4_shared import _shared_backend


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _write_merged_index(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def test_wave4_shared_seam_validators_are_local_and_envelope_only(monkeypatch) -> None:
    monkeypatch.setenv("M_CACHE_SHARED_SOURCE", "local")
    _shared_backend.reset_shared_backend_for_tests()
    import py_sec_edgar.wave4_shared.validators as validators

    importlib.reload(validators)

    schema = validators.load_wave4_schema("producer-target-descriptor.schema.json")
    assert "required" in schema
    assert "canonical_key" in schema["required"]

    target = validators.validate_producer_target_descriptor(
        {
            "domain": "sec",
            "resource_family": "filing",
            "canonical_key": "0000320193-25-000010",
            "text_source": "api:/filings/0000320193-25-000010/content",
            "source_text_version": "sha256:abc",
        }
    )
    assert target["domain"] == "sec"
    assert validators.validate_target_descriptor_envelope(target)["domain"] == "sec"

    run = validators.validate_producer_run_submission(
        {
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
    )
    assert run["producer_name"] == "producer-x"
    assert validators.validate_run_submission_envelope(run)["run_id"] == "run-1"

    artifact = validators.validate_producer_artifact_submission(
        {
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
    )
    assert artifact["success"] is True
    assert validators.validate_artifact_submission_envelope(artifact)["success"] is True


def test_wave4_source_text_version_is_deterministic_and_staleness_is_additive(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )
    filing_path = config.download_root / "edgar" / "data" / "320193" / "0000320193-25-000010.txt"
    filing_path.parent.mkdir(parents=True, exist_ok=True)
    filing_path.write_text("v1 filing payload", encoding="utf-8")

    persist_augmentation_submission(
        config,
        producer_id="ext-annotator",
        layer_type="entities",
        schema_version="v1",
        producer_run_id="run-1",
        pipeline_id="pipe-1",
        model_id="model-1",
        producer_version="1.2.3",
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple"}]},
                "payload_schema_version": "p1",
            }
        ],
        raw_request={"seed": True},
    )
    meta_before = build_api_augmentation_meta(config, "0000320193-25-000010")
    assert meta_before["augmentation_available"] is True
    assert meta_before["source_text_version"]
    assert meta_before["augmentation_stale"] is False
    assert meta_before["target_descriptor"]["canonical_key"] == "0000320193-25-000010"

    filing_path.write_text("v2 filing payload changed", encoding="utf-8")
    meta_after = build_api_augmentation_meta(config, "0000320193-25-000010")
    assert meta_after["augmentation_stale"] is True
    assert meta_after["source_text_version"] != meta_before["source_text_version"]

    # No second protocol write authority artifact is introduced in this pass.
    assert not (config.normalized_refdata_root / "producer_protocol_inbox.parquet").exists()
    assert not (config.normalized_refdata_root / "producer_submissions.parquet").exists()


@pytest.mark.anyio
async def test_wave4_target_descriptor_endpoint_is_read_only_and_additive(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )
    filing_path = config.download_root / "edgar" / "data" / "320193" / "0000320193-25-000010.txt"
    filing_path.parent.mkdir(parents=True, exist_ok=True)
    filing_path.write_text("descriptor payload", encoding="utf-8")

    transport = ASGITransport(app=create_app(config))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/filings/0000320193-25-000010/augmentation-target-descriptor"
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["domain"] == "sec"
    assert payload["resource_family"] == "filing"
    assert payload["canonical_key"] == "0000320193-25-000010"
    assert payload["text_source"] == "api:/filings/0000320193-25-000010/content"
    assert str(payload["source_text_version"]).startswith("sha256:")
