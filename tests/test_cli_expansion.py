from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import py_sec_edgar.cli as cli
from py_sec_edgar.config import load_config


def test_cli_help_includes_new_commands():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["--help"])

    assert result.exit_code == 0
    assert "refdata" in result.output
    assert "index" in result.output
    assert "backfill" in result.output
    assert "filing-parties" in result.output
    assert "lookup" in result.output
    assert "monitor" in result.output


def test_backfill_help_includes_entity_aware_selection_options():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["backfill", "--help"])

    assert result.exit_code == 0
    assert "--issuer-ticker" in result.output
    assert "--issuer-cik" in result.output
    assert "--entity-cik" in result.output
    assert "--form-family" in result.output
    assert "--date-from" in result.output
    assert "--date-to" in result.output
    assert "--execute-downloads" in result.output
    assert "--execute-extraction" in result.output
    assert "--persist-filing-parties" in result.output
    assert "--summary-json" in result.output
    assert "--verbose" in result.output
    assert "--quiet" in result.output
    assert "--log-level" in result.output
    assert "--log-file" in result.output


def test_index_refresh_help_includes_runtime_options():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["index", "refresh", "--help"])

    assert result.exit_code == 0
    assert "--verbose" in result.output
    assert "--quiet" in result.output
    assert "--log-level" in result.output
    assert "--log-file" in result.output


def test_refdata_refresh_help_includes_runtime_options():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["refdata", "refresh", "--help"])

    assert result.exit_code == 0
    assert "--verbose" in result.output
    assert "--quiet" in result.output
    assert "--log-level" in result.output
    assert "--log-file" in result.output


def test_lookup_refresh_help_includes_global_inventory_option():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["lookup", "refresh", "--help"])
    assert result.exit_code == 0
    assert "--include-global-filings" in result.output
    assert "--summary-json" in result.output


def test_lookup_query_help_includes_all_option():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["lookup", "query", "--help"])
    assert result.exit_code == 0
    assert "--all" in result.output
    assert "--scope" in result.output


def test_index_refresh_invokes_pipeline(monkeypatch):
    runner = CliRunner()
    calls = {}

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_index_refresh(config, *, save_idx_as_csv, skip_if_exists):
        calls["config"] = config
        calls["save_idx_as_csv"] = save_idx_as_csv
        calls["skip_if_exists"] = skip_if_exists

    monkeypatch.setattr(cli, "run_index_refresh", fake_run_index_refresh)

    result = runner.invoke(cli.main, ["index", "refresh", "--no-skip-if-exists", "--no-save-idx-as-csv"])

    assert result.exit_code == 0
    assert calls["skip_if_exists"] is False
    assert calls["save_idx_as_csv"] is False
    assert "Index refresh complete." in result.output


