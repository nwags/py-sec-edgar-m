from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import urljoin

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.download import ProxyRequest
from py_sec_edgar.lookup import local_lookup_filings_path
from py_sec_edgar.refdata.normalize import normalize_cik
from py_sec_edgar.settings import get_config


DEFAULT_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/"
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class RetrievalDecision(str, Enum):
    LOCAL_HIT = "local_hit"
    REMOTE_FETCHED_AND_PERSISTED = "remote_fetched_and_persisted"
    NOT_FOUND = "not_found"
    REMOTE_FETCH_FAILED = "remote_fetch_failed"


@dataclass(frozen=True)
class FilingMetadata:
    accession_number: str
    filing_cik: str | None
    form_type: str | None
    filing_date: str | None
    filename: str | None
    submission_path: str | None
    metadata_source: str


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    status_code: int | None = None
    reason: str | None = None
    error: str | None = None
    error_class: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    decision: RetrievalDecision
    metadata: FilingMetadata | None = None
    local_path: Path | None = None
    remote_url: str | None = None
    status_code: int | None = None
    reason: str | None = None
    error: str | None = None
    error_class: str | None = None


class FilingFetchClient(Protocol):
    def fetch(self, url: str, destination_path: Path) -> FetchResult: ...


class ProxyRequestFetchClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def fetch(self, url: str, destination_path: Path) -> FetchResult:
        downloader = ProxyRequest(CONFIG=self._config)
        ok = downloader.GET_FILE(url, str(destination_path))
        failure = downloader.last_failure or {}
        return FetchResult(
            ok=bool(ok),
            status_code=failure.get("status_code"),
            reason=failure.get("reason"),
            error=failure.get("error"),
            error_class=failure.get("error_class"),
        )


def _normalize_accession_number(accession_number: str) -> str:
    normalized = str(accession_number or "").strip()
    if not _ACCESSION_RE.match(normalized):
        raise ValueError("Invalid accession number format. Expected ##########-##-######.")
    return normalized


def _as_clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _accession_from_filename(filename: str) -> str | None:
    match = re.search(r"(\d{10}-\d{2}-\d{6})", str(filename or ""))
    if not match:
        return None
    return match.group(1)


def _metadata_from_row(row: dict[str, object], *, metadata_source: str) -> FilingMetadata:
    accession = _as_clean_text(row.get("accession_number"))
    if accession is None:
        accession = _accession_from_filename(str(row.get("filename") or row.get("Filename") or ""))
    if accession is None:
        raise ValueError("Unable to derive accession_number from lookup/index row.")

    return FilingMetadata(
        accession_number=accession,
        filing_cik=normalize_cik(row.get("filing_cik") or row.get("CIK")),
        form_type=_as_clean_text(row.get("form_type") or row.get("Form Type")),
        filing_date=_as_clean_text(row.get("filing_date") or row.get("Date Filed")),
        filename=_as_clean_text(row.get("filename") or row.get("Filename")),
        submission_path=_as_clean_text(row.get("submission_path")),
        metadata_source=metadata_source,
    )


def derive_archives_base_url(config: AppConfig) -> str:
    candidates = [
        getattr(config, "archives_base_url", None),
        getattr(config, "edgar_Archives_url", None),
        getattr(config, "SEC_ARCHIVES_URL", None),
    ]
    try:
        legacy = get_config()
        candidates.append(getattr(legacy, "edgar_Archives_url", None))
    except Exception:
        pass

    for candidate in candidates:
        text = _as_clean_text(candidate)
        if text:
            return text if text.endswith("/") else f"{text}/"
    return DEFAULT_ARCHIVES_BASE_URL


def derive_remote_filing_url(config: AppConfig, filename: str) -> str:
    base = derive_archives_base_url(config)
    relative = str(filename or "").strip().lstrip("/")
    if not relative:
        raise ValueError("Cannot derive remote filing URL without a filename.")
    return urljoin(base, relative)


