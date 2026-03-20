from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from typing import Protocol
from urllib.parse import urljoin

import feedparser
import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.download import ProxyRequest
from py_sec_edgar.filing import complete_submission_filing
from py_sec_edgar.filing_parties import (
    SUPPORTED_FORMS,
    extract_filing_parties_from_file,
    upsert_filing_parties_parquet,
)
from py_sec_edgar.filters import FORM_FAMILY_MAP
from py_sec_edgar.lookup import refresh_local_lookup_indexes
from py_sec_edgar.lookup import register_local_filings_in_lookup
from py_sec_edgar.refdata.normalize import normalize_cik


DEFAULT_MONITOR_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&count=100&output=atom"
)
_DEFAULT_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/"
_MAX_EVENTS_ROWS = 10000
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")
_CIK_RE = re.compile(r"(?:CIK=|CIK:|CIK\\s)(\d{1,10})", re.IGNORECASE)


@dataclass(frozen=True)
class MonitorCandidate:
    accession_number: str
    filing_date: str | None
    form_type: str | None
    filing_cik: str | None
    filename: str | None
    url: str | None
    source_id: str | None


@dataclass(frozen=True)
class NormalizationSkip:
    reason: str
    detail: str | None
    source_id: str | None
    accession_number: str | None = None
    filing_cik: str | None = None
    url: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class FeedNormalizationResult:
    candidates: list[MonitorCandidate]
    rejected: list[NormalizationSkip]


@dataclass(frozen=True)
class WarmFetchResult:
    ok: bool
    status_code: int | None = None
    reason: str | None = None
    error: str | None = None
    error_class: str | None = None


class FeedClient(Protocol):
    def fetch_candidates(self, config: AppConfig) -> FeedNormalizationResult | list[MonitorCandidate]: ...


class WarmFetcher(Protocol):
    def fetch(self, config: AppConfig, url: str, destination_path: Path) -> WarmFetchResult: ...


class SecCurrentAtomFeedClient:
    def __init__(self, feed_url: str = DEFAULT_MONITOR_FEED_URL) -> None:
        self.feed_url = feed_url

    def fetch_candidates(self, config: AppConfig) -> FeedNormalizationResult:
        downloader = ProxyRequest(CONFIG=config)
        response = downloader.GET_RESPONSE(self.feed_url)
        if response is None:
            return FeedNormalizationResult(candidates=[], rejected=[])
        return parse_atom_feed_candidates_detailed(response.text, source_id=self.feed_url)


class ProxyRequestWarmFetcher:
    def fetch(self, config: AppConfig, url: str, destination_path: Path) -> WarmFetchResult:
        downloader = ProxyRequest(CONFIG=config)
        ok = downloader.GET_FILE(url, str(destination_path))
        failure = downloader.last_failure or {}
        return WarmFetchResult(
            ok=bool(ok),
            status_code=failure.get("status_code"),
            reason=failure.get("reason"),
            error=failure.get("error"),
            error_class=failure.get("error_class"),
        )


def monitor_seen_accessions_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "monitor_seen_accessions.parquet"


def monitor_events_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "monitor_events.parquet"


def parse_atom_feed_candidates(feed_text: str, *, source_id: str) -> list[MonitorCandidate]:
    return parse_atom_feed_candidates_detailed(feed_text, source_id=source_id).candidates


