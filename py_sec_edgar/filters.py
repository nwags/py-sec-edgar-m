from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from py_sec_edgar.refdata.normalize import normalize_cik, normalize_ticker


FORM_FAMILY_MAP = {
    "beneficial_ownership": {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"},
    "insider_transactions": {"3", "4", "5"},
    "current_reports": {"8-K", "8-K/A", "6-K"},
    "proxy": {"DEF 14A", "DEFA14A", "PRE 14A"},
    "mna": {"S-4", "S-4/A", "F-4", "F-4/A", "425"},
    "tender_offers": {"SC TO-T", "SC TO-T/A", "SC TO-I", "SC TO-I/A", "SC 14D9", "SC 14D9/A", "SC 13E-3", "SC 13E-3/A"},
    "holdings": {"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"},
    "filing_distress": {"NT 10-K", "NT 10-Q"},
    "resales": {"144"},
}


def _normalize_cik_values(values: Iterable[object] | None) -> set[str]:
    if not values:
        return set()
    out = set()
    for value in values:
        cik = normalize_cik(value)
        if cik:
            out.add(cik)
    return out


def _normalize_ticker_values(values: Iterable[object] | None) -> set[str]:
    if not values:
        return set()
    out = set()
    for value in values:
        ticker = normalize_ticker(value)
        if ticker:
            out.add(ticker)
    return out


def _expand_forms(
    *,
    forms: Iterable[str] | None,
    form_families: Iterable[str] | None,
) -> set[str]:
    selected = set(forms or [])
    for family in (form_families or []):
        selected.update(FORM_FAMILY_MAP.get(str(family), set()))
    return {str(item).strip() for item in selected if str(item).strip()}


def load_normalized_filter_tables(normalized_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    issuers_path = normalized_root / "issuers.parquet"
    entities_path = normalized_root / "entities.parquet"
    if not issuers_path.exists() or not entities_path.exists():
        raise FileNotFoundError(
            f"Normalized filter inputs missing at {normalized_root}. "
            "Expected issuers.parquet and entities.parquet. "
            "Run `py-sec-edgar refdata refresh` for the current configured normalized root."
        )

    issuers = pd.read_parquet(issuers_path)
    entities = pd.read_parquet(entities_path)

    if "issuer_cik" in issuers.columns:
        issuers["issuer_cik"] = issuers["issuer_cik"].map(normalize_cik)
    if "ticker" in issuers.columns:
        issuers["ticker"] = issuers["ticker"].map(normalize_ticker)

    if "entity_cik" in entities.columns:
        entities["entity_cik"] = entities["entity_cik"].map(normalize_cik)

    return issuers, entities


def build_cik_filter_set(
    *,
    issuers: pd.DataFrame,
    entities: pd.DataFrame,
    issuer_tickers: Iterable[object] | None = None,
    issuer_ciks: Iterable[object] | None = None,
    entity_ciks: Iterable[object] | None = None,
) -> set[str] | None:
    had_input_values = any(
        value is not None
        for group in (issuer_tickers, issuer_ciks, entity_ciks)
        if group is not None
        for value in group
    )
    ticker_set = _normalize_ticker_values(issuer_tickers)
    issuer_cik_set = _normalize_cik_values(issuer_ciks)
    entity_cik_set = _normalize_cik_values(entity_ciks)

    any_filter = bool(ticker_set or issuer_cik_set or entity_cik_set)
    if not any_filter and not had_input_values:
        return None
    if not any_filter and had_input_values:
        # Explicit but malformed/non-normalized inputs should not fall through to
        # unfiltered selection.
        return set()

    resolved: set[str] = set()

    if ticker_set and {"ticker", "issuer_cik"}.issubset(issuers.columns):
        ticker_matches = issuers[issuers["ticker"].isin(ticker_set)]
        resolved.update(c for c in ticker_matches["issuer_cik"].dropna().tolist() if c)

    if issuer_cik_set:
        resolved.update(issuer_cik_set)

    if entity_cik_set:
        resolved.update(entity_cik_set)
        # If entities are issuers with issuer flag, include their CIKs explicitly.
        if {"entity_cik", "is_issuer"}.issubset(entities.columns):
            issuer_entity_matches = entities[
                entities["entity_cik"].isin(entity_cik_set) & entities["is_issuer"].fillna(False)
            ]
            resolved.update(c for c in issuer_entity_matches["entity_cik"].dropna().tolist() if c)

    return resolved


def apply_filing_filters(
    filings_df: pd.DataFrame,
    *,
    cik_filter_set: set[str] | None,
    forms: Iterable[str] | None = None,
    form_families: Iterable[str] | None = None,
    date_from: str | datetime | None = None,
    date_to: str | datetime | None = None,
) -> pd.DataFrame:
    df = filings_df.copy()

    if "CIK" in df.columns:
        df["CIK_CANONICAL"] = df["CIK"].map(normalize_cik)

    if cik_filter_set is not None:
        df = df[df["CIK_CANONICAL"].isin(cik_filter_set)]

    form_set = _expand_forms(forms=forms, form_families=form_families)
    if form_set and "Form Type" in df.columns:
        df = df[df["Form Type"].isin(form_set)]

    if "Date Filed" in df.columns and (date_from is not None or date_to is not None):
        filed_dates = pd.to_datetime(df["Date Filed"], errors="coerce")
        if date_from is not None:
            lower = pd.to_datetime(date_from)
            df = df[filed_dates >= lower]
            filed_dates = pd.to_datetime(df["Date Filed"], errors="coerce")
        if date_to is not None:
            upper = pd.to_datetime(date_to)
            df = df[filed_dates <= upper]

    return df
