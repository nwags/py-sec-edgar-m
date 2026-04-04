from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from py_sec_edgar.augmentation_sidecars import (
    EVENT_FAMILY_GOVERNANCE,
    EVENT_FAMILY_LIFECYCLE,
    EVENT_SOURCE_AUGMENTATION_GOVERNANCE_EVENTS_V1,
    EVENT_SOURCE_AUGMENTATION_SUBMISSION_LIFECYCLE_EVENTS_V1,
    EVENT_TYPE_GOVERNANCE_DIAGNOSTIC,
    EVENT_TYPE_SUBMISSION_LIFECYCLE_TRANSITION,
    LIFECYCLE_STATE_ACTIVE,
    LIFECYCLE_STATE_DISABLED,
    LIFECYCLE_STATE_SUPERSEDED,
    SIDE_CAR_ERROR_DUPLICATE_LIFECYCLE_STATE,
    SIDE_CAR_ERROR_INVALID_EVENT_FAMILY,
    SIDE_CAR_ERROR_INVALID_EVENT_TYPE,
    SIDE_CAR_ERROR_INVALID_GROUP_BY,
    SIDE_CAR_ERROR_INVALID_LIFECYCLE_TRANSITION,
    SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND,
    OVERLAY_IMPACT_REASON_LIFECYCLE_INELIGIBLE,
    OVERLAY_IMPACT_REASON_SELECTED,
    OVERLAY_IMPACT_REASON_SUPERSEDED_BY_WINNER,
    SidecarContractError,
    SidecarNotFoundError,
    GOV_WARNING_AUGMENTATION_TYPE_MISMATCH,
    GOV_WARNING_MISSING_RECOMMENDED_PAYLOAD_KEYS,
    GOV_WARNING_UNKNOWN_FAMILY,
    RESOLVED_OVERLAY_SELECTION_POLICY,
    augmentation_entity_index_path,
    augmentation_submission_lifecycle_events_path,
    augmentation_governance_events_path,
    augmentation_items_path,
    augmentation_raw_requests_dir,
    augmentation_submissions_path,
    build_augmentation_entity_index,
    extract_entities_from_payload,
    get_submission_review_bundle,
    list_augmentation_events,
    list_augmentation_submissions_cross_accession,
    list_augmentation_submissions_for_accession,
    list_submission_entity_impact,
    list_submission_lifecycle_events,
    list_submission_overlay_impact,
    list_augmentations_for_accession,
    list_governance_events,
    summarize_augmentation_events,
    summarize_governance_events,
    persist_augmentation_submission,
    record_submission_lifecycle_transition,
    resolve_overlay_for_accession,
    search_filings_by_entity_index,
)
from py_sec_edgar.config import load_config


def test_persist_augmentation_submission_writes_split_artifacts(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    result = persist_augmentation_submission(
        config,
        producer_id="ext-annotator",
        layer_type="entities",
        schema_version="v1",
        producer_run_id="run-1",
        pipeline_id="pipe-a",
        model_id="model-x",
        producer_version="1.2.3",
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_tag",
                "payload_schema_version": "1",
                "payload": {"entities": [{"text": "Apple", "type": "ORG"}]},
                "filename": "edgar/data/320193/0000320193-25-000010.txt",
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2025-01-15",
            }
        ],
        raw_request={"producer_id": "ext-annotator"},
    )

    submissions_df = pd.read_parquet(augmentation_submissions_path(config))
    items_df = pd.read_parquet(augmentation_items_path(config))

    assert len(submissions_df.index) == 1
    assert len(items_df.index) == 1
    assert submissions_df.iloc[0]["submission_id"] == result.submission_id
    assert items_df.iloc[0]["submission_id"] == result.submission_id
    raw_path = Path(result.raw_request_path)
    assert raw_path.exists()
    assert raw_path.parent == augmentation_raw_requests_dir(config)


