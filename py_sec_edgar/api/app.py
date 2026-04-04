from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from py_sec_edgar.api.models import (
    AugmentationUnifiedEventsResponse,
    AugmentationUnifiedEventsSummaryResponse,
    AugmentationSubmissionDetailResponse,
    AugmentationSubmissionLifecycleTransitionRequest,
    AugmentationSubmissionLifecycleTransitionResponse,
    AugmentationSubmissionRequest,
    CrossAccessionAugmentationSubmissionsResponse,
    FilingSearchResponse,
    FilingAugmentationSubmissionsResponse,
    AugmentationSubmissionResponse,
    FilingAugmentationsResponse,
    SubmissionEntityImpactResponse,
    FilingMetadataResponse,
    FilingResolvedOverlayResponse,
    GovernanceEventsResponse,
    GovernanceSummaryResponse,
    HealthResponse,
    SubmissionOverlayImpactResponse,
    SubmissionReviewBundleResponse,
    SubmissionLifecycleEventsResponse,
)
from py_sec_edgar.api.service import (
    FilingRetrievalService,
    RetrievalDecision,
)
from py_sec_edgar.config import AppConfig, load_config


def create_app(
    config: AppConfig | None = None,
    *,
    retrieval_service: FilingRetrievalService | None = None,
) -> FastAPI:
    runtime_config = config or load_config()
    service = retrieval_service or FilingRetrievalService(runtime_config)

    app = FastAPI(
        title="py-sec-edgar API",
        version="0.1.0",
        description=(
            "Local-first API scaffold for filing metadata lookup and filing content "
            "retrieval over the existing py-sec-edgar storage model."
        ),
    )
    app.state.config = runtime_config
    app.state.retrieval_service = service

    class ApiContractError(Exception):
        def __init__(
            self,
            *,
            status_code: int,
            code: str,
            message: str,
            details: dict[str, object] | None = None,
        ) -> None:
            super().__init__(message)
            self.status_code = int(status_code)
            self.code = str(code)
            self.message = str(message)
            self.details = details or {}

    @app.exception_handler(ApiContractError)
    async def _api_contract_error_handler(_, exc: ApiContractError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    def _require_admin_api_key(x_api_key: str | None) -> None:
        expected = runtime_config.augmentation_ingest_api_key
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="Augmentation ingestion is disabled: operator API key is not configured.",
            )
        if x_api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    def _model_dump(model) -> dict[str, object]:
        if hasattr(model, "model_dump"):
            return model.model_dump()  # pydantic v2
        return model.dict()  # pragma: no cover (v1 compatibility)

    def _error_detail(exc: Exception, *, default_code: str) -> dict[str, str]:
        code = getattr(exc, "code", None)
        return {
            "code": str(code or default_code),
            "message": str(exc),
        }

    def _raise_contract_error(
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        raise ApiContractError(
            status_code=status_code,
            code=code,
            message=message,
            details=details,
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="py-sec-edgar-api")

    @app.get(
        "/filings/search",
        response_model=FilingSearchResponse,
        response_model_exclude_none=True,
    )
    async def search_filings(
        entity_text: str | None = Query(default=None),
        entity_normalized: str | None = Query(default=None),
        entity_type: str | None = Query(default=None),
        entity_id: str | None = Query(default=None),
        cik: str | None = Query(default=None),
        form_type: str | None = Query(default=None),
        filing_date_from: str | None = Query(default=None),
        filing_date_to: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=0),
    ) -> FilingSearchResponse:
        try:
            rows = service.search_filings(
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
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FilingSearchResponse(results=rows)

    @app.get(
        "/filings/{accession_number}",
        response_model=FilingMetadataResponse,
        response_model_exclude_none=True,
    )
    async def get_filing_metadata(
        accession_number: str,
        include_augmentations: bool = Query(default=False),
        augmentation_view: str = Query(default="history"),
    ) -> FilingMetadataResponse:
        try:
            metadata = service.find_filing_metadata(accession_number)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if metadata is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Filing metadata was not found in local lookup or merged index metadata."
                ),
            )
        local_path = service.resolve_local_submission_path(metadata)
        canonical_path = service.resolve_canonical_submission_path(metadata)
        augmentations = None
        if include_augmentations:
            if augmentation_view == "history":
                augmentations = service.list_augmentations_for_accession(accession_number)
            elif augmentation_view == "resolved":
                resolved = service.resolve_overlay_for_accession(accession_number)
                augmentations = resolved["augmentations"]
            else:
                raise HTTPException(
                    status_code=422,
                    detail="augmentation_view must be one of: history, resolved.",
                )
        return FilingMetadataResponse(
            accession_number=metadata.accession_number,
            filing_cik=metadata.filing_cik,
            form_type=metadata.form_type,
            filing_date=metadata.filing_date,
            filename=metadata.filename,
            submission_path=str(canonical_path) if canonical_path is not None else metadata.submission_path,
            local_content_available=bool(local_path is not None),
            metadata_source=metadata.metadata_source,
            metadata_surface=metadata.metadata_surface,
            augmentations=augmentations,
        )

    @app.get(
        "/filings/{accession_number}/augmentations",
        response_model=FilingAugmentationsResponse,
        response_model_exclude_none=True,
    )
    async def get_filing_augmentations(
        accession_number: str,
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        augmentation_type: str | None = Query(default=None),
        schema_version: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        include_submission_metadata: bool = Query(default=False),
        lifecycle_state: str | None = Query(default=None),
        submission_id: str | None = Query(default=None),
        latest_submission_only: bool = Query(default=False),
        limit: int | None = Query(default=None, ge=0),
    ) -> FilingAugmentationsResponse:
        try:
            metadata = service.find_filing_metadata(accession_number)
            if metadata is None:
                raise HTTPException(
                    status_code=404,
                    detail="Filing metadata was not found in local lookup or merged index metadata.",
                )
            augmentations = service.list_augmentations_for_accession(
                accession_number,
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
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FilingAugmentationsResponse(
            accession_number=accession_number,
            augmentations=augmentations,
        )

    @app.get(
        "/filings/{accession_number}/overlay",
        response_model=FilingResolvedOverlayResponse,
        response_model_exclude_none=True,
    )
    async def get_filing_overlay(
        accession_number: str,
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        augmentation_type: str | None = Query(default=None),
        schema_version: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        include_submission_metadata: bool = Query(default=False),
        lifecycle_state: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=0),
    ) -> FilingResolvedOverlayResponse:
        try:
            metadata = service.find_filing_metadata(accession_number)
            if metadata is None:
                raise HTTPException(
                    status_code=404,
                    detail="Filing metadata was not found in local lookup or merged index metadata.",
                )
            resolved = service.resolve_overlay_for_accession(
                accession_number,
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
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return FilingResolvedOverlayResponse(
            accession_number=accession_number,
            selection_policy=resolved["selection_policy"],
            selected_submission_keys=resolved["selected_submission_keys"],
            augmentations=resolved["augmentations"],
        )

    @app.get(
        "/filings/{accession_number}/augmentation-submissions",
        response_model=FilingAugmentationSubmissionsResponse,
        response_model_exclude_none=True,
    )
    async def get_filing_augmentation_submissions(
        accession_number: str,
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        schema_version: str | None = Query(default=None),
        lifecycle_state: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=0),
    ) -> FilingAugmentationSubmissionsResponse:
        try:
            metadata = service.find_filing_metadata(accession_number)
            if metadata is None:
                raise HTTPException(
                    status_code=404,
                    detail="Filing metadata was not found in local lookup or merged index metadata.",
                )
            submissions = service.list_augmentation_submissions_for_accession(
                accession_number,
                producer_id=producer_id,
                layer_type=layer_type,
                schema_version=schema_version,
                lifecycle_state=lifecycle_state,
                received_at_from=received_at_from,
                received_at_to=received_at_to,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FilingAugmentationSubmissionsResponse(
            accession_number=accession_number,
            submissions=submissions,
        )

    @app.get(
        "/augmentations/events",
        response_model=AugmentationUnifiedEventsResponse,
        response_model_exclude_none=True,
    )
    async def get_augmentation_events(
        accession_number: list[str] | None = Query(default=None),
        submission_id: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        event_family: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        event_source: str | None = Query(default=None),
        warning_code: str | None = Query(default=None),
        match_status: str | None = Query(default=None),
        to_state: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        event_time_from: str | None = Query(default=None),
        event_time_to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=0),
    ) -> AugmentationUnifiedEventsResponse:
        try:
            events = service.list_augmentation_events(
                accession_numbers=accession_number,
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
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "submission_not_found")),
                message=str(exc),
                details={"submission_id": submission_id} if submission_id else {},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return AugmentationUnifiedEventsResponse(events=events)

    @app.get(
        "/filings/{accession_number}/events",
        response_model=AugmentationUnifiedEventsResponse,
        response_model_exclude_none=True,
    )
    async def get_filing_events(
        accession_number: str,
        submission_id: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        event_family: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        event_source: str | None = Query(default=None),
        warning_code: str | None = Query(default=None),
        match_status: str | None = Query(default=None),
        to_state: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        event_time_from: str | None = Query(default=None),
        event_time_to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=0),
    ) -> AugmentationUnifiedEventsResponse:
        try:
            metadata = service.find_filing_metadata(accession_number)
            if metadata is None:
                raise LookupError(
                    "Filing metadata was not found in local lookup or merged index metadata."
                )
            events = service.list_augmentation_events(
                accession_numbers=[accession_number],
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
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "not_found")),
                message=str(exc),
                details={"accession_number": accession_number},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return AugmentationUnifiedEventsResponse(events=events)

    @app.get(
        "/augmentations/events/summary",
        response_model=AugmentationUnifiedEventsSummaryResponse,
        response_model_exclude_none=True,
    )
    async def get_augmentation_events_summary(
        accession_number: list[str] | None = Query(default=None),
        submission_id: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        event_family: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        event_source: str | None = Query(default=None),
        warning_code: str | None = Query(default=None),
        match_status: str | None = Query(default=None),
        to_state: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        event_time_from: str | None = Query(default=None),
        event_time_to: str | None = Query(default=None),
        group_by: list[str] | None = Query(default=None),
        limit: int = Query(default=100, ge=0),
    ) -> AugmentationUnifiedEventsSummaryResponse:
        try:
            rows = service.summarize_augmentation_events(
                accession_numbers=accession_number,
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
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "submission_not_found")),
                message=str(exc),
                details={"submission_id": submission_id} if submission_id else {},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return AugmentationUnifiedEventsSummaryResponse(rows=rows)

    # Compatibility alias: filing-scoped governance-only events.
    @app.get(
        "/filings/{accession_number}/governance-events",
        response_model=GovernanceEventsResponse,
        response_model_exclude_none=True,
    )
    async def get_filing_governance_events(
        accession_number: str,
        submission_id: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        warning_code: str | None = Query(default=None),
        family_id: str | None = Query(default=None),
        match_status: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        event_time_from: str | None = Query(default=None),
        event_time_to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=0),
    ) -> GovernanceEventsResponse:
        try:
            events = service.list_governance_events(
                accession_number=accession_number,
                submission_id=submission_id,
                producer_id=producer_id,
                layer_type=layer_type,
                warning_code=warning_code,
                family_id=family_id,
                match_status=match_status,
                received_at_from=received_at_from,
                received_at_to=received_at_to,
                event_time_from=event_time_from,
                event_time_to=event_time_to,
                limit=limit,
            )
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "submission_not_found")),
                message=str(exc),
                details={"submission_id": submission_id} if submission_id else {"accession_number": accession_number},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return GovernanceEventsResponse(events=events)

    # Compatibility alias: cross-accession governance-only events.
    @app.get(
        "/augmentations/governance-events",
        response_model=GovernanceEventsResponse,
        response_model_exclude_none=True,
    )
    async def get_governance_events(
        accession_number: str | None = Query(default=None),
        submission_id: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        warning_code: str | None = Query(default=None),
        family_id: str | None = Query(default=None),
        match_status: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        event_time_from: str | None = Query(default=None),
        event_time_to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=0),
    ) -> GovernanceEventsResponse:
        try:
            events = service.list_governance_events(
                accession_number=accession_number,
                submission_id=submission_id,
                producer_id=producer_id,
                layer_type=layer_type,
                warning_code=warning_code,
                family_id=family_id,
                match_status=match_status,
                received_at_from=received_at_from,
                received_at_to=received_at_to,
                event_time_from=event_time_from,
                event_time_to=event_time_to,
                limit=limit,
            )
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "submission_not_found")),
                message=str(exc),
                details={"submission_id": submission_id} if submission_id else {},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return GovernanceEventsResponse(events=events)

    # Compatibility alias: governance summary rows.
    @app.get(
        "/augmentations/governance-events/summary",
        response_model=GovernanceSummaryResponse,
        response_model_exclude_none=True,
    )
    async def get_governance_events_summary(
        accession_number: str | None = Query(default=None),
        submission_id: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        warning_code: str | None = Query(default=None),
        family_id: str | None = Query(default=None),
        match_status: str | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        event_time_from: str | None = Query(default=None),
        event_time_to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=0),
    ) -> GovernanceSummaryResponse:
        try:
            rows = service.summarize_governance_events(
                accession_number=accession_number,
                submission_id=submission_id,
                producer_id=producer_id,
                layer_type=layer_type,
                warning_code=warning_code,
                family_id=family_id,
                match_status=match_status,
                received_at_from=received_at_from,
                received_at_to=received_at_to,
                event_time_from=event_time_from,
                event_time_to=event_time_to,
                limit=limit,
            )
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "submission_not_found")),
                message=str(exc),
                details={"submission_id": submission_id} if submission_id else {},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return GovernanceSummaryResponse(rows=rows)

    @app.get(
        "/augmentations/submissions",
        response_model=CrossAccessionAugmentationSubmissionsResponse,
        response_model_exclude_none=True,
    )
    async def get_cross_accession_augmentation_submissions(
        submission_id: str | None = Query(default=None),
        accession_number: str | None = Query(default=None),
        producer_id: str | None = Query(default=None),
        layer_type: str | None = Query(default=None),
        schema_version: str | None = Query(default=None),
        lifecycle_state: str | None = Query(default=None),
        has_governance_warnings: bool | None = Query(default=None),
        received_at_from: str | None = Query(default=None),
        received_at_to: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=0),
    ) -> CrossAccessionAugmentationSubmissionsResponse:
        try:
            submissions = service.list_augmentation_submissions_cross_accession(
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
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_detail(exc, default_code="invalid_request")) from exc
        return CrossAccessionAugmentationSubmissionsResponse(submissions=submissions)

    @app.get(
        "/augmentations/submissions/{submission_id}",
        response_model=AugmentationSubmissionDetailResponse,
        response_model_exclude_none=True,
    )
    async def get_augmentation_submission_detail(submission_id: str) -> AugmentationSubmissionDetailResponse:
        try:
            submission = service.get_augmentation_submission_detail(submission_id=submission_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc, default_code="not_found")) from exc
        return AugmentationSubmissionDetailResponse(submission=submission)

    @app.get(
        "/augmentations/submissions/{submission_id}/lifecycle-events",
        response_model=SubmissionLifecycleEventsResponse,
        response_model_exclude_none=True,
    )
    async def get_submission_lifecycle_events(
        submission_id: str,
        limit: int | None = Query(default=None, ge=0),
    ) -> SubmissionLifecycleEventsResponse:
        try:
            events = service.list_submission_lifecycle_events(
                submission_id=submission_id,
                limit=limit,
            )
        except LookupError as exc:
            _raise_contract_error(
                status_code=404,
                code=str(getattr(exc, "code", "submission_not_found")),
                message=str(exc),
                details={"submission_id": submission_id},
            )
        except ValueError as exc:
            _raise_contract_error(
                status_code=422,
                code=str(getattr(exc, "code", "invalid_request")),
                message=str(exc),
            )
        return SubmissionLifecycleEventsResponse(submission_id=submission_id, events=events)

    @app.get(
        "/augmentations/submissions/{submission_id}/overlay-impact",
        response_model=SubmissionOverlayImpactResponse,
        response_model_exclude_none=True,
    )
    async def get_submission_overlay_impact(
        submission_id: str,
        accession_number: list[str] | None = Query(default=None),
        limit: int = Query(default=50, ge=0),
    ) -> SubmissionOverlayImpactResponse:
        try:
            payload = service.list_submission_overlay_impact(
                submission_id=submission_id,
                accession_numbers=accession_number,
                limit=limit,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc, default_code="not_found")) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_detail(exc, default_code="invalid_request")) from exc
        return SubmissionOverlayImpactResponse(**payload)

    @app.get(
        "/augmentations/submissions/{submission_id}/entity-impact",
        response_model=SubmissionEntityImpactResponse,
        response_model_exclude_none=True,
    )
    async def get_submission_entity_impact(
        submission_id: str,
        accession_number: list[str] | None = Query(default=None),
        limit: int = Query(default=50, ge=0),
    ) -> SubmissionEntityImpactResponse:
        try:
            payload = service.list_submission_entity_impact(
                submission_id=submission_id,
                accession_numbers=accession_number,
                limit=limit,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc, default_code="not_found")) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_detail(exc, default_code="invalid_request")) from exc
        return SubmissionEntityImpactResponse(**payload)

    @app.get(
        "/augmentations/submissions/{submission_id}/review-bundle",
        response_model=SubmissionReviewBundleResponse,
        response_model_exclude_none=True,
    )
    async def get_submission_review_bundle(
        submission_id: str,
        overlay_limit: int = Query(default=50, ge=0),
        entity_limit: int = Query(default=50, ge=0),
        lifecycle_limit: int = Query(default=50, ge=0),
        governance_limit: int = Query(default=50, ge=0),
    ) -> SubmissionReviewBundleResponse:
        try:
            payload = service.get_submission_review_bundle(
                submission_id=submission_id,
                overlay_limit=overlay_limit,
                entity_limit=entity_limit,
                lifecycle_limit=lifecycle_limit,
                governance_limit=governance_limit,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc, default_code="not_found")) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_detail(exc, default_code="invalid_request")) from exc
        return SubmissionReviewBundleResponse(**payload)

    @app.post(
        "/admin/augmentations/submissions",
        response_model=AugmentationSubmissionResponse,
    )
    async def post_augmentation_submission(
        request: AugmentationSubmissionRequest,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> AugmentationSubmissionResponse:
        _require_admin_api_key(x_api_key)
        if not request.items:
            raise HTTPException(status_code=422, detail="Augmentation submission must include at least one item.")
        try:
            result = service.ingest_augmentation_submission(
                producer_id=request.producer_id,
                layer_type=request.layer_type,
                schema_version=request.schema_version,
                producer_run_id=request.producer_run_id,
                pipeline_id=request.pipeline_id,
                model_id=request.model_id,
                producer_version=request.producer_version,
                items=[_model_dump(item) for item in request.items],
                raw_request=_model_dump(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_detail(exc, default_code="invalid_request")) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc, default_code="not_found")) from exc

        return AugmentationSubmissionResponse(
            submission_id=result.submission_id,
            received_at=result.received_at,
            item_count=result.item_count,
            submissions_path=result.submissions_path,
            items_path=result.items_path,
            raw_request_path=result.raw_request_path,
        )

    @app.post(
        "/admin/augmentations/submissions/{submission_id}/lifecycle",
        response_model=AugmentationSubmissionLifecycleTransitionResponse,
        response_model_exclude_none=True,
    )
    async def post_submission_lifecycle_transition(
        submission_id: str,
        request: AugmentationSubmissionLifecycleTransitionRequest,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> AugmentationSubmissionLifecycleTransitionResponse:
        _require_admin_api_key(x_api_key)
        try:
            event = service.record_submission_lifecycle_transition(
                submission_id=submission_id,
                to_state=request.to_state,
                reason=request.reason,
                changed_by=request.changed_by,
                source=request.source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_detail(exc, default_code="invalid_request")) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc, default_code="not_found")) from exc
        return AugmentationSubmissionLifecycleTransitionResponse(**event)

    @app.get("/filings/{accession_number}/content")
    async def get_filing_content(accession_number: str):
        try:
            result = service.retrieve_filing_content_local_first(accession_number)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if result.decision == RetrievalDecision.NOT_FOUND:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Filing was not found in local lookup/index metadata for this API instance."
                ),
            )
        if result.decision in {
            RetrievalDecision.LOCAL_HIT,
            RetrievalDecision.REMOTE_FETCHED_AND_PERSISTED,
        } and result.local_path is not None:
            data = result.local_path.read_bytes()
            return Response(content=data, media_type="text/plain")
        if result.decision == RetrievalDecision.REMOTE_FETCH_FAILED:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Remote SEC retrieval failed; filing content is unavailable locally.",
                    "reason": result.reason,
                    "status_code": result.status_code,
                    "error": result.error,
                    "error_class": result.error_class,
                    "remote_url": result.remote_url,
                    "local_path": str(result.local_path) if result.local_path is not None else None,
                },
            )
        raise HTTPException(
            status_code=500,
            detail=(
                "Unexpected retrieval result state."
            ),
        )

    return app
