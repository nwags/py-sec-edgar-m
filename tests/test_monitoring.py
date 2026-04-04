from __future__ import annotations

from pathlib import Path

import pandas as pd

from py_sec_edgar.config import load_config
from py_sec_edgar.monitoring import (
    FeedNormalizationResult,
    MonitorCandidate,
    NormalizationSkip,
    WarmFetchResult,
    build_monitor_candidate_from_filename,
    monitor_events_path,
    monitor_seen_accessions_path,
    parse_atom_feed_candidates,
    run_monitor_loop,
    run_monitor_poll,
)
from py_sec_edgar.resolution_provenance import filing_resolution_provenance_path


class FakeFeedClient:
    def __init__(self, candidates: list[MonitorCandidate], *, rejected: list[NormalizationSkip] | None = None) -> None:
        self._candidates = list(candidates)
        self._rejected = list(rejected or [])
        self.calls = 0

    def fetch_candidates(self, config):
        self.calls += 1
        return FeedNormalizationResult(candidates=list(self._candidates), rejected=list(self._rejected))


class FakeWarmFetcher:
    def __init__(self, outcomes: list[WarmFetchResult], *, payload: bytes = b"monitor payload") -> None:
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


def _candidate() -> MonitorCandidate:
    return build_monitor_candidate_from_filename(
        filename="edgar/data/320193/0000320193-25-000010.txt",
        filing_date="2025-01-15",
        form_type="SC 13D",
        filing_cik="320193",
        source_id="unit-test-feed",
    )


