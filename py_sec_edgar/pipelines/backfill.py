from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from py_sec_edgar.config import AppConfig
from py_sec_edgar.downloader import DownloadTask, run_bounded_downloads
from py_sec_edgar.filing import complete_submission_filing
from py_sec_edgar.filing_parties import (
    SUPPORTED_FORMS,
    extract_filing_parties_from_file,
    upsert_filing_parties_parquet,
)
import py_sec_edgar.feeds as feeds
from py_sec_edgar.pipelines.index_refresh import run_index_refresh


def _build_download_tasks(config: AppConfig, df_filings) -> list[DownloadTask]:
    tasks: list[DownloadTask] = []
    download_root = config.project_root / ".sec_cache" / "Archives"
    for row in df_filings.itertuples(index=False):
        filename = getattr(row, "Filename", None)
        if not filename:
            continue
        relative = str(filename).lstrip("/")
        url = getattr(row, "url", None) or urljoin("https://www.sec.gov/Archives/", relative)
        local_path = download_root / Path(relative)
        tasks.append(DownloadTask(url=url, filepath=str(local_path)))
    return tasks


def _build_extraction_targets(config: AppConfig, df_filings) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    download_root = config.project_root / ".sec_cache" / "Archives"
    for row in df_filings.itertuples(index=False):
        filename = getattr(row, "Filename", None)
        if not filename:
            continue
        relative = str(filename).lstrip("/")
        local_path = download_root / Path(relative)
        filing_folder = local_path.stem.replace("-", "")
        extracted_dir = local_path.parent / filing_folder
        targets.append(
            {
                "filename": str(filename),
                "filing_filepath": str(local_path),
                "extracted_filing_directory": str(extracted_dir),
            }
        )
    return targets


def _local_filing_path(config: AppConfig, filename: str | None) -> Path | None:
    if not filename:
        return None
    relative = str(filename).lstrip("/")
    return config.project_root / ".sec_cache" / "Archives" / Path(relative)


