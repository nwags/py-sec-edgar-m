from __future__ import annotations

from pathlib import Path

import pandas as pd
from datetime import datetime, timezone

from py_sec_edgar.config import load_config
from py_sec_edgar.monitoring import (
    FeedNormalizationResult,
    MonitorCandidate,
    WarmFetchResult,
    build_monitor_candidate_from_filename,
    parse_atom_feed_candidates,
)
from py_sec_edgar.reconciliation import (
    reconciliation_discrepancies_path,
    reconciliation_events_path,
    run_reconciliation,
)


class FakeFeedClient:
    def __init__(self, candidates: list[MonitorCandidate]) -> None:
        self._candidates = list(candidates)

    def fetch_candidates(self, config):
        return FeedNormalizationResult(candidates=list(self._candidates), rejected=[])


class FakeWarmFetcher:
    def __init__(self, outcomes: list[WarmFetchResult], *, payload: bytes = b"reconcile") -> None:
        self._outcomes = list(outcomes)
        self._payload = payload
        self.calls: list[tuple[str, Path]] = []

    def fetch(self, config, url: str, destination_path: Path) -> WarmFetchResult:
        self.calls.append((url, destination_path))
        if not self._outcomes:
            raise AssertionError("No warm outcomes left.")
        out = self._outcomes.pop(0)
        if out.ok:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(self._payload)
        return out


