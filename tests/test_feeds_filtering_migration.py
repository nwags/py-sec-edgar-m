from __future__ import annotations

from pathlib import Path

import pytest

pandas = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import py_sec_edgar.feeds as feeds
from py_sec_edgar.settings import get_config


def _write_filter_inputs(tmp_path: Path) -> dict[str, Path]:
    ref_root = tmp_path / "refdata"
    normalized_root = ref_root / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)

    issuers = pandas.DataFrame(
        [
            {"issuer_cik": "0000320193", "ticker": "AAPL", "issuer_name": "Apple"},
            {"issuer_cik": "0000789019", "ticker": "MSFT", "issuer_name": "Microsoft"},
        ]
    )
    entities = pandas.DataFrame(
        [
            {"entity_cik": "0000320193", "entity_name": "Apple Inc.", "is_issuer": True},
            {"entity_cik": "0000001234", "entity_name": "Fund GP", "is_issuer": False},
        ]
    )
    issuers.to_parquet(normalized_root / "issuers.parquet", index=False)
    entities.to_parquet(normalized_root / "entities.parquet", index=False)

    merged_idx = pandas.DataFrame(
        [
            {"CIK": "320193", "Form Type": "8-K", "Date Filed": "2025-01-15", "Filename": "edgar/data/320193/a.txt"},
            {"CIK": "789019", "Form Type": "SC 13D", "Date Filed": "2025-01-20", "Filename": "edgar/data/789019/b.txt"},
            {"CIK": "1234", "Form Type": "4", "Date Filed": "2025-01-21", "Filename": "edgar/data/1234/c.txt"},
        ]
    )
    merged_path = ref_root / "merged_idx_files.pq"
    merged_idx.to_parquet(merged_path, index=False)

    ticker_list = ref_root / "tickers.csv"
    ticker_list.write_text("aapl\n", encoding="utf-8")

    return {"ref_root": ref_root, "merged_path": merged_path, "ticker_list": ticker_list}


def _set_explicit_config(monkeypatch, paths: dict[str, Path]) -> None:
    cfg = get_config()
    monkeypatch.setattr(feeds, "CONFIG", cfg)
    monkeypatch.setattr(cfg, "REF_DIR", str(paths["ref_root"]))
    monkeypatch.setattr(cfg, "MERGED_IDX_FILEPATH", str(paths["merged_path"]))
    monkeypatch.setattr(cfg, "TICKER_LIST_FILEPATH", str(paths["ticker_list"]))
    monkeypatch.setattr(cfg, "edgar_Archives_url", "https://www.sec.gov/Archives/")


def test_load_filings_feed_legacy_ticker_bridge_resolves_via_normalized_parquet(monkeypatch, tmp_path):
    paths = _write_filter_inputs(tmp_path)
    _set_explicit_config(monkeypatch, paths)
    monkeypatch.setattr(feeds.CONFIG, "forms_list", ["8-K", "SC 13D"])

    df = feeds.load_filings_feed(ticker_list_filter=True, form_list_filter=False)

    assert df["CIK"].tolist() == ["320193"]
    assert df["Form Type"].tolist() == ["8-K"]
    assert df["url"].tolist() == ["https://www.sec.gov/Archives/edgar/data/320193/a.txt"]


def test_load_filings_feed_supports_entity_filters_and_forms_dates(monkeypatch, tmp_path):
    paths = _write_filter_inputs(tmp_path)
    _set_explicit_config(monkeypatch, paths)
    monkeypatch.setattr(feeds.CONFIG, "forms_list", ["8-K", "SC 13D", "4"])

    df = feeds.load_filings_feed(
        ticker_list_filter=False,
        form_list_filter=False,
        entity_ciks=["1234"],
        forms=["4"],
        date_from="2025-01-20",
        date_to="2025-01-22",
    )

    assert df["CIK"].tolist() == ["1234"]
    assert df["Form Type"].tolist() == ["4"]


def test_load_filings_feed_malformed_identifier_input_does_not_unfilter(monkeypatch, tmp_path):
    paths = _write_filter_inputs(tmp_path)
    _set_explicit_config(monkeypatch, paths)
    monkeypatch.setattr(feeds.CONFIG, "forms_list", ["8-K", "SC 13D", "4"])

    df = feeds.load_filings_feed(
        ticker_list_filter=False,
        form_list_filter=False,
        issuer_ciks=["not-a-cik"],
    )

    assert df.empty
