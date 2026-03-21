from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
import pandas as pd

import py_sec_edgar.cli as cli
from py_sec_edgar.config import load_config


def _seed_lookup_inputs(config, *, with_filing_parties: bool = True) -> list[dict]:
    config.ensure_runtime_dirs()
    merged_rows = [
        {
            "CIK": "320193",
            "Form Type": "SC 13D",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/320193/0000320193-25-000010.txt",
        },
        {
            "CIK": "999999",
            "Form Type": "SC 13D/A",
            "Date Filed": "2025-01-16",
            "Filename": "edgar/data/999999/0000320193-25-000010.txt",
        },
        {
            "CIK": "789019",
            "Form Type": "4",
            "Date Filed": "2025-02-10",
            "Filename": "edgar/data/789019/0000789019-25-000123.txt",
        },
    ]
    pd.DataFrame(merged_rows).to_parquet(config.merged_index_path, index=False)

    for rel in [merged_rows[0]["Filename"], merged_rows[1]["Filename"]]:
        submission = config.download_root / rel
        submission.parent.mkdir(parents=True, exist_ok=True)
        submission.write_text("submission", encoding="utf-8")
        extracted_dir = submission.parent / submission.stem.replace("-", "")
        extracted_dir.mkdir(parents=True, exist_ok=True)
        (extracted_dir / "primary_doc.xml").write_text("x", encoding="utf-8")

    if with_filing_parties:
        filing_parties = pd.DataFrame(
            [
                {"accession_number": "0000320193-25-000010", "party_role": "issuer"},
                {"accession_number": "0000320193-25-000010", "party_role": "reporting_owner"},
            ]
        )
        filing_parties.to_parquet(config.normalized_refdata_root / "filing_parties.parquet", index=False)
    return merged_rows


def test_lookup_help_includes_commands(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: load_config(tmp_path))
    result = runner.invoke(cli.main, ["lookup", "--help"])
    assert result.exit_code == 0
    assert "refresh" in result.output
    assert "query" in result.output


def test_lookup_refresh_help_and_query_help(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: load_config(tmp_path))
    refresh_help = runner.invoke(cli.main, ["lookup", "refresh", "--help"])
    query_help = runner.invoke(cli.main, ["lookup", "query", "--help"])
    assert refresh_help.exit_code == 0
    assert "--summary-json" in refresh_help.output
    assert "--progress-json" in refresh_help.output
    assert "--include-global-filings" in refresh_help.output
    assert query_help.exit_code == 0
    assert "--scope" in query_help.output
    assert "--all" in query_help.output
    assert "--accession-number" in query_help.output
    assert "--artifact-type" in query_help.output
    assert "--path-contains" in query_help.output
    assert "--columns" in query_help.output
    assert "--json" in query_help.output


