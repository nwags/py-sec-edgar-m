from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from httpx import ASGITransport, AsyncClient

from py_sec_edgar.api.app import create_app
from py_sec_edgar.augmentation_sidecars import (
    augmentation_entity_index_path,
    augmentation_governance_events_path,
    augmentation_submission_lifecycle_events_path,
    augmentation_items_path,
    augmentation_raw_requests_dir,
    augmentation_submissions_path,
)
from py_sec_edgar.config import load_config


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _write_merged_index(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


@pytest.mark.anyio
async def test_admin_augmentation_ingest_returns_503_when_api_key_not_configured(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))

    payload = {
        "producer_id": "ext-annotator",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_tag",
                "payload": {"entities": [{"text": "Apple"}]},
            }
        ],
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/admin/augmentations/submissions", json=payload)

    assert response.status_code == 503
    assert not augmentation_submissions_path(config).exists()
    assert not augmentation_items_path(config).exists()


@pytest.mark.anyio
async def test_admin_augmentation_ingest_enforces_api_key_and_persists_on_success(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))
    payload = {
        "producer_id": "ext-annotator",
        "layer_type": "entities",
        "schema_version": "v1",
        "producer_run_id": "run-001",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_tag",
                "payload": {"entities": [{"text": "Apple", "type": "ORG"}]},
            }
        ],
    }

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.post("/admin/augmentations/submissions", json=payload)
        wrong = await client.post(
            "/admin/augmentations/submissions",
            json=payload,
            headers={"X-API-Key": "wrong"},
        )
        ok = await client.post(
            "/admin/augmentations/submissions",
            json=payload,
            headers={"X-API-Key": "top-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    body = ok.json()
    assert body["item_count"] == 1
    assert Path(body["raw_request_path"]).exists()
    assert augmentation_submissions_path(config).exists()
    assert augmentation_items_path(config).exists()

    submissions_df = pd.read_parquet(augmentation_submissions_path(config))
    items_df = pd.read_parquet(augmentation_items_path(config))
    governance_df = pd.read_parquet(augmentation_governance_events_path(config))
    assert len(submissions_df.index) == 1
    assert len(items_df.index) == 1
    assert len(governance_df.index) == 1
    assert submissions_df.iloc[0]["submission_id"] == body["submission_id"]
    assert items_df.iloc[0]["submission_id"] == body["submission_id"]
    assert Path(body["raw_request_path"]).parent == augmentation_raw_requests_dir(config)


@pytest.mark.anyio
async def test_admin_ingest_invalid_accession_returns_422_and_writes_nothing(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config = type(config)(
        **{**config.__dict__, "augmentation_ingest_api_key": "top-secret"},
    )
    transport = ASGITransport(app=create_app(config))
    payload = {
        "producer_id": "ext-annotator",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "not-an-accession",
                "augmentation_type": "entity_tag",
                "payload": {"entities": []},
            }
        ],
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/admin/augmentations/submissions",
            json=payload,
            headers={"X-API-Key": "top-secret"},
        )

    assert response.status_code == 422
    assert not augmentation_submissions_path(config).exists()
    assert not augmentation_items_path(config).exists()


@pytest.mark.anyio
async def test_admin_ingest_unresolved_accession_returns_404_and_writes_nothing(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config = type(config)(
        **{**config.__dict__, "augmentation_ingest_api_key": "top-secret"},
    )
    transport = ASGITransport(app=create_app(config))
    payload = {
        "producer_id": "ext-annotator",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_tag",
                "payload": {"entities": []},
            }
        ],
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/admin/augmentations/submissions",
            json=payload,
            headers={"X-API-Key": "top-secret"},
        )

    assert response.status_code == 404
    assert not augmentation_submissions_path(config).exists()
    assert not augmentation_items_path(config).exists()