def parse_atom_feed_candidates_detailed(feed_text: str, *, source_id: str) -> FeedNormalizationResult:
    parsed = feedparser.parse(feed_text)
    out: list[MonitorCandidate] = []
    rejected: list[NormalizationSkip] = []
    for entry in parsed.entries:
        link = _non_empty(entry.get("link"))
        title = _non_empty(entry.get("title")) or ""
        summary = _non_empty(entry.get("summary")) or ""
        combined = " ".join([title, summary, link or ""])

        accession_number = _extract_accession(combined)
        filing_cik = normalize_cik(_extract_cik(combined))
        form_type = _extract_form_type(title, summary)
        filing_date = _normalize_date_string(
            _non_empty(entry.get("updated")) or _non_empty(entry.get("published"))
        )
        filename = _filename_from_link(link) or _filename_from_text(combined)
        if accession_number is None and filename:
            accession_number = _extract_accession(filename)

        if filing_cik is None and filename:
            filing_cik = _extract_cik_from_filename(filename)

        if filename is None and accession_number and filing_cik:
            filename = _derive_filename_from_accession_and_cik(accession_number, filing_cik)

        if accession_number is None:
            rejected.append(
                NormalizationSkip(
                    reason="missing_accession",
                    detail="Unable to derive accession number from feed entry.",
                    source_id=source_id,
                    accession_number=None,
                    filing_cik=filing_cik,
                    url=link,
                    filename=filename,
                )
            )
            continue

        if filename is None:
            rejected.append(
                NormalizationSkip(
                    reason="missing_filename",
                    detail="Unable to derive canonical SEC filename for accession.",
                    source_id=source_id,
                    accession_number=accession_number,
                    filing_cik=filing_cik,
                    url=link,
                    filename=None,
                )
            )
            continue

        normalized_filename = _canonical_submission_filename(
            filename=filename,
            accession_number=accession_number,
            filing_cik=filing_cik,
        )
        if normalized_filename is None:
            rejected.append(
                NormalizationSkip(
                    reason="missing_filename",
                    detail="Unable to derive canonical SEC filename for accession.",
                    source_id=source_id,
                    accession_number=accession_number,
                    filing_cik=filing_cik,
                    url=link,
                    filename=None,
                )
            )
            continue

        canonical_url = urljoin(_DEFAULT_ARCHIVES_BASE_URL, normalized_filename)
        out.append(
            MonitorCandidate(
                accession_number=accession_number,
                filing_date=filing_date,
                form_type=form_type,
                filing_cik=filing_cik,
                filename=normalized_filename,
                url=canonical_url,
                source_id=source_id,
            )
        )
    return FeedNormalizationResult(candidates=out, rejected=rejected)


