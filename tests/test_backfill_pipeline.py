from __future__ import annotations

from pathlib import Path

import pytest

pandas = pytest.importorskip("pandas")

from py_sec_edgar.config import load_config
from py_sec_edgar.pipelines.backfill import run_backfill


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
        def __init__(self, *, url, filepath, success, reason=None, status_code=None, error=None):
            self.url = url
            self.filepath = filepath
            self.success = success
            self.reason = reason
            self.status_code = status_code
            self.error = error

    captured = {}

    def fake_run_bounded_downloads(tasks, *, max_workers=None, downloader_config=None):
        work = list(tasks)
        captured["tasks"] = work
        captured["downloader_config"] = downloader_config
        return [
            _Result(url=work[0].url, filepath=work[0].filepath, success=True),
            _Result(url=work[1].url, filepath=work[1].filepath, success=False, reason="not_found", status_code=404),
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
    assert result["download_failures"][0]["reason"] == "not_found"
    assert result["download_failures"][0]["status_code"] == 404
    assert result["extraction_attempted_count"] == 0
    assert result["extraction_succeeded_count"] == 0
    assert result["extraction_failed_count"] == 0
    assert result["filing_party_record_count"] == 0
    assert result["filing_party_failed_count"] == 0


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