def test_parse_atom_feed_candidates_normalizes_entries() -> None:
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>8-K - Example Corp (CIK 0000320193)</title>
        <link href="https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt"/>
        <updated>2025-01-15T13:10:00-05:00</updated>
      </entry>
    </feed>"""
    out = parse_atom_feed_candidates(atom, source_id="atom-fixture")
    assert len(out) == 1
    row = out[0]
    assert row.accession_number == "0000320193-25-000010"
    assert row.filename == "edgar/data/320193/0000320193-25-000010.txt"
    assert row.url == "https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt"


def test_monitor_poll_warm_success_then_second_poll_skips_seen_and_local(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    warmer = FakeWarmFetcher([WarmFetchResult(ok=True)])

    first = run_monitor_poll(config, feed_client=feed, warm_fetcher=warmer, refresh_lookup=False)
    second = run_monitor_poll(config, feed_client=feed, warm_fetcher=warmer, refresh_lookup=False)

    assert first["warm_succeeded_count"] == 1
    assert second["warm_attempted_count"] == 0
    assert second["skipped_already_local_count"] == 1
    assert len(warmer.calls) == 1


def test_lookup_refresh_skipped_event_is_persisted(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    out = run_monitor_poll(
        config,
        feed_client=FakeFeedClient([]),
        warm_fetcher=FakeWarmFetcher([]),
        refresh_lookup=True,
    )
    assert out["lookup_refresh_performed"] is False
    assert out["lookup_refresh_skipped_reason"] == "no_local_visibility_change"
    events_df = pd.read_parquet(monitor_events_path(config))
    assert "lookup_refresh_skipped" in set(events_df["action"].astype(str).tolist())


def test_monitor_poll_persists_canonical_local_file_path(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    warmer = FakeWarmFetcher([WarmFetchResult(ok=True)], payload=b"abc")

    out = run_monitor_poll(config, feed_client=feed, warm_fetcher=warmer, refresh_lookup=False)

    expected = config.download_root / "edgar/data/320193/0000320193-25-000010.txt"
    assert out["warm_succeeded_count"] == 1
    assert expected.exists()
    assert expected.read_bytes() == b"abc"
    provenance = pd.read_parquet(filing_resolution_provenance_path(config))
    assert len(provenance.index) == 1
    row = provenance.iloc[0]
    assert row["flow"] == "monitor"
    assert row["decision"] == "warm_succeeded"
    assert bool(row["persisted_locally"]) is True


def test_seen_but_missing_local_triggers_self_healing_rewarm_success(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    warm = FakeWarmFetcher([WarmFetchResult(ok=True)], payload=b"first")
    first = run_monitor_poll(config, feed_client=feed, warm_fetcher=warm, refresh_lookup=False)
    assert first["warm_succeeded_count"] == 1

    target = config.download_root / "edgar/data/320193/0000320193-25-000010.txt"
    target.unlink()
    assert not target.exists()

    second_warm = FakeWarmFetcher([WarmFetchResult(ok=True)], payload=b"healed")
    second = run_monitor_poll(config, feed_client=feed, warm_fetcher=second_warm, refresh_lookup=False)
    assert second["warm_attempted_count"] == 1
    assert second["warm_succeeded_count"] == 1
    assert target.exists()
    assert target.read_bytes() == b"healed"
    seen_df = pd.read_parquet(monitor_seen_accessions_path(config))
    row = seen_df[seen_df["accession_number"] == "0000320193-25-000010"].iloc[0]
    assert bool(row["local_submission_present"]) is True
    assert bool(row["warmed_by_monitor"]) is True


def test_seen_but_missing_local_rewarm_failure_keeps_local_false(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        refresh_lookup=False,
    )
    target = config.download_root / "edgar/data/320193/0000320193-25-000010.txt"
    target.unlink()
    assert not target.exists()

    out = run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=False, reason="http_error", status_code=503)]),
        refresh_lookup=False,
    )
    assert out["warm_attempted_count"] == 1
    assert out["warm_failed_count"] == 1
    seen_df = pd.read_parquet(monitor_seen_accessions_path(config))
    row = seen_df[seen_df["accession_number"] == "0000320193-25-000010"].iloc[0]
    assert bool(row["local_submission_present"]) is False
    events_df = pd.read_parquet(monitor_events_path(config))
    assert "warm_failed" in set(events_df["action"].astype(str).tolist())


def test_monitor_poll_refreshes_lookup_only_when_local_visibility_changes(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    refresh_calls: list[int] = []
    incremental_calls: list[int] = []

    def fake_lookup_refresh(cfg, include_global_filings=False):
        refresh_calls.append(1)
        return {"filings_row_count": 1}

    def fake_incremental(cfg, warmed_filenames=None, warmed_accession_numbers=None):
        incremental_calls.append(1)
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
            "filings_index_path": "local_lookup_filings.parquet",
            "artifacts_index_path": "local_lookup_artifacts.parquet",
        }

    monkeypatch.setattr("py_sec_edgar.monitoring.refresh_local_lookup_indexes", fake_lookup_refresh)
    monkeypatch.setattr("py_sec_edgar.monitoring.register_local_filings_in_lookup", fake_incremental)

    changed = run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        refresh_lookup=True,
    )
    unchanged = run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([]),
        refresh_lookup=True,
    )

    assert changed["lookup_refresh_performed"] is True
    assert changed["lookup_update_mode"] == "incremental"
    assert changed["lookup_full_refresh_fallback_performed"] is False
    assert unchanged["lookup_refresh_performed"] is False
    assert unchanged["lookup_refresh_skipped_reason"] == "no_local_visibility_change"
    assert len(incremental_calls) == 1
    assert len(refresh_calls) == 0


def test_monitor_poll_fallbacks_to_full_refresh_when_incremental_is_unsafe(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    refresh_calls: list[int] = []

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
            "filings_index_path": "local_lookup_filings.parquet",
            "artifacts_index_path": "local_lookup_artifacts.parquet",
        }

    def fake_lookup_refresh(cfg, include_global_filings=False):
        refresh_calls.append(1)
        return {"filings_row_count": 1, "artifacts_row_count": 1}

    monkeypatch.setattr("py_sec_edgar.monitoring.register_local_filings_in_lookup", fake_incremental)
    monkeypatch.setattr("py_sec_edgar.monitoring.refresh_local_lookup_indexes", fake_lookup_refresh)

    out = run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        refresh_lookup=True,
    )
    assert out["lookup_update_mode"] == "full_refresh_fallback"
    assert out["lookup_full_refresh_fallback_performed"] is True
    assert out["lookup_refresh_performed"] is True
    assert len(refresh_calls) == 1
    events_df = pd.read_parquet(monitor_events_path(config))
    assert "lookup_incremental_skipped" in set(events_df["action"].astype(str).tolist())
    assert "lookup_full_refresh_fallback_performed" in set(events_df["action"].astype(str).tolist())


def test_monitor_poll_refresh_lookup_disabled_records_fallback_not_allowed(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    calls: list[int] = []

    def fake_incremental(cfg, warmed_filenames=None, warmed_accession_numbers=None):
        calls.append(1)
        return {"safe_to_use": True}

    monkeypatch.setattr("py_sec_edgar.monitoring.register_local_filings_in_lookup", fake_incremental)

    out = run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        refresh_lookup=False,
    )
    assert out["lookup_update_mode"] == "skipped"
    assert out["lookup_refresh_skipped_reason"] == "refresh_lookup_disabled"
    assert out["lookup_full_refresh_fallback_skipped_reason"] == "fallback_not_allowed_refresh_disabled"
    assert len(calls) == 0
    events_df = pd.read_parquet(monitor_events_path(config))
    actions = set(events_df["action"].astype(str).tolist())
    assert "lookup_incremental_skipped" in actions
    assert "lookup_full_refresh_fallback_skipped" in actions


def test_monitor_loop_respects_max_iterations(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    warmer = FakeWarmFetcher([WarmFetchResult(ok=True)])

    result = run_monitor_loop(
        config,
        interval_seconds=0.0,
        max_iterations=2,
        feed_client=feed,
        warm_fetcher=warmer,
        refresh_lookup=False,
    )

    assert result["iterations_run"] == 2


def test_monitor_poll_failure_records_event_and_state(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    feed = FakeFeedClient([_candidate()])
    warmer = FakeWarmFetcher([WarmFetchResult(ok=False, status_code=503, reason="http_error", error="upstream")])

    out = run_monitor_poll(config, feed_client=feed, warm_fetcher=warmer, refresh_lookup=False)

    assert out["warm_failed_count"] == 1
    seen_df = pd.read_parquet(monitor_seen_accessions_path(config))
    assert len(seen_df.index) == 1
    assert bool(seen_df.iloc[0]["local_submission_present"]) is False

    events_df = pd.read_parquet(monitor_events_path(config))
    assert "warm_failed" in set(events_df["action"].astype(str).tolist())
    provenance = pd.read_parquet(filing_resolution_provenance_path(config))
    assert len(provenance.index) == 1
    row = provenance.iloc[0]
    assert row["flow"] == "monitor"
    assert row["decision"] == "warm_failed"
    assert bool(row["persisted_locally"]) is False


def test_parse_atom_feed_candidates_supports_text_derived_filename_shape() -> None:
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Current filing 8-K CIK=0000320193 Accession Number: 0000320193-25-000010</title>
        <summary>See edgar/data/320193/0000320193-25-000010.txt for full submission.</summary>
        <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=320193"/>
        <updated>2025-01-15T13:10:00-05:00</updated>
      </entry>
    </feed>"""
    out = parse_atom_feed_candidates(atom, source_id="atom-fixture")
    assert len(out) == 1
    assert out[0].filename == "edgar/data/320193/0000320193-25-000010.txt"