def run_monitor_poll(
    config: AppConfig,
    *,
    feed_client: FeedClient | None = None,
    warm_fetcher: WarmFetcher | None = None,
    warm: bool = True,
    form_types: list[str] | None = None,
    form_families: list[str] | None = None,
    issuer_ciks: list[str] | None = None,
    entity_ciks: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    execute_extraction: bool = False,
    persist_filing_parties: bool = False,
    refresh_lookup: bool = True,
) -> dict[str, object]:
    started_at = time.monotonic()
    now = _now_utc_iso()
    config.ensure_runtime_dirs()

    seen_path = monitor_seen_accessions_path(config)
    events_out_path = monitor_events_path(config)
    seen_df = _load_seen_df(seen_path)
    seen_map = {str(row["accession_number"]): row for row in seen_df.to_dict(orient="records")}

    source = feed_client or SecCurrentAtomFeedClient(feed_url=monitor_feed_url(config))
    fetcher = warm_fetcher or ProxyRequestWarmFetcher()

    fetched = source.fetch_candidates(config)
    if isinstance(fetched, FeedNormalizationResult):
        detected = fetched.candidates
        rejected = fetched.rejected
    else:
        detected = list(fetched)
        rejected = []

    events: list[dict[str, object]] = []
    for rejected_item in rejected:
        events.append(
            {
                "event_time": now,
                "accession_number": rejected_item.accession_number,
                "action": "normalization_skipped",
                "reason": rejected_item.reason,
                "status_code": None,
                "url": rejected_item.url,
                "filepath": (
                    str(_canonical_local_submission_path(config, rejected_item.filename))
                    if rejected_item.filename
                    else None
                ),
                "source_id": rejected_item.source_id,
                "error": rejected_item.detail,
                "error_class": None,
            }
        )

    filtered = _filter_candidates(
        detected,
        form_types=form_types,
        form_families=form_families,
        issuer_ciks=issuer_ciks,
        entity_ciks=entity_ciks,
        date_from=date_from,
        date_to=date_to,
    )

    seen_updates: dict[str, dict[str, object]] = {}
    warmed_success_candidates: list[MonitorCandidate] = []

    warm_attempted_count = 0
    warm_succeeded_count = 0
    warm_failed_count = 0
    skipped_already_local_count = 0
    seen_duplicate_count = 0
    local_visibility_changed = False

    for candidate in filtered:
        accession = candidate.accession_number
        canonical_path = _canonical_local_submission_path(config, candidate.filename)
        local_exists_before = bool(canonical_path is not None and canonical_path.exists())
        is_seen = accession in seen_map

        event_base = {
            "event_time": now,
            "accession_number": accession,
            "url": candidate.url,
            "filepath": str(canonical_path) if canonical_path is not None else None,
            "source_id": candidate.source_id,
            "status_code": None,
            "error": None,
            "error_class": None,
        }

        if local_exists_before:
            skipped_already_local_count += 1
            events.append(
                {
                    **event_base,
                    "action": "skipped_already_local",
                    "reason": "already_local",
                }
            )
            seen_updates[accession] = _build_seen_row(
                previous=seen_map.get(accession),
                candidate=candidate,
                first_seen_at=now,
                last_seen_at=now,
                local_submission_present=True,
                warmed_by_monitor=bool(seen_map.get(accession, {}).get("warmed_by_monitor", False)),
            )
            continue

        if is_seen:
            seen_duplicate_count += 1

        if not warm:
            events.append(
                {
                    **event_base,
                    "action": "seen",
                    "reason": "warm_disabled",
                }
            )
            seen_updates[accession] = _build_seen_row(
                previous=seen_map.get(accession),
                candidate=candidate,
                first_seen_at=now,
                last_seen_at=now,
                local_submission_present=False,
                warmed_by_monitor=False,
            )
            continue

        warm_attempted_count += 1
        events.append(
            {
                **event_base,
                "action": "warm_attempted",
                "reason": "seen_missing_local" if is_seen else "new_candidate",
            }
        )
        if canonical_path is None or not candidate.url:
            warm_failed_count += 1
            events.append(
                {
                    **event_base,
                    "action": "warm_failed",
                    "reason": "missing_url_or_filename",
                }
            )
            seen_updates[accession] = _build_seen_row(
                previous=seen_map.get(accession),
                candidate=candidate,
                first_seen_at=now,
                last_seen_at=now,
                local_submission_present=False,
                warmed_by_monitor=bool(seen_map.get(accession, {}).get("warmed_by_monitor", False)),
            )
            continue

        fetch_result = fetcher.fetch(config, candidate.url, canonical_path)
        local_exists_after = bool(canonical_path.exists())
        if fetch_result.ok and local_exists_after:
            warm_succeeded_count += 1
            local_visibility_changed = True
            warmed_success_candidates.append(candidate)
            events.append(
                {
                    **event_base,
                    "action": "warm_succeeded",
                    "reason": "downloaded",
                }
            )
            seen_updates[accession] = _build_seen_row(
                previous=seen_map.get(accession),
                candidate=candidate,
                first_seen_at=now,
                last_seen_at=now,
                local_submission_present=True,
                warmed_by_monitor=True,
            )
        else:
            warm_failed_count += 1
            events.append(
                {
                    **event_base,
                    "action": "warm_failed",
                    "reason": fetch_result.reason or "warm_failed",
                    "status_code": fetch_result.status_code,
                    "error": fetch_result.error,
                    "error_class": fetch_result.error_class,
                }
            )
            seen_updates[accession] = _build_seen_row(
                previous=seen_map.get(accession),
                candidate=candidate,
                first_seen_at=now,
                last_seen_at=now,
                local_submission_present=False,
                warmed_by_monitor=bool(seen_map.get(accession, {}).get("warmed_by_monitor", False)),
            )

    extraction_attempted_count = 0
    extraction_succeeded_count = 0
    extraction_failed_count = 0
    filing_party_record_count = 0
    filing_party_persisted_count = 0
    filing_party_persist_path: str | None = None

    if execute_extraction and warmed_success_candidates:
        extraction_attempted_count, extraction_succeeded_count, extraction_failed_count = _run_optional_extraction(
            config,
            warmed_success_candidates,
        )
        if extraction_succeeded_count > 0:
            local_visibility_changed = True

    if persist_filing_parties and warmed_success_candidates:
        filing_party_record_count, filing_party_persisted_count = _run_optional_filing_party_persist(
            config,
            warmed_success_candidates,
        )
        if filing_party_persisted_count > 0:
            filing_party_persist_path = str(config.normalized_refdata_root / "filing_parties.parquet")
            local_visibility_changed = True

    lookup_refresh_attempted = bool(refresh_lookup)
    lookup_refresh_performed = False
    lookup_refresh_skipped_reason: str | None = None
    lookup_refresh_result: dict[str, object] | None = None
    lookup_update_mode = "skipped"
    lookup_incremental_result: dict[str, object] | None = None
    lookup_full_refresh_fallback_performed = False
    lookup_full_refresh_fallback_skipped_reason: str | None = None

    if not refresh_lookup:
        lookup_refresh_skipped_reason = "refresh_lookup_disabled"
        lookup_update_mode = "skipped"
        lookup_full_refresh_fallback_skipped_reason = "fallback_not_allowed_refresh_disabled"
        events.append(
            {
                "event_time": now,
                "accession_number": None,
                "action": "lookup_incremental_skipped",
                "reason": "refresh_lookup_disabled",
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "monitor",
                "error": None,
                "error_class": None,
            }
        )
        events.append(
            {
                "event_time": now,
                "accession_number": None,
                "action": "lookup_full_refresh_fallback_skipped",
                "reason": lookup_full_refresh_fallback_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "monitor",
                "error": None,
                "error_class": None,
            }
        )
        events.append(
            {
                "event_time": now,
                "accession_number": None,
                "action": "lookup_refresh_skipped",
                "reason": lookup_refresh_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "monitor",
                "error": None,
                "error_class": None,
            }
        )
    elif not local_visibility_changed:
        lookup_refresh_skipped_reason = "no_local_visibility_change"
        lookup_update_mode = "skipped"
        lookup_full_refresh_fallback_skipped_reason = "no_local_visibility_change"
        events.append(
            {
                "event_time": now,
                "accession_number": None,
                "action": "lookup_incremental_skipped",
                "reason": "no_local_visibility_change",
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "monitor",
                "error": None,
                "error_class": None,
            }
        )
        events.append(
            {
                "event_time": now,
                "accession_number": None,
                "action": "lookup_full_refresh_fallback_skipped",
                "reason": lookup_full_refresh_fallback_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "monitor",
                "error": None,
                "error_class": None,
            }
        )
        events.append(
            {
                "event_time": now,
                "accession_number": None,
                "action": "lookup_refresh_skipped",
                "reason": lookup_refresh_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "monitor",
                "error": None,
                "error_class": None,
            }
        )
    else:
        warmed_filenames = [str(c.filename) for c in warmed_success_candidates if c.filename]
        warmed_accessions = [str(c.accession_number) for c in warmed_success_candidates if c.accession_number]
        lookup_incremental_result = register_local_filings_in_lookup(
            config,
            warmed_filenames=warmed_filenames,
            warmed_accession_numbers=warmed_accessions,
        )
        lookup_refresh_result = lookup_incremental_result
        if bool(lookup_incremental_result.get("safe_to_use")):
            lookup_refresh_performed = True
            lookup_update_mode = "incremental"
            lookup_full_refresh_fallback_skipped_reason = "incremental_safe_to_use"
            events.append(
                {
                    "event_time": now,
                    "accession_number": None,
                    "action": "lookup_incremental_performed",
                    "reason": "safe_to_use",
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "monitor",
                    "error": None,
                    "error_class": None,
                }
            )
            events.append(
                {
                    "event_time": now,
                    "accession_number": None,
                    "action": "lookup_full_refresh_fallback_skipped",
                    "reason": lookup_full_refresh_fallback_skipped_reason,
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "monitor",
                    "error": None,
                    "error_class": None,
                }
            )
        else:
            events.append(
                {
                    "event_time": now,
                    "accession_number": None,
                    "action": "lookup_incremental_skipped",
                    "reason": "unsafe_or_incomplete",
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "monitor",
                    "error": None,
                    "error_class": None,
                }
            )
            lookup_refresh_result = refresh_local_lookup_indexes(config)
            lookup_refresh_performed = True
            lookup_update_mode = "full_refresh_fallback"
            lookup_full_refresh_fallback_performed = True
            events.append(
                {
                    "event_time": now,
                    "accession_number": None,
                    "action": "lookup_full_refresh_fallback_performed",
                    "reason": "incremental_unsafe_or_incomplete",
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "monitor",
                    "error": None,
                    "error_class": None,
                }
            )

    merged_seen_df = _merge_seen_updates(seen_df, seen_updates.values())
    merged_seen_df.to_parquet(seen_path, index=False)

    persisted_events = _append_events(events_out_path, events)

    return {
        "detected_candidate_count": int(len(detected)),
        "normalization_skipped_count": int(len(rejected)),
        "filtered_candidate_count": int(len(filtered)),
        "seen_duplicate_count": int(seen_duplicate_count),
        "warm_enabled": bool(warm),
        "warm_attempted_count": int(warm_attempted_count),
        "warm_succeeded_count": int(warm_succeeded_count),
        "warm_failed_count": int(warm_failed_count),
        "skipped_already_local_count": int(skipped_already_local_count),
        "execute_extraction": bool(execute_extraction),
        "persist_filing_parties": bool(persist_filing_parties),
        "extraction_attempted_count": int(extraction_attempted_count),
        "extraction_succeeded_count": int(extraction_succeeded_count),
        "extraction_failed_count": int(extraction_failed_count),
        "filing_party_record_count": int(filing_party_record_count),
        "filing_party_persisted_count": int(filing_party_persisted_count),
        "filing_party_persist_path": filing_party_persist_path,
        "local_visibility_changed": bool(local_visibility_changed),
        "lookup_refresh_attempted": bool(lookup_refresh_attempted),
        "lookup_refresh_performed": bool(lookup_refresh_performed),
        "lookup_refresh_skipped_reason": lookup_refresh_skipped_reason,
        "lookup_refresh_result": lookup_refresh_result,
        "lookup_update_mode": lookup_update_mode,
        "lookup_incremental_result": lookup_incremental_result,
        "lookup_full_refresh_fallback_performed": bool(lookup_full_refresh_fallback_performed),
        "lookup_full_refresh_fallback_skipped_reason": lookup_full_refresh_fallback_skipped_reason,
        "seen_state_path": str(seen_path),
        "events_path": str(events_out_path),
        "events_written_count": int(len(events)),
        "events_total_count": int(persisted_events),
        "activity_events": events[-200:],
        "total_elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def run_monitor_loop(
    config: AppConfig,
    *,
    interval_seconds: float,
    max_iterations: int,
    feed_client: FeedClient | None = None,
    warm_fetcher: WarmFetcher | None = None,
    warm: bool = True,
    form_types: list[str] | None = None,
    form_families: list[str] | None = None,
    issuer_ciks: list[str] | None = None,
    entity_ciks: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    execute_extraction: bool = False,
    persist_filing_parties: bool = False,
    refresh_lookup: bool = True,
) -> dict[str, object]:
    started_at = time.monotonic()
    max_iters = max(1, int(max_iterations))
    sleep_seconds = max(0.0, float(interval_seconds))
    iteration_results: list[dict[str, object]] = []

    for idx in range(max_iters):
        result = run_monitor_poll(
            config,
            feed_client=feed_client,
            warm_fetcher=warm_fetcher,
            warm=warm,
            form_types=form_types,
            form_families=form_families,
            issuer_ciks=issuer_ciks,
            entity_ciks=entity_ciks,
            date_from=date_from,
            date_to=date_to,
            execute_extraction=execute_extraction,
            persist_filing_parties=persist_filing_parties,
            refresh_lookup=refresh_lookup,
        )
        iteration_results.append(result)
        if idx < (max_iters - 1) and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {
        "iterations_run": int(len(iteration_results)),
        "interval_seconds": float(sleep_seconds),
        "total_elapsed_seconds": round(time.monotonic() - started_at, 3),
        "iteration_results": iteration_results,
        "total_detected_candidate_count": int(sum(int(r.get("detected_candidate_count", 0)) for r in iteration_results)),
        "total_filtered_candidate_count": int(sum(int(r.get("filtered_candidate_count", 0)) for r in iteration_results)),
        "total_warm_attempted_count": int(sum(int(r.get("warm_attempted_count", 0)) for r in iteration_results)),
        "total_warm_succeeded_count": int(sum(int(r.get("warm_succeeded_count", 0)) for r in iteration_results)),
        "total_warm_failed_count": int(sum(int(r.get("warm_failed_count", 0)) for r in iteration_results)),
    }