def find_filing_metadata(config: AppConfig, accession_number: str) -> FilingMetadata | None:
    accession = _normalize_accession_number(accession_number)

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
                return _metadata_from_row(prioritized.iloc[0].to_dict(), metadata_source="local_lookup_filings")

    merged_path = config.merged_index_path
    if not merged_path.exists():
        return None

    merged_df = pd.read_parquet(merged_path)
    for row in merged_df.to_dict(orient="records"):
        filename = _as_clean_text(row.get("Filename"))
        if not filename:
            continue
        if _accession_from_filename(filename) != accession:
            continue
        row = dict(row)
        row["submission_path"] = str(config.download_root / Path(filename.lstrip("/")))
        return _metadata_from_row(row, metadata_source="merged_index")
    return None


def resolve_canonical_submission_path(config: AppConfig, metadata: FilingMetadata | None) -> Path | None:
    if metadata is None:
        return None
    if metadata.filename:
        # Canonical API persistence/read path always mirrors SEC relative filename under download_root.
        return config.download_root / Path(metadata.filename.lstrip("/"))
    if metadata.submission_path:
        return Path(metadata.submission_path)
    return None


def resolve_local_submission_path(config: AppConfig, metadata: FilingMetadata | None) -> Path | None:
    path = resolve_canonical_submission_path(config, metadata)
    if path is not None and path.exists() and path.is_file():
        return path
    return None


def retrieve_filing_content_local_first(
    config: AppConfig,
    accession_number: str,
    *,
    fetch_client: FilingFetchClient | None = None,
) -> RetrievalResult:
    _normalize_accession_number(accession_number)
    metadata = find_filing_metadata(config, accession_number)
    if metadata is None:
        return RetrievalResult(decision=RetrievalDecision.NOT_FOUND)

    local_path = resolve_local_submission_path(config, metadata)
    if local_path is not None:
        return RetrievalResult(
            decision=RetrievalDecision.LOCAL_HIT,
            metadata=metadata,
            local_path=local_path,
        )

    canonical_path = resolve_canonical_submission_path(config, metadata)
    if canonical_path is None or metadata.filename is None:
        return RetrievalResult(
            decision=RetrievalDecision.REMOTE_FETCH_FAILED,
            metadata=metadata,
            local_path=canonical_path,
            reason="missing_filename",
            error="Filing metadata is missing filename required for SEC retrieval.",
        )

    remote_url = derive_remote_filing_url(config, metadata.filename)
    client = fetch_client or ProxyRequestFetchClient(config)
    fetch_result = client.fetch(remote_url, canonical_path)

    if fetch_result.ok and canonical_path.exists() and canonical_path.is_file():
        return RetrievalResult(
            decision=RetrievalDecision.REMOTE_FETCHED_AND_PERSISTED,
            metadata=metadata,
            local_path=canonical_path,
            remote_url=remote_url,
        )

    return RetrievalResult(
        decision=RetrievalDecision.REMOTE_FETCH_FAILED,
        metadata=metadata,
        local_path=canonical_path,
        remote_url=remote_url,
        status_code=fetch_result.status_code,
        reason=fetch_result.reason or "remote_fetch_failed",
        error=fetch_result.error,
        error_class=fetch_result.error_class,
    )


class FilingRetrievalService:
    def __init__(self, config: AppConfig, *, fetch_client: FilingFetchClient | None = None) -> None:
        self._config = config
        self._fetch_client = fetch_client

    def find_filing_metadata(self, accession_number: str) -> FilingMetadata | None:
        return find_filing_metadata(self._config, accession_number)

    def resolve_canonical_submission_path(self, metadata: FilingMetadata | None) -> Path | None:
        return resolve_canonical_submission_path(self._config, metadata)

    def resolve_local_submission_path(self, metadata: FilingMetadata | None) -> Path | None:
        return resolve_local_submission_path(self._config, metadata)

    def retrieve_filing_content_local_first(self, accession_number: str) -> RetrievalResult:
        return retrieve_filing_content_local_first(
            self._config,
            accession_number,
            fetch_client=self._fetch_client,
        )

