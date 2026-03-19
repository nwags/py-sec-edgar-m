from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

pandas = pytest.importorskip("pandas")

from py_sec_edgar.config import load_config
from py_sec_edgar.pipelines.backfill import run_backfill
from py_sec_edgar.pipelines.refdata_refresh import run_refdata_refresh


def _write_minimal_raw_sources(raw_root: Path) -> None:
    raw_root.mkdir(parents=True, exist_ok=True)
    (raw_root / "company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 320193, "ticker": "aapl", "title": "APPLE INC"}}),
        encoding="utf-8",
    )
    (raw_root / "company_tickers_exchange.json").write_text(
        json.dumps(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, "Apple Inc", "AAPL", "Nasdaq"]],
            }
        ),
        encoding="utf-8",
    )
    (raw_root / "company_tickers_mf.json").write_text(
        json.dumps(
            {
                "fields": ["cik", "seriesId", "classId", "symbol"],
                "data": [[2110, "S0001", "C0001", "lacax"]],
            }
        ),
        encoding="utf-8",
    )
    (raw_root / "ticker.txt").write_text("aapl\t320193\n", encoding="utf-8")
    (raw_root / "cik-lookup-data.txt").write_text("APPLE INC:0000320193:\n", encoding="utf-8")
    (raw_root / "investment-company-series-class-2025.csv").write_text(
        "Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,Series Name,"
        "Class ID,Class Name,Class Ticker,Address_1,Address_2,City,State,Zip Code\n"
        "002-2,0000002110,New Fund,32,S0002,New Series,C0002,New Class,newx,,,,,\n",
        encoding="utf-8",
    )


def test_run_backfill_passes_entity_aware_selection_inputs(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    calls = {}

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    def fake_load_filings_feed(**kwargs):
        calls.update(kwargs)
        return pandas.DataFrame([{"CIK": "0000320193"}])

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", fake_load_filings_feed)

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: None)

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=False,
        ticker_list_filter=True,
        form_list_filter=True,
        issuer_tickers=["aapl"],
        issuer_ciks=["320193"],
        entity_ciks=["1234"],
        forms=["8-K"],
        form_families=["current_reports"],
        date_from="2025-01-01",
        date_to="2025-01-31",
    )

    assert calls["ticker_list_filter"] is False
    assert calls["form_list_filter"] is False
    assert calls["issuer_tickers"] == ["aapl"]
    assert calls["issuer_ciks"] == ["320193"]
    assert calls["entity_ciks"] == ["1234"]
    assert calls["forms"] == ["8-K"]
    assert calls["form_families"] == ["current_reports"]
    assert calls["date_from"] == "2025-01-01"
    assert calls["date_to"] == "2025-01-31"
    assert result["candidate_count"] == 1
    assert result["download_attempted_count"] == 0
    assert result["download_succeeded_count"] == 0
    assert result["download_failed_count"] == 0
    assert result["extraction_attempted_count"] == 0
    assert result["extraction_succeeded_count"] == 0
    assert result["extraction_failed_count"] == 0
    assert result["filing_party_record_count"] == 0
    assert result["filing_party_failed_count"] == 0


def test_run_backfill_modern_scope_disables_legacy_ticker_filter_when_not_explicit(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    calls = {}

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    def fake_load_filings_feed(**kwargs):
        calls.update(kwargs)
        return pandas.DataFrame([])

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", fake_load_filings_feed)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: None)

    run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=False,
        ticker_list_filter=True,
        form_list_filter=True,
        ticker_list_filter_explicit=False,
        form_list_filter_explicit=False,
        form_families=["beneficial_ownership"],
        date_from="2024-12-01",
        date_to="2025-03-31",
    )

    assert calls["ticker_list_filter"] is False
    assert calls["form_list_filter"] is False


def test_run_backfill_explicit_legacy_ticker_filter_is_honored_with_modern_scope(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    calls = {}

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    def fake_load_filings_feed(**kwargs):
        calls.update(kwargs)
        return pandas.DataFrame([])

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", fake_load_filings_feed)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: None)

    run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=False,
        ticker_list_filter=True,
        form_list_filter=True,
        ticker_list_filter_explicit=True,
        form_list_filter_explicit=False,
        form_families=["beneficial_ownership"],
        date_from="2024-12-01",
        date_to="2025-03-31",
    )

    assert calls["ticker_list_filter"] is True