def _filter_candidates(
    candidates: list[MonitorCandidate],
    *,
    form_types: list[str] | None,
    form_families: list[str] | None,
    issuer_ciks: list[str] | None,
    entity_ciks: list[str] | None,
    date_from: str | None,
    date_to: str | None,
) -> list[MonitorCandidate]:
    allowed_forms = {str(v).strip().upper() for v in (form_types or []) if str(v).strip()}
    for family in (form_families or []):
        for form in FORM_FAMILY_MAP.get(str(family).strip().lower(), []):
            if str(form).strip():
                allowed_forms.add(str(form).strip().upper())
    cik_filter = {normalize_cik(v) for v in ((issuer_ciks or []) + (entity_ciks or [])) if normalize_cik(v)}
    date_from_ts = pd.to_datetime(date_from) if date_from else None
    date_to_ts = pd.to_datetime(date_to) if date_to else None

    out: list[MonitorCandidate] = []
    for item in candidates:
        if allowed_forms and (item.form_type or "").strip().upper() not in allowed_forms:
            continue
        if cik_filter and normalize_cik(item.filing_cik) not in cik_filter:
            continue
        if item.filing_date and (date_from_ts is not None or date_to_ts is not None):
            date_val = pd.to_datetime(item.filing_date, errors="coerce")
            if pd.notna(date_val):
                if date_from_ts is not None and date_val < date_from_ts:
                    continue
                if date_to_ts is not None and date_val > date_to_ts:
                    continue
        out.append(item)
    return out


