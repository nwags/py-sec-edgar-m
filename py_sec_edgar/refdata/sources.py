from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from py_sec_edgar.refdata.normalize import normalize_cik, normalize_ticker


KNOWN_SOURCE_URLS: Dict[str, str] = {
    "company_tickers.json": "https://www.sec.gov/files/company_tickers.json",
    "company_tickers_exchange.json": "https://www.sec.gov/files/company_tickers_exchange.json",
    "company_tickers_mf.json": "https://www.sec.gov/files/company_tickers_mf.json",
    "ticker.txt": "https://www.sec.gov/include/ticker.txt",
    "cik-lookup-data.txt": "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt",
}

_INVESTMENT_PATTERN = re.compile(r"investment-company-series-class-(\d{4})\.csv$")
_CIK_LOOKUP_PATTERN = re.compile(r"^(?P<name>.*):(?P<cik>\d{1,10}):\s*$")


@dataclass(frozen=True)
class LoadedSources:
    company_tickers: pd.DataFrame
    company_tickers_exchange: pd.DataFrame
    company_tickers_mf: pd.DataFrame
    ticker_txt: pd.DataFrame
    cik_lookup: pd.DataFrame
    investment_company_series_class: pd.DataFrame
    source_paths: Dict[str, Path]


def discover_latest_investment_company_file(raw_root: Path) -> Path:
    matches = sorted(raw_root.glob("investment-company-series-class-*.csv"))
    if not matches:
        raise FileNotFoundError("No investment-company-series-class-*.csv found")

    ranked = []
    for path in matches:
        m = _INVESTMENT_PATTERN.search(path.name)
        year = int(m.group(1)) if m else -1
        ranked.append((year, path.stat().st_mtime, path))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_company_tickers(path: Path) -> pd.DataFrame:
    obj = _read_json(path)
    rows = []
    for item in obj.values():
        cik_raw = item.get("cik_str")
        ticker_raw = item.get("ticker")
        rows.append(
            {
                "issuer_cik_raw": str(cik_raw) if cik_raw is not None else None,
                "issuer_cik": normalize_cik(cik_raw),
                "ticker_raw": ticker_raw,
                "ticker": normalize_ticker(ticker_raw),
                "issuer_name": item.get("title"),
                "exchange": None,
                "sic": None,
                "is_mutual_fund": False,
                "is_etf": False,
                "source": "company_tickers.json",
            }
        )
    return pd.DataFrame(rows)


def load_company_tickers_exchange(path: Path) -> pd.DataFrame:
    obj = _read_json(path)
    fields = obj["fields"]
    rows = []
    for data_row in obj["data"]:
        item = dict(zip(fields, data_row))
        cik_raw = item.get("cik")
        ticker_raw = item.get("ticker")
        rows.append(
            {
                "issuer_cik_raw": str(cik_raw) if cik_raw is not None else None,
                "issuer_cik": normalize_cik(cik_raw),
                "ticker_raw": ticker_raw,
                "ticker": normalize_ticker(ticker_raw),
                "issuer_name": item.get("name"),
                "exchange": item.get("exchange"),
                "sic": None,
                "is_mutual_fund": False,
                "is_etf": False,
                "source": "company_tickers_exchange.json",
            }
        )
    return pd.DataFrame(rows)


def load_company_tickers_mf(path: Path) -> pd.DataFrame:
    obj = _read_json(path)
    fields = obj["fields"]
    rows = []
    for data_row in obj["data"]:
        item = dict(zip(fields, data_row))
        cik_raw = item.get("cik")
        ticker_raw = item.get("symbol")
        rows.append(
            {
                "fund_cik_raw": str(cik_raw) if cik_raw is not None else None,
                "fund_cik": normalize_cik(cik_raw),
                "series_id": item.get("seriesId"),
                "class_id": item.get("classId"),
                "class_ticker_raw": ticker_raw,
                "class_ticker": normalize_ticker(ticker_raw),
                "source": "company_tickers_mf.json",
            }
        )
    return pd.DataFrame(rows)


def load_ticker_txt(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            ticker_raw, cik_raw = line.split("\t", 1)
            rows.append(
                {
                    "entity_cik_raw": cik_raw,
                    "entity_cik": normalize_cik(cik_raw),
                    "ticker_raw": ticker_raw,
                    "ticker": normalize_ticker(ticker_raw),
                    "entity_name": None,
                    "source": "ticker.txt",
                }
            )
    return pd.DataFrame(rows)


def load_cik_lookup(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            match = _CIK_LOOKUP_PATTERN.match(raw)
            if match is None:
                continue
            name_value = match.group("name").strip()
            name = name_value if name_value else None
            cik_raw = match.group("cik").strip()
            rows.append(
                {
                    "entity_cik_raw": cik_raw,
                    "entity_cik": normalize_cik(cik_raw),
                    "entity_name": name,
                    "source": "cik-lookup-data.txt",
                }
            )
    return pd.DataFrame(rows)


def load_investment_company_series_class(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df = df.rename(
        columns={
            "CIK Number": "fund_cik_raw",
            "Entity Name": "entity_name",
            "Series ID": "series_id",
            "Series Name": "series_name",
            "Class ID": "class_id",
            "Class Name": "class_name",
            "Class Ticker": "class_ticker_raw",
            "Entity Org Type": "entity_org_type",
        }
    )
    out = pd.DataFrame(
        {
            "fund_cik_raw": df.get("fund_cik_raw"),
            "fund_cik": df.get("fund_cik_raw", pd.Series(dtype=str)).map(normalize_cik),
            "entity_name": df.get("entity_name"),
            "series_id": df.get("series_id"),
            "series_name": df.get("series_name"),
            "class_id": df.get("class_id"),
            "class_name": df.get("class_name"),
            "class_ticker_raw": df.get("class_ticker_raw"),
            "class_ticker": df.get("class_ticker_raw", pd.Series(dtype=str)).map(normalize_ticker),
            "entity_org_type": df.get("entity_org_type"),
            "source": path.name,
        }
    )
    return out


def load_all_sources(raw_root: Path) -> LoadedSources:
    source_paths = {
        "company_tickers": raw_root / "company_tickers.json",
        "company_tickers_exchange": raw_root / "company_tickers_exchange.json",
        "company_tickers_mf": raw_root / "company_tickers_mf.json",
        "ticker_txt": raw_root / "ticker.txt",
        "cik_lookup": raw_root / "cik-lookup-data.txt",
        "investment_company_series_class": discover_latest_investment_company_file(raw_root),
    }

    return LoadedSources(
        company_tickers=load_company_tickers(source_paths["company_tickers"]),
        company_tickers_exchange=load_company_tickers_exchange(source_paths["company_tickers_exchange"]),
        company_tickers_mf=load_company_tickers_mf(source_paths["company_tickers_mf"]),
        ticker_txt=load_ticker_txt(source_paths["ticker_txt"]),
        cik_lookup=load_cik_lookup(source_paths["cik_lookup"]),
        investment_company_series_class=load_investment_company_series_class(source_paths["investment_company_series_class"]),
        source_paths=source_paths,
    )


def source_url_for_filename(filename: str) -> Optional[str]:
    if filename in KNOWN_SOURCE_URLS:
        return KNOWN_SOURCE_URLS[filename]
    if filename.startswith("investment-company-series-class-"):
        return (
            "https://www.sec.gov/files/investment/data/other/"
            "investment-company-series-class-information/" + filename
        )
    return None