def test_list_augmentations_filters_and_latest_submission_only(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    first = persist_augmentation_submission(
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
                "augmentation_type": "entity_tag",
                "payload": {"value": 1},
            }
        ],
        raw_request={"submission": 1},
    )
    second = persist_augmentation_submission(
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
                "augmentation_type": "entity_tag",
                "payload": {"value": 2},
            }
        ],
        raw_request={"submission": 2},
    )

    all_rows = list_augmentations_for_accession(config, accession_number="0000320193-25-000010")
    assert len(all_rows) == 2
    assert {row["submission_id"] for row in all_rows} == {first.submission_id, second.submission_id}

    latest_rows = list_augmentations_for_accession(
        config,
        accession_number="0000320193-25-000010",
        latest_submission_only=True,
    )
    assert len(latest_rows) == 1
    assert latest_rows[0]["submission_id"] == all_rows[0]["submission_id"]

    filtered = list_augmentations_for_accession(
        config,
        accession_number="0000320193-25-000010",
        submission_id=second.submission_id,
    )
    assert len(filtered) == 1
    assert filtered[0]["submission_id"] == second.submission_id


def test_deterministic_sort_contracts_for_submissions_and_items(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    persist_augmentation_submission(
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
                "augmentation_type": "entity_tag",
                "payload": {"a": 1},
            },
            {
                "accession_number": "0000789019-25-000123",
                "augmentation_type": "entity_tag",
                "payload": {"a": 2},
            },
        ],
        raw_request={"req": 1},
    )

    persist_augmentation_submission(
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
                "augmentation_type": "entity_tag",
                "payload": {"a": 3},
            }
        ],
        raw_request={"req": 2},
    )

    submissions_df = pd.read_parquet(augmentation_submissions_path(config))
    items_df = pd.read_parquet(augmentation_items_path(config))

    submissions_sorted = submissions_df.sort_values(["received_at", "submission_id"], ascending=[False, True]).reset_index(drop=True)
    items_sorted = items_df.sort_values(
        ["accession_number", "received_at", "submission_id", "item_index"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)

    pd.testing.assert_frame_equal(submissions_df.reset_index(drop=True), submissions_sorted)
    pd.testing.assert_frame_equal(items_df.reset_index(drop=True), items_sorted)

    payload_sample = items_df.iloc[0]["payload_json"]
    loaded = json.loads(str(payload_sample))
    assert isinstance(loaded, dict)


def test_resolved_overlay_selects_latest_per_producer_layer_bucket(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    first = persist_augmentation_submission(
        config,
        producer_id="producer-a",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"rev": 1}}],
        raw_request={"n": 1},
    )
    second = persist_augmentation_submission(
        config,
        producer_id="producer-a",
        layer_type="entities",
        schema_version="v2",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"rev": 2}}],
        raw_request={"n": 2},
    )
    third = persist_augmentation_submission(
        config,
        producer_id="producer-b",
        layer_type="temporal",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "temporal_expressions", "payload": {"rev": 1}}],
        raw_request={"n": 3},
    )

    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == first.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == second.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.loc[items_df["submission_id"] == third.submission_id, "received_at"] = "2026-01-01T00:00:05Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)

    resolved = resolve_overlay_for_accession(config, accession_number="0000320193-25-000010")
    assert resolved.selection_policy == RESOLVED_OVERLAY_SELECTION_POLICY
    assert len(resolved.selected_submission_keys) == 2
    assert len(resolved.augmentations) == 2
    assert [(row["producer_id"], row["layer_type"]) for row in resolved.augmentations] == [
        ("producer-a", "entities"),
        ("producer-b", "temporal"),
    ]
    # producer-a entities should be selected from latest submission only
    producer_a_rows = [row for row in resolved.augmentations if row["producer_id"] == "producer-a"]
    assert len(producer_a_rows) == 1
    assert producer_a_rows[0]["payload"]["rev"] == 2


def test_resolved_overlay_is_deterministic_under_received_at_tie(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    result_a = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"id": "a"}}],
        raw_request={"force": "a"},
    )
    result_b = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"id": "b"}}],
        raw_request={"force": "b"},
    )

    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"].isin([result_a.submission_id, result_b.submission_id]), "received_at"] = "2026-01-01T00:00:00Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)

    resolved = resolve_overlay_for_accession(config, accession_number="0000320193-25-000010")
    winner_id = min(result_a.submission_id, result_b.submission_id)
    assert resolved.selected_submission_keys[0]["submission_id"] == winner_id
    assert resolved.augmentations[0]["submission_id"] == winner_id