def _run_optional_extraction(
    config: AppConfig,
    candidates: list[MonitorCandidate],
) -> tuple[int, int, int]:
    attempted = 0
    succeeded = 0
    failed = 0
    for candidate in candidates:
        if not candidate.filename:
            continue
        filing_path = _canonical_local_submission_path(config, candidate.filename)
        if filing_path is None or not filing_path.exists():
            continue
        output_dir = filing_path.parent / filing_path.stem.replace("-", "")
        if output_dir.exists():
            continue
        attempted += 1
        try:
            complete_submission_filing(str(filing_path), output_directory=str(output_dir))
            succeeded += 1
        except Exception:
            failed += 1
    return attempted, succeeded, failed


def _run_optional_filing_party_persist(
    config: AppConfig,
    candidates: list[MonitorCandidate],
) -> tuple[int, int]:
    records: list[dict[str, object]] = []
    for candidate in candidates:
        form_type = (candidate.form_type or "").strip().upper()
        if form_type not in SUPPORTED_FORMS:
            continue
        if not candidate.filename:
            continue
        filing_path = _canonical_local_submission_path(config, candidate.filename)
        if filing_path is None or not filing_path.exists():
            continue
        extracted = extract_filing_parties_from_file(
            filing_filepath=filing_path,
            form_type=form_type,
            filing_date=str(candidate.filing_date or ""),
            source_filename=str(candidate.filename),
        )
        records.extend(extracted)
    persisted = upsert_filing_parties_parquet(
        records=records,
        output_path=config.normalized_refdata_root / "filing_parties.parquet",
    )
    return int(len(records)), int(persisted)


