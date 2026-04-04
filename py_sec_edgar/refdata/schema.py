ISSUERS_COLUMNS = [
    "issuer_cik",
    "ticker",
    "issuer_name",
    "exchange",
    "sic",
    "is_mutual_fund",
    "is_etf",
    "source",
    "source_updated_at",
    "issuer_cik_raw",
    "ticker_raw",
]

ENTITIES_COLUMNS = [
    "entity_cik",
    "entity_name",
    "entity_type",
    "has_ticker",
    "ticker",
    "is_individual",
    "is_fund",
    "is_manager",
    "is_issuer",
    "source",
    "source_updated_at",
    "entity_cik_raw",
    "ticker_raw",
]

ENTITY_ALIASES_COLUMNS = [
    "entity_cik",
    "alias_name",
    "alias_type",
    "normalized_alias",
    "source",
]

SERIES_CLASSES_COLUMNS = [
    "fund_cik",
    "series_id",
    "series_name",
    "class_id",
    "class_name",
    "class_ticker",
    "source",
    "fund_cik_raw",
    "class_ticker_raw",
]

REFERENCE_FILE_MANIFEST_COLUMNS = [
    "filename",
    "source_url",
    "sha256",
    "file_size_bytes",
    "mtime_utc",
    "ingested_at_utc",
    "source_type",
    "schema_version",
]

SEC_SOURCE_SURFACES_COLUMNS = [
    "provider_id",
    "provider_type",
    "surface_id",
    "surface_name",
    "base_url",
    "auth_model",
    "supports_historical_discovery",
    "supports_recent_discovery",
    "supports_metadata_resolution",
    "supports_content_retrieval",
    "content_fetch_canonical",
    "metadata_only",
    "retrieval_priority",
    "rate_limit_notes",
    "fair_access_notes",
    "operational_caveats",
]
