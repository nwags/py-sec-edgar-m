import json
from pathlib import Path

import pandas as pd

from py_sec_edgar.config import load_config
from py_sec_edgar.pipelines.refdata_refresh import run_refdata_refresh


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
    (raw_root / "cik-lookup-data.txt").write_text("APPLE INC:0000320193:\n", encoding="utf-8")
    (raw_root / "investment-company-series-class-2025.csv").write_text(
        "Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,Series Name,"
        "Class ID,Class Name,Class Ticker,Address_1,Address_2,City,State,Zip Code\n"
        "002-2,0000002110,New Fund,32,S0002,New Series,C0002,New Class,newx,,,,,\n",
        encoding="utf-8",
    )


def test_refdata_refresh_writes_expected_parquet_outputs(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _write_raw_sources(config.raw_refdata_root)

    written = run_refdata_refresh(config)

    expected = {
        "issuers",
        "entities",
        "entity_aliases",
        "series_classes",
        "reference_file_manifest",
    }
    assert set(written.keys()) == expected
    for path in written.values():
        assert path.exists()

    issuers = pd.read_parquet(written["issuers"])
    assert (issuers["issuer_cik"].str.len() == 10).all()
    assert issuers["ticker"].dropna().str.upper().equals(issuers["ticker"].dropna())

    manifest = pd.read_parquet(written["reference_file_manifest"])
    entities = pd.read_parquet(written["entities"])
    required_cols = {
        "filename",
        "source_url",
        "sha256",
        "file_size_bytes",
        "mtime_utc",
        "ingested_at_utc",
        "source_type",
        "schema_version",
    }
    assert required_cols.issubset(set(manifest.columns))
    assert (manifest["sha256"].str.len() == 64).all()
    assert (manifest["schema_version"] == "refdata_v1").all()

    fund_entities = entities[entities["entity_type"] == "fund"]
    fund_2110 = fund_entities[fund_entities["entity_cik"] == "0000002110"].iloc[0]
    assert fund_2110["entity_name"] == "New Fund"
    assert fund_entities["source_updated_at"].notna().all()