def _build_seen_row(
    *,
    previous: dict[str, object] | None,
    candidate: MonitorCandidate,
    first_seen_at: str,
    last_seen_at: str,
    local_submission_present: bool,
    warmed_by_monitor: bool,
) -> dict[str, object]:
    prior = previous or {}
    return {
        "accession_number": candidate.accession_number,
        "filing_date": candidate.filing_date,
        "form_type": candidate.form_type,
        "filing_cik": normalize_cik(candidate.filing_cik),
        "source_reference": candidate.filename or candidate.url or candidate.source_id,
        "first_seen_at": prior.get("first_seen_at") or first_seen_at,
        "last_seen_at": last_seen_at,
        "local_submission_present": bool(local_submission_present),
        "warmed_by_monitor": bool(prior.get("warmed_by_monitor", False) or warmed_by_monitor),
    }


def _merge_seen_updates(existing: pd.DataFrame, updates: object) -> pd.DataFrame:
    updates_list = list(updates)
    if not updates_list:
        return existing.copy()
    updated = pd.concat([existing, pd.DataFrame(updates_list)], ignore_index=True)
    if updated.empty:
        return updated
    # Deterministic update precedence: for identical timestamps, later rows win.
    updated["__row_order"] = range(len(updated.index))
    updated = updated.sort_values(
        ["accession_number", "last_seen_at", "__row_order"],
        ascending=[True, True, True],
        na_position="last",
    )
    updated = updated.drop_duplicates(subset=["accession_number"], keep="last")
    updated = updated.drop(columns=["__row_order"])
    return updated.sort_values(["last_seen_at", "accession_number"], ascending=[False, True], na_position="last").reset_index(drop=True)


