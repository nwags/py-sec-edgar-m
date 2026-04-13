from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.refdata.normalize import normalize_cik


def filing_parties_parquet_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "filing_parties.parquet"


def load_filing_parties_parquet(config: AppConfig) -> pd.DataFrame:
    path = filing_parties_parquet_path(config)
    if not path.exists():
        raise FileNotFoundError(
            "Missing filing-party artifact: "
            f"{path}. Build it first with a backfill run that includes "
            "`--persist-filing-parties` (for example: "
            "`py-sec-edgar backfill --execute-downloads --persist-filing-parties`)."
        )
    return pd.read_parquet(path)


def _normalize_many_ciks(values: Iterable[str]) -> set[str]:
    out = set()
    for value in values:
        cik = normalize_cik(value)
        if cik:
            out.add(cik)
    return out


def query_filing_parties(
    df: pd.DataFrame,
    *,
    issuer_ciks: list[str] | None = None,
    party_ciks: list[str] | None = None,
    roles: list[str] | None = None,
    form_types: list[str] | None = None,
    accession_numbers: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> pd.DataFrame:
    out = df.copy()

    issuer_cik_set = _normalize_many_ciks(issuer_ciks or [])
    party_cik_set = _normalize_many_ciks(party_ciks or [])
    role_set = {str(item).strip().lower() for item in (roles or []) if str(item).strip()}
    form_set = {str(item).strip().upper() for item in (form_types or []) if str(item).strip()}
    accession_set = {str(item).strip() for item in (accession_numbers or []) if str(item).strip()}

    if issuer_cik_set and "issuer_cik" in out.columns:
        out["issuer_cik"] = out["issuer_cik"].map(normalize_cik)
        out = out[out["issuer_cik"].isin(issuer_cik_set)]
    if party_cik_set and "party_cik" in out.columns:
        out["party_cik"] = out["party_cik"].map(normalize_cik)
        out = out[out["party_cik"].isin(party_cik_set)]
    if role_set and "party_role" in out.columns:
        out = out[out["party_role"].astype(str).str.strip().str.lower().isin(role_set)]
    if form_set and "form_type" in out.columns:
        out = out[out["form_type"].astype(str).str.strip().str.upper().isin(form_set)]
    if accession_set and "accession_number" in out.columns:
        out = out[out["accession_number"].astype(str).str.strip().isin(accession_set)]

    if (date_from is not None or date_to is not None) and "filing_date" in out.columns:
        filing_dates = pd.to_datetime(out["filing_date"], errors="coerce")
        if date_from is not None:
            out = out[filing_dates >= pd.to_datetime(date_from)]
            filing_dates = pd.to_datetime(out["filing_date"], errors="coerce")
        if date_to is not None:
            out = out[filing_dates <= pd.to_datetime(date_to)]

    sort_cols = [c for c in ["accession_number", "party_role", "party_cik", "party_name", "source_filename"] if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols, na_position="last")
    return out.reset_index(drop=True)


def parse_columns_option(columns_csv: str | None) -> list[str] | None:
    if columns_csv is None:
        return None
    requested = [item.strip() for item in columns_csv.split(",") if item.strip()]
    return requested or None


def apply_limit_and_columns(
    df: pd.DataFrame,
    *,
    limit: int | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    out = df.copy()
    if limit is not None:
        out = out.head(int(limit))

    if columns is not None:
        missing = [name for name in columns if name not in out.columns]
        if missing:
            raise ValueError(f"Unknown column(s): {', '.join(missing)}")
        out = out[columns]

    return out