def test_governance_events_persist_with_stable_warning_codes(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    persist_augmentation_submission(
        config,
        producer_id="p",
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
            },
            {
                "accession_number": "0000320193-25-000011",
                "augmentation_type": "totally_unknown",
                "payload": {"x": 1},
            },
            {
                "accession_number": "0000320193-25-000012",
                "augmentation_type": "entity_links",
                "payload": {"bad": True},
            },
        ],
        raw_request={"n": 1},
    )
    events_df = pd.read_parquet(augmentation_governance_events_path(config))
    assert len(events_df.index) == 3
    assert list(events_df.columns) == [
        "event_time",
        "contract_version_id",
        "submission_id",
        "item_index",
        "accession_number",
        "producer_id",
        "layer_type",
        "augmentation_type",
        "schema_version",
        "family_id",
        "family_inferred",
        "match_status",
        "warning_codes_json",
        "warning_messages_json",
    ]
    row_by_index = {int(row["item_index"]): row for row in events_df.to_dict(orient="records")}
    matched_codes = json.loads(str(row_by_index[0]["warning_codes_json"]))
    assert matched_codes == []
    assert row_by_index[0]["match_status"] == "match"

    unknown_codes = json.loads(str(row_by_index[1]["warning_codes_json"]))
    assert unknown_codes == [GOV_WARNING_UNKNOWN_FAMILY]
    assert row_by_index[1]["match_status"] == "unknown"

    warning_codes = json.loads(str(row_by_index[2]["warning_codes_json"]))
    assert GOV_WARNING_AUGMENTATION_TYPE_MISMATCH not in warning_codes
    assert GOV_WARNING_MISSING_RECOMMENDED_PAYLOAD_KEYS in warning_codes
    assert row_by_index[2]["match_status"] == "warning"


def test_history_and_overlay_filters_and_metadata_enrichment(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    old = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="entities",
        schema_version="v1",
        producer_run_id="run-old",
        pipeline_id="pipe-1",
        model_id="m-1",
        producer_version="1.0",
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"r": "old"},
    )
    new = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="entities",
        schema_version="v2",
        producer_run_id="run-new",
        pipeline_id="pipe-1",
        model_id="m-2",
        producer_version="2.0",
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": [{"t": 1}]}}],
        raw_request={"r": "new"},
    )
    temporal = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="temporal",
        schema_version="v1",
        producer_run_id="run-time",
        pipeline_id="pipe-2",
        model_id="m-3",
        producer_version="1.0",
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "temporal_expressions", "payload": {"expressions": []}}],
        raw_request={"r": "time"},
    )
    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == old.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == new.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.loc[items_df["submission_id"] == temporal.submission_id, "received_at"] = "2026-01-01T00:00:05Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)

    history = list_augmentations_for_accession(
        config,
        accession_number="0000320193-25-000010",
        augmentation_type="entity_mentions",
        schema_version="v2",
        received_at_from="2026-01-01T00:00:10Z",
        received_at_to="2026-01-01T00:00:10Z",
        include_submission_metadata=True,
    )
    assert len(history) == 1
    assert history[0]["submission_id"] == new.submission_id
    assert history[0]["producer_run_id"] == "run-new"
    assert history[0]["raw_request_path"]

    overlay = resolve_overlay_for_accession(
        config,
        accession_number="0000320193-25-000010",
        received_at_from="2026-01-01T00:00:00Z",
        received_at_to="2026-01-01T00:00:10Z",
        include_submission_metadata=True,
    )
    assert len(overlay.augmentations) == 2
    entity_rows = [r for r in overlay.augmentations if r["layer_type"] == "entities"]
    assert len(entity_rows) == 1
    assert entity_rows[0]["submission_id"] == new.submission_id
    assert entity_rows[0]["producer_run_id"] == "run-new"