def _write_merged(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def _candidate(filename: str, *, source_id: str = "feed") -> MonitorCandidate:
    return build_monitor_candidate_from_filename(
        filename=filename,
        filing_date="2025-01-15",
        form_type="8-K",
        filing_cik="320193",
        source_id=source_id,
    )


def test_reconciliation_classifies_and_persists_discrepancies(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    merged_rows = [
        {
            "CIK": "320193",
            "Form Type": "8-K",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/320193/0000320193-25-000010.txt",
        },
        {
            "CIK": "789019",
            "Form Type": "8-K",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/789019/0000789019-25-000020.txt",
        },
        {
            "CIK": "654321",
            "Form Type": "8-K",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/654321/0000654321-25-000030.txt",
        },
    ]
    _write_merged(config, merged_rows)

    local_present = config.download_root / "edgar/data/654321/0000654321-25-000030.txt"
    local_present.parent.mkdir(parents=True, exist_ok=True)
    local_present.write_text("ok", encoding="utf-8")

    feed = FakeFeedClient(
        [
            _candidate("edgar/data/320193/0000320193-25-000010.txt", source_id="f1"),
            _candidate("edgar/data/111111/0000111111-25-000040.txt", source_id="f2"),
        ]
    )

    result = run_reconciliation(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([]),
        catch_up_warm=False,
        refresh_lookup=True,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    assert result["reconciled_row_count"] == 4
    assert result["catch_up_attempted_count"] == 0
    assert result["lookup_update_mode"] == "skipped"
    assert result["lookup_refresh_skipped_reason"] == "no_catch_up_visibility_change"

    discrepancy_df = pd.read_parquet(reconciliation_discrepancies_path(config))
    assert len(discrepancy_df.index) == 4
    cats = discrepancy_df["discrepancy_type"].value_counts().to_dict()
    assert cats["index_and_feed_but_missing_local"] == 1
    assert cats["index_only_not_seen_in_feed"] == 1
    assert cats["feed_seen_missing_local"] == 1
    assert cats["index_only_not_seen_in_feed"] >= 1

    events_df = pd.read_parquet(reconciliation_events_path(config))
    assert len(events_df.index) == result["events_total_count"]
    assert "reconcile_lookup_incremental_skipped" in set(events_df["action"].astype(str).tolist())


def test_reconciliation_recent_days_handles_tz_mixed_inputs_without_crash(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    filing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _write_merged(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": filing_date,
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )
    feed_candidates = [
        MonitorCandidate(
            accession_number="0000320193-25-000010",
            filing_date=f"{filing_date}T13:10:00-05:00",
            form_type="8-K",
            filing_cik="320193",
            filename="edgar/data/320193/0000320193-25-000010.txt",
            url="https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt",
            source_id="tz-feed",
        )
    ]
    out = run_reconciliation(
        config,
        feed_client=FakeFeedClient(feed_candidates),
        warm_fetcher=FakeWarmFetcher([]),
        recent_days=7,
        catch_up_warm=False,
        refresh_lookup=True,
    )
    assert out["reconciled_row_count"] == 1


def test_reconciliation_date_bounds_filter_correctly_with_unified_strategy(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            },
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2024-12-20",
                "Filename": "edgar/data/320193/0000320193-24-000999.txt",
            },
        ],
    )
    feed_candidates = [
        MonitorCandidate(
            accession_number="0000320193-25-000010",
            filing_date="2025-01-15T13:10:00-05:00",
            form_type="8-K",
            filing_cik="320193",
            filename="edgar/data/320193/0000320193-25-000010.txt",
            url="https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt",
            source_id="tz-feed",
        ),
        MonitorCandidate(
            accession_number="0000320193-24-000999",
            filing_date="2024-12-20T13:10:00-05:00",
            form_type="8-K",
            filing_cik="320193",
            filename="edgar/data/320193/0000320193-24-000999.txt",
            url="https://www.sec.gov/Archives/edgar/data/320193/0000320193-24-000999.txt",
            source_id="tz-feed",
        ),
    ]
    out = run_reconciliation(
        config,
        feed_client=FakeFeedClient(feed_candidates),
        warm_fetcher=FakeWarmFetcher([]),
        date_from="2025-01-01",
        date_to="2025-01-31",
        catch_up_warm=False,
        refresh_lookup=True,
    )
    assert out["reconciled_row_count"] == 1


def test_reconciliation_catch_up_success_uses_incremental_lookup(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged(
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
    feed = FakeFeedClient([_candidate("edgar/data/320193/0000320193-25-000010.txt")])
    warmer = FakeWarmFetcher([WarmFetchResult(ok=True)], payload=b"abc")

    called = {"incremental": 0, "refresh": 0}

    def fake_incremental(cfg, warmed_filenames=None, warmed_accession_numbers=None):
        called["incremental"] += 1
        return {
            "safe_to_use": True,
            "attempted_input_count": 1,
            "matched_merged_rows_count": 1,
            "registered_filing_row_count": 1,
            "registered_artifact_row_count": 1,
            "skipped_count": 0,
            "skip_reasons": {},
            "touched_accession_count": 1,
            "touched_filename_count": 1,
            "filings_index_path": "x",
            "artifacts_index_path": "y",
        }

    def fake_refresh(cfg, include_global_filings=False):
        called["refresh"] += 1
        return {"filings_row_count": 1}

    monkeypatch.setattr("py_sec_edgar.reconciliation.register_local_filings_in_lookup", fake_incremental)
    monkeypatch.setattr("py_sec_edgar.reconciliation.refresh_local_lookup_indexes", fake_refresh)

    result = run_reconciliation(
        config,
        feed_client=feed,
        warm_fetcher=warmer,
        catch_up_warm=True,
        refresh_lookup=True,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    expected = config.download_root / "edgar/data/320193/0000320193-25-000010.txt"
    assert expected.exists()
    assert expected.read_bytes() == b"abc"
    assert result["catch_up_succeeded_count"] == 1
    assert result["lookup_update_mode"] == "incremental"
    assert called["incremental"] == 1
    assert called["refresh"] == 0


def test_reconciliation_catch_up_skips_weak_feed_only_candidates_explicitly(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2024-01-01",
                "Filename": "edgar/data/320193/0000320193-24-000001.txt",
            }
        ],
    )
    weak_feed = FakeFeedClient(
        [
            MonitorCandidate(
                accession_number="0000111111-25-000040",
                filing_date="2025-01-15",
                form_type="8-K",
                filing_cik=None,
                filename="edgar/data/111111/0000111111-25-000040.txt",
                url="https://www.sec.gov/Archives/edgar/data/111111/0000111111-25-000040.txt",
                source_id="weak-feed",
            )
        ]
    )
    warmer = FakeWarmFetcher([])

    out = run_reconciliation(
        config,
        feed_client=weak_feed,
        warm_fetcher=warmer,
        catch_up_warm=True,
        refresh_lookup=True,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    assert len(warmer.calls) == 0
    assert out["catch_up_attempted_count"] == 0
    assert out["catch_up_skipped_count"] == 1
    assert out["catch_up_skip_reasons"]["feed_only_missing_accession_or_cik"] == 1
    assert any(event.get("action") == "reconcile_catch_up_skipped" for event in out["activity_events"])
    events_df = pd.read_parquet(reconciliation_events_path(config))
    assert "reconcile_catch_up_skipped" in set(events_df["action"].astype(str).tolist())


def test_reconciliation_catch_up_from_index_link_candidate_warms_canonical_txt(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged(
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
    feed_candidates = parse_atom_feed_candidates(
        """<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>8-K filing CIK 0000320193 accession 0000320193-25-000010</title>
            <summary>Current filing notice</summary>
            <link href="https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010-index.htm"/>
            <updated>2025-01-15T13:10:00-05:00</updated>
          </entry>
        </feed>""",
        source_id="atom-fixture",
    )

    out = run_reconciliation(
        config,
        feed_client=FakeFeedClient(feed_candidates),
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)], payload=b"from-index-link"),
        catch_up_warm=True,
        refresh_lookup=False,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    expected = config.download_root / "edgar/data/320193/0000320193-25-000010.txt"
    assert expected.exists()
    assert expected.read_bytes() == b"from-index-link"
    assert out["catch_up_succeeded_count"] == 1


def test_reconciliation_fallbacks_to_full_refresh_when_incremental_unsafe(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged(
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
    feed = FakeFeedClient([_candidate("edgar/data/320193/0000320193-25-000010.txt")])

    calls = {"refresh": 0}

    def fake_incremental(cfg, warmed_filenames=None, warmed_accession_numbers=None):
        return {
            "safe_to_use": False,
            "attempted_input_count": 1,
            "matched_merged_rows_count": 0,
            "registered_filing_row_count": 0,
            "registered_artifact_row_count": 0,
            "skipped_count": 1,
            "skip_reasons": {"no_merged_index_matches": 1},
            "touched_accession_count": 0,
            "touched_filename_count": 0,
            "filings_index_path": "x",
            "artifacts_index_path": "y",
        }

    def fake_refresh(cfg, include_global_filings=False):
        calls["refresh"] += 1
        return {"filings_row_count": 1}

    monkeypatch.setattr("py_sec_edgar.reconciliation.register_local_filings_in_lookup", fake_incremental)
    monkeypatch.setattr("py_sec_edgar.reconciliation.refresh_local_lookup_indexes", fake_refresh)

    result = run_reconciliation(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        catch_up_warm=True,
        refresh_lookup=True,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    assert result["lookup_update_mode"] == "full_refresh_fallback"
    assert result["lookup_full_refresh_fallback_performed"] is True
    assert calls["refresh"] == 1


def test_reconciliation_operator_smoke_second_run_reconciles_local_presence(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged(
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
    feed = FakeFeedClient([_candidate("edgar/data/320193/0000320193-25-000010.txt")])

    monkeypatch.setattr(
        "py_sec_edgar.reconciliation.register_local_filings_in_lookup",
        lambda *args, **kwargs: {
            "safe_to_use": True,
            "attempted_input_count": 1,
            "matched_merged_rows_count": 1,
            "registered_filing_row_count": 1,
            "registered_artifact_row_count": 1,
            "skipped_count": 0,
            "skip_reasons": {},
            "touched_accession_count": 1,
            "touched_filename_count": 1,
            "filings_index_path": "x",
            "artifacts_index_path": "y",
        },
    )

    first = run_reconciliation(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        catch_up_warm=True,
        refresh_lookup=True,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )
    second = run_reconciliation(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([]),
        catch_up_warm=False,
        refresh_lookup=True,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    assert first["catch_up_succeeded_count"] == 1
    assert second["discrepancy_type_counts"].get("fully_reconciled_local_present", 0) == 1
    assert second["catch_up_attempted_count"] == 0