def test_refdata_refresh_quiet_mode_emits_minimal_line(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_refdata_refresh(config):
        return {
            "written": {"issuers": "/tmp/refdata/normalized/issuers.parquet"},
            "artifact_count": 1,
            "artifact_paths": ["/tmp/refdata/normalized/issuers.parquet"],
            "elapsed_seconds": 0.1,
            "activity_events": [],
        }

    monkeypatch.setattr(cli, "run_refdata_refresh", fake_run_refdata_refresh)
    result = runner.invoke(cli.main, ["refdata", "refresh", "--quiet"])
    assert result.exit_code == 0
    assert result.output.strip() == "Refdata refresh complete."


def test_refdata_refresh_surfaces_actionable_missing_raw_sources_error(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_refdata_refresh(config):
        raise FileNotFoundError(
            "Raw SEC source inputs are missing. Checked: /tmp/a, /tmp/b. "
            "Populate <project_root>/refdata/sec_sources or run from a repo/package context "
            "that includes bundled refdata/sec_sources."
        )

    monkeypatch.setattr(cli, "run_refdata_refresh", fake_run_refdata_refresh)

    result = runner.invoke(cli.main, ["refdata", "refresh", "--quiet"])
    assert result.exit_code != 0
    assert "Raw SEC source inputs are missing" in result.output
    assert "refdata/sec_sources" in result.output


def test_backfill_invokes_pipeline_and_option_plumbing(monkeypatch):
    runner = CliRunner()
    calls = {}

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_backfill(
        config,
        *,
        refresh_index,
        execute_downloads,
        execute_extraction,
        persist_filing_parties,
        ticker_list_filter,
        form_list_filter,
        ticker_list_filter_explicit,
        form_list_filter_explicit,
        issuer_tickers,
        issuer_ciks,
        entity_ciks,
        forms,
        form_families,
        date_from,
        date_to,
    ):
        calls["config"] = config
        calls["refresh_index"] = refresh_index
        calls["execute_downloads"] = execute_downloads
        calls["execute_extraction"] = execute_extraction
        calls["persist_filing_parties"] = persist_filing_parties
        calls["ticker_list_filter"] = ticker_list_filter
        calls["form_list_filter"] = form_list_filter
        calls["ticker_list_filter_explicit"] = ticker_list_filter_explicit
        calls["form_list_filter_explicit"] = form_list_filter_explicit
        calls["issuer_tickers"] = issuer_tickers
        calls["issuer_ciks"] = issuer_ciks
        calls["entity_ciks"] = entity_ciks
        calls["forms"] = forms
        calls["form_families"] = form_families
        calls["date_from"] = date_from
        calls["date_to"] = date_to
        return {
            "candidate_count": 3,
            "download_attempted_count": 3,
            "download_succeeded_count": 2,
            "download_failed_count": 1,
            "download_failure_reason_counts": {"http_error": 1},
            "download_failure_status_code_counts": {"404": 1},
            "download_failure_error_class_counts": {},
            "download_failures_sample": [
                {
                    "url": "https://www.sec.gov/Archives/edgar/data/789019/0000789019-25-000011.txt",
                    "filepath": "/tmp/.sec_cache/Archives/edgar/data/789019/0000789019-25-000011.txt",
                    "reason": "http_error",
                    "status_code": 404,
                    "error_class": None,
                    "error": None,
                }
            ],
            "extraction_attempted_count": 2,
            "extraction_succeeded_count": 1,
            "extraction_failed_count": 1,
            "filing_party_record_count": 5,
            "filing_party_persisted_count": 3,
            "filing_party_persist_path": "/tmp/refdata/normalized/filing_parties.parquet",
        }

    monkeypatch.setattr(cli, "run_backfill", fake_run_backfill)

    result = runner.invoke(
        cli.main,
        [
            "backfill",
            "--no-refresh-index",
            "--execute-downloads",
            "--execute-extraction",
            "--persist-filing-parties",
            "--no-ticker-list-filter",
            "--no-form-list-filter",
            "--issuer-ticker",
            "aapl",
            "--issuer-ticker",
            "msft",
            "--issuer-cik",
            "320193",
            "--entity-cik",
            "1234",
            "--form",
            "8-K",
            "--form-family",
            "beneficial_ownership",
            "--date-from",
            "2025-01-01",
            "--date-to",
            "2025-03-31",
        ],
    )

    assert result.exit_code == 0
    assert calls["refresh_index"] is False
    assert calls["execute_downloads"] is True
    assert calls["execute_extraction"] is True
    assert calls["persist_filing_parties"] is True
    assert calls["ticker_list_filter"] is False
    assert calls["form_list_filter"] is False
    assert calls["ticker_list_filter_explicit"] is True
    assert calls["form_list_filter_explicit"] is True
    assert calls["issuer_tickers"] == ["aapl", "msft"]
    assert calls["issuer_ciks"] == ["320193"]
    assert calls["entity_ciks"] == ["1234"]
    assert calls["forms"] == ["8-K"]
    assert calls["form_families"] == ["beneficial_ownership"]
    assert calls["date_from"] == "2025-01-01"
    assert calls["date_to"] == "2025-03-31"
    assert "candidate_count: 3" in result.output
    assert "download_attempted_count: 3" in result.output
    assert "download_succeeded_count: 2" in result.output
    assert "download_failed_count: 1" in result.output
    assert "download_failure_reason_counts: {'http_error': 1}" in result.output
    assert "download_failure_status_code_counts: {'404': 1}" in result.output
    assert "extraction_attempted_count: 2" in result.output
    assert "extraction_succeeded_count: 1" in result.output
    assert "extraction_failed_count: 1" in result.output
    assert "filing_party_record_count: 5" in result.output
    assert "filing_party_persisted_count: 3" in result.output
    assert "filing_party_persist_path: /tmp/refdata/normalized/filing_parties.parquet" in result.output


def test_backfill_default_legacy_filter_flags_are_not_marked_explicit(monkeypatch):
    runner = CliRunner()
    calls = {}

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_backfill(config, **kwargs):
        calls.update(kwargs)
        return {
            "candidate_count": 0,
            "download_attempted_count": 0,
            "download_succeeded_count": 0,
            "download_failed_count": 0,
            "extraction_attempted_count": 0,
            "extraction_succeeded_count": 0,
            "extraction_failed_count": 0,
            "filing_party_candidate_count": 0,
            "filing_party_attempted_count": 0,
            "filing_party_zero_record_count": 0,
            "filing_party_successful_nonzero_record_filing_count": 0,
            "filing_party_failed_count": 0,
            "filing_party_record_count": 0,
            "filing_party_persisted_count": 0,
            "filing_party_persist_path": None,
        }

    monkeypatch.setattr(cli, "run_backfill", fake_run_backfill)
    result = runner.invoke(cli.main, ["backfill"])

    assert result.exit_code == 0
    assert calls["ticker_list_filter"] is True
    assert calls["form_list_filter"] is True
    assert calls["ticker_list_filter_explicit"] is False
    assert calls["form_list_filter_explicit"] is False


def test_backfill_summary_json_outputs_valid_json(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_backfill(config, **kwargs):
        return {
            "candidate_count": 3,
            "download_attempted_count": 3,
            "download_succeeded_count": 2,
            "download_failed_count": 1,
            "download_failure_reason_counts": {"timeout": 1},
            "download_failure_status_code_counts": {},
            "download_failure_error_class_counts": {"Timeout": 1},
            "download_failures_sample": [
                {
                    "url": "https://example.test/a",
                    "filepath": "/tmp/a",
                    "reason": "timeout",
                    "status_code": None,
                    "error_class": "Timeout",
                    "error": "timed out",
                }
            ],
            "extraction_attempted_count": 2,
            "extraction_succeeded_count": 1,
            "extraction_failed_count": 1,
            "filing_party_candidate_count": 2,
            "filing_party_attempted_count": 2,
            "filing_party_zero_record_count": 1,
            "filing_party_successful_nonzero_record_filing_count": 1,
            "filing_party_failed_count": 0,
            "filing_party_record_count": 5,
            "filing_party_persisted_count": 3,
            "filing_party_persist_path": "/tmp/refdata/normalized/filing_parties.parquet",
        }

    monkeypatch.setattr(cli, "run_backfill", fake_run_backfill)

    result = runner.invoke(cli.main, ["backfill", "--summary-json"])
    assert result.exit_code == 0

    payload = json.loads(result.output.strip())
    assert payload["candidate_count"] == 3
    assert payload["download_attempted_count"] == 3
    assert payload["download_succeeded_count"] == 2
    assert payload["download_failed_count"] == 1
    assert payload["download_failure_reason_counts"] == {"timeout": 1}
    assert payload["download_failure_status_code_counts"] == {}
    assert payload["download_failure_error_class_counts"] == {"Timeout": 1}
    assert isinstance(payload["download_failures_sample"], list)
    assert payload["download_failures_sample"][0]["reason"] == "timeout"
    assert payload["extraction_attempted_count"] == 2
    assert payload["extraction_succeeded_count"] == 1
    assert payload["extraction_failed_count"] == 1
    assert payload["filing_party_candidate_count"] == 2
    assert payload["filing_party_attempted_count"] == 2
    assert payload["filing_party_zero_record_count"] == 1
    assert payload["filing_party_successful_nonzero_record_filing_count"] == 1
    assert payload["filing_party_failed_count"] == 0
    assert payload["filing_party_record_count"] == 5
    assert payload["filing_party_persisted_count"] == 3
    assert payload["filing_party_persist_path"] == "/tmp/refdata/normalized/filing_parties.parquet"
    assert "Backfill candidate load complete." not in result.output


def test_backfill_summary_json_stays_stdout_clean_with_verbose(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_backfill(config, **kwargs):
        return {
            "candidate_count": 1,
            "download_attempted_count": 1,
            "download_succeeded_count": 1,
            "download_failed_count": 0,
            "extraction_attempted_count": 0,
            "extraction_succeeded_count": 0,
            "extraction_failed_count": 0,
            "filing_party_record_count": 0,
            "filing_party_persisted_count": 0,
            "filing_party_persist_path": None,
            "activity_events": [{"stage": "download", "status": "success", "item": "edgar/data/x.txt"}],
        }

    monkeypatch.setattr(cli, "run_backfill", fake_run_backfill)
    echoes: list[tuple[str, bool]] = []

    def fake_echo(message=None, file=None, nl=True, err=False, color=None):
        echoes.append((str(message), bool(err)))

    monkeypatch.setattr(cli.click, "echo", fake_echo)
    result = runner.invoke(cli.main, ["backfill", "--summary-json", "--verbose"])
    assert result.exit_code == 0
    stdout_messages = [msg for msg, err in echoes if not err]
    stderr_messages = [msg for msg, err in echoes if err]
    assert len(stdout_messages) == 1
    payload = json.loads(stdout_messages[0])
    assert payload["candidate_count"] == 1
    assert any("Recent activity:" in msg for msg in stderr_messages)


def test_backfill_quiet_mode_suppresses_non_essential_summary(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_backfill(config, **kwargs):
        return {
            "candidate_count": 3,
            "download_attempted_count": 0,
            "download_succeeded_count": 0,
            "download_failed_count": 0,
            "extraction_attempted_count": 0,
            "extraction_succeeded_count": 0,
            "extraction_failed_count": 0,
            "filing_party_record_count": 0,
            "filing_party_persisted_count": 0,
            "filing_party_persist_path": None,
            "selection_elapsed_seconds": 0.01,
            "download_elapsed_seconds": 0.0,
            "extraction_elapsed_seconds": 0.0,
            "total_elapsed_seconds": 0.01,
            "activity_events": [],
        }

    monkeypatch.setattr(cli, "run_backfill", fake_run_backfill)
    result = runner.invoke(cli.main, ["backfill", "--quiet"])
    assert result.exit_code == 0
    assert "Backfill complete." in result.output
    assert "candidate_count" not in result.output


def test_backfill_summary_json_with_extraction_path_remains_clean_json(monkeypatch, tmp_path):
    runner = CliRunner()
    config = load_config(tmp_path)

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: config)

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_index_refresh", lambda *args, **kwargs: None)

    def fake_load_filings_feed(**kwargs):
        import pandas as pd

        return pd.DataFrame(
            [
                {
                    "Filename": "edgar/data/999999/0000999999-25-000001.txt",
                    "Form Type": "SC 13D",
                    "Date Filed": "2025-01-31",
                }
            ]
        )

    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.feeds.load_filings_feed", fake_load_filings_feed)
    monkeypatch.setattr("py_sec_edgar.pipelines.backfill.run_bounded_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "py_sec_edgar.pipelines.backfill.complete_submission_filing",
        lambda filepath, output_directory: None,
    )

    src = Path("tests/fixtures/filings/sc13d_sample.txt")
    local_file = tmp_path / ".sec_cache" / "Archives" / "edgar/data/999999/0000999999-25-000001.txt"
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = runner.invoke(
        cli.main,
        ["backfill", "--summary-json", "--execute-extraction", "--no-refresh-index"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["candidate_count"] == 1
    assert payload["extraction_attempted_count"] == 1
    assert payload["extraction_failed_count"] == 0
    assert payload["filing_party_record_count"] >= 1


def test_backfill_missing_merged_index_surfaces_actionable_error(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run_backfill(config, **kwargs):
        raise FileNotFoundError("Merged index file not found: /tmp/x/refdata/merged_idx_files.pq")

    monkeypatch.setattr(cli, "run_backfill", fake_run_backfill)

    result = runner.invoke(cli.main, ["backfill", "--no-refresh-index"])
    assert result.exit_code != 0
    assert "Merged index file not found:" in result.output
    assert "Run `py-sec-edgar index refresh` first." in result.output
