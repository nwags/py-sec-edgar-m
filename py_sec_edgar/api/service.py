from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import pandas as pd

from py_sec_edgar.augmentation_sidecars import (
    AugmentationSubmissionPersistResult,
    build_augmentation_entity_index,
    EVENT_FAMILY_GOVERNANCE,
    EVENT_FAMILY_LIFECYCLE,
    get_augmentation_submission_detail,
    get_submission_review_bundle,
    list_augmentation_events,
    list_submission_entity_impact,
    list_submission_overlay_impact,
    list_augmentation_submissions_cross_accession,
    list_augmentations_for_accession,
    list_augmentation_submissions_for_accession,
    summarize_augmentation_events,
    persist_augmentation_submission,
    record_submission_lifecycle_transition,
    resolve_overlay_for_accession,
    search_filings_by_entity_index,
)
from py_sec_edgar.config import AppConfig
from py_sec_edgar.download import ProxyRequest
from py_sec_edgar.filing_resolution import (
    ARCHIVES_CONTENT_SURFACE_ID,
    FilingRecordIdentity,
    canonical_local_submission_path,
    canonical_submission_url,
    parse_accession_number,
    resolve_filing_identity,
    sec_archives_base_url,
)
from py_sec_edgar.resolution_provenance import append_resolution_provenance_events, now_utc_iso
from py_sec_edgar.sec_surfaces import SEC_PROVIDER_ID


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
    metadata_surface: str


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


def _metadata_from_identity(identity: FilingRecordIdentity) -> FilingMetadata:
    return FilingMetadata(
        accession_number=identity.accession_number,
        filing_cik=identity.filing_cik,
        form_type=identity.form_type,
        filing_date=identity.filing_date,
        filename=identity.filename,
        submission_path=None,
        metadata_source=identity.metadata_source,
        metadata_surface=identity.metadata_surface,
    )


def _record_remote_resolution_provenance(
    config: AppConfig,
    *,
    metadata: FilingMetadata,
    decision: RetrievalDecision,
    remote_url: str | None,
    local_path: Path | None,
    persisted_locally: bool,
    status_code: int | None = None,
    reason: str | None = None,
    error: str | None = None,
    error_class: str | None = None,
) -> None:
    append_resolution_provenance_events(
        config,
        [
            {
                "event_time": now_utc_iso(),
                "flow": "api",
                "provider_id": SEC_PROVIDER_ID,
                "accession_number": metadata.accession_number,
                "filename": metadata.filename,
                "filing_cik": metadata.filing_cik,
                "form_type": metadata.form_type,
                "filing_date": metadata.filing_date,
                "metadata_surface": metadata.metadata_surface,
                "content_surface": ARCHIVES_CONTENT_SURFACE_ID,
                "decision": str(decision.value),
                "remote_url": remote_url,
                "local_path": str(local_path) if local_path is not None else None,
                "persisted_locally": bool(persisted_locally),
                "status_code": status_code,
                "reason": reason,
                "error": error,
                "error_class": error_class,
            }
        ],
    )


def derive_archives_base_url(config: AppConfig) -> str:
    return sec_archives_base_url(config)


def derive_remote_filing_url(config: AppConfig, filename: str) -> str:
    out = canonical_submission_url(filename, config=config)
    if out is None:
        raise ValueError("Cannot derive remote filing URL without a filename.")
    return out


def find_filing_metadata(config: AppConfig, accession_number: str) -> FilingMetadata | None:
    identity = resolve_filing_identity(config, accession_number)
    if identity is None:
        return None
    return _metadata_from_identity(identity)


