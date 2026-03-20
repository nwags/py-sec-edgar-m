from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class FilingMetadataResponse(BaseModel):
    accession_number: str
    filing_cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    filename: str | None = None
    submission_path: str | None = None
    local_content_available: bool
    metadata_source: str | None = None