def test_submission_summary_endpoint_source_function_returns_submission_rows(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    first = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id="r1",
        pipeline_id=None,
        model_id=None,
        producer_version="1",
        items=[
            {"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}},
            {"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": [{"x": 1}]}}
        ],
        raw_request={"n": 1},
    )
    second = persist_augmentation_submission(
        config,
        producer_id="p2",
        layer_type="temporal",
        schema_version="v1",
        producer_run_id="r2",
        pipeline_id=None,
        model_id=None,
        producer_version="1",
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "temporal_expressions", "payload": {"expressions": []}}],
        raw_request={"n": 2},
    )
    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == first.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == second.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)
    submissions_df = pd.read_parquet(augmentation_submissions_path(config))
    submissions_df.loc[submissions_df["submission_id"] == first.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    submissions_df.loc[submissions_df["submission_id"] == second.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    submissions_df.to_parquet(augmentation_submissions_path(config), index=False)

    out = list_augmentation_submissions_for_accession(
        config,
        accession_number="0000320193-25-000010",
        received_at_from="2026-01-01T00:00:00Z",
        received_at_to="2026-01-01T00:00:10Z",
    )
    assert len(out) == 2
    assert out[0].submission_id == second.submission_id
    assert out[0].item_count_for_accession == 1
    assert out[1].submission_id == first.submission_id
    assert out[1].item_count_for_accession == 2


def test_governance_events_query_filters_and_ordering(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    first = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "unknown_x", "payload": {"x": 1}}],
        raw_request={"r": 1},
    )
    second = persist_augmentation_submission(
        config,
        producer_id="p2",
        layer_type="temporal",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000011", "augmentation_type": "temporal_expressions", "payload": {"expressions": []}}],
        raw_request={"r": 2},
    )
    events_df = pd.read_parquet(augmentation_governance_events_path(config))
    events_df.loc[events_df["submission_id"] == first.submission_id, "event_time"] = "2026-01-01T00:00:00Z"
    events_df.loc[events_df["submission_id"] == second.submission_id, "event_time"] = "2026-01-01T00:00:10Z"
    events_df.to_parquet(augmentation_governance_events_path(config), index=False)

    rows = list_governance_events(
        config,
        warning_code=GOV_WARNING_UNKNOWN_FAMILY,
        received_at_from="2026-01-01T00:00:00Z",
        received_at_to="2026-01-01T00:00:10Z",
    )
    assert len(rows) == 1
    assert rows[0].submission_id == first.submission_id
    assert rows[0].warning_codes == [GOV_WARNING_UNKNOWN_FAMILY]


def test_lifecycle_events_and_overlay_eligibility(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    old = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": [{"v": 1}]}}],
        raw_request={"r": "old"},
    )
    new = persist_augmentation_submission(
        config,
        producer_id="p",
        layer_type="entities",
        schema_version="v2",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": [{"v": 2}]}}],
        raw_request={"r": "new"},
    )
    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == old.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == new.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)

    before = resolve_overlay_for_accession(config, accession_number="0000320193-25-000010")
    assert len(before.augmentations) == 1
    assert before.augmentations[0]["submission_id"] == new.submission_id

    event = record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state=LIFECYCLE_STATE_DISABLED,
        reason="bad_run",
        changed_by="tester",
        source="unit_test",
    )
    assert event["from_state"] == LIFECYCLE_STATE_ACTIVE
    assert event["to_state"] == LIFECYCLE_STATE_DISABLED
    lifecycle_df = pd.read_parquet(augmentation_submission_lifecycle_events_path(config))
    assert len(lifecycle_df.index) == 1

    after = resolve_overlay_for_accession(config, accession_number="0000320193-25-000010")
    assert len(after.augmentations) == 1
    assert after.augmentations[0]["submission_id"] == old.submission_id

    summaries = list_augmentation_submissions_cross_accession(config, lifecycle_state=LIFECYCLE_STATE_DISABLED)
    assert len(summaries) == 1
    assert summaries[0].submission_id == new.submission_id
    assert summaries[0].lifecycle_state == LIFECYCLE_STATE_DISABLED

    acc_summaries = list_augmentation_submissions_for_accession(
        config,
        accession_number="0000320193-25-000010",
        lifecycle_state=LIFECYCLE_STATE_ACTIVE,
    )
    assert len(acc_summaries) == 1
    assert acc_summaries[0].submission_id == old.submission_id
    assert acc_summaries[0].lifecycle_state == LIFECYCLE_STATE_ACTIVE

    with_active = resolve_overlay_for_accession(
        config,
        accession_number="0000320193-25-000010",
        lifecycle_state=LIFECYCLE_STATE_ACTIVE,
    )
    assert len(with_active.augmentations) == 1
    assert with_active.augmentations[0]["submission_id"] == old.submission_id

    record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state=LIFECYCLE_STATE_ACTIVE,
        reason="restore",
        changed_by="tester",
        source="unit_test",
    )
    record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state=LIFECYCLE_STATE_SUPERSEDED,
        reason="superseded",
        changed_by="tester",
        source="unit_test",
    )
    final_state = list_augmentation_submissions_cross_accession(
        config,
        lifecycle_state=LIFECYCLE_STATE_SUPERSEDED,
    )
    assert len(final_state) == 1
    assert final_state[0].submission_id == new.submission_id


