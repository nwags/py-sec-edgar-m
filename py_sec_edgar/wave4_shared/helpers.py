from __future__ import annotations

import hashlib

from py_sec_edgar.config import AppConfig
from py_sec_edgar.filing_resolution import (
    canonical_local_submission_path,
    parse_accession_number,
    resolve_filing_identity,
)
from py_sec_edgar.wave4_shared.models import ProducerTargetDescriptorModel


def deterministic_source_text_version(config: AppConfig, accession_number: str) -> str:
    accession = parse_accession_number(accession_number)
    identity = resolve_filing_identity(config, accession)
    filename = identity.filename if identity is not None else None

    local_path = canonical_local_submission_path(config, filename) if filename else None
    if local_path is not None and local_path.exists() and local_path.is_file():
        digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
        return f"sha256:{digest}"

    fallback_fingerprint = f"sec|filing|{accession}|{filename or ''}|missing_text_source"
    fallback_digest = hashlib.sha256(fallback_fingerprint.encode("utf-8")).hexdigest()
    return f"sha256:{fallback_digest}"


def build_filing_target_descriptor(config: AppConfig, accession_number: str) -> dict[str, object]:
    accession = parse_accession_number(accession_number)
    model = ProducerTargetDescriptorModel(
        domain="sec",
        resource_family="filing",
        canonical_key=accession,
        text_source=f"api:/filings/{accession}/content",
        source_text_version=deterministic_source_text_version(config, accession),
        language="en",
        document_time_reference=None,
        producer_hints={},
    )
    return model.model_dump()