def _append_events(path: Path, rows: list[dict[str, object]]) -> int:
    current = _load_events_df(path)
    if rows:
        current = pd.concat([current, pd.DataFrame(rows)], ignore_index=True)
    if len(current.index) > _MAX_EVENTS_ROWS:
        current = current.tail(_MAX_EVENTS_ROWS).reset_index(drop=True)
    current.to_parquet(path, index=False)
    return int(len(current.index))


def _load_seen_df(path: Path) -> pd.DataFrame:
    columns = [
        "accession_number",
        "filing_date",
        "form_type",
        "filing_cik",
        "source_reference",
        "first_seen_at",
        "last_seen_at",
        "local_submission_present",
        "warmed_by_monitor",
    ]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_parquet(path)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _load_events_df(path: Path) -> pd.DataFrame:
    columns = [
        "event_time",
        "accession_number",
        "action",
        "reason",
        "status_code",
        "url",
        "filepath",
        "source_id",
        "error",
        "error_class",
    ]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_parquet(path)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _canonical_local_submission_path(config: AppConfig, filename: str | None) -> Path | None:
    if not filename:
        return None
    return config.download_root / Path(str(filename).lstrip("/"))


def _extract_accession(text: str) -> str | None:
    match = _ACCESSION_RE.search(str(text or ""))
    return match.group(1) if match else None