def test_extract_entities_from_payload_supports_mentions_and_links() -> None:
    mention_rows = extract_entities_from_payload(
        {
            "mentions": [
                {"text": "Apple Inc.", "type": "ORG"},
                {"entity_text": "Tim Cook", "entity_type": "PERSON"},
            ]
        },
        "entity_mentions",
    )
    assert len(mention_rows) == 2
    assert mention_rows[0]["entity_normalized"] == "apple inc."
    assert mention_rows[1]["entity_type"] == "PERSON"

    link_rows = extract_entities_from_payload(
        {
            "links": [
                {"text": "Apple Inc.", "entity_id": "ORG:apple"},
                {"mention_text": "Cook", "canonical_id": "PERSON:tim-cook"},
            ]
        },
        "entity_links",
    )
    assert len(link_rows) == 2
    assert link_rows[0]["entity_id"] == "ORG:apple"
    assert link_rows[1]["entity_id"] == "PERSON:tim-cook"


def test_extract_entities_from_payload_skips_malformed_values() -> None:
    assert extract_entities_from_payload({"mentions": [{"type": "ORG"}, 123, None]}, "entity_mentions") == []
    assert extract_entities_from_payload("not-a-dict", "entity_mentions") == []
    assert extract_entities_from_payload({"links": [{"entity_id": "x"}]}, "entity_links") == []


def test_build_entity_index_is_resolved_overlay_backed_and_lifecycle_aware(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    old = persist_augmentation_submission(
        config,
        producer_id="producer-a",
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
        raw_request={"n": 1},
    )
    new = persist_augmentation_submission(
        config,
        producer_id="producer-a",
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
        raw_request={"n": 2},
    )
    links = persist_augmentation_submission(
        config,
        producer_id="producer-b",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_links",
                "payload": {"links": [{"text": "Apple Inc.", "entity_id": "ORG:apple"}]},
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2025-01-15",
            }
        ],
        raw_request={"n": 3},
    )
    persist_augmentation_submission(
        config,
        producer_id="producer-b",
        layer_type="temporal",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "temporal_expressions",
                "payload": {"expressions": [{"text": "tomorrow"}]},
            }
        ],
        raw_request={"n": 4},
    )

    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == old.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == new.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.loc[items_df["submission_id"] == links.submission_id, "received_at"] = "2026-01-01T00:00:05Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)

    result = build_augmentation_entity_index(config)
    assert result["entity_row_count"] == 2
    entity_df = pd.read_parquet(augmentation_entity_index_path(config))
    assert len(entity_df.index) == 2
    assert set(entity_df["augmentation_type"].astype(str).tolist()) == {"entity_mentions", "entity_links"}
    assert "temporal_expressions" not in set(entity_df["augmentation_type"].astype(str).tolist())
    assert old.submission_id not in set(entity_df["submission_id"].astype(str).tolist())
    assert new.submission_id in set(entity_df["submission_id"].astype(str).tolist())

    first_pass = entity_df.copy()
    second_result = build_augmentation_entity_index(config)
    second_pass = pd.read_parquet(augmentation_entity_index_path(config))
    assert second_result["entity_row_count"] == result["entity_row_count"]
    pd.testing.assert_frame_equal(first_pass.reset_index(drop=True), second_pass.reset_index(drop=True))

    record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state=LIFECYCLE_STATE_DISABLED,
        reason="disable winner",
        changed_by="tester",
        source="unit_test",
    )
    build_augmentation_entity_index(config)
    after_disable = pd.read_parquet(augmentation_entity_index_path(config))
    assert new.submission_id not in set(after_disable["submission_id"].astype(str).tolist())
    assert old.submission_id in set(after_disable["submission_id"].astype(str).tolist())