def test_run_backfill_proceeds_past_normalized_preconditions_after_fallback_refdata_refresh(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    fallback_raw = tmp_path / "bundled_sources" / "sec_sources"
    _write_minimal_raw_sources(fallback_raw)
    config = replace(config, canonical_raw_refdata_root=fallback_raw)

    run_refdata_refresh(config)

    merged = pandas.DataFrame(
        [
            {
                "CIK": "0000320193",
                "Company Name": "APPLE INC",
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ]
    )
    config.merged_index_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(config.merged_index_path, index=False)

    monkeypatch.setattr("py_sec_edgar.settings.CONFIG.MERGED_IDX_FILEPATH", str(config.merged_index_path))
    monkeypatch.setattr("py_sec_edgar.settings.CONFIG.NORMALIZED_REFDATA_DIR", str(config.normalized_refdata_root))
    monkeypatch.setattr("py_sec_edgar.settings.CONFIG.forms_list", list(config.forms))
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=False,
        ticker_list_filter=False,
        form_list_filter=False,
        form_families=["beneficial_ownership"],
        date_from="2024-12-01",
        date_to="2025-03-31",
    )

    assert result["candidate_count"] == 1


def test_run_backfill_keeps_legacy_switches_without_explicit_selectors(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    calls = {}

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    def fake_load_filings_feed(**kwargs):
        calls.update(kwargs)
        return pandas.DataFrame([])

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", fake_load_filings_feed)

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: None)

    run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=False,
        ticker_list_filter=True,
        form_list_filter=True,
    )

    assert calls["ticker_list_filter"] is True
    assert calls["form_list_filter"] is True


def test_run_backfill_execute_downloads_routes_selected_rows_to_orchestrator(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    df = pandas.DataFrame(
        [
            {
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt",
            },
            {
                "Filename": "edgar/data/789019/0000789019-25-000011.txt",
                "url": "https://www.sec.gov/Archives/edgar/data/789019/0000789019-25-000011.txt",
            },
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)

    class _Result:
        def __init__(
            self,
            *,
            url,
            filepath,
            success,
            reason=None,
            status_code=None,
            error=None,
            error_class=None,
            retry_exhausted=False,
        ):
            self.url = url
            self.filepath = filepath
            self.success = success
            self.reason = reason
            self.status_code = status_code
            self.error = error
            self.error_class = error_class
            self.retry_exhausted = retry_exhausted

    captured = {}

    def fake_run_bounded_downloads(tasks, *, max_workers=None, downloader_config=None):
        work = list(tasks)
        captured["tasks"] = work
        captured["downloader_config"] = downloader_config
        return [
            _Result(url=work[0].url, filepath=work[0].filepath, success=True),
            _Result(
                url=work[1].url,
                filepath=work[1].filepath,
                success=False,
                reason="http_error",
                status_code=404,
                error_class=None,
                retry_exhausted=True,
            ),
        ]

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", fake_run_bounded_downloads)

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=True,
        execute_extraction=False,
    )

    assert len(captured["tasks"]) == 2
    assert all(task.filepath.startswith(str(tmp_path / ".sec_cache" / "Archives")) for task in captured["tasks"])
    assert captured["downloader_config"] is config
    assert result["candidate_count"] == 2
    assert result["download_attempted_count"] == 2
    assert result["download_succeeded_count"] == 1
    assert result["download_failed_count"] == 1
    assert result["download_failures"][0]["reason"] == "http_error"
    assert result["download_failures"][0]["status_code"] == 404
    assert result["download_failures"][0]["retry_exhausted"] is True
    assert result["download_failure_reason_counts"] == {"http_error": 1}
    assert result["download_failure_status_code_counts"] == {"404": 1}
    assert result["download_failure_error_class_counts"] == {}
    assert len(result["download_failures_sample"]) == 1
    assert set(result["download_failures_sample"][0].keys()) == {
        "url",
        "filepath",
        "reason",
        "status_code",
        "error_class",
        "error",
    }
    assert result["extraction_attempted_count"] == 0
    assert result["extraction_succeeded_count"] == 0
    assert result["extraction_failed_count"] == 0
    assert result["filing_party_record_count"] == 0
    assert result["filing_party_failed_count"] == 0
    assert "total_elapsed_seconds" in result
    assert "activity_events" in result


def test_run_backfill_download_failure_sample_is_bounded(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rows = []
    for i in range(25):
        rows.append(
            {
                "Filename": f"edgar/data/320193/0000320193-25-{i:06d}.txt",
                "url": f"https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-{i:06d}.txt",
            }
        )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: pandas.DataFrame(rows))

    class _Result:
        def __init__(self, *, url, filepath):
            self.url = url
            self.filepath = filepath
            self.success = False
            self.reason = "timeout"
            self.status_code = None
            self.error = "timed out"
            self.error_class = "Timeout"
            self.retry_exhausted = True

    def fake_run_bounded_downloads(tasks, *, max_workers=None, downloader_config=None):
        return [_Result(url=item.url, filepath=item.filepath) for item in tasks]

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", fake_run_bounded_downloads)

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=True,
        execute_extraction=False,
    )

    assert result["download_failed_count"] == 25
    assert result["download_failure_reason_counts"] == {"timeout": 25}
    assert result["download_failure_error_class_counts"] == {"Timeout": 25}
    assert len(result["download_failures_sample"]) == 20