def test_parse_atom_feed_candidates_supports_accession_plus_cik_derivation() -> None:
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>8-K filing CIK 0000320193 accession 0000320193-25-000010</title>
        <summary>Current filing notice</summary>
        <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=320193"/>
        <updated>2025-01-15T13:10:00-05:00</updated>
      </entry>
    </feed>"""
    out = parse_atom_feed_candidates(atom, source_id="atom-fixture")
    assert len(out) == 1
    assert out[0].filename == "edgar/data/320193/0000320193-25-000010.txt"


def test_parse_atom_feed_candidates_normalizes_index_link_to_raw_submission_txt() -> None:
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>8-K filing CIK 0001193125 accession 0001193125-26-116240</title>
        <summary>Current filing notice</summary>
        <link href="https://www.sec.gov/Archives/edgar/data/320193/0001193125-26-116240-index.htm"/>
        <updated>2025-01-15T13:10:00-05:00</updated>
      </entry>
    </feed>"""
    out = parse_atom_feed_candidates(atom, source_id="atom-fixture")
    assert len(out) == 1
    assert out[0].filename == "edgar/data/320193/0001193125-26-116240.txt"
    assert out[0].url == "https://www.sec.gov/Archives/edgar/data/320193/0001193125-26-116240.txt"


def test_monitor_poll_index_link_candidate_keeps_incremental_lookup_path(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>8-K filing CIK 0000320193 accession 0000320193-25-000010</title>
        <summary>Current filing notice</summary>
        <link href="https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010-index.htm"/>
        <updated>2025-01-15T13:10:00-05:00</updated>
      </entry>
    </feed>"""
    candidates = parse_atom_feed_candidates(atom, source_id="atom-fixture")
    feed = FakeFeedClient(candidates)
    refresh_calls: list[int] = []
    incremental_calls: list[int] = []

    def fake_incremental(cfg, warmed_filenames=None, warmed_accession_numbers=None):
        incremental_calls.append(1)
        assert warmed_filenames == ["edgar/data/320193/0000320193-25-000010.txt"]
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
            "filings_index_path": "local_lookup_filings.parquet",
            "artifacts_index_path": "local_lookup_artifacts.parquet",
        }

    def fake_lookup_refresh(cfg, include_global_filings=False):
        refresh_calls.append(1)
        return {"filings_row_count": 1}

    monkeypatch.setattr("py_sec_edgar.monitoring.register_local_filings_in_lookup", fake_incremental)
    monkeypatch.setattr("py_sec_edgar.monitoring.refresh_local_lookup_indexes", fake_lookup_refresh)

    out = run_monitor_poll(
        config,
        feed_client=feed,
        warm_fetcher=FakeWarmFetcher([WarmFetchResult(ok=True)]),
        refresh_lookup=True,
    )

    expected = config.download_root / "edgar/data/320193/0000320193-25-000010.txt"
    assert expected.exists()
    assert out["lookup_update_mode"] == "incremental"
    assert out["lookup_full_refresh_fallback_performed"] is False
    assert len(incremental_calls) == 1
    assert len(refresh_calls) == 0


def test_normalization_skips_are_persisted_as_events(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    rejected = [
        NormalizationSkip(
            reason="missing_filename",
            detail="unable to derive filename",
            source_id="fixture-feed",
            accession_number="0000320193-25-000010",
            filing_cik="0000320193",
            url="https://example.test/item",
            filename=None,
        )
    ]
    out = run_monitor_poll(
        config,
        feed_client=FakeFeedClient([], rejected=rejected),
        warm_fetcher=FakeWarmFetcher([]),
        refresh_lookup=False,
    )
    assert out["normalization_skipped_count"] == 1
    events_df = pd.read_parquet(monitor_events_path(config))
    skipped = events_df[events_df["action"].astype(str) == "normalization_skipped"]
    assert len(skipped.index) == 1