def _run_serial_extraction(config: AppConfig, df_filings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for target in _build_extraction_targets(config, df_filings):
        filing_filepath = Path(target["filing_filepath"])
        extracted_dir = Path(target["extracted_filing_directory"])
        if not filing_filepath.exists():
            failures.append(
                {
                    "filename": target["filename"],
                    "filing_filepath": str(filing_filepath),
                    "reason": "missing_local_filing",
                    "error": None,
                }
            )
            continue

        if extracted_dir.exists():
            successes.append(
                {
                    "filename": target["filename"],
                    "filing_filepath": str(filing_filepath),
                    "extracted_filing_directory": str(extracted_dir),
                    "reason": "already_extracted",
                }
            )
            continue

        try:
            complete_submission_filing(
                str(filing_filepath),
                output_directory=str(extracted_dir),
            )
            successes.append(
                {
                    "filename": target["filename"],
                    "filing_filepath": str(filing_filepath),
                    "extracted_filing_directory": str(extracted_dir),
                    "reason": "extracted",
                }
            )
        except Exception as exc:  # pragma: no cover - guarded with tests via monkeypatch
            failures.append(
                {
                    "filename": target["filename"],
                    "filing_filepath": str(filing_filepath),
                    "reason": "extraction_exception",
                    "error": str(exc),
                }
            )

    return successes, failures


def _run_filing_party_extraction(config: AppConfig, df_filings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for row in df_filings.to_dict(orient="records"):
        form_type = str(row.get("Form Type") or row.get("Form_Type") or "").strip().upper()
        if form_type not in SUPPORTED_FORMS:
            continue

        filename = row.get("Filename")
        filing_filepath = _local_filing_path(config, filename)
        if filing_filepath is None or not filing_filepath.exists():
            failures.append(
                {
                    "filename": str(filename) if filename else None,
                    "filing_filepath": str(filing_filepath) if filing_filepath else None,
                    "reason": "missing_local_filing",
                    "error": None,
                }
            )
            continue

        try:
            extracted = extract_filing_parties_from_file(
                filing_filepath=filing_filepath,
                form_type=form_type,
                filing_date=str(row.get("Date Filed") or row.get("Date_Filed") or ""),
                source_filename=str(filename),
            )
            records.extend(extracted)
        except Exception as exc:  # pragma: no cover - covered via monkeypatch tests
            failures.append(
                {
                    "filename": str(filename),
                    "filing_filepath": str(filing_filepath),
                    "reason": "filing_party_extraction_exception",
                    "error": str(exc),
                }
            )

    return records, failures


def run_backfill(
    config: AppConfig,
    *,
    refresh_index: bool = True,
    execute_downloads: bool = False,
    execute_extraction: bool = False,
    persist_filing_parties: bool = False,
    ticker_list_filter: bool = True,
    form_list_filter: bool = True,
    issuer_tickers: list[str] | None = None,
    issuer_ciks: list[str] | None = None,
    entity_ciks: list[str] | None = None,
    forms: list[str] | None = None,
    form_families: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Run staged backfill with optional download, extraction, and filing-party persistence."""
    config.ensure_runtime_dirs()

    if refresh_index:
        run_index_refresh(config, save_idx_as_csv=True, skip_if_exists=True)

    has_explicit_entity_filters = bool(issuer_tickers or issuer_ciks or entity_ciks)
    has_explicit_form_filters = bool(forms or form_families)

    effective_ticker_list_filter = bool(ticker_list_filter and not has_explicit_entity_filters)
    effective_form_list_filter = bool(form_list_filter and not has_explicit_form_filters)

    df_filings = feeds.load_filings_feed(
        ticker_list_filter=effective_ticker_list_filter,
        form_list_filter=effective_form_list_filter,
        issuer_tickers=issuer_tickers,
        issuer_ciks=issuer_ciks,
        entity_ciks=entity_ciks,
        forms=forms,
        form_families=form_families,
        date_from=date_from,
        date_to=date_to,
    )

    download_results = []
    if execute_downloads:
        tasks = _build_download_tasks(config, df_filings)
        download_results = run_bounded_downloads(tasks, downloader_config=config)

    failed_downloads = [
        {
            "url": item.url,
            "filepath": item.filepath,
            "reason": item.reason,
            "status_code": item.status_code,
            "error": item.error,
        }
        for item in download_results
        if not item.success
    ]

    extraction_successes = []
    extraction_failures = []
    filing_party_records: list[dict[str, Any]] = []
    filing_party_failures: list[dict[str, Any]] = []
    filing_party_persisted_count = 0
    filing_party_persist_path: str | None = None
    if execute_extraction:
        extraction_successes, extraction_failures = _run_serial_extraction(config, df_filings)
        filing_party_records, filing_party_failures = _run_filing_party_extraction(config, df_filings)
        if persist_filing_parties:
            requested_persist_path = config.normalized_refdata_root / "filing_parties.parquet"
            filing_party_persisted_count = upsert_filing_parties_parquet(
                records=filing_party_records,
                output_path=requested_persist_path,
            )
            if requested_persist_path.exists():
                filing_party_persist_path = str(requested_persist_path)

    return {
        "candidate_count": int(len(df_filings.index)),
        "execute_downloads": bool(execute_downloads),
        "execute_extraction": bool(execute_extraction),
        "persist_filing_parties": bool(persist_filing_parties),
        "download_attempted_count": int(len(download_results)),
        "download_succeeded_count": int(sum(1 for item in download_results if item.success)),
        "download_failed_count": int(sum(1 for item in download_results if not item.success)),
        "download_failures": failed_downloads,
        "extraction_attempted_count": int(len(extraction_successes) + len(extraction_failures)),
        "extraction_succeeded_count": int(len(extraction_successes)),
        "extraction_failed_count": int(len(extraction_failures)),
        "extraction_failures": extraction_failures,
        "filing_party_attempted_count": int(len(filing_party_records) + len(filing_party_failures)),
        "filing_party_record_count": int(len(filing_party_records)),
        "filing_party_failed_count": int(len(filing_party_failures)),
        "filing_party_failures": filing_party_failures,
        "filing_parties": filing_party_records,
        "filing_party_persisted_count": int(filing_party_persisted_count),
        "filing_party_persist_path": filing_party_persist_path,
        "refresh_index": bool(refresh_index),
        "ticker_list_filter_requested": bool(ticker_list_filter),
        "ticker_list_filter_applied": effective_ticker_list_filter,
        "form_list_filter_requested": bool(form_list_filter),
        "form_list_filter_applied": effective_form_list_filter,
        "issuer_tickers": list(issuer_tickers or []),
        "issuer_ciks": list(issuer_ciks or []),
        "entity_ciks": list(entity_ciks or []),
        "forms": list(forms or []),
        "form_families": list(form_families or []),
        "date_from": date_from,
        "date_to": date_to,
    }