def test_search_filings_by_entity_index_filters_and_sorts_distinct_filings(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    persist_augmentation_submission(
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
                "payload": {"mentions": [{"text": "Apple Inc."}, {"text": "Apple"}]},
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2025-01-15",
            },
            {
                "accession_number": "0000789019-25-000123",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Microsoft"}]},
                "filing_cik": "0000789019",
                "form_type": "10-K",
                "filing_date": "2025-01-10",
            },
        ],
        raw_request={"n": 1},
    )
    build_augmentation_entity_index(config)

    rows = search_filings_by_entity_index(config, entity_text="apple")
    assert len(rows) == 1
    assert rows[0]["accession_number"] == "0000320193-25-000010"
    assert int(rows[0]["entity_match_count"]) == 2

    exact = search_filings_by_entity_index(config, entity_normalized="microsoft")
    assert len(exact) == 1
    assert exact[0]["accession_number"] == "0000789019-25-000123"

    filtered = search_filings_by_entity_index(config, entity_text="apple", cik="320193", form_type="8-k")
    assert len(filtered) == 1
    assert filtered[0]["accession_number"] == "0000320193-25-000010"

    by_date = search_filings_by_entity_index(config, filing_date_from="2025-01-12")
    assert len(by_date) == 1
    assert by_date[0]["accession_number"] == "0000320193-25-000010"


def test_governance_summary_is_deterministic_and_filterable(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    bad = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "unknown_family", "payload": {"x": 1}}],
        raw_request={"n": 1},
    )
    good = persist_augmentation_submission(
        config,
        producer_id="p2",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"n": 2},
    )
    events_df = pd.read_parquet(augmentation_governance_events_path(config))
    events_df.loc[events_df["submission_id"] == bad.submission_id, "event_time"] = "2026-01-01T00:00:00Z"
    events_df.loc[events_df["submission_id"] == good.submission_id, "event_time"] = "2026-01-01T00:00:10Z"
    events_df.to_parquet(augmentation_governance_events_path(config), index=False)

    rows = summarize_governance_events(
        config,
        received_at_from="2026-01-01T00:00:00Z",
        received_at_to="2026-01-01T00:00:10Z",
    )
    assert len(rows) >= 2
    ordered = sorted(
        [(row.warning_code, str(row.family_id), row.match_status) for row in rows],
        key=lambda x: (x[0], x[1], x[2]),
    )
    assert [(row.warning_code, str(row.family_id), row.match_status) for row in rows] == ordered

    by_warning = summarize_governance_events(
        config,
        warning_code=GOV_WARNING_UNKNOWN_FAMILY,
        event_time_from="2026-01-01T00:00:00Z",
        event_time_to="2026-01-01T00:00:10Z",
    )
    assert len(by_warning) == 1
    assert by_warning[0].warning_code == GOV_WARNING_UNKNOWN_FAMILY
    assert by_warning[0].event_count >= 1


def test_cross_accession_submission_filters_for_submission_and_accession(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    first = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"n": 1},
    )
    second = persist_augmentation_submission(
        config,
        producer_id="p2",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000789019-25-000123", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"n": 2},
    )
    by_submission = list_augmentation_submissions_cross_accession(config, submission_id=first.submission_id)
    assert len(by_submission) == 1
    assert by_submission[0].submission_id == first.submission_id

    by_accession = list_augmentation_submissions_cross_accession(config, accession_number="0000789019-25-000123")
    assert len(by_accession) == 1
    assert by_accession[0].submission_id == second.submission_id


def test_lifecycle_events_and_error_codes_are_stable(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    result = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"n": 1},
    )
    first = record_submission_lifecycle_transition(
        config,
        submission_id=result.submission_id,
        to_state=LIFECYCLE_STATE_DISABLED,
        reason="bad",
        changed_by="test",
        source="unit",
    )
    with pytest.raises(SidecarContractError) as invalid_exc:
        record_submission_lifecycle_transition(
            config,
            submission_id=result.submission_id,
            to_state=LIFECYCLE_STATE_SUPERSEDED,
            reason="bad",
            changed_by="test",
            source="unit",
        )
    assert invalid_exc.value.code == SIDE_CAR_ERROR_INVALID_LIFECYCLE_TRANSITION

    second = record_submission_lifecycle_transition(
        config,
        submission_id=result.submission_id,
        to_state=LIFECYCLE_STATE_ACTIVE,
        reason="restore",
        changed_by="test",
        source="unit",
    )
    events = list_submission_lifecycle_events(config, submission_id=result.submission_id)
    assert len(events) == 2
    assert events[0].event_time >= events[1].event_time
    if events[0].event_time == events[1].event_time:
        assert events[0].lifecycle_event_id <= events[1].lifecycle_event_id
    assert {events[0].to_state, events[1].to_state} == {first["to_state"], second["to_state"]}

    with pytest.raises(SidecarContractError) as dup_exc:
        record_submission_lifecycle_transition(
            config,
            submission_id=result.submission_id,
            to_state=LIFECYCLE_STATE_ACTIVE,
            reason="noop",
            changed_by="test",
            source="unit",
        )
    assert dup_exc.value.code == SIDE_CAR_ERROR_DUPLICATE_LIFECYCLE_STATE

    with pytest.raises(SidecarNotFoundError) as missing_exc:
        list_submission_lifecycle_events(config, submission_id="missing-id")
    assert missing_exc.value.code == SIDE_CAR_ERROR_SUBMISSION_NOT_FOUND


