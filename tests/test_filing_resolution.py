from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from py_sec_edgar.config import load_config
from py_sec_edgar.filing_resolution import (
    canonical_local_submission_path,
    canonical_submission_filename,
    canonical_submission_url,
    parse_accession_number,
    resolve_filing_identity,
)
from py_sec_edgar.lookup import local_lookup_filings_path


def _write_merged_index(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def _write_local_lookup(config, rows: list[dict[str, object]]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(local_lookup_filings_path(config), index=False)


def test_parse_accession_number_strict_validation() -> None:
    assert parse_accession_number("0000320193-25-000010") == "0000320193-25-000010"
    with pytest.raises(ValueError, match="Invalid accession number format"):
        parse_accession_number("320193-25-10")


def test_canonical_submission_filename_normalizes_index_link_to_txt() -> None:
    out = canonical_submission_filename(
        filename="edgar/data/320193/0000320193-25-000010-index.htm",
        accession_number="0000320193-25-000010",
        filing_cik="0000320193",
    )
    assert out == "edgar/data/320193/0000320193-25-000010.txt"


def test_canonical_submission_url_and_local_path_are_deterministic(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    filename = "edgar/data/320193/0000320193-25-000010.txt"
    assert canonical_submission_url(filename, config=config) == "https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000010.txt"
    assert canonical_local_submission_path(config, filename) == config.download_root / Path(filename)


def test_resolve_filing_identity_prefers_local_lookup_over_merged_index(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_local_lookup(
        config,
        [
            {
                "accession_number": "0000320193-25-000010",
                "filing_cik": "0000320193",
                "form_type": "SC 13D",
                "filing_date": "2025-01-15",
                "filename": "edgar/data/320193/0000320193-25-000010.txt",
                "submission_exists": True,
                "submission_path_count": 1,
            }
        ],
    )
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2025-01-20",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )

    identity = resolve_filing_identity(config, "0000320193-25-000010")
    assert identity is not None
    assert identity.metadata_source == "local_lookup_filings"
    assert identity.metadata_surface == "local_lookup_filings"
    assert identity.form_type == "SC 13D"


def test_resolve_filing_identity_falls_back_to_merged_index(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_merged_index(
        config,
        [
            {
                "CIK": "320193",
                "Form Type": "SC 13D",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ],
    )

    identity = resolve_filing_identity(config, "0000320193-25-000010")
    assert identity is not None
    assert identity.metadata_source == "merged_index"
    assert identity.metadata_surface == "sec_archives_full_or_daily_index_merged"
    assert identity.filename == "edgar/data/320193/0000320193-25-000010.txt"
