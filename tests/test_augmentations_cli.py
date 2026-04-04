from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
import pandas as pd

import py_sec_edgar.cli as cli
from py_sec_edgar.augmentation_sidecars import (
    augmentation_items_path,
    augmentation_submissions_path,
    build_augmentation_entity_index,
    persist_augmentation_submission,
    record_submission_lifecycle_transition,
)
from py_sec_edgar.config import load_config


def _seed_submission_pair(tmp_path: Path):
    config = load_config(tmp_path)
    old = persist_augmentation_submission(
        config,
        producer_id="p1",
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
                "payload": {"mentions": [{"text": "Old Apple"}]},
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2025-01-15",
            }
        ],
        raw_request={"n": "old"},
    )
    new = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v2",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple Inc."}]},
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2025-01-15",
            }
        ],
        raw_request={"n": "new"},
    )
    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == old.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == new.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)
    submissions_df = pd.read_parquet(augmentation_submissions_path(config))
    submissions_df.loc[submissions_df["submission_id"] == old.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    submissions_df.loc[submissions_df["submission_id"] == new.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    submissions_df.to_parquet(augmentation_submissions_path(config), index=False)
    build_augmentation_entity_index(config)
    return config, old, new


def test_augmentations_help_includes_commands(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: load_config(tmp_path))
    result = runner.invoke(cli.main, ["augmentations", "--help"])
    assert result.exit_code == 0
    assert "submission" in result.output
    assert "events" in result.output
    assert "events-summary" in result.output
    assert "filing-events" in result.output
    assert "lifecycle-events" in result.output
    assert "governance-summary" in result.output
    assert "governance-events" in result.output
    assert "overlay-impact" in result.output
    assert "entity-impact" in result.output
    assert "review-bundle" in result.output


def test_augmentations_submission_and_lifecycle_json(monkeypatch, tmp_path: Path) -> None:
    config, _old, new = _seed_submission_pair(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: config)
    record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state="disabled",
        reason="bad",
        changed_by="ops",
        source="unit",
    )
    runner = CliRunner()
    submission = runner.invoke(cli.main, ["augmentations", "submission", new.submission_id, "--json"])
    lifecycle = runner.invoke(cli.main, ["augmentations", "lifecycle-events", new.submission_id, "--json"])
    assert submission.exit_code == 0
    submission_payload = json.loads(submission.output)
    assert submission_payload["submission_id"] == new.submission_id
    assert submission_payload["lifecycle_state"] == "disabled"
    assert lifecycle.exit_code == 0
    lifecycle_rows = json.loads(lifecycle.output)
    assert len(lifecycle_rows) == 1
    assert lifecycle_rows[0]["to_state"] == "disabled"


def test_augmentations_overlay_entity_and_review_bundle_json(monkeypatch, tmp_path: Path) -> None:
    config, old, new = _seed_submission_pair(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: config)
    runner = CliRunner()

    old_overlay = runner.invoke(cli.main, ["augmentations", "overlay-impact", old.submission_id, "--json"])
    new_overlay = runner.invoke(cli.main, ["augmentations", "overlay-impact", new.submission_id, "--json"])
    entity = runner.invoke(cli.main, ["augmentations", "entity-impact", new.submission_id, "--json"])
    bundle = runner.invoke(
        cli.main,
        [
            "augmentations",
            "review-bundle",
            new.submission_id,
            "--overlay-limit",
            "1",
            "--entity-limit",
            "1",
            "--lifecycle-limit",
            "1",
            "--governance-limit",
            "1",
            "--json",
        ],
    )
    assert old_overlay.exit_code == 0
    old_payload = json.loads(old_overlay.output)
    assert old_payload["rows"][0]["reason_code"] == "superseded_by_winner"

    assert new_overlay.exit_code == 0
    new_payload = json.loads(new_overlay.output)
    assert new_payload["rows"][0]["reason_code"] == "selected"

    assert entity.exit_code == 0
    entity_payload = json.loads(entity.output)
    assert entity_payload["row_count"] >= 1
    assert entity_payload["rows"][0]["entity_normalized"]

    assert bundle.exit_code == 0
    bundle_payload = json.loads(bundle.output)
    assert bundle_payload["submission"]["submission_id"] == new.submission_id
    assert bundle_payload["overlay_impact"]["selection_policy"] == "latest_per_producer_layer_v1"
    assert bundle_payload["overlay_impact"]["returned_count"] <= 1
    assert bundle_payload["entity_impact"]["returned_count"] <= 1


def test_augmentations_generalized_events_and_summary_json(monkeypatch, tmp_path: Path) -> None:
    config, old, new = _seed_submission_pair(tmp_path)
    record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state="disabled",
        reason="bad",
        changed_by="ops",
        source="unit",
    )
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: config)
    runner = CliRunner()

    events = runner.invoke(cli.main, ["augmentations", "events", "--json"])
    filing_events = runner.invoke(
        cli.main,
        ["augmentations", "filing-events", "0000320193-25-000010", "--json"],
    )
    summary = runner.invoke(
        cli.main,
        ["augmentations", "events-summary", "--group-by", "event_family", "--group-by", "event_type", "--json"],
    )

    assert events.exit_code == 0
    events_payload = json.loads(events.output)
    assert "events" in events_payload
    assert any(row["event_family"] == "governance" for row in events_payload["events"])
    assert any(row["event_family"] == "lifecycle" for row in events_payload["events"])

    assert filing_events.exit_code == 0
    filing_payload = json.loads(filing_events.output)
    assert "events" in filing_payload
    assert all("0000320193-25-000010" in row["accession_numbers"] for row in filing_payload["events"])

    assert summary.exit_code == 0
    summary_payload = json.loads(summary.output)
    assert "rows" in summary_payload
    assert len(summary_payload["rows"]) >= 1
