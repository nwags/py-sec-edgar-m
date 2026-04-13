from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
import pandas as pd

import py_sec_edgar.cli as cli
from py_sec_edgar.config import load_config


def _write_filing_parties_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [
            {
                "accession_number": "0000000001-25-000001",
                "form_type": "SC 13D",
                "filing_date": "2025-01-15",
                "party_role": "issuer",
                "party_cik": "0000123456",
                "party_name": "ACME CORP",
                "issuer_cik": "0000123456",
                "issuer_name": "ACME CORP",
                "source": "sec_header",
                "source_filename": "edgar/data/123456/0000000001-25-000001.txt",
            },
            {
                "accession_number": "0000000001-25-000001",
                "form_type": "SC 13D",
                "filing_date": "2025-01-15",
                "party_role": "reporting_owner",
                "party_cik": "0000999999",
                "party_name": "ACTIVIST FUND LP",
                "issuer_cik": "0000123456",
                "issuer_name": "ACME CORP",
                "source": "sec_header",
                "source_filename": "edgar/data/123456/0000000001-25-000001.txt",
            },
            {
                "accession_number": "0000000002-25-000001",
                "form_type": "4",
                "filing_date": "2025-02-01",
                "party_role": "director",
                "party_cik": "0001777777",
                "party_name": "JANE DOE",
                "issuer_cik": "0000123456",
                "issuer_name": "ACME CORP",
                "source": "ownership_xml",
                "source_filename": "edgar/data/1777777/0000000002-25-000001.txt",
            },
        ]
    )
    df.to_parquet(path, index=False)


def test_filing_parties_query_help_includes_options(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: load_config(tmp_path))

    result = runner.invoke(cli.main, ["filing-parties", "query", "--help"])
    assert result.exit_code == 0
    assert "--issuer-cik" in result.output
    assert "--party-cik" in result.output
    assert "--role" in result.output
    assert "--form-type" in result.output
    assert "--accession-number" in result.output
    assert "--limit" in result.output
    assert "--columns" in result.output
    assert "--json" in result.output


def test_filing_parties_query_human_readable_filters(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = runner = CliRunner().invoke(
        cli.main,
        [
            "filing-parties",
            "query",
            "--issuer-cik",
            "123456",
            "--role",
            "director",
            "--form-type",
            "4",
        ],
    )
    assert result.exit_code == 0
    assert "JANE DOE" in result.output
    assert "director" in result.output
    assert "0000000002-25-000001" in result.output


def test_filing_parties_query_json_output_and_filters(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(
        cli.main,
        [
            "filing-parties",
            "query",
            "--party-cik",
            "999999",
            "--accession-number",
            "0000000001-25-000001",
            "--date-from",
            "2025-01-01",
            "--date-to",
            "2025-01-31",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["party_name"] == "ACTIVIST FUND LP"
    assert payload[0]["party_role"] == "reporting_owner"


def test_filing_parties_query_limit_applies_after_filtering(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(
        cli.main,
        [
            "filing-parties",
            "query",
            "--issuer-cik",
            "123456",
            "--limit",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert len(payload) == 1
    assert payload[0]["issuer_cik"] == "0000123456"


def test_filing_parties_query_columns_human_readable(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(
        cli.main,
        [
            "filing-parties",
            "query",
            "--role",
            "reporting_owner",
            "--columns",
            "accession_number,party_name,party_role",
        ],
    )
    assert result.exit_code == 0
    assert "accession_number" in result.output
    assert "party_name" in result.output
    assert "party_role" in result.output
    assert "form_type" not in result.output


def test_filing_parties_query_columns_json(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(
        cli.main,
        [
            "filing-parties",
            "query",
            "--party-cik",
            "999999",
            "--columns",
            "accession_number,party_name",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert len(payload) == 1
    assert set(payload[0].keys()) == {"accession_number", "party_name"}


def test_filing_parties_query_invalid_columns_fails_cleanly(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(
        cli.main,
        ["filing-parties", "query", "--columns", "accession_number,not_a_column"],
    )
    assert result.exit_code != 0
    assert "Unknown column(s): not_a_column" in result.output


def test_filing_parties_query_missing_artifact_fails_cleanly(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(cli.main, ["filing-parties", "query"])
    assert result.exit_code != 0
    assert "Missing filing-party artifact" in result.output
    assert "--persist-filing-parties" in result.output


def test_filing_parties_query_empty_match_human_readable(monkeypatch, tmp_path):
    cfg = load_config(tmp_path)
    _write_filing_parties_fixture(cfg.normalized_refdata_root / "filing_parties.parquet")
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)

    result = CliRunner().invoke(
        cli.main,
        ["filing-parties", "query", "--form-type", "8-K"],
    )
    assert result.exit_code == 0
    assert "No filing-party rows matched." in result.output
