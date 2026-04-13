from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from httpx import ASGITransport, AsyncClient

from py_sec_edgar.api.app import create_app
from py_sec_edgar.augmentation_sidecars import (
    persist_augmentation_submission,
    record_submission_lifecycle_transition,
)
from py_sec_edgar.augmentation_wave3 import (
    augmentation_events_path,
    augmentation_runs_path,
    build_api_augmentation_meta,
    materialize_shared_augmentation_metadata,
)
from py_sec_edgar.config import load_config


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _write_merged_index(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def test_wave3_shared_augmentation_metadata_companions_are_materialized(tmp_path: Path) -> None:
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
    persisted = persist_augmentation_submission(
        config,
        producer_id="ext-annotator",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple"}]},
            }
        ],
        raw_request={"seed": True},
    )
    record_submission_lifecycle_transition(
        config,
        submission_id=persisted.submission_id,
        to_state="disabled",
        reason="test",
        changed_by="unit",
        source="unit",
    )

    runs_out, runs_count, events_out, events_count = materialize_shared_augmentation_metadata(config)
    assert runs_out == augmentation_runs_path(config)
    assert events_out == augmentation_events_path(config)
    assert runs_count >= 1
    assert events_count >= 1

    runs = pd.read_parquet(runs_out)
    events = pd.read_parquet(events_out)
    assert "run_id" in runs.columns
    assert "augmentation_type" in runs.columns
    assert "source_submission_id" in runs.columns
    assert set(runs["augmentation_type"].astype(str).tolist()).issubset(
        {"entity_tagging", "temporal_expression_tagging"}
    )
    assert "event_family" in events.columns
    assert "event_source" in events.columns
    assert set(events["augmentation_type"].astype(str).tolist()).issubset(
        {"entity_tagging", "temporal_expression_tagging"}
    )


@pytest.mark.anyio
async def test_wave3_api_additive_augmentation_meta_on_existing_endpoints(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config = type(config)(
        **{**config.__dict__, "augmentation_ingest_api_key": "top-secret"},
    )
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
    filing_path.write_text("filing payload", encoding="utf-8")
    persist_augmentation_submission(
        config,
        producer_id="ext-annotator",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple"}]},
            }
        ],
        raw_request={"seed": True},
    )
    transport = ASGITransport(app=create_app(config))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        metadata = await client.get("/filings/0000320193-25-000010")
        content = await client.get("/filings/0000320193-25-000010/content")

    assert metadata.status_code == 200
    payload = metadata.json()
    assert "augmentation_meta" in payload
    assert payload["augmentation_meta"]["augmentation_available"] is True
    assert "entity_tagging" in payload["augmentation_meta"]["augmentation_types_present"]
    assert payload["augmentation_meta"]["augmentation_stale"] is False
    assert str(payload["augmentation_meta"]["source_text_version"]).startswith("sha256:")
    assert payload["augmentation_meta"]["target_descriptor"]["canonical_key"] == "0000320193-25-000010"

    assert content.status_code == 200
    assert content.headers["x-m-cache-augmentation-available"] == "true"
    assert "entity_tagging" in content.headers["x-m-cache-augmentation-types-present"]
    assert content.headers["x-m-cache-augmentation-source-text-version"].startswith("sha256:")

    direct_meta = build_api_augmentation_meta(config, "0000320193-25-000010")
    assert direct_meta["augmentation_available"] is True
    assert "entity_tagging" in direct_meta["augmentation_types_present"]
    assert direct_meta["augmentation_stale"] is False
