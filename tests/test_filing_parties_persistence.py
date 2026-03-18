from __future__ import annotations

from pathlib import Path

import pandas as pd

from py_sec_edgar.filing_parties import upsert_filing_parties_parquet


def _sample_records() -> list[dict]:
    return [
        {
            "accession_number": "0000000001-25-000001",
            "form_type": "SC 13D",
            "filing_date": "2025-01-31",
            "party_role": "issuer",
            "party_cik": "123456",
            "party_name": "ACME CORP",
            "issuer_cik": "123456",
            "issuer_name": "ACME CORP",
            "source": "sec_header",
            "source_filename": "edgar/data/123456/0000000001-25-000001.txt",
        },
        {
            "accession_number": "0000000001-25-000001",
            "form_type": "SC 13D",
            "filing_date": "2025-01-31",
            "party_role": "reporting_owner",
            "party_cik": "999999",
            "party_name": "ACTIVIST FUND",
            "issuer_cik": "123456",
            "issuer_name": "ACME CORP",
            "source": "sec_header",
            "source_filename": "edgar/data/123456/0000000001-25-000001.txt",
        },
    ]


def test_upsert_filing_parties_parquet_writes_and_normalizes(tmp_path: Path) -> None:
    out = tmp_path / "filing_parties.parquet"
    inserted = upsert_filing_parties_parquet(records=_sample_records(), output_path=out)

    assert inserted == 2
    assert out.exists()
    df = pd.read_parquet(out)
    assert len(df.index) == 2
    assert set(df.columns) >= {
        "accession_number",
        "party_role",
        "party_cik",
        "party_name",
        "source_filename",
    }
    assert df["party_cik"].tolist()[0].startswith("000")


def test_upsert_filing_parties_parquet_is_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "filing_parties.parquet"
    records = _sample_records()
    first = upsert_filing_parties_parquet(records=records, output_path=out)
    second = upsert_filing_parties_parquet(records=records, output_path=out)

    assert first == 2
    assert second == 0
    df = pd.read_parquet(out)
    assert len(df.index) == 2


def test_upsert_filing_parties_parquet_dedupes_across_runs(tmp_path: Path) -> None:
    out = tmp_path / "filing_parties.parquet"
    base = _sample_records()
    upsert_filing_parties_parquet(records=base, output_path=out)

    second_batch = [
        base[0],  # duplicate
        {
            "accession_number": "0000000002-25-000001",
            "form_type": "4",
            "filing_date": "2025-02-01",
            "party_role": "reporting_owner",
            "party_cik": "1777777",
            "party_name": "JANE DOE",
            "issuer_cik": "123456",
            "issuer_name": "ACME CORP",
            "source": "ownership_xml",
            "source_filename": "edgar/data/1777777/0000000002-25-000001.txt",
        },
    ]

    inserted = upsert_filing_parties_parquet(records=second_batch, output_path=out)
    assert inserted == 1
    df = pd.read_parquet(out)
    assert len(df.index) == 3
