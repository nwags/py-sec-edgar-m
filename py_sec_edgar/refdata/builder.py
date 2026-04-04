from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from py_sec_edgar.refdata.schema import (
    ENTITIES_COLUMNS,
    ENTITY_ALIASES_COLUMNS,
    ISSUERS_COLUMNS,
    REFERENCE_FILE_MANIFEST_COLUMNS,
    SEC_SOURCE_SURFACES_COLUMNS,
    SERIES_CLASSES_COLUMNS,
)
from py_sec_edgar.refdata.sources import LoadedSources, source_url_for_filename
from py_sec_edgar.sec_surfaces import sec_surfaces_dataframe

REFDATA_SCHEMA_VERSION = "refdata_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = None
    return out[columns]


def _preferred_name(*candidates: object) -> str | None:
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value
    return None


def build_issuers(sources: LoadedSources, source_updated_at: str) -> pd.DataFrame:
    combined = pd.concat(
        [sources.company_tickers, sources.company_tickers_exchange],
        ignore_index=True,
        sort=False,
    )
    combined = combined.dropna(subset=["issuer_cik"])
    combined["source_updated_at"] = source_updated_at
    combined = combined.sort_values(["issuer_cik", "ticker", "source"]).drop_duplicates(
        subset=["issuer_cik", "ticker"], keep="first"
    )
    return _ensure_columns(combined, ISSUERS_COLUMNS)


def build_series_classes(sources: LoadedSources) -> pd.DataFrame:
    mf = sources.company_tickers_mf.rename(
        columns={
            "fund_cik": "fund_cik",
            "fund_cik_raw": "fund_cik_raw",
            "class_ticker": "class_ticker",
            "class_ticker_raw": "class_ticker_raw",
        }
    ).copy()
    mf["series_name"] = None
    mf["class_name"] = None

    investment = sources.investment_company_series_class.copy()

    combined = pd.concat([mf, investment], ignore_index=True, sort=False)
    combined = combined.dropna(subset=["fund_cik", "series_id", "class_id"], how="any")
    combined = combined.sort_values(["fund_cik", "series_id", "class_id", "source"]).drop_duplicates(
        subset=["fund_cik", "series_id", "class_id"], keep="first"
    )
    return _ensure_columns(combined, SERIES_CLASSES_COLUMNS)


def build_entities(
    sources: LoadedSources,
    issuers: pd.DataFrame,
    series_classes: pd.DataFrame,
    source_updated_at: str,
) -> pd.DataFrame:
    rows = []
    fund_names = (
        sources.investment_company_series_class.dropna(subset=["fund_cik"])
        .assign(entity_name=lambda df: df["entity_name"].fillna("").map(lambda v: str(v).strip()))
    )
    fund_names = fund_names[fund_names["entity_name"] != ""]
    fund_name_by_cik = (
        fund_names.sort_values(["fund_cik", "source"])
        .drop_duplicates(subset=["fund_cik"], keep="first")
        .set_index("fund_cik")["entity_name"]
        .to_dict()
    )

    for _, row in issuers.iterrows():
        rows.append(
            {
                "entity_cik": row["issuer_cik"],
                "entity_cik_raw": row["issuer_cik_raw"],
                "entity_name": row["issuer_name"],
                "entity_type": "issuer",
                "has_ticker": pd.notna(row["ticker"]),
                "ticker": row["ticker"],
                "ticker_raw": row["ticker_raw"],
                "is_individual": False,
                "is_fund": bool(row.get("is_mutual_fund", False)),
                "is_manager": False,
                "is_issuer": True,
                "source": row["source"],
            }
        )

    for _, row in sources.ticker_txt.iterrows():
        rows.append(
            {
                "entity_cik": row["entity_cik"],
                "entity_cik_raw": row["entity_cik_raw"],
                "entity_name": row.get("entity_name"),
                "entity_type": "ticker_lookup",
                "has_ticker": pd.notna(row.get("ticker")),
                "ticker": row.get("ticker"),
                "ticker_raw": row.get("ticker_raw"),
                "is_individual": False,
                "is_fund": False,
                "is_manager": False,
                "is_issuer": False,
                "source": row["source"],
            }
        )

    lookup = sources.cik_lookup.copy()
    for _, row in lookup.iterrows():
        rows.append(
            {
                "entity_cik": row["entity_cik"],
                "entity_cik_raw": row["entity_cik_raw"],
                "entity_name": row.get("entity_name"),
                "entity_type": "cik_lookup",
                "has_ticker": False,
                "ticker": None,
                "ticker_raw": None,
                "is_individual": False,
                "is_fund": False,
                "is_manager": False,
                "is_issuer": False,
                "source": row["source"],
            }
        )

    for _, row in series_classes.iterrows():
        rows.append(
            {
                "entity_cik": row["fund_cik"],
                "entity_cik_raw": row["fund_cik_raw"],
                "entity_name": _preferred_name(
                    fund_name_by_cik.get(row["fund_cik"]),
                    row.get("series_name"),
                    row.get("class_name"),
                ),
                "entity_type": "fund",
                "has_ticker": pd.notna(row.get("class_ticker")),
                "ticker": row.get("class_ticker"),
                "ticker_raw": row.get("class_ticker_raw"),
                "is_individual": False,
                "is_fund": True,
                "is_manager": False,
                "is_issuer": False,
                "source": row["source"],
            }
        )

    entities = pd.DataFrame(rows).dropna(subset=["entity_cik"])
    entities["source_updated_at"] = source_updated_at
    entities = entities.sort_values(["entity_cik", "source", "entity_type"]).drop_duplicates(
        subset=["entity_cik", "entity_type", "source", "ticker"], keep="first"
    )
    return _ensure_columns(entities, ENTITIES_COLUMNS)


