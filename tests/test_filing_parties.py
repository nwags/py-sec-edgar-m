from __future__ import annotations

from pathlib import Path

from py_sec_edgar.filing_parties import (
    extract_filing_parties_from_file,
    extract_filing_parties_from_text,
)


def test_extract_filing_parties_from_text_sc13d_foundational_roles() -> None:
    raw_text = (
        "<SEC-HEADER>\n"
        "SUBJECT COMPANY:\n"
        "    COMPANY CONFORMED NAME: ACME CORP\n"
        "    CENTRAL INDEX KEY: 123456\n"
        "FILED BY:\n"
        "    COMPANY CONFORMED NAME: ACTIVIST FUND LP\n"
        "    CENTRAL INDEX KEY: 999999\n"
        "</SEC-HEADER>\n"
    )

    records = extract_filing_parties_from_text(
        raw_text=raw_text,
        form_type="SC 13D",
        filing_date="2025-01-31",
        source_filename="edgar/data/999999/0000999999-25-000001.txt",
    )

    roles = {row["party_role"] for row in records}
    assert roles == {"subject_company", "issuer", "reporting_owner"}

    issuer = [row for row in records if row["party_role"] == "issuer"][0]
    owner = [row for row in records if row["party_role"] == "reporting_owner"][0]
    assert issuer["party_cik"] == "0000123456"
    assert owner["party_cik"] == "0000999999"
    assert issuer["accession_number"] == "0000999999-25-000001"


def test_extract_filing_parties_from_text_unsupported_form_returns_empty() -> None:
    records = extract_filing_parties_from_text(
        raw_text="<SEC-HEADER>SUBJECT COMPANY:</SEC-HEADER>",
        form_type="8-K",
    )
    assert records == []


def test_extract_filing_parties_from_file_fixture() -> None:
    fixture = Path("tests/fixtures/filings/sc13d_sample.txt")
    records = extract_filing_parties_from_file(
        filing_filepath=fixture,
        form_type="SC 13D/A",
        filing_date="2025-01-31",
        source_filename="edgar/data/999999/0000999999-25-000001.txt",
    )
    assert len(records) == 3
    assert all(row["form_type"] == "SC 13D/A" for row in records)


def test_extract_filing_parties_sc13da_real_header_variant_fixture() -> None:
    fixture = Path("tests/fixtures/filings/sc13da_real_header_variant.txt")
    records = extract_filing_parties_from_file(
        filing_filepath=fixture,
        form_type="SC 13D/A",
        filing_date="2024-12-11",
        source_filename="edgar/data/72971/0001193125-24-275026.txt",
    )
    assert len(records) >= 2
    roles = {row["party_role"] for row in records}
    assert "issuer" in roles
    assert "reporting_owner" in roles


def test_extract_filing_parties_sc13ga_real_header_variant_fixture() -> None:
    fixture = Path("tests/fixtures/filings/sc13ga_real_header_variant.txt")
    records = extract_filing_parties_from_file(
        filing_filepath=fixture,
        form_type="SC 13G/A",
        filing_date="2024-12-04",
        source_filename="edgar/data/19617/0000019617-24-000658.txt",
    )
    assert len(records) >= 2
    roles = {row["party_role"] for row in records}
    assert "issuer" in roles
    assert "reporting_owner" in roles


def test_extract_filing_parties_from_text_form4_roles() -> None:
    raw_text = Path("tests/fixtures/filings/form4_sample.txt").read_text(encoding="utf-8")
    records = extract_filing_parties_from_text(
        raw_text=raw_text,
        form_type="4",
        filing_date="2025-02-01",
        source_filename="edgar/data/1777777/0001777777-25-000010.txt",
    )
    roles = {row["party_role"] for row in records}
    assert roles == {"issuer", "reporting_owner", "director", "officer", "ten_percent_owner"}

    issuer = [row for row in records if row["party_role"] == "issuer"][0]
    assert issuer["party_cik"] == "0000123456"
    assert issuer["party_name"] == "ACME CORP"

    directors = [row for row in records if row["party_role"] == "director"]
    assert len(directors) == 1
    assert directors[0]["party_name"] == "JANE DOE"

    ten_pct = [row for row in records if row["party_role"] == "ten_percent_owner"]
    assert len(ten_pct) == 1
    assert ten_pct[0]["party_name"] == "VALUE PARTNERS LP"


def test_extract_filing_parties_from_file_fixture_form3_and_form5_supported() -> None:
    fixture = Path("tests/fixtures/filings/form4_sample.txt")
    form3_records = extract_filing_parties_from_file(
        filing_filepath=fixture,
        form_type="3",
        filing_date="2025-02-01",
        source_filename="edgar/data/1777777/0001777777-25-000010.txt",
    )
    form5_records = extract_filing_parties_from_file(
        filing_filepath=fixture,
        form_type="5",
        filing_date="2025-02-01",
        source_filename="edgar/data/1777777/0001777777-25-000010.txt",
    )
    assert form3_records
    assert form5_records
    assert all(item["form_type"] == "3" for item in form3_records)
    assert all(item["form_type"] == "5" for item in form5_records)
