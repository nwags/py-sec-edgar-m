from __future__ import annotations

from pathlib import Path

import pytest

pandas = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from py_sec_edgar.filters import (
    apply_filing_filters,
    build_cik_filter_set,
    load_normalized_filter_tables,
)


def _write_normalized_filter_tables(root: Path) -> tuple[pandas.DataFrame, pandas.DataFrame]:
    root.mkdir(parents=True, exist_ok=True)
    issuers = pandas.DataFrame(
        [
            {"issuer_cik": "320193", "ticker": "aapl", "issuer_name": "Apple"},
            {"issuer_cik": "0000789019", "ticker": "MSFT", "issuer_name": "Microsoft"},
        ]
    )
    entities = pandas.DataFrame(
        [
            {"entity_cik": "0000320193", "entity_name": "Apple Inc.", "is_issuer": True},
            {"entity_cik": "1234", "entity_name": "Fund GP", "is_issuer": False},
        ]
    )
    issuers.to_parquet(root / "issuers.parquet", index=False)
    entities.to_parquet(root / "entities.parquet", index=False)
    return issuers, entities


def test_load_normalized_filter_tables_normalizes_keys(tmp_path: Path) -> None:
    _write_normalized_filter_tables(tmp_path)

    issuers, entities = load_normalized_filter_tables(tmp_path)

    assert issuers["issuer_cik"].tolist() == ["0000320193", "0000789019"]
    assert issuers["ticker"].tolist() == ["AAPL", "MSFT"]
    assert entities["entity_cik"].tolist() == ["0000320193", "0000001234"]


def test_build_cik_filter_set_supports_ticker_issuer_and_entity_inputs(tmp_path: Path) -> None:
    _write_normalized_filter_tables(tmp_path)
    issuers, entities = load_normalized_filter_tables(tmp_path)

    selected = build_cik_filter_set(
        issuers=issuers,
        entities=entities,
        issuer_tickers=["aapl"],
        issuer_ciks=["789019"],
        entity_ciks=["1234"],
    )

    assert selected == {"0000320193", "0000789019", "0000001234"}


def test_build_cik_filter_set_with_only_malformed_inputs_returns_empty_set(tmp_path: Path) -> None:
    _write_normalized_filter_tables(tmp_path)
    issuers, entities = load_normalized_filter_tables(tmp_path)

    selected = build_cik_filter_set(
        issuers=issuers,
        entities=entities,
        issuer_tickers=["!!!"],
        issuer_ciks=["not-a-cik"],
        entity_ciks=["also-bad"],
    )

    assert selected == set()


def test_apply_filing_filters_supports_cik_forms_and_date_range() -> None:
    filings = pandas.DataFrame(
        [
            {"CIK": "320193", "Form Type": "8-K", "Date Filed": "2025-01-15"},
            {"CIK": "0000789019", "Form Type": "SC 13D", "Date Filed": "2025-01-20"},
            {"CIK": "1234", "Form Type": "10-K", "Date Filed": "2025-01-25"},
        ]
    )

    filtered = apply_filing_filters(
        filings,
        cik_filter_set={"0000320193", "0000789019"},
        form_families=["beneficial_ownership", "current_reports"],
        date_from="2025-01-10",
        date_to="2025-01-22",
    )

    assert filtered["Form Type"].tolist() == ["8-K", "SC 13D"]
    assert filtered["CIK_CANONICAL"].tolist() == ["0000320193", "0000789019"]