def test_run_backfill_execute_extraction_serial_success_and_failure_reporting(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    existing_rel = "edgar/data/320193/0000320193-25-000010.txt"
    missing_rel = "edgar/data/789019/0000789019-25-000011.txt"
    df = pandas.DataFrame(
        [
            {"Filename": existing_rel, "url": "https://www.sec.gov/Archives/" + existing_rel},
            {"Filename": missing_rel, "url": "https://www.sec.gov/Archives/" + missing_rel},
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])

    existing_path = tmp_path / ".sec_cache" / "Archives" / existing_rel
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("dummy filing", encoding="utf-8")

    calls = []

    def fake_complete_submission_filing(filepath, output_directory):
        calls.append((filepath, output_directory))
        out = pandas.DataFrame([{"FILENAME": "a.txt"}])
        Path(output_directory).mkdir(parents=True, exist_ok=True)
        return out

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", fake_complete_submission_filing)

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
    )

    assert len(calls) == 1
    assert calls[0][0] == str(existing_path)
    assert result["candidate_count"] == 2
    assert result["download_attempted_count"] == 0
    assert result["extraction_attempted_count"] == 2
    assert result["extraction_succeeded_count"] == 1
    assert result["extraction_failed_count"] == 1
    assert result["extraction_failures"][0]["reason"] == "missing_local_filing"
    assert result["filing_party_record_count"] == 0
    assert result["filing_party_failed_count"] == 0


def test_run_backfill_execute_extraction_reports_exceptions(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/320193/0000320193-25-000010.txt"
    df = pandas.DataFrame([{"Filename": rel, "url": "https://www.sec.gov/Archives/" + rel}])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])

    path = tmp_path / ".sec_cache" / "Archives" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("dummy filing", encoding="utf-8")

    def fake_complete_submission_filing(filepath, output_directory):
        raise RuntimeError("boom")

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", fake_complete_submission_filing)

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
    )

    assert result["extraction_attempted_count"] == 1
    assert result["extraction_succeeded_count"] == 0
    assert result["extraction_failed_count"] == 1
    assert result["extraction_failures"][0]["reason"] == "extraction_exception"
    assert "boom" in result["extraction_failures"][0]["error"]
    assert result["filing_party_record_count"] == 0
    assert result["filing_party_failed_count"] == 0