def test_unified_events_and_summary_contracts_are_deterministic(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    bad = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "unknown_family", "payload": {"x": 1}}],
        raw_request={"n": 1},
    )
    good = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v2",
        producer_run_id=None,
        pipeline_id=None,
        model_id=None,
        producer_version=None,
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"n": 2},
    )
    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == bad.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == good.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)
    submissions_df = pd.read_parquet(augmentation_submissions_path(config))
    submissions_df.loc[submissions_df["submission_id"] == bad.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    submissions_df.loc[submissions_df["submission_id"] == good.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    submissions_df.to_parquet(augmentation_submissions_path(config), index=False)
    gov_df = pd.read_parquet(augmentation_governance_events_path(config))
    gov_df.loc[gov_df["submission_id"] == bad.submission_id, "event_time"] = "2026-01-01T00:00:00Z"
    gov_df.loc[gov_df["submission_id"] == good.submission_id, "event_time"] = "2026-01-01T00:00:10Z"
    gov_df.to_parquet(augmentation_governance_events_path(config), index=False)
    record_submission_lifecycle_transition(
        config,
        submission_id=good.submission_id,
        to_state=LIFECYCLE_STATE_DISABLED,
        reason="bad",
        changed_by="ops",
        source="unit",
    )
    lifecycle_df = pd.read_parquet(augmentation_submission_lifecycle_events_path(config))
    lifecycle_df.loc[lifecycle_df["submission_id"] == good.submission_id, "event_time"] = "2026-01-01T00:00:20Z"
    lifecycle_df.to_parquet(augmentation_submission_lifecycle_events_path(config), index=False)

    events = list_augmentation_events(config)
    assert len(events) >= 3
    ordered = [
        (row.event_time, row.event_family, row.event_id)
        for row in events
    ]
    assert ordered == sorted(
        ordered,
        key=lambda value: (-int(pd.to_datetime(value[0], utc=True).value), value[1], value[2]),
    )
    assert events[0].event_family == EVENT_FAMILY_LIFECYCLE
    assert events[0].event_type == EVENT_TYPE_SUBMISSION_LIFECYCLE_TRANSITION
    assert events[0].event_source == EVENT_SOURCE_AUGMENTATION_SUBMISSION_LIFECYCLE_EVENTS_V1
    assert events[0].event_id == str(lifecycle_df.iloc[0]["lifecycle_event_id"])
    assert events[0].accession_numbers == ["0000320193-25-000010"]

    gov_rows = list_augmentation_events(
        config,
        event_family=EVENT_FAMILY_GOVERNANCE,
        event_type=EVENT_TYPE_GOVERNANCE_DIAGNOSTIC,
        event_source=EVENT_SOURCE_AUGMENTATION_GOVERNANCE_EVENTS_V1,
        warning_code=GOV_WARNING_UNKNOWN_FAMILY,
    )
    assert len(gov_rows) == 1
    expected_event_id = "|".join(
        [
            "2026-01-01T00:00:00Z",
            bad.submission_id,
            "0",
            "0000320193-25-000010",
            "p1",
            "entities",
            "unknown_family",
            "v1",
            "augmentation_family_conventions_v1",
        ]
    )
    assert gov_rows[0].event_id == expected_event_id

    summary = summarize_augmentation_events(
        config,
        group_by=["event_family", "event_source", "warning_code"],
    )
    assert len(summary) >= 2
    summary_keys = [
        (row.get("event_family"), row.get("event_source"), row.get("warning_code"))
        for row in summary
    ]
    assert summary_keys == sorted(
        summary_keys,
        key=lambda value: tuple((item is None, "" if item is None else str(item)) for item in value),
    )
    assert any(row.get("event_family") == EVENT_FAMILY_LIFECYCLE and row.get("warning_code") is None for row in summary)

    with pytest.raises(SidecarContractError) as bad_family:
        list_augmentation_events(config, event_family="bad")
    assert bad_family.value.code == SIDE_CAR_ERROR_INVALID_EVENT_FAMILY

    with pytest.raises(SidecarContractError) as bad_type:
        list_augmentation_events(config, event_type="bad")
    assert bad_type.value.code == SIDE_CAR_ERROR_INVALID_EVENT_TYPE

    with pytest.raises(SidecarContractError) as bad_group:
        summarize_augmentation_events(config, group_by=["family_id"])
    assert bad_group.value.code == SIDE_CAR_ERROR_INVALID_GROUP_BY


def test_submission_overlay_impact_reports_selected_and_superseded_reasons(tmp_path: Path) -> None:
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
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
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
        items=[{"accession_number": "0000320193-25-000010", "augmentation_type": "entity_mentions", "payload": {"mentions": []}}],
        raw_request={"n": "new"},
    )
    items_df = pd.read_parquet(augmentation_items_path(config))
    items_df.loc[items_df["submission_id"] == old.submission_id, "received_at"] = "2026-01-01T00:00:00Z"
    items_df.loc[items_df["submission_id"] == new.submission_id, "received_at"] = "2026-01-01T00:00:10Z"
    items_df.to_parquet(augmentation_items_path(config), index=False)

    superseded = list_submission_overlay_impact(config, submission_id=old.submission_id)
    assert len(superseded) == 1
    assert superseded[0].reason_code == OVERLAY_IMPACT_REASON_SUPERSEDED_BY_WINNER
    assert superseded[0].winning_submission_id == new.submission_id
    assert superseded[0].contributes_to_resolved_overlay is False

    selected = list_submission_overlay_impact(config, submission_id=new.submission_id)
    assert len(selected) == 1
    assert selected[0].reason_code == OVERLAY_IMPACT_REASON_SELECTED
    assert selected[0].winning_submission_id == new.submission_id
    assert selected[0].contributes_to_resolved_overlay is True

    record_submission_lifecycle_transition(
        config,
        submission_id=new.submission_id,
        to_state=LIFECYCLE_STATE_DISABLED,
        reason="bad",
        changed_by="ops",
        source="unit",
    )
    ineligible = list_submission_overlay_impact(config, submission_id=new.submission_id)
    assert len(ineligible) == 1
    assert ineligible[0].reason_code == OVERLAY_IMPACT_REASON_LIFECYCLE_INELIGIBLE


def test_submission_entity_impact_and_review_bundle_are_deterministic(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    result = persist_augmentation_submission(
        config,
        producer_id="p1",
        layer_type="entities",
        schema_version="v1",
        producer_run_id="run-1",
        pipeline_id="pipe-1",
        model_id="model-1",
        producer_version="1.0",
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple"}, {"text": "Tim Cook", "entity_type": "PERSON"}]},
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2025-01-15",
            }
        ],
        raw_request={"n": 1},
    )
    build_augmentation_entity_index(config)
    present, rows = list_submission_entity_impact(config, submission_id=result.submission_id, limit=10)
    assert present is True
    assert len(rows) == 2
    assert rows[0].accession_number == "0000320193-25-000010"
    assert rows[0].entity_normalized <= rows[1].entity_normalized

    bundle = get_submission_review_bundle(
        config,
        submission_id=result.submission_id,
        overlay_limit=1,
        entity_limit=1,
        lifecycle_limit=1,
        governance_limit=1,
    )
    assert bundle["submission"]["submission_id"] == result.submission_id
    assert bundle["overlay_impact"]["selection_policy"] == "latest_per_producer_layer_v1"
    assert bundle["overlay_impact"]["returned_count"] <= 1
    assert bundle["entity_impact"]["returned_count"] <= 1
    assert bundle["governance_summary"]["returned_count"] <= 1
