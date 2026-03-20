from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from py_sec_edgar.api.models import FilingMetadataResponse, HealthResponse
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

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="py-sec-edgar-api")

    @app.get("/filings/{accession_number}", response_model=FilingMetadataResponse)
    async def get_filing_metadata(accession_number: str) -> FilingMetadataResponse:
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
        return FilingMetadataResponse(
            accession_number=metadata.accession_number,
            filing_cik=metadata.filing_cik,
            form_type=metadata.form_type,
            filing_date=metadata.filing_date,
            filename=metadata.filename,
            submission_path=str(canonical_path) if canonical_path is not None else metadata.submission_path,
            local_content_available=bool(local_path is not None),
            metadata_source=metadata.metadata_source,
        )

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