def test_run_backfill_extraction_stage_emits_filing_party_records(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/999999/0000999999-25-000001.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel,
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-31",
                "url": "https://www.sec.gov/Archives/" + rel,
            }
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    src = Path("tests/fixtures/filings/sc13d_sample.txt")
    path = tmp_path / ".sec_cache" / "Archives" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
    )

    assert result["candidate_count"] == 1
    assert result["extraction_attempted_count"] == 1
    assert result["extraction_succeeded_count"] == 1
    assert result["filing_party_candidate_count"] == 1
    assert result["filing_party_attempted_count"] == 1
    assert result["filing_party_zero_record_count"] == 0
    assert result["filing_party_successful_nonzero_record_filing_count"] == 1
    assert result["filing_party_attempted_invariant_ok"] is True
    assert result["filing_party_record_count"] == 3
    assert result["filing_party_failed_count"] == 0
    roles = {row["party_role"] for row in result["filing_parties"]}
    assert roles == {"subject_company", "issuer", "reporting_owner"}


def test_run_backfill_extraction_stage_emits_form4_filing_party_records(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/1777777/0001777777-25-000010.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel,
                "Form Type": "4",
                "Date Filed": "2025-02-01",
                "url": "https://www.sec.gov/Archives/" + rel,
            }
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    src = Path("tests/fixtures/filings/form4_sample.txt")
    path = tmp_path / ".sec_cache" / "Archives" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
    )

    assert result["candidate_count"] == 1
    assert result["extraction_succeeded_count"] == 1
    assert result["filing_party_candidate_count"] == 1
    assert result["filing_party_attempted_count"] == 1
    assert result["filing_party_zero_record_count"] == 0
    assert result["filing_party_successful_nonzero_record_filing_count"] == 1
    assert result["filing_party_attempted_invariant_ok"] is True
    assert result["filing_party_record_count"] >= 4
    roles = {row["party_role"] for row in result["filing_parties"]}
    assert "issuer" in roles
    assert "reporting_owner" in roles
    assert "director" in roles
    assert "officer" in roles
    assert "ten_percent_owner" in roles


def test_run_backfill_can_persist_filing_parties(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/999999/0000999999-25-000001.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel,
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-31",
                "url": "https://www.sec.gov/Archives/" + rel,
            }
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    src = Path("tests/fixtures/filings/sc13d_sample.txt")
    path = tmp_path / ".sec_cache" / "Archives" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    first = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
        persist_filing_parties=True,
    )
    second = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
        persist_filing_parties=True,
    )

    assert first["filing_party_record_count"] == 3
    assert first["filing_party_attempted_count"] == 1
    assert first["filing_party_persisted_count"] == 3
    assert first["filing_party_persist_path"] is not None
    assert Path(first["filing_party_persist_path"]).exists()
    assert second["filing_party_persisted_count"] == 0


def test_run_backfill_persistence_path_is_omitted_when_zero_records_and_no_artifact(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/123456/0000123456-25-000001.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel,
                "Form Type": "8-K",
                "Date Filed": "2025-01-31",
                "url": "https://www.sec.gov/Archives/" + rel,
            }
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])

    path = tmp_path / ".sec_cache" / "Archives" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("dummy filing", encoding="utf-8")

    # Keep extraction stage successful while ensuring no filing-party records are eligible.
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
        persist_filing_parties=True,
    )

    expected_artifact = tmp_path / "refdata" / "normalized" / "filing_parties.parquet"
    assert result["filing_party_record_count"] == 0
    assert result["filing_party_candidate_count"] == 0
    assert result["filing_party_attempted_count"] == 0
    assert result["filing_party_zero_record_count"] == 0
    assert result["filing_party_persisted_count"] == 0
    assert result["filing_party_persist_path"] is None
    assert not expected_artifact.exists()