def resolve_canonical_submission_path(config: AppConfig, metadata: FilingMetadata | None) -> Path | None:
    if metadata is None:
        return None
    if metadata.filename:
        return canonical_local_submission_path(config, metadata.filename)
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
    parse_accession_number(accession_number)
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
        _record_remote_resolution_provenance(
            config,
            metadata=metadata,
            decision=RetrievalDecision.REMOTE_FETCH_FAILED,
            remote_url=None,
            local_path=canonical_path,
            persisted_locally=False,
            reason="missing_filename",
            error="Filing metadata is missing filename required for SEC retrieval.",
        )
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
        _record_remote_resolution_provenance(
            config,
            metadata=metadata,
            decision=RetrievalDecision.REMOTE_FETCHED_AND_PERSISTED,
            remote_url=remote_url,
            local_path=canonical_path,
            persisted_locally=True,
        )
        return RetrievalResult(
            decision=RetrievalDecision.REMOTE_FETCHED_AND_PERSISTED,
            metadata=metadata,
            local_path=canonical_path,
            remote_url=remote_url,
        )

    _record_remote_resolution_provenance(
        config,
        metadata=metadata,
        decision=RetrievalDecision.REMOTE_FETCH_FAILED,
        remote_url=remote_url,
        local_path=canonical_path,
        persisted_locally=False,
        status_code=fetch_result.status_code,
        reason=fetch_result.reason or "remote_fetch_failed",
        error=fetch_result.error,
        error_class=fetch_result.error_class,
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

    def list_augmentations_for_accession(
        self,
        accession_number: str,
        *,
        producer_id: str | None = None,
        layer_type: str | None = None,
        augmentation_type: str | None = None,
        schema_version: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        include_submission_metadata: bool = False,
        lifecycle_state: str | None = None,
        submission_id: str | None = None,
        latest_submission_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        parse_accession_number(accession_number)
        return list_augmentations_for_accession(
            self._config,
            accession_number=accession_number,
            producer_id=producer_id,
            layer_type=layer_type,
            augmentation_type=augmentation_type,
            schema_version=schema_version,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            include_submission_metadata=include_submission_metadata,
            lifecycle_state=lifecycle_state,
            submission_id=submission_id,
            latest_submission_only=latest_submission_only,
            limit=limit,
        )

    def resolve_overlay_for_accession(
        self,
        accession_number: str,
        *,
        producer_id: str | None = None,
        layer_type: str | None = None,
        augmentation_type: str | None = None,
        schema_version: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        include_submission_metadata: bool = False,
        lifecycle_state: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        parse_accession_number(accession_number)
        result = resolve_overlay_for_accession(
            self._config,
            accession_number=accession_number,
            producer_id=producer_id,
            layer_type=layer_type,
            augmentation_type=augmentation_type,
            schema_version=schema_version,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            include_submission_metadata=include_submission_metadata,
            lifecycle_state=lifecycle_state,
            limit=limit,
        )
        return {
            "selection_policy": result.selection_policy,
            "selected_submission_keys": result.selected_submission_keys,
            "augmentations": result.augmentations,
        }

    def list_augmentation_submissions_for_accession(
        self,
        accession_number: str,
        *,
        producer_id: str | None = None,
        layer_type: str | None = None,
        schema_version: str | None = None,
        lifecycle_state: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        parse_accession_number(accession_number)
        rows = list_augmentation_submissions_for_accession(
            self._config,
            accession_number=accession_number,
            producer_id=producer_id,
            layer_type=layer_type,
            schema_version=schema_version,
            lifecycle_state=lifecycle_state,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            limit=limit,
        )
        return [
            {
                "submission_id": row.submission_id,
                "received_at": row.received_at,
                "producer_id": row.producer_id,
                "layer_type": row.layer_type,
                "schema_version": row.schema_version,
                "producer_run_id": row.producer_run_id,
                "pipeline_id": row.pipeline_id,
                "model_id": row.model_id,
                "producer_version": row.producer_version,
                "raw_request_path": row.raw_request_path,
                "item_count_for_accession": row.item_count_for_accession,
                "lifecycle_state": row.lifecycle_state,
            }
            for row in rows
        ]

    def list_governance_events(
        self,
        *,
        accession_number: str | None = None,
        submission_id: str | None = None,
        producer_id: str | None = None,
        layer_type: str | None = None,
        warning_code: str | None = None,
        family_id: str | None = None,
        match_status: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        event_time_from: str | None = None,
        event_time_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        rows = self.list_augmentation_events(
            accession_numbers=[accession_number] if accession_number else None,
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=EVENT_FAMILY_GOVERNANCE,
            warning_code=warning_code,
            match_status=match_status,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            limit=limit,
        )
        filtered: list[dict[str, object]] = []
        for row in rows:
            if family_id is not None and row.get("family_id") != family_id:
                continue
            filtered.append(
                {
                    "event_time": row.get("event_time"),
                    "contract_version_id": row.get("contract_version_id"),
                    "submission_id": row.get("submission_id"),
                    "item_index": int(row.get("item_index") or 0),
                    "accession_number": (row.get("accession_numbers") or [None])[0],
                    "producer_id": row.get("producer_id"),
                    "layer_type": row.get("layer_type"),
                    "augmentation_type": row.get("augmentation_type"),
                    "schema_version": row.get("schema_version"),
                    "family_id": row.get("family_id"),
                    "family_inferred": bool(row.get("family_inferred")),
                    "match_status": row.get("match_status"),
                    "warning_codes": list(row.get("warning_codes") or []),
                    "warning_messages": list(row.get("warning_messages") or []),
                }
            )
        return filtered

    def list_augmentation_events(
        self,
        *,
        accession_numbers: list[str] | None = None,
        submission_id: str | None = None,
        producer_id: str | None = None,
        layer_type: str | None = None,
        event_family: str | None = None,
        event_type: str | None = None,
        event_source: str | None = None,
        warning_code: str | None = None,
        match_status: str | None = None,
        to_state: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        event_time_from: str | None = None,
        event_time_to: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, object]]:
        if accession_numbers:
            for accession_number in accession_numbers:
                parse_accession_number(accession_number)
        rows = list_augmentation_events(
            self._config,
            accession_numbers=accession_numbers,
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=event_family,
            event_type=event_type,
            event_source=event_source,
            warning_code=warning_code,
            match_status=match_status,
            to_state=to_state,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            limit=limit,
        )
        return [
            {
                "event_family": row.event_family,
                "event_type": row.event_type,
                "event_source": row.event_source,
                "event_time": row.event_time,
                "event_id": row.event_id,
                "submission_id": row.submission_id,
                "accession_numbers": row.accession_numbers,
                "producer_id": row.producer_id,
                "layer_type": row.layer_type,
                "item_index": int(row.event_id.split("|")[2]) if row.event_family == EVENT_FAMILY_GOVERNANCE else None,
                "contract_version_id": row.contract_version_id,
                "augmentation_type": row.augmentation_type,
                "schema_version": row.schema_version,
                "family_id": row.family_id,
                "family_inferred": row.family_inferred,
                "warning_codes": row.warning_codes or [],
                "match_status": row.match_status,
                "warning_messages": row.warning_messages or [],
                "from_state": row.from_state,
                "to_state": row.to_state,
                "reason": row.reason,
                "changed_by": row.changed_by,
                "source": row.source,
            }
            for row in rows
        ]

    def summarize_governance_events(
        self,
        *,
        accession_number: str | None = None,
        submission_id: str | None = None,
        producer_id: str | None = None,
        layer_type: str | None = None,
        warning_code: str | None = None,
        family_id: str | None = None,
        match_status: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        event_time_from: str | None = None,
        event_time_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        rows = self.list_augmentation_events(
            accession_numbers=[accession_number] if accession_number else None,
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=EVENT_FAMILY_GOVERNANCE,
            warning_code=warning_code,
            match_status=match_status,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            limit=None,
        )
        if family_id is not None:
            rows = [row for row in rows if row.get("family_id") == family_id]
        summary_rows: list[dict[str, object]] = []
        for row in rows:
            warning_codes = list(row.get("warning_codes") or [])
            if not warning_codes:
                warning_codes = [""]
            for code in warning_codes:
                summary_rows.append(
                    {
                        "warning_code": str(code),
                        "family_id": row.get("family_id"),
                        "match_status": row.get("match_status"),
                        "submission_id": row.get("submission_id"),
                        "accession_number": (row.get("accession_numbers") or [None])[0],
                    }
                )
        if not summary_rows:
            return []
        summary_df = (
            pd.DataFrame(summary_rows)
            .groupby(["warning_code", "family_id", "match_status"], dropna=False, as_index=False)
            .agg(
                event_count=("submission_id", "count"),
                submission_count=("submission_id", "nunique"),
                accession_count=("accession_number", "nunique"),
            )
            .sort_values(["warning_code", "family_id", "match_status"], ascending=[True, True, True], na_position="last")
            .reset_index(drop=True)
        )
        if limit is not None:
            summary_df = summary_df.head(int(limit)).reset_index(drop=True)
        out: list[dict[str, object]] = []
        for row in summary_df.to_dict(orient="records"):
            out.append(
                {
                    "warning_code": str(row.get("warning_code") or ""),
                    "family_id": None if pd.isna(row.get("family_id")) else row.get("family_id"),
                    "match_status": str(row.get("match_status") or ""),
                    "event_count": int(row.get("event_count") or 0),
                    "submission_count": int(row.get("submission_count") or 0),
                    "accession_count": int(row.get("accession_count") or 0),
                }
            )
        return out

    def summarize_augmentation_events(
        self,
        *,
        accession_numbers: list[str] | None = None,
        submission_id: str | None = None,
        producer_id: str | None = None,
        layer_type: str | None = None,
        event_family: str | None = None,
        event_type: str | None = None,
        event_source: str | None = None,
        warning_code: str | None = None,
        match_status: str | None = None,
        to_state: str | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        event_time_from: str | None = None,
        event_time_to: str | None = None,
        group_by: list[str] | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, object]]:
        if accession_numbers:
            for accession_number in accession_numbers:
                parse_accession_number(accession_number)
        return summarize_augmentation_events(
            self._config,
            accession_numbers=accession_numbers,
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=event_family,
            event_type=event_type,
            event_source=event_source,
            warning_code=warning_code,
            match_status=match_status,
            to_state=to_state,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            group_by=group_by,
            limit=limit,
        )

    def list_augmentation_submissions_cross_accession(
        self,
        *,
        submission_id: str | None = None,
        accession_number: str | None = None,
        producer_id: str | None = None,
        layer_type: str | None = None,
        schema_version: str | None = None,
        lifecycle_state: str | None = None,
        has_governance_warnings: bool | None = None,
        received_at_from: str | None = None,
        received_at_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        rows = list_augmentation_submissions_cross_accession(
            self._config,
            submission_id=submission_id,
            accession_number=accession_number,
            producer_id=producer_id,
            layer_type=layer_type,
            schema_version=schema_version,
            lifecycle_state=lifecycle_state,
            has_governance_warnings=has_governance_warnings,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            limit=limit,
        )
        return [
            {
                "submission_id": row.submission_id,
                "received_at": row.received_at,
                "producer_id": row.producer_id,
                "layer_type": row.layer_type,
                "schema_version": row.schema_version,
                "producer_run_id": row.producer_run_id,
                "pipeline_id": row.pipeline_id,
                "model_id": row.model_id,
                "producer_version": row.producer_version,
                "raw_request_path": row.raw_request_path,
                "item_count_total": row.item_count_total,
                "accession_count": row.accession_count,
                "warning_item_count": row.warning_item_count,
                "lifecycle_state": row.lifecycle_state,
            }
            for row in rows
        ]

    def get_augmentation_submission_detail(
        self,
        *,
        submission_id: str,
    ) -> dict[str, object]:
        row = get_augmentation_submission_detail(self._config, submission_id=submission_id)
        return {
            "submission_id": row.submission_id,
            "received_at": row.received_at,
            "producer_id": row.producer_id,
            "layer_type": row.layer_type,
            "schema_version": row.schema_version,
            "producer_run_id": row.producer_run_id,
            "pipeline_id": row.pipeline_id,
            "model_id": row.model_id,
            "producer_version": row.producer_version,
            "raw_request_path": row.raw_request_path,
            "item_count_total": row.item_count_total,
            "accession_count": row.accession_count,
            "warning_item_count": row.warning_item_count,
            "lifecycle_state": row.lifecycle_state,
        }

    def list_submission_lifecycle_events(
        self,
        *,
        submission_id: str,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        rows = self.list_augmentation_events(
            submission_id=submission_id,
            event_family=EVENT_FAMILY_LIFECYCLE,
            limit=limit,
        )
        return [
            {
                "event_time": row.get("event_time"),
                "lifecycle_event_id": row.get("event_id"),
                "submission_id": row.get("submission_id"),
                "from_state": row.get("from_state"),
                "to_state": row.get("to_state"),
                "reason": row.get("reason"),
                "changed_by": row.get("changed_by"),
                "source": row.get("source"),
            }
            for row in rows
        ]

    def list_submission_overlay_impact(
        self,
        *,
        submission_id: str,
        accession_numbers: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        rows = list_submission_overlay_impact(
            self._config,
            submission_id=submission_id,
            accession_numbers=accession_numbers,
            limit=limit,
        )
        contributing = len([row for row in rows if row.contributes_to_resolved_overlay])
        return {
            "submission_id": submission_id,
            "selection_policy": "latest_per_producer_layer_v1",
            "affected_accession_count": len(rows),
            "contributing_accession_count": contributing,
            "non_contributing_accession_count": len(rows) - contributing,
            "rows": [
                {
                    "accession_number": row.accession_number,
                    "producer_id": row.producer_id,
                    "layer_type": row.layer_type,
                    "submission_id": row.submission_id,
                    "lifecycle_state": row.lifecycle_state,
                    "contributes_to_resolved_overlay": row.contributes_to_resolved_overlay,
                    "winning_submission_id": row.winning_submission_id,
                    "reason_code": row.reason_code,
                    "reason_message": row.reason_message,
                }
                for row in rows
            ],
        }

    def list_submission_entity_impact(
        self,
        *,
        submission_id: str,
        accession_numbers: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        entity_index_present, rows = list_submission_entity_impact(
            self._config,
            submission_id=submission_id,
            accession_numbers=accession_numbers,
            limit=limit,
        )
        accession_count = len({row.accession_number for row in rows})
        return {
            "submission_id": submission_id,
            "entity_index_present": bool(entity_index_present),
            "row_count": len(rows),
            "accession_count": accession_count,
            "rows": [
                {
                    "accession_number": row.accession_number,
                    "entity_text": row.entity_text,
                    "entity_normalized": row.entity_normalized,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "filing_cik": row.filing_cik,
                    "form_type": row.form_type,
                    "filing_date": row.filing_date,
                }
                for row in rows
            ],
        }

    def get_submission_review_bundle(
        self,
        *,
        submission_id: str,
        overlay_limit: int = 50,
        entity_limit: int = 50,
        lifecycle_limit: int = 50,
        governance_limit: int = 50,
    ) -> dict[str, object]:
        return get_submission_review_bundle(
            self._config,
            submission_id=submission_id,
            overlay_limit=overlay_limit,
            entity_limit=entity_limit,
            lifecycle_limit=lifecycle_limit,
            governance_limit=governance_limit,
        )

    def record_submission_lifecycle_transition(
        self,
        *,
        submission_id: str,
        to_state: str,
        reason: str | None = None,
        changed_by: str | None = None,
        source: str | None = None,
    ) -> dict[str, object]:
        event = record_submission_lifecycle_transition(
            self._config,
            submission_id=submission_id,
            to_state=to_state,
            reason=reason,
            changed_by=changed_by,
            source=source,
        )
        build_augmentation_entity_index(self._config)
        return event

    def search_filings(
        self,
        *,
        entity_text: str | None = None,
        entity_normalized: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        cik: str | None = None,
        form_type: str | None = None,
        filing_date_from: str | None = None,
        filing_date_to: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        return search_filings_by_entity_index(
            self._config,
            entity_text=entity_text,
            entity_normalized=entity_normalized,
            entity_type=entity_type,
            entity_id=entity_id,
            cik=cik,
            form_type=form_type,
            filing_date_from=filing_date_from,
            filing_date_to=filing_date_to,
            limit=limit,
        )

    def ingest_augmentation_submission(
        self,
        *,
        producer_id: str,
        layer_type: str,
        schema_version: str,
        producer_run_id: str | None,
        pipeline_id: str | None,
        model_id: str | None,
        producer_version: str | None,
        items: list[dict[str, object]],
        raw_request: dict[str, object],
    ) -> AugmentationSubmissionPersistResult:
        resolved_items: list[dict[str, object]] = []
        for item in items:
            accession_number = parse_accession_number(str(item.get("accession_number") or ""))
            identity = resolve_filing_identity(self._config, accession_number)
            if identity is None:
                raise LookupError(
                    f"Accession {accession_number} was not found in local lookup or merged index metadata."
                )
            resolved_items.append(
                {
                    "accession_number": accession_number,
                    "augmentation_type": item.get("augmentation_type"),
                    "payload": item.get("payload") or {},
                    "payload_schema_version": item.get("payload_schema_version"),
                    "filename": item.get("filename") or identity.filename,
                    "filing_cik": item.get("filing_cik") or identity.filing_cik,
                    "form_type": item.get("form_type") or identity.form_type,
                    "filing_date": item.get("filing_date") or identity.filing_date,
                }
            )

        result = persist_augmentation_submission(
            self._config,
            producer_id=producer_id,
            layer_type=layer_type,
            schema_version=schema_version,
            producer_run_id=producer_run_id,
            pipeline_id=pipeline_id,
            model_id=model_id,
            producer_version=producer_version,
            items=resolved_items,
            raw_request=raw_request,
        )
        build_augmentation_entity_index(self._config)
        return result