def _extract_cik(text: str) -> str | None:
    match = _CIK_RE.search(str(text or ""))
    return match.group(1) if match else None


def _extract_form_type(title: str, summary: str) -> str | None:
    value = f"{title} {summary}".upper()
    if "SC 13D/A" in value:
        return "SC 13D/A"
    if "SC 13D" in value:
        return "SC 13D"
    if "SC 13G/A" in value:
        return "SC 13G/A"
    if "SC 13G" in value:
        return "SC 13G"
    match = re.search(r"\b(8-K/A|8-K|6-K|4|3|5|13F-HR/A|13F-HR|13F-NT/A|13F-NT|DEF 14A|DEFA14A|PRE 14A)\b", value)
    return match.group(1) if match else None


def _filename_from_link(link: str | None) -> str | None:
    text = _non_empty(link)
    if text is None:
        return None
    marker = "/Archives/"
    if marker in text:
        return text.split(marker, 1)[1].lstrip("/")
    return None


def _filename_from_text(text: str | None) -> str | None:
    value = _non_empty(text)
    if value is None:
        return None
    # Accept direct SEC-style archive relative paths embedded in title/summary text.
    match = re.search(r"(edgar/data/\d{1,10}/\d{10}-\d{2}-\d{6}\.txt)", value, re.IGNORECASE)
    if match:
        return match.group(1).lstrip("/")
    match = re.search(r"/Archives/(edgar/data/\d{1,10}/\d{10}-\d{2}-\d{6}\.txt)", value, re.IGNORECASE)
    if match:
        return match.group(1).lstrip("/")
    return None


def _extract_cik_from_filename(filename: str | None) -> str | None:
    text = _non_empty(filename)
    if text is None:
        return None
    match = re.search(r"edgar/data/(\d{1,10})/", text, re.IGNORECASE)
    if not match:
        return None
    return normalize_cik(match.group(1))


def _derive_filename_from_accession_and_cik(accession_number: str, filing_cik: str) -> str:
    cik_raw = str(int(str(filing_cik))) if str(filing_cik).isdigit() else str(filing_cik).lstrip("0") or "0"
    return f"edgar/data/{cik_raw}/{accession_number}.txt"


def _canonical_submission_filename(
    *,
    filename: str | None,
    accession_number: str | None,
    filing_cik: str | None,
) -> str | None:
    text = _non_empty(filename)
    if text is None:
        return None
    normalized = text.lstrip("/")

    lower_name = normalized.lower()
    if lower_name.endswith("-index.htm") or lower_name.endswith("-index.html"):
        resolved_accession = accession_number or _extract_accession(normalized)
        resolved_cik = filing_cik or _extract_cik_from_filename(normalized)
        if resolved_accession and resolved_cik:
            return _derive_filename_from_accession_and_cik(resolved_accession, resolved_cik)

    return normalized


def _normalize_date_string(value: str | None) -> str | None:
    text = _non_empty(value)
    if text is None:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _non_empty(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def monitor_feed_url(config: AppConfig) -> str:
    candidate = _non_empty(getattr(config, "monitor_feed_url", None))
    if candidate:
        return candidate
    return DEFAULT_MONITOR_FEED_URL


def build_monitor_candidate_from_filename(
    *,
    filename: str,
    accession_number: str | None = None,
    filing_date: str | None = None,
    form_type: str | None = None,
    filing_cik: str | None = None,
    source_id: str | None = None,
    archives_base_url: str = _DEFAULT_ARCHIVES_BASE_URL,
) -> MonitorCandidate:
    normalized_filename = str(filename).lstrip("/")
    accession = accession_number or _extract_accession(normalized_filename) or ""
    return MonitorCandidate(
        accession_number=accession,
        filing_date=filing_date,
        form_type=form_type,
        filing_cik=normalize_cik(filing_cik),
        filename=normalized_filename,
        url=urljoin(archives_base_url, normalized_filename),
        source_id=source_id,
    )