@pytest.mark.anyio
async def test_public_augmentation_reads_and_metadata_overlay_are_optional(tmp_path: Path) -> None:
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
    filing_path.write_text("canonical filing body", encoding="utf-8")

    transport = ASGITransport(app=create_app(config))
    payload = {
        "producer_id": "ext-annotator",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_tag",
                "payload": {"entities": [{"text": "Apple", "type": "ORG"}]},
            }
        ],
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        ingest = await client.post(
            "/admin/augmentations/submissions",
            json=payload,
            headers={"X-API-Key": "top-secret"},
        )
        submission_id = ingest.json()["submission_id"]
        # newer submission for same producer/layer should win resolved overlay selection
        newer = await client.post(
            "/admin/augmentations/submissions",
            json={
                **payload,
                "schema_version": "v2",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "entity_tag",
                        "payload": {"entities": [{"text": "Apple Inc.", "type": "ORG"}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        newer_submission_id = newer.json()["submission_id"]
        other_layer = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "ext-annotator",
                "layer_type": "temporal",
                "schema_version": "v1",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "temporal_expressions",
                        "payload": {"times": [{"text": "tomorrow", "normalized": "2025-01-16"}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        other_layer_submission_id = other_layer.json()["submission_id"]

        # Force deterministic received_at ordering across rapid test submissions.
        items_df = pd.read_parquet(augmentation_items_path(config))
        items_df.loc[items_df["submission_id"] == submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        items_df.loc[items_df["submission_id"] == newer_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        items_df.loc[items_df["submission_id"] == other_layer_submission_id, "received_at"] = "2026-01-01T00:00:05Z"
        items_df.to_parquet(augmentation_items_path(config), index=False)

        submissions_df = pd.read_parquet(augmentation_submissions_path(config))
        submissions_df.loc[submissions_df["submission_id"] == submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        submissions_df.loc[submissions_df["submission_id"] == newer_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        submissions_df.loc[submissions_df["submission_id"] == other_layer_submission_id, "received_at"] = "2026-01-01T00:00:05Z"
        submissions_df.to_parquet(augmentation_submissions_path(config), index=False)

        plain_metadata = await client.get("/filings/0000320193-25-000010")
        overlay_metadata = await client.get("/filings/0000320193-25-000010?include_augmentations=true")
        resolved_overlay_metadata = await client.get(
            "/filings/0000320193-25-000010?include_augmentations=true&augmentation_view=resolved"
        )
        all_augmentations = await client.get("/filings/0000320193-25-000010/augmentations")
        filtered_by_schema = await client.get(
            "/filings/0000320193-25-000010/augmentations"
            "?augmentation_type=entity_tag&schema_version=v2&received_at_from=2026-01-01T00:00:10Z&received_at_to=2026-01-01T00:00:10Z"
            "&include_submission_metadata=true"
        )
        filtered = await client.get(
            f"/filings/0000320193-25-000010/augmentations?submission_id={submission_id}"
            "&producer_id=ext-annotator&layer_type=entities&latest_submission_only=true&limit=1"
        )
        resolved_overlay = await client.get(
            "/filings/0000320193-25-000010/overlay"
            "?received_at_from=2026-01-01T00:00:00Z&received_at_to=2026-01-01T00:00:10Z"
            "&include_submission_metadata=true"
        )
        resolved_entities_overlay = await client.get(
            "/filings/0000320193-25-000010/overlay?producer_id=ext-annotator&layer_type=entities"
        )
        submissions_summary = await client.get(
            "/filings/0000320193-25-000010/augmentation-submissions"
            "?received_at_from=2026-01-01T00:00:00Z&received_at_to=2026-01-01T00:00:10Z"
        )
        bad_time = await client.get(
            "/filings/0000320193-25-000010/augmentations?received_at_from=not-a-time"
        )
        bad_overlay_view = await client.get(
            "/filings/0000320193-25-000010?include_augmentations=true&augmentation_view=invalid"
        )
        content = await client.get("/filings/0000320193-25-000010/content")

    assert plain_metadata.status_code == 200
    assert "augmentations" not in plain_metadata.json() or plain_metadata.json()["augmentations"] is None

    assert overlay_metadata.status_code == 200
    overlay = overlay_metadata.json()["augmentations"]
    assert isinstance(overlay, list)
    assert len(overlay) == 3
    assert {row["submission_id"] for row in overlay} == {
        submission_id,
        newer_submission_id,
        other_layer_submission_id,
    }

    assert resolved_overlay_metadata.status_code == 200
    resolved_overlay_meta_rows = resolved_overlay_metadata.json()["augmentations"]
    assert len(resolved_overlay_meta_rows) == 2
    assert {(row["producer_id"], row["layer_type"]) for row in resolved_overlay_meta_rows} == {
        ("ext-annotator", "entities"),
        ("ext-annotator", "temporal"),
    }
    assert newer_submission_id in {row["submission_id"] for row in resolved_overlay_meta_rows}
    assert submission_id not in {row["submission_id"] for row in resolved_overlay_meta_rows}

    assert all_augmentations.status_code == 200
    all_rows = all_augmentations.json()["augmentations"]
    assert len(all_rows) == 3
    assert all("raw_request_path" not in row for row in all_rows)
    assert filtered_by_schema.status_code == 200
    filtered_schema_rows = filtered_by_schema.json()["augmentations"]
    assert len(filtered_schema_rows) == 1
    assert filtered_schema_rows[0]["submission_id"] == newer_submission_id
    assert "producer_run_id" not in filtered_schema_rows[0]
    assert "raw_request_path" in filtered_schema_rows[0]
    assert filtered.status_code == 200
    filtered_rows = filtered.json()["augmentations"]
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["submission_id"] == submission_id

    assert resolved_overlay.status_code == 200
    resolved_payload = resolved_overlay.json()
    assert resolved_payload["selection_policy"] == "latest_per_producer_layer_v1"
    assert len(resolved_payload["selected_submission_keys"]) == 2
    assert len(resolved_payload["augmentations"]) == 2
    assert newer_submission_id in {row["submission_id"] for row in resolved_payload["augmentations"]}
    assert submission_id not in {row["submission_id"] for row in resolved_payload["augmentations"]}
    assert all("raw_request_path" in row for row in resolved_payload["augmentations"])

    assert resolved_entities_overlay.status_code == 200
    resolved_entities_rows = resolved_entities_overlay.json()["augmentations"]
    assert len(resolved_entities_rows) == 1
    assert resolved_entities_rows[0]["submission_id"] == newer_submission_id
    assert resolved_entities_rows[0]["layer_type"] == "entities"

    assert submissions_summary.status_code == 200
    submission_rows = submissions_summary.json()["submissions"]
    assert len(submission_rows) == 3
    assert submission_rows[0]["submission_id"] == newer_submission_id
    assert submission_rows[1]["submission_id"] == other_layer_submission_id
    assert submission_rows[2]["submission_id"] == submission_id
    assert all("item_count_for_accession" in row for row in submission_rows)

    assert bad_time.status_code == 422
    assert bad_overlay_view.status_code == 422

    assert content.status_code == 200
    assert content.text == "canonical filing body"


@pytest.mark.anyio
async def test_governance_and_lifecycle_api_surfaces(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))
    payload_bad = {
        "producer_id": "p1",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "unknown_family",
                "payload": {"x": 1},
            }
        ],
    }
    payload_good = {
        "producer_id": "p2",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"t": "Apple"}]},
            }
        ],
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad = await client.post(
            "/admin/augmentations/submissions",
            json=payload_bad,
            headers={"X-API-Key": "top-secret"},
        )
        good = await client.post(
            "/admin/augmentations/submissions",
            json=payload_good,
            headers={"X-API-Key": "top-secret"},
        )
        bad_submission_id = bad.json()["submission_id"]
        good_submission_id = good.json()["submission_id"]

        items_df = pd.read_parquet(augmentation_items_path(config))
        items_df.loc[items_df["submission_id"] == bad_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        items_df.loc[items_df["submission_id"] == good_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        items_df.to_parquet(augmentation_items_path(config), index=False)
        submissions_df = pd.read_parquet(augmentation_submissions_path(config))
        submissions_df.loc[submissions_df["submission_id"] == bad_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        submissions_df.loc[submissions_df["submission_id"] == good_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        submissions_df.to_parquet(augmentation_submissions_path(config), index=False)
        gov_df = pd.read_parquet(augmentation_governance_events_path(config))
        gov_df.loc[gov_df["submission_id"] == bad_submission_id, "event_time"] = "2026-01-01T00:00:00Z"
        gov_df.loc[gov_df["submission_id"] == good_submission_id, "event_time"] = "2026-01-01T00:00:10Z"
        gov_df.to_parquet(augmentation_governance_events_path(config), index=False)

        filing_gov = await client.get(
            "/filings/0000320193-25-000010/governance-events?warning_code=gov_unknown_family"
        )
        global_gov = await client.get(
            "/augmentations/governance-events?producer_id=p1&received_at_from=2026-01-01T00:00:00Z&received_at_to=2026-01-01T00:00:10Z"
        )
        cross_submissions = await client.get(
            "/augmentations/submissions?has_governance_warnings=true"
        )
        disable = await client.post(
            f"/admin/augmentations/submissions/{good_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled", "reason": "bad", "changed_by": "ops", "source": "api_test"},
        )
        overlay = await client.get("/filings/0000320193-25-000010/overlay")
        lifecycle_filtered = await client.get(
            "/augmentations/submissions?lifecycle_state=disabled"
        )
        invalid_transition = await client.post(
            f"/admin/augmentations/submissions/{good_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled"},
        )

    assert filing_gov.status_code == 200
    filing_events = filing_gov.json()["events"]
    assert len(filing_events) >= 1
    assert all("warning_codes" in row for row in filing_events)
    assert all("gov_unknown_family" in row["warning_codes"] for row in filing_events)

    assert global_gov.status_code == 200
    global_events = global_gov.json()["events"]
    assert len(global_events) >= 1
    assert all(row["producer_id"] == "p1" for row in global_events)

    assert cross_submissions.status_code == 200
    cross_rows = cross_submissions.json()["submissions"]
    assert len(cross_rows) >= 1
    assert all(row["warning_item_count"] > 0 for row in cross_rows)

    assert disable.status_code == 200
    disable_payload = disable.json()
    assert disable_payload["from_state"] == "active"
    assert disable_payload["to_state"] == "disabled"

    assert overlay.status_code == 200
    overlay_rows = overlay.json()["augmentations"]
    assert len(overlay_rows) == 1
    assert overlay_rows[0]["submission_id"] == bad_submission_id

    assert lifecycle_filtered.status_code == 200
    lifecycle_rows = lifecycle_filtered.json()["submissions"]
    assert len(lifecycle_rows) == 1
    assert lifecycle_rows[0]["submission_id"] == good_submission_id
    assert lifecycle_rows[0]["lifecycle_state"] == "disabled"

    assert invalid_transition.status_code == 422


@pytest.mark.anyio
async def test_entity_search_endpoint_is_overlay_backed_and_lifecycle_aware(tmp_path: Path) -> None:
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
            },
            {
                "CIK": "789019",
                "Form Type": "10-K",
                "Date Filed": "2025-01-10",
                "Filename": "edgar/data/789019/0000789019-25-000123.txt",
            },
        ],
    )
    transport = ASGITransport(app=create_app(config))
    base_payload = {
        "producer_id": "ext-annotator",
        "layer_type": "entities",
        "schema_version": "v1",
        "items": [
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple Inc."}, {"text": "Apple"}]},
            }
        ],
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/admin/augmentations/submissions",
            json={**base_payload, "items": [{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": [{"text": "Old Apple"}]}}]},
            headers={"X-API-Key": "top-secret"},
        )
        second = await client.post(
            "/admin/augmentations/submissions",
            json=base_payload,
            headers={"X-API-Key": "top-secret"},
        )
        second_submission_id = second.json()["submission_id"]
        third = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "ext-annotator",
                "layer_type": "entities",
                "schema_version": "v1",
                "items": [
                    {
                        "accession_number": "0000789019-25-000123",
                        "augmentation_type": "entity_links",
                        "payload": {"links": [{"text": "Microsoft", "entity_id": "ORG:msft"}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 200
        assert augmentation_entity_index_path(config).exists()

        first_submission_id = first.json()["submission_id"]
        third_submission_id = third.json()["submission_id"]
        items_df = pd.read_parquet(augmentation_items_path(config))
        items_df.loc[items_df["submission_id"] == first_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        items_df.loc[items_df["submission_id"] == second_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        items_df.loc[items_df["submission_id"] == third_submission_id, "received_at"] = "2026-01-01T00:00:05Z"
        items_df.to_parquet(augmentation_items_path(config), index=False)
        submissions_df = pd.read_parquet(augmentation_submissions_path(config))
        submissions_df.loc[submissions_df["submission_id"] == first_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        submissions_df.loc[submissions_df["submission_id"] == second_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        submissions_df.loc[submissions_df["submission_id"] == third_submission_id, "received_at"] = "2026-01-01T00:00:05Z"
        submissions_df.to_parquet(augmentation_submissions_path(config), index=False)
        disable_second = await client.post(
            f"/admin/augmentations/submissions/{second_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled", "reason": "normalize-order", "changed_by": "test", "source": "api_test"},
        )
        assert disable_second.status_code == 200
        enable_second = await client.post(
            f"/admin/augmentations/submissions/{second_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "active", "reason": "normalize-order", "changed_by": "test", "source": "api_test"},
        )
        assert enable_second.status_code == 200

        apple = await client.get("/filings/search?entity_text=apple")
        assert apple.status_code == 200
        apple_rows = apple.json()["results"]
        assert len(apple_rows) == 1
        assert apple_rows[0]["accession_number"] == "0000320193-25-000010"
        assert int(apple_rows[0]["entity_match_count"]) == 2

        normalized = await client.get("/filings/search?entity_normalized=microsoft")
        assert normalized.status_code == 200
        normalized_rows = normalized.json()["results"]
        assert len(normalized_rows) == 1
        assert normalized_rows[0]["accession_number"] == "0000789019-25-000123"

        filtered = await client.get(
            "/filings/search?entity_text=apple&cik=320193&form_type=8-k&filing_date_from=2025-01-01&filing_date_to=2025-12-31"
        )
        assert filtered.status_code == 200
        filtered_rows = filtered.json()["results"]
        assert len(filtered_rows) == 1
        assert filtered_rows[0]["accession_number"] == "0000320193-25-000010"

        lifecycle_disable = await client.post(
            f"/admin/augmentations/submissions/{second_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled", "reason": "bad_run", "changed_by": "ops", "source": "api_test"},
        )
        assert lifecycle_disable.status_code == 200

        apple_after_disable = await client.get("/filings/search?entity_text=old apple")
        assert apple_after_disable.status_code == 200
        old_rows = apple_after_disable.json()["results"]
        assert len(old_rows) == 1
        assert old_rows[0]["accession_number"] == "0000320193-25-000010"

        apple_new_after_disable = await client.get("/filings/search?entity_text=apple inc")
        assert apple_new_after_disable.status_code == 200
        assert apple_new_after_disable.json()["results"] == []

        bad_cik = await client.get("/filings/search?entity_text=apple&cik=bad")
        bad_date = await client.get("/filings/search?filing_date_from=not-a-date")
        assert bad_cik.status_code == 422
        assert bad_date.status_code == 422


@pytest.mark.anyio
async def test_reviewer_governance_summary_and_submission_surfaces(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "p1",
                "layer_type": "entities",
                "schema_version": "v1",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "unknown_family",
                        "payload": {"x": 1},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        good = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "p2",
                "layer_type": "entities",
                "schema_version": "v1",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "entity_mentions",
                        "payload": {"mentions": [{"text": "Apple"}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        assert bad.status_code == 200
        assert good.status_code == 200
        bad_submission_id = bad.json()["submission_id"]
        good_submission_id = good.json()["submission_id"]

        items_df = pd.read_parquet(augmentation_items_path(config))
        items_df.loc[items_df["submission_id"] == bad_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        items_df.loc[items_df["submission_id"] == good_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        items_df.to_parquet(augmentation_items_path(config), index=False)
        submissions_df = pd.read_parquet(augmentation_submissions_path(config))
        submissions_df.loc[submissions_df["submission_id"] == bad_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        submissions_df.loc[submissions_df["submission_id"] == good_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        submissions_df.to_parquet(augmentation_submissions_path(config), index=False)
        gov_df = pd.read_parquet(augmentation_governance_events_path(config))
        gov_df.loc[gov_df["submission_id"] == bad_submission_id, "event_time"] = "2026-01-01T00:00:00Z"
        gov_df.loc[gov_df["submission_id"] == good_submission_id, "event_time"] = "2026-01-01T00:00:10Z"
        gov_df.to_parquet(augmentation_governance_events_path(config), index=False)

        summary = await client.get(
            "/augmentations/governance-events/summary?event_time_from=2026-01-01T00:00:00Z&event_time_to=2026-01-01T00:00:10Z"
        )
        summary_alias = await client.get(
            "/augmentations/governance-events/summary?received_at_from=2026-01-01T00:00:00Z&received_at_to=2026-01-01T00:00:10Z"
        )
        summary_bad_status = await client.get(
            "/augmentations/governance-events/summary?match_status=nope"
        )
        summary_bad_time = await client.get(
            "/augmentations/governance-events/summary?event_time_from=bad-time"
        )
        cross_submission_filter = await client.get(
            f"/augmentations/submissions?submission_id={good_submission_id}"
        )
        cross_accession_filter = await client.get(
            "/augmentations/submissions?accession_number=0000320193-25-000010"
        )
        submission_detail = await client.get(f"/augmentations/submissions/{good_submission_id}")
        lifecycle_none = await client.get(f"/augmentations/submissions/{good_submission_id}/lifecycle-events")
        lifecycle_disable = await client.post(
            f"/admin/augmentations/submissions/{good_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled", "reason": "bad_run", "changed_by": "ops", "source": "api_test"},
        )
        lifecycle_rows = await client.get(f"/augmentations/submissions/{good_submission_id}/lifecycle-events")
        invalid_transition = await client.post(
            f"/admin/augmentations/submissions/{good_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "superseded"},
        )
        duplicate_transition = await client.post(
            f"/admin/augmentations/submissions/{good_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled"},
        )
        missing_submission = await client.get("/augmentations/submissions/does-not-exist")

    assert summary.status_code == 200
    assert summary_alias.status_code == 200
    summary_rows = summary.json()["rows"]
    assert len(summary_rows) >= 1
    tuples = [(row["warning_code"], str(row.get("family_id")), row["match_status"]) for row in summary_rows]
    assert tuples == sorted(tuples)
    assert summary.json() == summary_alias.json()

    assert summary_bad_status.status_code == 422
    assert summary_bad_status.json()["error"]["code"] == "invalid_match_status"
    assert summary_bad_time.status_code == 422
    assert summary_bad_time.json()["error"]["code"] == "invalid_timestamp"

    assert cross_submission_filter.status_code == 200
    filtered_rows = cross_submission_filter.json()["submissions"]
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["submission_id"] == good_submission_id

    assert cross_accession_filter.status_code == 200
    assert len(cross_accession_filter.json()["submissions"]) == 2

    assert submission_detail.status_code == 200
    detail = submission_detail.json()["submission"]
    assert detail["submission_id"] == good_submission_id
    assert "item_count_total" in detail
    assert "warning_item_count" in detail

    assert lifecycle_none.status_code == 200
    assert lifecycle_none.json()["events"] == []
    assert lifecycle_disable.status_code == 200
    assert lifecycle_rows.status_code == 200
    assert len(lifecycle_rows.json()["events"]) == 1
    assert lifecycle_rows.json()["events"][0]["to_state"] == "disabled"

    assert invalid_transition.status_code == 422
    assert invalid_transition.json()["detail"]["code"] == "invalid_lifecycle_transition"
    assert duplicate_transition.status_code == 422
    assert duplicate_transition.json()["detail"]["code"] == "duplicate_lifecycle_state"

    assert missing_submission.status_code == 404
    assert missing_submission.json()["detail"]["code"] == "submission_not_found"


@pytest.mark.anyio
async def test_submission_overlay_entity_and_review_bundle_surfaces(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        old_submission = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "p1",
                "layer_type": "entities",
                "schema_version": "v1",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "entity_mentions",
                        "payload": {"mentions": [{"text": "Old Apple"}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        new_submission = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "p1",
                "layer_type": "entities",
                "schema_version": "v2",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "entity_mentions",
                        "payload": {"mentions": [{"text": "Apple Inc."}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        assert old_submission.status_code == 200
        assert new_submission.status_code == 200
        old_submission_id = old_submission.json()["submission_id"]
        new_submission_id = new_submission.json()["submission_id"]

        items_df = pd.read_parquet(augmentation_items_path(config))
        items_df.loc[items_df["submission_id"] == old_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        items_df.loc[items_df["submission_id"] == new_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        items_df.to_parquet(augmentation_items_path(config), index=False)
        submissions_df = pd.read_parquet(augmentation_submissions_path(config))
        submissions_df.loc[submissions_df["submission_id"] == old_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        submissions_df.loc[submissions_df["submission_id"] == new_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        submissions_df.to_parquet(augmentation_submissions_path(config), index=False)

        old_overlay = await client.get(f"/augmentations/submissions/{old_submission_id}/overlay-impact")
        new_overlay = await client.get(f"/augmentations/submissions/{new_submission_id}/overlay-impact")
        old_entity = await client.get(f"/augmentations/submissions/{old_submission_id}/entity-impact")
        new_entity = await client.get(
            f"/augmentations/submissions/{new_submission_id}/entity-impact?limit=1"
        )
        review_bundle = await client.get(
            f"/augmentations/submissions/{new_submission_id}/review-bundle?overlay_limit=1&entity_limit=1&lifecycle_limit=1&governance_limit=1"
        )
        disable = await client.post(
            f"/admin/augmentations/submissions/{new_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled", "reason": "bad", "changed_by": "ops", "source": "api_test"},
        )
        after_disable = await client.get(f"/augmentations/submissions/{new_submission_id}/overlay-impact")

    assert old_overlay.status_code == 200
    old_rows = old_overlay.json()["rows"]
    assert len(old_rows) == 1
    assert old_rows[0]["reason_code"] == "superseded_by_winner"
    assert old_rows[0]["contributes_to_resolved_overlay"] is False

    assert new_overlay.status_code == 200
    new_rows = new_overlay.json()["rows"]
    assert len(new_rows) == 1
    assert new_rows[0]["reason_code"] == "selected"
    assert new_rows[0]["contributes_to_resolved_overlay"] is True

    assert old_entity.status_code == 200
    assert old_entity.json()["row_count"] == 0
    assert new_entity.status_code == 200
    assert new_entity.json()["row_count"] == 1
    assert len(new_entity.json()["rows"]) == 1

    assert review_bundle.status_code == 200
    bundle = review_bundle.json()
    assert bundle["submission"]["submission_id"] == new_submission_id
    assert bundle["overlay_impact"]["selection_policy"] == "latest_per_producer_layer_v1"
    assert bundle["overlay_impact"]["returned_count"] <= 1
    assert bundle["entity_impact"]["returned_count"] <= 1
    assert bundle["governance_summary"]["returned_count"] <= 1

    assert disable.status_code == 200
    assert after_disable.status_code == 200
    assert after_disable.json()["rows"][0]["reason_code"] == "lifecycle_ineligible"


@pytest.mark.anyio
async def test_generalized_event_endpoints_and_summary(tmp_path: Path) -> None:
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
    transport = ASGITransport(app=create_app(config))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "p1",
                "layer_type": "entities",
                "schema_version": "v1",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "unknown_family",
                        "payload": {"x": 1},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        good = await client.post(
            "/admin/augmentations/submissions",
            json={
                "producer_id": "p1",
                "layer_type": "entities",
                "schema_version": "v2",
                "items": [
                    {
                        "accession_number": "0000320193-25-000010",
                        "augmentation_type": "entity_mentions",
                        "payload": {"mentions": [{"text": "Apple"}]},
                    }
                ],
            },
            headers={"X-API-Key": "top-secret"},
        )
        assert bad.status_code == 200
        assert good.status_code == 200
        bad_submission_id = bad.json()["submission_id"]
        good_submission_id = good.json()["submission_id"]

        items_df = pd.read_parquet(augmentation_items_path(config))
        items_df.loc[items_df["submission_id"] == bad_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        items_df.loc[items_df["submission_id"] == good_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        items_df.to_parquet(augmentation_items_path(config), index=False)
        submissions_df = pd.read_parquet(augmentation_submissions_path(config))
        submissions_df.loc[submissions_df["submission_id"] == bad_submission_id, "received_at"] = "2026-01-01T00:00:00Z"
        submissions_df.loc[submissions_df["submission_id"] == good_submission_id, "received_at"] = "2026-01-01T00:00:10Z"
        submissions_df.to_parquet(augmentation_submissions_path(config), index=False)
        gov_df = pd.read_parquet(augmentation_governance_events_path(config))
        gov_df.loc[gov_df["submission_id"] == bad_submission_id, "event_time"] = "2026-01-01T00:00:00Z"
        gov_df.loc[gov_df["submission_id"] == good_submission_id, "event_time"] = "2026-01-01T00:00:10Z"
        gov_df.to_parquet(augmentation_governance_events_path(config), index=False)

        disable = await client.post(
            f"/admin/augmentations/submissions/{good_submission_id}/lifecycle",
            headers={"X-API-Key": "top-secret"},
            json={"to_state": "disabled", "reason": "bad_run", "changed_by": "ops", "source": "api_test"},
        )
        assert disable.status_code == 200
        lifecycle_df = pd.read_parquet(augmentation_submission_lifecycle_events_path(config))
        lifecycle_df.loc[lifecycle_df["submission_id"] == good_submission_id, "event_time"] = "2026-01-01T00:00:20Z"
        lifecycle_df.to_parquet(augmentation_submission_lifecycle_events_path(config), index=False)

        events = await client.get("/augmentations/events?limit=10")
        filing_events = await client.get("/filings/0000320193-25-000010/events?limit=10")
        summary = await client.get(
            "/augmentations/events/summary?group_by=event_family&group_by=event_type&group_by=warning_code"
        )
        filtered = await client.get(
            "/augmentations/events?event_family=lifecycle&to_state=disabled"
        )
        alias_time = await client.get(
            "/augmentations/events?received_at_from=2026-01-01T00:00:00Z&received_at_to=2026-01-01T00:00:20Z"
        )
        invalid_family = await client.get("/augmentations/events?event_family=nope")
        invalid_type = await client.get("/augmentations/events?event_type=nope")
        invalid_group = await client.get("/augmentations/events/summary?group_by=family_id")
        missing_submission = await client.get("/augmentations/events?submission_id=missing-submission")

    assert events.status_code == 200
    rows = events.json()["events"]
    assert len(rows) >= 3
    ordering = [(row["event_time"], row["event_family"], row["event_id"]) for row in rows]
    assert ordering == sorted(
        ordering,
        key=lambda value: (-int(pd.to_datetime(value[0], utc=True).value), value[1], value[2]),
    )
    lifecycle_rows = [row for row in rows if row["event_family"] == "lifecycle"]
    assert lifecycle_rows[0]["event_type"] == "submission_lifecycle_transition"
    assert lifecycle_rows[0]["event_source"] == "augmentation_submission_lifecycle_events_v1"
    assert lifecycle_rows[0]["accession_numbers"] == sorted(set(lifecycle_rows[0]["accession_numbers"]))

    governance_rows = [row for row in rows if row["event_family"] == "governance"]
    first_governance = governance_rows[0]
    expected_event_id = "|".join(
        [
            first_governance["event_time"],
            first_governance["submission_id"],
            str(first_governance["item_index"]),
            first_governance["accession_numbers"][0],
            str(first_governance["producer_id"] or ""),
            str(first_governance["layer_type"] or ""),
            str(first_governance["augmentation_type"] or ""),
            str(first_governance["schema_version"] or ""),
            str(first_governance["contract_version_id"] or ""),
        ]
    )
    assert first_governance["event_id"] == expected_event_id

    assert filing_events.status_code == 200
    filing_rows = filing_events.json()["events"]
    assert len(filing_rows) >= 1
    assert all("0000320193-25-000010" in row["accession_numbers"] for row in filing_rows)

    assert filtered.status_code == 200
    assert all(row["event_family"] == "lifecycle" for row in filtered.json()["events"])
    assert all(row["to_state"] == "disabled" for row in filtered.json()["events"])

    assert summary.status_code == 200
    summary_rows = summary.json()["rows"]
    assert len(summary_rows) >= 2
    summary_keys = [
        (row.get("event_family"), row.get("event_type"), row.get("warning_code"))
        for row in summary_rows
    ]
    assert summary_keys == sorted(
        summary_keys,
        key=lambda value: tuple((item is None, "" if item is None else str(item)) for item in value),
    )

    assert alias_time.status_code == 200
    assert invalid_family.status_code == 422
    assert invalid_family.json()["error"]["code"] == "invalid_event_family"
    assert invalid_type.status_code == 422
    assert invalid_type.json()["error"]["code"] == "invalid_event_type"
    assert invalid_group.status_code == 422
    assert invalid_group.json()["error"]["code"] == "invalid_group_by"
    assert missing_submission.status_code == 404
    assert missing_submission.json()["error"]["code"] == "submission_not_found"