def test_lookup_refresh_summary_json_is_valid_and_bounded(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    _seed_lookup_inputs(cfg, with_filing_parties=True)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(cli.main, ["lookup", "refresh", "--summary-json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert set(payload.keys()) == {
        "artifacts_index_path",
        "artifacts_row_count",
        "deduped_global_filing_row_count",
        "deduped_local_filing_row_count",
        "elapsed_seconds",
        "filing_parties_available",
        "filings_index_path",
        "filings_row_count",
        "global_filings_index_path",
        "global_filings_index_written",
        "global_filings_row_count",
        "local_placement_row_count",
        "placement_row_count",
        "scanned_extracted_dir_count",
    }
    assert payload["filings_row_count"] == 1
    assert payload["global_filings_index_written"] is False
    assert payload["global_filings_row_count"] == 0
    assert payload["placement_row_count"] == 3
    assert payload["local_placement_row_count"] == 2
    assert payload["deduped_local_filing_row_count"] == 1
    assert payload["deduped_global_filing_row_count"] == 0
    assert payload["scanned_extracted_dir_count"] == 3


def test_lookup_query_default_filings_is_local_first_and_deduped(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    _seed_lookup_inputs(cfg, with_filing_parties=True)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    runner = CliRunner()
    assert runner.invoke(cli.main, ["lookup", "refresh"]).exit_code == 0

    by_default = runner.invoke(cli.main, ["lookup", "query", "--scope", "filings", "--json"])
    assert by_default.exit_code == 0
    payload = json.loads(by_default.output.strip())
    assert len(payload) == 1
    assert payload[0]["accession_number"] == "0000320193-25-000010"
    assert payload[0]["local_submission_path_count"] == 2
    assert payload[0]["local_extracted_dir_count"] == 2
    assert payload[0]["local_artifact_file_count"] == 2
    assert payload[0]["filing_party_record_count"] == 2
    assert payload[0]["filing_party_record_count_max"] == 2


def test_lookup_query_all_requires_global_and_works_when_present(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    _seed_lookup_inputs(cfg, with_filing_parties=False)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    runner = CliRunner()

    assert runner.invoke(cli.main, ["lookup", "refresh"]).exit_code == 0
    missing_global = runner.invoke(cli.main, ["lookup", "query", "--scope", "filings", "--all", "--json"])
    assert missing_global.exit_code != 0
    assert "lookup refresh --include-global-filings" in missing_global.output

    assert runner.invoke(cli.main, ["lookup", "refresh", "--include-global-filings"]).exit_code == 0
    all_rows = runner.invoke(cli.main, ["lookup", "query", "--scope", "filings", "--all", "--json"])
    assert all_rows.exit_code == 0
    payload = json.loads(all_rows.output.strip())
    assert len(payload) == 2


def test_lookup_query_artifacts_scope_remains_path_level(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    _seed_lookup_inputs(cfg, with_filing_parties=False)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    runner = CliRunner()
    assert runner.invoke(cli.main, ["lookup", "refresh"]).exit_code == 0

    result = runner.invoke(
        cli.main,
        [
            "lookup",
            "query",
            "--scope",
            "artifacts",
            "--artifact-type",
            "submission",
            "--path-contains",
            "0000320193-25-000010",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert len(payload) == 2
    assert all(item["artifact_type"] == "submission" for item in payload)


def test_lookup_query_all_rejected_for_artifacts(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    _seed_lookup_inputs(cfg, with_filing_parties=False)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    runner = CliRunner()
    assert runner.invoke(cli.main, ["lookup", "refresh"]).exit_code == 0
    result = runner.invoke(cli.main, ["lookup", "query", "--scope", "artifacts", "--all"])
    assert result.exit_code != 0
    assert "`--all` is only supported for `--scope filings`." in result.output


def test_lookup_query_invalid_columns_and_missing_artifact_fail_cleanly(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    runner = CliRunner()

    missing = runner.invoke(cli.main, ["lookup", "query"])
    assert missing.exit_code != 0
    assert "Missing lookup artifact" in missing.output
    assert "lookup refresh" in missing.output

    _seed_lookup_inputs(cfg, with_filing_parties=False)
    assert runner.invoke(cli.main, ["lookup", "refresh"]).exit_code == 0
    invalid_cols = runner.invoke(
        cli.main,
        ["lookup", "query", "--columns", "accession_number,not_a_column"],
    )
    assert invalid_cols.exit_code != 0
    assert "Unknown column(s): not_a_column" in invalid_cols.output


def test_lookup_smoke_local_flow_refresh_then_queries(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "smoke_root")
    _seed_lookup_inputs(cfg, with_filing_parties=True)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    runner = CliRunner()

    refresh = runner.invoke(cli.main, ["lookup", "refresh", "--summary-json"])
    assert refresh.exit_code == 0
    refresh_payload = json.loads(refresh.output.strip())
    assert refresh_payload["filings_row_count"] == 1
    assert refresh_payload["artifacts_row_count"] == 4
    assert refresh_payload["placement_row_count"] == 3
    assert refresh_payload["local_placement_row_count"] == 2
    assert refresh_payload["deduped_local_filing_row_count"] == 1
    assert refresh_payload["scanned_extracted_dir_count"] == 3

    filings_default = runner.invoke(cli.main, ["lookup", "query", "--scope", "filings", "--limit", "1"])
    assert filings_default.exit_code == 0
    assert "local_submission_path_count" in filings_default.output
    assert "local_extracted_dir_count" in filings_default.output
    assert "local_artifact_file_count" in filings_default.output
    assert "filing_party_record_count_max" in filings_default.output

    artifacts_json = runner.invoke(cli.main, ["lookup", "query", "--scope", "artifacts", "--limit", "2", "--json"])
    assert artifacts_json.exit_code == 0
    payload = json.loads(artifacts_json.output.strip())
    assert len(payload) == 2


def test_lookup_refresh_keyboard_interrupt_exits_cleanly(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    def fake_refresh(config, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "refresh_local_lookup_indexes", fake_refresh)
    result = CliRunner().invoke(cli.main, ["lookup", "refresh"])
    assert result.exit_code != 0
    assert "Interrupted by user." in result.output
    assert "Traceback" not in result.output


def test_lookup_refresh_summary_json_with_progress_json_keeps_stdout_clean(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    _seed_lookup_inputs(cfg, with_filing_parties=True)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(cli.main, ["lookup", "refresh", "--summary-json", "--progress-json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout.strip())
    assert payload["filings_row_count"] == 1

