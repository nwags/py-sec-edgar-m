from __future__ import annotations

import pandas as pd

from py_sec_edgar.config import load_config
from py_sec_edgar.reconciliation import run_reconciliation
from py_sec_edgar.resolution_provenance import append_resolution_provenance_events, resolution_events_path


def test_resolution_events_canonical_companion_artifact_is_written(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    cfg.ensure_runtime_dirs()

    append_resolution_provenance_events(
        cfg,
        [
            {
                "event_time": "2026-01-01T00:00:00Z",
                "flow": "api",
                "provider_id": "sec",
                "accession_number": "0000320193-25-000010",
                "filename": "edgar/data/320193/0000320193-25-000010.txt",
                "filing_cik": "0000320193",
                "form_type": "8-K",
                "filing_date": "2026-01-01",
                "metadata_surface": "local_lookup_filings",
                "content_surface": "sec_archives_submissions",
                "decision": "remote_fetched_and_persisted",
                "remote_url": "https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt",
                "local_path": str(cfg.download_root / "edgar/data/320193/0000320193-25-000010.txt"),
                "persisted_locally": True,
                "status_code": 200,
                "reason": None,
                "error": None,
                "error_class": None,
            }
        ],
    )

    canonical = pd.read_parquet(resolution_events_path(cfg))
    required = {
        "event_at",
        "domain",
        "content_domain",
        "canonical_key",
        "resolution_mode",
        "provider_requested",
        "provider_used",
        "method_used",
        "served_from",
        "remote_attempted",
        "success",
        "reason_code",
        "message",
        "persisted_locally",
    }
    assert required.issubset(set(canonical.columns))
    row = canonical.iloc[0]
    assert row["domain"] == "sec"
    assert row["content_domain"] == "filing"


class _EmptyFeed:
    def fetch_candidates(self, config):
        return []


def test_reconcile_artifacts_include_canonical_columns_additively(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    cfg.ensure_runtime_dirs()
    pd.DataFrame(columns=["CIK", "Form Type", "Date Filed", "Filename"]).to_parquet(cfg.merged_index_path, index=False)

    out = run_reconciliation(cfg, feed_client=_EmptyFeed(), recent_days=0, catch_up_warm=False, refresh_lookup=False)

    discrepancies = pd.read_parquet(out["discrepancies_path"])
    events = pd.read_parquet(out["events_path"])

    assert {
        "discrepancy_key",
        "domain",
        "target_type",
        "seen_key",
        "discrepancy_code",
        "target_date",
        "details",
        "observed_at",
    }.issubset(set(discrepancies.columns))

    assert {
        "event_at",
        "domain",
        "event_code",
        "target_date",
        "discrepancy_count",
        "catch_up_warm",
    }.issubset(set(events.columns))
