from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import time
from urllib.parse import urljoin

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.filters import FORM_FAMILY_MAP
from py_sec_edgar.lookup import register_local_filings_in_lookup, refresh_local_lookup_indexes
from py_sec_edgar.monitoring import (
    FeedClient,
    FeedNormalizationResult,
    MonitorCandidate,
    ProxyRequestWarmFetcher,
    SecCurrentAtomFeedClient,
    WarmFetcher,
    monitor_feed_url,
)
from py_sec_edgar.refdata.normalize import normalize_cik


_DEFAULT_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/"
_MERGED_REQUIRED_COLUMNS = {"CIK", "Form Type", "Date Filed", "Filename"}
_MAX_RECONCILIATION_EVENTS_ROWS = 10000
_MAX_RECONCILIATION_DISCREPANCIES_ROWS = 50000
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")


@dataclass(frozen=True)
class ReconciliationItem:
    key: str
    accession_number: str | None
    filing_date: str | None
    form_type: str | None
    filing_cik: str | None
    filename: str | None
    source_url: str | None
    feed_seen: bool
    merged_index_seen: bool


def reconciliation_discrepancies_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "reconciliation_discrepancies.parquet"


def reconciliation_events_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "reconciliation_events.parquet"


def run_reconciliation(
    config: AppConfig,
    *,
    feed_client: FeedClient | None = None,
    warm_fetcher: WarmFetcher | None = None,
    recent_days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    form_types: list[str] | None = None,
    form_families: list[str] | None = None,
    issuer_ciks: list[str] | None = None,
    catch_up_warm: bool = False,
    refresh_lookup: bool = True,
) -> dict[str, object]:
    started_at = time.monotonic()
    run_time = _now_utc_iso()
    config.ensure_runtime_dirs()

    merged_df = _load_merged_index_df(config)
    filtered_merged = _filter_merged_rows(
        merged_df,
        recent_days=recent_days,
        date_from=date_from,
        date_to=date_to,
        form_types=form_types,
        form_families=form_families,
        issuer_ciks=issuer_ciks,
    )

    source = feed_client or SecCurrentAtomFeedClient(feed_url=monitor_feed_url(config))
    fetched = source.fetch_candidates(config)
    if isinstance(fetched, FeedNormalizationResult):
        feed_candidates = list(fetched.candidates)
    else:
        feed_candidates = list(fetched)
    filtered_feed = _filter_feed_candidates(
        feed_candidates,
        recent_days=recent_days,
        date_from=date_from,
        date_to=date_to,
        form_types=form_types,
        form_families=form_families,
        issuer_ciks=issuer_ciks,
    )

    merged_items = _build_items_from_merged(filtered_merged)
    feed_items = _build_items_from_feed(filtered_feed)

    merged_map = {item.key: item for item in merged_items}
    feed_map = {item.key: item for item in feed_items}

    keys = sorted(set(merged_map.keys()) | set(feed_map.keys()))
    rows: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    warmer = warm_fetcher or ProxyRequestWarmFetcher()

    catch_up_attempted_count = 0
    catch_up_succeeded_count = 0
    catch_up_failed_count = 0
    catch_up_skipped_count = 0
    catch_up_skip_reasons: dict[str, int] = {}
    warmed_success_filenames: list[str] = []
    warmed_success_accessions: list[str] = []

    for key in keys:
        merged_item = merged_map.get(key)
        feed_item = feed_map.get(key)
        combined = _merge_item(merged_item, feed_item)
        local_path = _canonical_local_submission_path(config, combined.filename)
        local_present = bool(local_path is not None and local_path.exists())
        resolved_source_url = _canonical_source_url(combined.filename) or combined.source_url

        discrepancy_type = _classify_discrepancy(
            feed_seen=combined.feed_seen,
            merged_index_seen=combined.merged_index_seen,
            local_present=local_present,
        )

        catch_up_eligible, catch_up_skip_reason = _evaluate_catch_up_eligibility(
            item=combined,
            discrepancy_type=discrepancy_type,
            local_present=local_present,
            source_url=resolved_source_url,
        )
        catch_up_attempted = False
        catch_up_succeeded = False
        catch_up_skipped = False

        if catch_up_eligible and catch_up_warm:
            catch_up_attempted = True
            catch_up_attempted_count += 1
            events.append(
                {
                    "event_time": run_time,
                    "accession_number": combined.accession_number,
                    "action": "reconcile_catch_up_attempted",
                    "reason": discrepancy_type,
                    "status_code": None,
                    "url": resolved_source_url,
                    "filepath": str(local_path) if local_path is not None else None,
                    "source_id": "reconciliation",
                    "error": None,
                    "error_class": None,
                }
            )

            if local_path is None or not resolved_source_url:
                catch_up_failed_count += 1
                events.append(
                    {
                        "event_time": run_time,
                        "accession_number": combined.accession_number,
                        "action": "reconcile_catch_up_failed",
                        "reason": "missing_url_or_filename",
                        "status_code": None,
                        "url": resolved_source_url,
                        "filepath": str(local_path) if local_path is not None else None,
                        "source_id": "reconciliation",
                        "error": None,
                        "error_class": None,
                    }
                )
            else:
                fetch_result = warmer.fetch(config, resolved_source_url, local_path)
                local_present_after = bool(local_path.exists())
                if fetch_result.ok and local_present_after:
                    catch_up_succeeded = True
                    catch_up_succeeded_count += 1
                    warmed_success_filenames.append(str(combined.filename))
                    if combined.accession_number:
                        warmed_success_accessions.append(str(combined.accession_number))
                    events.append(
                        {
                            "event_time": run_time,
                            "accession_number": combined.accession_number,
                            "action": "reconcile_catch_up_succeeded",
                            "reason": "downloaded",
                            "status_code": None,
                            "url": resolved_source_url,
                            "filepath": str(local_path),
                            "source_id": "reconciliation",
                            "error": None,
                            "error_class": None,
                        }
                    )
                else:
                    catch_up_failed_count += 1
                    events.append(
                        {
                            "event_time": run_time,
                            "accession_number": combined.accession_number,
                            "action": "reconcile_catch_up_failed",
                            "reason": fetch_result.reason or "catch_up_failed",
                            "status_code": fetch_result.status_code,
                            "url": resolved_source_url,
                            "filepath": str(local_path),
                            "source_id": "reconciliation",
                            "error": fetch_result.error,
                            "error_class": fetch_result.error_class,
                        }
                    )
        elif catch_up_warm and _is_actionable_discrepancy(discrepancy_type) and not local_present:
            catch_up_skipped = True
            reason = catch_up_skip_reason or "ineligible_for_catch_up"
            catch_up_skipped_count += 1
            catch_up_skip_reasons[reason] = int(catch_up_skip_reasons.get(reason, 0) + 1)
            events.append(
                {
                    "event_time": run_time,
                    "accession_number": combined.accession_number,
                    "action": "reconcile_catch_up_skipped",
                    "reason": reason,
                    "status_code": None,
                    "url": resolved_source_url,
                    "filepath": str(local_path) if local_path is not None else None,
                    "source_id": "reconciliation",
                    "error": None,
                    "error_class": None,
                }
            )

        local_present_final = bool(local_path is not None and local_path.exists())
        final_discrepancy_type = _classify_discrepancy(
            feed_seen=combined.feed_seen,
            merged_index_seen=combined.merged_index_seen,
            local_present=local_present_final,
        )

        rows.append(
            {
                "run_time": run_time,
                "accession_number": combined.accession_number,
                "filing_date": combined.filing_date,
                "form_type": combined.form_type,
                "filing_cik": combined.filing_cik,
                "filename": combined.filename,
                "source_url": resolved_source_url,
                "discrepancy_type": final_discrepancy_type,
                "local_submission_present": bool(local_present_final),
                "feed_seen": bool(combined.feed_seen),
                "merged_index_seen": bool(combined.merged_index_seen),
                "catch_up_eligible": bool(catch_up_eligible),
                "catch_up_attempted": bool(catch_up_attempted),
                "catch_up_succeeded": bool(catch_up_succeeded),
                "catch_up_skipped": bool(catch_up_skipped),
                "catch_up_skip_reason": catch_up_skip_reason if catch_up_skipped else None,
            }
        )

    lookup_refresh_attempted = bool(refresh_lookup)
    lookup_refresh_performed = False
    lookup_refresh_skipped_reason: str | None = None
    lookup_refresh_result: dict[str, object] | None = None
    lookup_update_mode = "skipped"
    lookup_incremental_result: dict[str, object] | None = None
    lookup_full_refresh_fallback_performed = False
    lookup_full_refresh_fallback_skipped_reason: str | None = None

    if catch_up_succeeded_count <= 0:
        lookup_refresh_skipped_reason = "no_catch_up_visibility_change"
        lookup_full_refresh_fallback_skipped_reason = "no_catch_up_visibility_change"
        events.append(
            {
                "event_time": run_time,
                "accession_number": None,
                "action": "reconcile_lookup_incremental_skipped",
                "reason": lookup_refresh_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "reconciliation",
                "error": None,
                "error_class": None,
            }
        )
        events.append(
            {
                "event_time": run_time,
                "accession_number": None,
                "action": "reconcile_lookup_full_refresh_fallback_skipped",
                "reason": lookup_full_refresh_fallback_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "reconciliation",
                "error": None,
                "error_class": None,
            }
        )
    elif not refresh_lookup:
        lookup_refresh_skipped_reason = "refresh_lookup_disabled"
        lookup_full_refresh_fallback_skipped_reason = "fallback_not_allowed_refresh_disabled"
        events.append(
            {
                "event_time": run_time,
                "accession_number": None,
                "action": "reconcile_lookup_incremental_skipped",
                "reason": lookup_refresh_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "reconciliation",
                "error": None,
                "error_class": None,
            }
        )
        events.append(
            {
                "event_time": run_time,
                "accession_number": None,
                "action": "reconcile_lookup_full_refresh_fallback_skipped",
                "reason": lookup_full_refresh_fallback_skipped_reason,
                "status_code": None,
                "url": None,
                "filepath": None,
                "source_id": "reconciliation",
                "error": None,
                "error_class": None,
            }
        )
    else:
        lookup_incremental_result = register_local_filings_in_lookup(
            config,
            warmed_filenames=warmed_success_filenames,
            warmed_accession_numbers=warmed_success_accessions,
        )
        lookup_refresh_result = lookup_incremental_result
        if bool(lookup_incremental_result.get("safe_to_use")):
            lookup_refresh_performed = True
            lookup_update_mode = "incremental"
            lookup_full_refresh_fallback_skipped_reason = "incremental_safe_to_use"
            events.append(
                {
                    "event_time": run_time,
                    "accession_number": None,
                    "action": "reconcile_lookup_incremental_performed",
                    "reason": "safe_to_use",
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "reconciliation",
                    "error": None,
                    "error_class": None,
                }
            )
            events.append(
                {
                    "event_time": run_time,
                    "accession_number": None,
                    "action": "reconcile_lookup_full_refresh_fallback_skipped",
                    "reason": lookup_full_refresh_fallback_skipped_reason,
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "reconciliation",
                    "error": None,
                    "error_class": None,
                }
            )
        else:
            events.append(
                {
                    "event_time": run_time,
                    "accession_number": None,
                    "action": "reconcile_lookup_incremental_skipped",
                    "reason": "unsafe_or_incomplete",
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "reconciliation",
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
                    "event_time": run_time,
                    "accession_number": None,
                    "action": "reconcile_lookup_full_refresh_fallback_performed",
                    "reason": "incremental_unsafe_or_incomplete",
                    "status_code": None,
                    "url": None,
                    "filepath": None,
                    "source_id": "reconciliation",
                    "error": None,
                    "error_class": None,
                }
            )

    discrepancy_path = reconciliation_discrepancies_path(config)
    events_path = reconciliation_events_path(config)

    discrepancies_written = _append_discrepancies(discrepancy_path, rows)
    events_written_total = _append_events(events_path, events)

    discrepancy_counts = pd.Series([row["discrepancy_type"] for row in rows], dtype="object").value_counts(dropna=False).to_dict()
    discrepancy_counts = {str(k): int(v) for k, v in discrepancy_counts.items()}

    return {
        "run_time": run_time,
        "merged_index_candidate_count": int(len(filtered_merged.index)),
        "feed_candidate_count": int(len(filtered_feed)),
        "reconciled_row_count": int(len(rows)),
        "discrepancy_type_counts": discrepancy_counts,
        "catch_up_warm_enabled": bool(catch_up_warm),
        "catch_up_attempted_count": int(catch_up_attempted_count),
        "catch_up_succeeded_count": int(catch_up_succeeded_count),
        "catch_up_failed_count": int(catch_up_failed_count),
        "catch_up_skipped_count": int(catch_up_skipped_count),
        "catch_up_skip_reasons": {str(k): int(v) for k, v in sorted(catch_up_skip_reasons.items())},
        "lookup_refresh_attempted": bool(lookup_refresh_attempted),
        "lookup_refresh_performed": bool(lookup_refresh_performed),
        "lookup_refresh_skipped_reason": lookup_refresh_skipped_reason,
        "lookup_refresh_result": lookup_refresh_result,
        "lookup_update_mode": lookup_update_mode,
        "lookup_incremental_result": lookup_incremental_result,
        "lookup_full_refresh_fallback_performed": bool(lookup_full_refresh_fallback_performed),
        "lookup_full_refresh_fallback_skipped_reason": lookup_full_refresh_fallback_skipped_reason,
        "discrepancies_path": str(discrepancy_path),
        "events_path": str(events_path),
        "discrepancy_rows_written_count": int(len(rows)),
        "discrepancy_rows_total_count": int(discrepancies_written),
        "events_written_count": int(len(events)),
        "events_total_count": int(events_written_total),
        "activity_events": events[-200:],
        "total_elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def _load_merged_index_df(config: AppConfig) -> pd.DataFrame:
    if not config.merged_index_path.exists():
        raise FileNotFoundError(
            f"Merged index file not found: {config.merged_index_path}. Run `py-sec-edgar index refresh` first."
        )
    merged = pd.read_parquet(config.merged_index_path)
    missing = sorted(_MERGED_REQUIRED_COLUMNS.difference(merged.columns))
    if missing:
        raise ValueError(
            f"Merged index dataset is missing required columns: {', '.join(missing)}. "
            "Run `py-sec-edgar index refresh` to regenerate merged index data."
        )
    return merged


def _filter_merged_rows(
    merged: pd.DataFrame,
    *,
    recent_days: int | None,
    date_from: str | None,
    date_to: str | None,
    form_types: list[str] | None,
    form_families: list[str] | None,
    issuer_ciks: list[str] | None,
) -> pd.DataFrame:
    allowed_forms = _resolved_form_set(form_types, form_families)
    allowed_ciks = _resolved_cik_set(issuer_ciks)
    min_date, max_date = _resolved_date_bounds(recent_days, date_from, date_to)

    out = merged.copy()
    if allowed_forms:
        out = out[out["Form Type"].astype(str).str.upper().isin(allowed_forms)]
    if allowed_ciks:
        normalized = out["CIK"].map(normalize_cik)
        out = out[normalized.isin(allowed_ciks)]
    if min_date is not None or max_date is not None:
        dates = _normalize_datetime_series(out["Date Filed"])
        mask = pd.Series(True, index=out.index)
        if min_date is not None:
            mask = mask & dates.ge(min_date)
        if max_date is not None:
            mask = mask & dates.le(max_date)
        mask = mask.fillna(False)
        out = out[mask]
    return out.reset_index(drop=True)


def _filter_feed_candidates(
    candidates: list[MonitorCandidate],
    *,
    recent_days: int | None,
    date_from: str | None,
    date_to: str | None,
    form_types: list[str] | None,
    form_families: list[str] | None,
    issuer_ciks: list[str] | None,
) -> list[MonitorCandidate]:
    allowed_forms = _resolved_form_set(form_types, form_families)
    allowed_ciks = _resolved_cik_set(issuer_ciks)
    min_date, max_date = _resolved_date_bounds(recent_days, date_from, date_to)

    out: list[MonitorCandidate] = []
    for item in candidates:
        form_type = str(item.form_type or "").strip().upper()
        filing_cik = normalize_cik(item.filing_cik)
        if allowed_forms and form_type not in allowed_forms:
            continue
        if allowed_ciks and filing_cik not in allowed_ciks:
            continue
        if min_date is not None or max_date is not None:
            if item.filing_date:
                date_val = _to_naive_timestamp(item.filing_date)
                if date_val is not None:
                    if min_date is not None and date_val < min_date:
                        continue
                    if max_date is not None and date_val > max_date:
                        continue
        out.append(item)
    return out


def _resolved_form_set(form_types: list[str] | None, form_families: list[str] | None) -> set[str]:
    forms = {str(v).strip().upper() for v in (form_types or []) if str(v).strip()}
    for family in (form_families or []):
        for form in FORM_FAMILY_MAP.get(str(family).strip().lower(), []):
            if str(form).strip():
                forms.add(str(form).strip().upper())
    return forms


def _resolved_cik_set(issuer_ciks: list[str] | None) -> set[str]:
    return {normalize_cik(v) for v in (issuer_ciks or []) if normalize_cik(v)}


def _resolved_date_bounds(
    recent_days: int | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    max_date = _to_naive_timestamp(date_to)
    if date_from:
        min_date = _to_naive_timestamp(date_from)
    elif recent_days is not None:
        min_date = _to_naive_timestamp(datetime.now(timezone.utc) - timedelta(days=max(0, int(recent_days))))
    else:
        min_date = _to_naive_timestamp(datetime.now(timezone.utc) - timedelta(days=7))
    return min_date, max_date


def _normalize_datetime_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    return parsed.dt.tz_convert(None)


def _to_naive_timestamp(value: object) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_convert(None)


def _build_items_from_merged(df: pd.DataFrame) -> list[ReconciliationItem]:
    out: list[ReconciliationItem] = []
    for row in df.to_dict(orient="records"):
        filename = _normalize_filename(row.get("Filename"))
        if filename is None:
            continue
        accession = _derive_accession_number(filename)
        key = accession or filename
        out.append(
            ReconciliationItem(
                key=key,
                accession_number=accession,
                filing_date=_as_text(row.get("Date Filed")),
                form_type=_as_text(row.get("Form Type")),
                filing_cik=normalize_cik(row.get("CIK")),
                filename=filename,
                source_url=urljoin(_DEFAULT_ARCHIVES_BASE_URL, filename),
                feed_seen=False,
                merged_index_seen=True,
            )
        )
    return out


def _build_items_from_feed(candidates: list[MonitorCandidate]) -> list[ReconciliationItem]:
    out: list[ReconciliationItem] = []
    for candidate in candidates:
        filename = _normalize_filename(candidate.filename)
        accession = _as_text(candidate.accession_number) or _derive_accession_number(filename or "")
        key = accession or filename
        if key is None:
            continue
        out.append(
            ReconciliationItem(
                key=key,
                accession_number=accession,
                filing_date=_as_text(candidate.filing_date),
                form_type=_as_text(candidate.form_type),
                filing_cik=normalize_cik(candidate.filing_cik),
                filename=filename,
                source_url=_as_text(candidate.url) or (urljoin(_DEFAULT_ARCHIVES_BASE_URL, filename) if filename else None),
                feed_seen=True,
                merged_index_seen=False,
            )
        )
    return out


def _merge_item(index_item: ReconciliationItem | None, feed_item: ReconciliationItem | None) -> ReconciliationItem:
    if index_item is None and feed_item is None:
        raise ValueError("Cannot merge empty reconciliation items.")
    if index_item is None:
        assert feed_item is not None
        return feed_item
    if feed_item is None:
        return index_item
    return ReconciliationItem(
        key=index_item.key,
        accession_number=index_item.accession_number or feed_item.accession_number,
        filing_date=index_item.filing_date or feed_item.filing_date,
        form_type=index_item.form_type or feed_item.form_type,
        filing_cik=index_item.filing_cik or feed_item.filing_cik,
        filename=index_item.filename or feed_item.filename,
        source_url=feed_item.source_url or index_item.source_url,
        feed_seen=True,
        merged_index_seen=True,
    )


def _classify_discrepancy(*, feed_seen: bool, merged_index_seen: bool, local_present: bool) -> str:
    if feed_seen and merged_index_seen and not local_present:
        return "index_and_feed_but_missing_local"
    if feed_seen and merged_index_seen and local_present:
        return "fully_reconciled_local_present"
    if feed_seen and not merged_index_seen and not local_present:
        return "feed_seen_missing_local"
    if feed_seen and not merged_index_seen:
        return "feed_only_not_in_index"
    if merged_index_seen and not feed_seen and not local_present:
        return "index_only_not_seen_in_feed"
    if merged_index_seen and not feed_seen and local_present:
        return "fully_reconciled_local_present"
    return "fully_reconciled_local_present"


def _is_actionable_discrepancy(discrepancy_type: str) -> bool:
    return discrepancy_type in {
        "index_only_not_seen_in_feed",
        "index_and_feed_but_missing_local",
        "feed_seen_missing_local",
    }


def _canonical_source_url(filename: str | None) -> str | None:
    normalized = _normalize_filename(filename)
    if normalized is None:
        return None
    return urljoin(_DEFAULT_ARCHIVES_BASE_URL, normalized)


def _is_canonical_txt_filename(filename: str | None) -> bool:
    normalized = _normalize_filename(filename)
    if normalized is None:
        return False
    lowered = normalized.lower()
    return lowered.startswith("edgar/data/") and lowered.endswith(".txt")


def _evaluate_catch_up_eligibility(
    *,
    item: ReconciliationItem,
    discrepancy_type: str,
    local_present: bool,
    source_url: str | None,
) -> tuple[bool, str | None]:
    if local_present:
        return False, "already_local"
    if not _is_actionable_discrepancy(discrepancy_type):
        return False, "discrepancy_not_actionable"
    if not _is_canonical_txt_filename(item.filename):
        return False, "non_canonical_filename"
    canonical_url = _canonical_source_url(item.filename)
    if canonical_url is None:
        return False, "missing_canonical_url"
    if source_url != canonical_url:
        return False, "non_canonical_source_url"

    if item.merged_index_seen:
        return True, None

    # Feed-only catch-up stays conservative by default.
    if not item.feed_seen:
        return False, "feed_not_seen"
    if not item.accession_number or not item.filing_cik:
        return False, "feed_only_missing_accession_or_cik"
    derived_accession = _derive_accession_number(item.filename or "")
    if derived_accession != item.accession_number:
        return False, "feed_only_accession_mismatch"
    return True, None


def _canonical_local_submission_path(config: AppConfig, filename: str | None) -> Path | None:
    if not filename:
        return None
    return config.download_root / Path(filename.lstrip("/"))


def _normalize_filename(value: object) -> str | None:
    text = _as_text(value)
    if text is None:
        return None
    return text.lstrip("/")


def _derive_accession_number(filename: str) -> str | None:
    text = str(filename or "")
    match = _ACCESSION_RE.search(text)
    if not match:
        return None
    out = str(match.group(1)).strip()
    return out or None


def _append_discrepancies(path: Path, rows: list[dict[str, object]]) -> int:
    columns = [
        "run_time",
        "accession_number",
        "filing_date",
        "form_type",
        "filing_cik",
        "filename",
        "source_url",
        "discrepancy_type",
        "local_submission_present",
        "feed_seen",
        "merged_index_seen",
        "catch_up_eligible",
        "catch_up_attempted",
        "catch_up_succeeded",
        "catch_up_skipped",
        "catch_up_skip_reason",
    ]
    current = _load_parquet_or_empty(path, columns)
    if rows:
        current = pd.concat([current, pd.DataFrame(rows)], ignore_index=True)
    if len(current.index) > _MAX_RECONCILIATION_DISCREPANCIES_ROWS:
        current = current.tail(_MAX_RECONCILIATION_DISCREPANCIES_ROWS).reset_index(drop=True)
    current.to_parquet(path, index=False)
    return int(len(current.index))


def _append_events(path: Path, rows: list[dict[str, object]]) -> int:
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
    current = _load_parquet_or_empty(path, columns)
    if rows:
        current = pd.concat([current, pd.DataFrame(rows)], ignore_index=True)
    if len(current.index) > _MAX_RECONCILIATION_EVENTS_ROWS:
        current = current.tail(_MAX_RECONCILIATION_EVENTS_ROWS).reset_index(drop=True)
    current.to_parquet(path, index=False)
    return int(len(current.index))


def _load_parquet_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_parquet(path)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