def test_run_backfill_extraction_path_emits_no_stdout_noise(monkeypatch, tmp_path, capsys):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/999999/0000999999-25-000001.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel,
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-31",
                "url": "https://www.sec.gov/Archives/" + rel,
            }
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])

    src = Path("tests/fixtures/filings/sc13d_sample.txt")
    path = tmp_path / ".sec_cache" / "Archives" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
        persist_filing_parties=False,
    )

    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_backfill_uses_configured_download_root_from_env(monkeypatch, tmp_path):
    download_root = tmp_path / "alt_cache" / "Archives"
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("PY_SEC_EDGAR_DOWNLOAD_ROOT", str(download_root))
    config = load_config()
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    rel = "edgar/data/320193/0000320193-25-000010.txt"
    df = pandas.DataFrame([{"Filename": rel, "url": "https://www.sec.gov/Archives/" + rel}])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)

    captured = {}

    class _Result:
        def __init__(self, url, filepath, success):
            self.url = url
            self.filepath = filepath
            self.success = success
            self.reason = None
            self.status_code = None
            self.error = None

    def fake_run_bounded_downloads(tasks, *, max_workers=None, downloader_config=None):
        task_list = list(tasks)
        captured["task"] = task_list[0]
        return [_Result(task_list[0].url, task_list[0].filepath, True)]

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", fake_run_bounded_downloads)

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=True,
        execute_extraction=False,
    )

    assert result["download_attempted_count"] == 1
    assert captured["task"].filepath.startswith(str(download_root.resolve()))


def test_run_backfill_fixture_backed_sc13da_and_sc13ga_extraction(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    rel_13da = "edgar/data/72971/0001193125-24-275026.txt"
    rel_13ga = "edgar/data/19617/0000019617-24-000658.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel_13da,
                "Form Type": "SC 13D/A",
                "Date Filed": "2024-12-11",
                "url": "https://www.sec.gov/Archives/" + rel_13da,
            },
            {
                "Filename": rel_13ga,
                "Form Type": "SC 13G/A",
                "Date Filed": "2024-12-04",
                "url": "https://www.sec.gov/Archives/" + rel_13ga,
            },
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)

    src_13da = Path("tests/fixtures/filings/sc13da_real_header_variant.txt")
    src_13ga = Path("tests/fixtures/filings/sc13ga_real_header_variant.txt")
    path_13da = tmp_path / ".sec_cache" / "Archives" / rel_13da
    path_13ga = tmp_path / ".sec_cache" / "Archives" / rel_13ga
    path_13da.parent.mkdir(parents=True, exist_ok=True)
    path_13ga.parent.mkdir(parents=True, exist_ok=True)
    path_13da.write_text(src_13da.read_text(encoding="utf-8"), encoding="utf-8")
    path_13ga.write_text(src_13ga.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
        persist_filing_parties=False,
    )

    assert result["candidate_count"] == 2
    assert result["filing_party_candidate_count"] == 2
    assert result["filing_party_attempted_count"] == 2
    assert result["filing_party_zero_record_count"] == 0
    assert result["filing_party_failed_count"] == 0
    assert result["filing_party_successful_nonzero_record_filing_count"] == 2
    assert result["filing_party_attempted_invariant_ok"] is True
    assert result["filing_party_record_count"] > 0


def test_run_backfill_zero_record_counter_for_supported_form_with_no_party_rows(monkeypatch, tmp_path):
    config = load_config(tmp_path)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.complete_submission_filing", lambda *args, **kwargs: pandas.DataFrame([]))

    rel = "edgar/data/72971/0001193125-24-275026.txt"
    df = pandas.DataFrame(
        [
            {
                "Filename": rel,
                "Form Type": "SC 13D/A",
                "Date Filed": "2024-12-11",
                "url": "https://www.sec.gov/Archives/" + rel,
            },
        ]
    )
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", lambda **kwargs: df)

    local = tmp_path / ".sec_cache" / "Archives" / rel
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("<SEC-HEADER>CONFORMED SUBMISSION TYPE: SC 13D/A</SEC-HEADER>", encoding="utf-8")

    result = run_backfill(
        config,
        refresh_index=False,
        execute_downloads=False,
        execute_extraction=True,
        persist_filing_parties=True,
    )

    assert result["filing_party_candidate_count"] == 1
    assert result["filing_party_attempted_count"] == 1
    assert result["filing_party_zero_record_count"] == 1
    assert result["filing_party_failed_count"] == 0
    assert result["filing_party_successful_nonzero_record_filing_count"] == 0
    assert result["filing_party_attempted_invariant_ok"] is True
    assert result["filing_party_persisted_count"] == 0
    assert result["filing_party_persist_path"] is None