def build_entity_aliases(sources: LoadedSources) -> pd.DataFrame:
    aliases = []

    for _, row in sources.cik_lookup.dropna(subset=["entity_cik", "entity_name"]).iterrows():
        aliases.append(
            {
                "entity_cik": row["entity_cik"],
                "alias_name": row["entity_name"],
                "alias_type": "cik_lookup_name",
                "normalized_alias": str(row["entity_name"]).strip().upper(),
                "source": row["source"],
            }
        )

    for _, row in sources.company_tickers.dropna(subset=["issuer_cik", "issuer_name"]).iterrows():
        aliases.append(
            {
                "entity_cik": row["issuer_cik"],
                "alias_name": row["issuer_name"],
                "alias_type": "issuer_name",
                "normalized_alias": str(row["issuer_name"]).strip().upper(),
                "source": row["source"],
            }
        )

    df = pd.DataFrame(aliases)
    if df.empty:
        return _ensure_columns(df, ENTITY_ALIASES_COLUMNS)
    df = df.sort_values(["entity_cik", "alias_type", "source"]).drop_duplicates(
        subset=["entity_cik", "normalized_alias", "alias_type"], keep="first"
    )
    return _ensure_columns(df, ENTITY_ALIASES_COLUMNS)


def build_reference_file_manifest(source_paths: Dict[str, Path], ingested_at_utc: str) -> pd.DataFrame:
    rows = []
    for source_type, path in sorted(source_paths.items()):
        content = path.read_bytes()
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rows.append(
            {
                "filename": path.name,
                "source_url": source_url_for_filename(path.name),
                "sha256": hashlib.sha256(content).hexdigest(),
                "file_size_bytes": stat.st_size,
                "mtime_utc": mtime,
                "ingested_at_utc": ingested_at_utc,
                "source_type": source_type,
                "schema_version": REFDATA_SCHEMA_VERSION,
            }
        )
    manifest = pd.DataFrame(rows)
    return _ensure_columns(manifest, REFERENCE_FILE_MANIFEST_COLUMNS)


def build_sec_source_surfaces() -> pd.DataFrame:
    return _ensure_columns(sec_surfaces_dataframe(), SEC_SOURCE_SURFACES_COLUMNS)


def build_all_tables(sources: LoadedSources) -> Dict[str, pd.DataFrame]:
    source_updated_at = _utc_now()
    issuers = build_issuers(sources, source_updated_at=source_updated_at)
    series_classes = build_series_classes(sources)
    entities = build_entities(
        sources,
        issuers=issuers,
        series_classes=series_classes,
        source_updated_at=source_updated_at,
    )
    entity_aliases = build_entity_aliases(sources)
    manifest = build_reference_file_manifest(
        sources.source_paths,
        ingested_at_utc=source_updated_at,
    )
    sec_source_surfaces = build_sec_source_surfaces()

    return {
        "issuers": issuers,
        "entities": entities,
        "entity_aliases": entity_aliases,
        "series_classes": series_classes,
        "reference_file_manifest": manifest,
        "sec_source_surfaces": sec_source_surfaces,
    }


def write_tables_to_parquet(tables: Dict[str, pd.DataFrame], output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for name, table in tables.items():
        out_path = output_dir / f"{name}.parquet"
        table.to_parquet(out_path, index=False)
        written[name] = out_path
    return written
