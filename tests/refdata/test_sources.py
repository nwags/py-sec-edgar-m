import json
from pathlib import Path

from py_sec_edgar.refdata.sources import discover_latest_investment_company_file, load_all_sources


def _write_raw_sources(raw_root: Path) -> None:
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
    (raw_root / "cik-lookup-data.txt").write_text(
        "APPLE INC:0000320193:\n"
        "ALPHA: BETA GP, LLC:0001234567:\n"
        "MALFORMED LINE WITHOUT CIK\n",
        encoding="utf-8",
    )

    header = (
        "Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,Series Name,"
        "Class ID,Class Name,Class Ticker,Address_1,Address_2,City,State,Zip Code\n"
    )
    old_row = (
        "002-1,0000002110,Old Fund,32,S0001,Old Series,C0001,Old Class,oldx,,,,,\n"
    )
    new_row = (
        "002-2,0000002110,New Fund,32,S0002,New Series,C0002,New Class,newx,,,,,\n"
    )
    (raw_root / "investment-company-series-class-2024.csv").write_text(header + old_row, encoding="utf-8")
    (raw_root / "investment-company-series-class-2025.csv").write_text(header + new_row, encoding="utf-8")


def test_discover_latest_investment_company_file(tmp_path: Path) -> None:
    raw_root = tmp_path / "sec_sources"
    _write_raw_sources(raw_root)

    latest = discover_latest_investment_company_file(raw_root)
    assert latest.name == "investment-company-series-class-2025.csv"


def test_load_all_sources_normalizes_cik_and_ticker(tmp_path: Path) -> None:
    raw_root = tmp_path / "sec_sources"
    _write_raw_sources(raw_root)

    loaded = load_all_sources(raw_root)

    assert loaded.company_tickers.iloc[0]["ticker"] == "AAPL"
    assert loaded.company_tickers.iloc[0]["issuer_cik"] == "0000320193"
    assert loaded.ticker_txt.iloc[0]["ticker"] == "AAPL"
    assert loaded.ticker_txt.iloc[0]["entity_cik"] == "0000320193"
    assert loaded.investment_company_series_class.iloc[0]["source"] == "investment-company-series-class-2025.csv"
    assert loaded.investment_company_series_class.iloc[0]["class_ticker"] == "NEWX"
    tricky = loaded.cik_lookup[loaded.cik_lookup["entity_cik"] == "0001234567"].iloc[0]
    assert tricky["entity_name"] == "ALPHA: BETA GP, LLC"
    assert "MALFORMED LINE WITHOUT CIK" not in loaded.cik_lookup["entity_name"].fillna("").tolist()
