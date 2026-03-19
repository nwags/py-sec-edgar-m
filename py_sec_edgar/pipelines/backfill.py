from __future__ import annotations

from collections import Counter
from pathlib import Path
import time
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

MAX_DOWNLOAD_FAILURE_SAMPLE = 20


def _build_download_tasks(config: AppConfig, df_filings) -> list[DownloadTask]:
    tasks: list[DownloadTask] = []
    download_root = config.download_root
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
    download_root = config.download_root
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
    return config.download_root / Path(relative)


def _build_download_failure_diagnostics(download_failures: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts = Counter()
    status_counts = Counter()
    error_class_counts = Counter()

    for item in download_failures:
        reason = str(item.get("reason") or "request_exception")
        reason_counts[reason] += 1
        status_code = item.get("status_code")
        if status_code is not None:
            status_counts[str(status_code)] += 1
        error_class = item.get("error_class")
        if error_class:
            error_class_counts[str(error_class)] += 1

    sample = [
        {
            "url": item.get("url"),
            "filepath": item.get("filepath"),
            "reason": item.get("reason"),
            "status_code": item.get("status_code"),
            "error_class": item.get("error_class"),
            "error": item.get("error"),
        }
        for item in download_failures[:MAX_DOWNLOAD_FAILURE_SAMPLE]
    ]
    return {
        "download_failure_reason_counts": dict(sorted(reason_counts.items())),
        "download_failure_status_code_counts": dict(sorted(status_counts.items())),
        "download_failure_error_class_counts": dict(sorted(error_class_counts.items())),
        "download_failures_sample": sample,
    }


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


def _run_filing_party_extraction(
    config: AppConfig,
    df_filings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    candidate_count = 0
    attempted_count = 0
    zero_record_count = 0
    successful_nonzero_record_filing_count = 0
    failed_count = 0
    missing_local_count = 0

    for row in df_filings.to_dict(orient="records"):
        form_type = str(row.get("Form Type") or row.get("Form_Type") or "").strip().upper()
        if form_type not in SUPPORTED_FORMS:
            continue
        candidate_count += 1

        filename = row.get("Filename")
        filing_filepath = _local_filing_path(config, filename)
        if filing_filepath is None or not filing_filepath.exists():
            missing_local_count += 1
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
            attempted_count += 1
            extracted = extract_filing_parties_from_file(
                filing_filepath=filing_filepath,
                form_type=form_type,
                filing_date=str(row.get("Date Filed") or row.get("Date_Filed") or ""),
                source_filename=str(filename),
            )
            records.extend(extracted)
            if extracted:
                successful_nonzero_record_filing_count += 1
            else:
                zero_record_count += 1
        except Exception as exc:  # pragma: no cover - covered via monkeypatch tests
            failed_count += 1
            failures.append(
                {
                    "filename": str(filename),
                    "filing_filepath": str(filing_filepath),
                    "reason": "filing_party_extraction_exception",
                    "error": str(exc),
                }
            )

    return records, failures, {
        "filing_party_candidate_count": int(candidate_count),
        "filing_party_attempted_count": int(attempted_count),
        "filing_party_zero_record_count": int(zero_record_count),
        "filing_party_successful_nonzero_record_filing_count": int(successful_nonzero_record_filing_count),
        "filing_party_failed_count": int(failed_count),
        "filing_party_missing_local_count": int(missing_local_count),
    }


def run_backfill(
    config: AppConfig,
    *,
    refresh_index: bool = True,
    execute_downloads: bool = False,
    execute_extraction: bool = False,
    persist_filing_parties: bool = False,
    ticker_list_filter: bool = True,
    form_list_filter: bool = True,
    ticker_list_filter_explicit: bool = False,
    form_list_filter_explicit: bool = False,
    issuer_tickers: list[str] | None = None,
    issuer_ciks: list[str] | None = None,
    entity_ciks: list[str] | None = None,
    forms: list[str] | None = None,
    form_families: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Run staged backfill with optional download, extraction, and filing-party persistence."""
    started_at = time.monotonic()
    config.ensure_runtime_dirs()
    activity_events: list[dict[str, Any]] = []
    max_activity_events = 200

    if refresh_index:
        index_metrics = run_index_refresh(config, save_idx_as_csv=True, skip_if_exists=True) or {}
        for event in index_metrics.get("activity_events", []):
            activity_events.append(event)
        if len(activity_events) > max_activity_events:
            activity_events = activity_events[-max_activity_events:]

    has_explicit_entity_filters = bool(issuer_tickers or issuer_ciks or entity_ciks)
    has_explicit_form_filters = bool(forms or form_families)
    has_modern_scope = bool(
        issuer_tickers
        or issuer_ciks
        or entity_ciks
        or forms
        or form_families
        or date_from
        or date_to
    )

    if ticker_list_filter_explicit:
        effective_ticker_list_filter = bool(ticker_list_filter)
    elif has_modern_scope:
        effective_ticker_list_filter = False
    else:
        effective_ticker_list_filter = bool(ticker_list_filter)

    if form_list_filter_explicit:
        effective_form_list_filter = bool(form_list_filter)
    elif has_explicit_form_filters:
        effective_form_list_filter = False
    else:
        effective_form_list_filter = bool(form_list_filter)

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
    selection_elapsed_seconds = round(time.monotonic() - started_at, 3)

    download_results = []
    download_elapsed_seconds = 0.0
    if execute_downloads:
        stage_start = time.monotonic()
        tasks = _build_download_tasks(config, df_filings)
        download_results = run_bounded_downloads(tasks, downloader_config=config)
        download_elapsed_seconds = round(time.monotonic() - stage_start, 3)

    failed_downloads = [
        {
            "url": item.url,
            "filepath": item.filepath,
            "reason": item.reason,
            "status_code": item.status_code,
            "error_class": item.error_class,
            "error": item.error,
            "retry_exhausted": item.retry_exhausted,
        }
        for item in download_results
        if not item.success
    ]
    download_failure_diagnostics = _build_download_failure_diagnostics(failed_downloads)
    for item in failed_downloads:
        activity_events.append(
            {
                "stage": "download",
                "status": "failed",
                "url": item["url"],
                "detail": item["reason"],
            }
        )
    for item in download_results:
        if item.success:
            activity_events.append(
                {
                    "stage": "download",
                    "status": "success",
                    "url": item.url,
                }
            )
    if len(activity_events) > max_activity_events:
        activity_events = activity_events[-max_activity_events:]

    extraction_successes = []
    extraction_failures = []
    extraction_elapsed_seconds = 0.0
    filing_party_records: list[dict[str, Any]] = []
    filing_party_failures: list[dict[str, Any]] = []
    filing_party_metrics = {
        "filing_party_candidate_count": 0,
        "filing_party_attempted_count": 0,
        "filing_party_zero_record_count": 0,
        "filing_party_successful_nonzero_record_filing_count": 0,
        "filing_party_failed_count": 0,
        "filing_party_missing_local_count": 0,
    }
    filing_party_persisted_count = 0
    filing_party_persist_path: str | None = None
    if execute_extraction:
        stage_start = time.monotonic()
        extraction_successes, extraction_failures = _run_serial_extraction(config, df_filings)
        filing_party_records, filing_party_failures, filing_party_metrics = _run_filing_party_extraction(config, df_filings)
        extraction_elapsed_seconds = round(time.monotonic() - stage_start, 3)
        if persist_filing_parties:
            requested_persist_path = config.normalized_refdata_root / "filing_parties.parquet"
            filing_party_persisted_count = upsert_filing_parties_parquet(
                records=filing_party_records,
                output_path=requested_persist_path,
            )
            if requested_persist_path.exists():
                filing_party_persist_path = str(requested_persist_path)
            if filing_party_metrics["filing_party_zero_record_count"] > 0:
                activity_events.append(
                    {
                        "stage": "filing_party_extraction",
                        "status": "zero_records",
                        "detail": "persist_requested_with_zero_record_filing_results",
                    }
                )
    for item in extraction_failures:
        activity_events.append(
            {
                "stage": "extraction",
                "status": "failed",
                "filename": item.get("filename"),
                "detail": item.get("reason"),
            }
        )
    for item in extraction_successes:
        activity_events.append(
            {
                "stage": "extraction",
                "status": "success",
                "filename": item.get("filename"),
                "detail": item.get("reason"),
            }
        )
    if len(activity_events) > max_activity_events:
        activity_events = activity_events[-max_activity_events:]
    total_elapsed_seconds = round(time.monotonic() - started_at, 3)
    filing_party_attempted_invariant_ok = (
        int(filing_party_metrics["filing_party_attempted_count"])
        == int(filing_party_metrics["filing_party_zero_record_count"])
        + int(filing_party_metrics["filing_party_failed_count"])
        + int(filing_party_metrics["filing_party_successful_nonzero_record_filing_count"])
    )

    return {
        "candidate_count": int(len(df_filings.index)),
        "execute_downloads": bool(execute_downloads),
        "execute_extraction": bool(execute_extraction),
        "persist_filing_parties": bool(persist_filing_parties),
        "download_attempted_count": int(len(download_results)),
        "download_succeeded_count": int(sum(1 for item in download_results if item.success)),
        "download_failed_count": int(sum(1 for item in download_results if not item.success)),
        "download_failures": failed_downloads,
        "download_failure_reason_counts": download_failure_diagnostics["download_failure_reason_counts"],
        "download_failure_status_code_counts": download_failure_diagnostics["download_failure_status_code_counts"],
        "download_failure_error_class_counts": download_failure_diagnostics["download_failure_error_class_counts"],
        "download_failures_sample": download_failure_diagnostics["download_failures_sample"],
        "extraction_attempted_count": int(len(extraction_successes) + len(extraction_failures)),
        "extraction_succeeded_count": int(len(extraction_successes)),
        "extraction_failed_count": int(len(extraction_failures)),
        "extraction_failures": extraction_failures,
        "filing_party_candidate_count": int(filing_party_metrics["filing_party_candidate_count"]),
        "filing_party_attempted_count": int(filing_party_metrics["filing_party_attempted_count"]),
        "filing_party_zero_record_count": int(filing_party_metrics["filing_party_zero_record_count"]),
        "filing_party_successful_nonzero_record_filing_count": int(
            filing_party_metrics["filing_party_successful_nonzero_record_filing_count"]
        ),
        "filing_party_record_count": int(len(filing_party_records)),
        "filing_party_failed_count": int(filing_party_metrics["filing_party_failed_count"]),
        "filing_party_missing_local_count": int(filing_party_metrics["filing_party_missing_local_count"]),
        "filing_party_attempted_invariant_ok": bool(filing_party_attempted_invariant_ok),
        "filing_party_failures": filing_party_failures,
        "filing_parties": filing_party_records,
        "filing_party_persisted_count": int(filing_party_persisted_count),
        "filing_party_persist_path": filing_party_persist_path,
        "refresh_index": bool(refresh_index),
        "ticker_list_filter_requested": bool(ticker_list_filter),
        "ticker_list_filter_explicit": bool(ticker_list_filter_explicit),
        "ticker_list_filter_applied": effective_ticker_list_filter,
        "form_list_filter_requested": bool(form_list_filter),
        "form_list_filter_explicit": bool(form_list_filter_explicit),
        "form_list_filter_applied": effective_form_list_filter,
        "issuer_tickers": list(issuer_tickers or []),
        "issuer_ciks": list(issuer_ciks or []),
        "entity_ciks": list(entity_ciks or []),
        "forms": list(forms or []),
        "form_families": list(form_families or []),
        "date_from": date_from,
        "date_to": date_to,
        "selection_elapsed_seconds": float(selection_elapsed_seconds),
        "download_elapsed_seconds": float(download_elapsed_seconds),
        "extraction_elapsed_seconds": float(extraction_elapsed_seconds),
        "total_elapsed_seconds": float(total_elapsed_seconds),
        "activity_events": activity_events,
    }
