from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urljoin

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.lookup import local_lookup_filings_path
from py_sec_edgar.refdata.normalize import normalize_cik
from py_sec_edgar.sec_surfaces import default_sec_surfaces


ACCESSION_PATTERN = re.compile(r"(\d{10}-\d{2}-\d{6})")
STRICT_ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")

LOCAL_LOOKUP_SURFACE_ID = "local_lookup_filings"
MERGED_INDEX_SURFACE_ID = "sec_archives_full_or_daily_index_merged"
ARCHIVES_CONTENT_SURFACE_ID = "sec_archives_submissions"


@dataclass(frozen=True)
class FilingRecordIdentity:
    accession_number: str
    filename: str | None
    filing_cik: str | None
    form_type: str | None
    filing_date: str | None
    metadata_source: str
    metadata_surface: str


def parse_accession_number(value: str) -> str:
    accession = str(value or "").strip()
    if not STRICT_ACCESSION_PATTERN.match(accession):
        raise ValueError("Invalid accession number format. Expected ##########-##-######.")
    return accession


def extract_accession_number(text: object) -> str | None:
    match = ACCESSION_PATTERN.search(str(text or ""))
    return match.group(1) if match else None


def normalize_filename(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.lstrip("/")


def derive_filename_from_accession_and_cik(accession_number: str, filing_cik: str) -> str:
    cik_raw = str(int(str(filing_cik))) if str(filing_cik).isdigit() else str(filing_cik).lstrip("0") or "0"
    return f"edgar/data/{cik_raw}/{accession_number}.txt"


def canonical_submission_filename(
    *,
    filename: str | None,
    accession_number: str | None,
    filing_cik: str | None,
) -> str | None:
    normalized = normalize_filename(filename)
    if normalized is None:
        return None

    lowered = normalized.lower()
    if lowered.endswith("-index.htm") or lowered.endswith("-index.html"):
        resolved_accession = accession_number or extract_accession_number(normalized)
        resolved_cik = normalize_cik(filing_cik) or extract_cik_from_filename(normalized)
        if resolved_accession and resolved_cik:
            return derive_filename_from_accession_and_cik(resolved_accession, resolved_cik)
    return normalized


def extract_cik_from_filename(filename: str | None) -> str | None:
    normalized = normalize_filename(filename)
    if normalized is None:
        return None
    match = re.search(r"edgar/data/(\d{1,10})/", normalized, re.IGNORECASE)
    if not match:
        return None
    return normalize_cik(match.group(1))


def is_canonical_submission_txt_filename(filename: str | None) -> bool:
    normalized = normalize_filename(filename)
    if normalized is None:
        return False
    lowered = normalized.lower()
    return lowered.startswith("edgar/data/") and lowered.endswith(".txt")


def sec_archives_base_url(config: AppConfig | None = None) -> str:
    del config  # reserved for future config-driven override
    for surface in default_sec_surfaces():
        if surface.surface_id == ARCHIVES_CONTENT_SURFACE_ID:
            base = str(surface.base_url).strip()
            return base if base.endswith("/") else f"{base}/"
    return "https://www.sec.gov/Archives/"


def canonical_submission_url(filename: str | None, *, config: AppConfig | None = None) -> str | None:
    normalized = normalize_filename(filename)
    if normalized is None:
        return None
    return urljoin(sec_archives_base_url(config), normalized)


def canonical_local_submission_path(config: AppConfig, filename: str | None) -> Path | None:
    normalized = normalize_filename(filename)
    if normalized is None:
        return None
    return config.download_root / Path(normalized)


def _as_clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def filing_identity_from_row(row: dict[str, object], *, metadata_source: str, metadata_surface: str) -> FilingRecordIdentity:
    accession = _as_clean_text(row.get("accession_number")) or extract_accession_number(
        row.get("filename") or row.get("Filename")
    )
    if accession is None:
        raise ValueError("Unable to derive accession_number from lookup/index row.")

    filename = canonical_submission_filename(
        filename=_as_clean_text(row.get("filename") or row.get("Filename")),
        accession_number=accession,
        filing_cik=normalize_cik(row.get("filing_cik") or row.get("CIK")),
    )

    return FilingRecordIdentity(
        accession_number=accession,
        filename=filename,
        filing_cik=normalize_cik(row.get("filing_cik") or row.get("CIK")),
        form_type=_as_clean_text(row.get("form_type") or row.get("Form Type")),
        filing_date=_as_clean_text(row.get("filing_date") or row.get("Date Filed")),
        metadata_source=metadata_source,
        metadata_surface=metadata_surface,
    )


def resolve_filing_identity(config: AppConfig, accession_number: str) -> FilingRecordIdentity | None:
    accession = parse_accession_number(accession_number)

    lookup_path = local_lookup_filings_path(config)
    if lookup_path.exists():
        lookup_df = pd.read_parquet(lookup_path)
        if "accession_number" in lookup_df.columns:
            matches = lookup_df[lookup_df["accession_number"].astype(str) == accession]
            if not matches.empty:
                prioritized = matches.sort_values(
                    ["submission_exists", "submission_path_count"],
                    ascending=[False, False],
                    na_position="last",
                ).reset_index(drop=True)
                return filing_identity_from_row(
                    prioritized.iloc[0].to_dict(),
                    metadata_source="local_lookup_filings",
                    metadata_surface=LOCAL_LOOKUP_SURFACE_ID,
                )

    merged_path = config.merged_index_path
    if not merged_path.exists():
        return None

    merged_df = pd.read_parquet(merged_path)
    for row in merged_df.to_dict(orient="records"):
        filename = _as_clean_text(row.get("Filename"))
        if not filename:
            continue
        if extract_accession_number(filename) != accession:
            continue
        return filing_identity_from_row(
            row,
            metadata_source="merged_index",
            metadata_surface=MERGED_INDEX_SURFACE_ID,
        )
    return None
