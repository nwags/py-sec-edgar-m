# REFDATA_SCHEMA.md

## Why the old schema is insufficient

`cik_tickers.csv` assumes the world is made of listed issuers with tickers.
That fails for many EDGAR actors that matter for 13D/G, 13F, Form 4, tender offers, activist campaigns, SPVs, insiders, funds, and acquirers.

## Canonical normalized tables

### issuers
Publicly relevant issuers.

Suggested columns:
- `issuer_cik`
- `ticker`
- `issuer_name`
- `exchange`
- `sic`
- `is_mutual_fund`
- `is_etf`
- `source`
- `source_updated_at`

### entities
All EDGAR filing entities, including non-ticker actors.

Suggested columns:
- `entity_cik`
- `entity_name`
- `entity_type`
- `has_ticker`
- `ticker`
- `is_individual`
- `is_fund`
- `is_manager`
- `is_issuer`
- `source`
- `source_updated_at`

### entity_aliases
Name harmonization table.

Suggested columns:
- `entity_cik`
- `alias_name`
- `alias_type`
- `normalized_alias`
- `source`

### series_classes
Fund / series / class mappings.

Suggested columns:
- `fund_cik`
- `series_id`
- `series_name`
- `class_id`
- `class_name`
- `class_ticker`
- `source`

### sec_source_surfaces
SEC provider/surface registry authority used for explicit source/surface-aware resolution behavior.

Suggested columns:
- `provider_id`
- `provider_type`
- `surface_id`
- `surface_name`
- `base_url`
- `auth_model`
- `supports_historical_discovery`
- `supports_recent_discovery`
- `supports_metadata_resolution`
- `supports_content_retrieval`
- `content_fetch_canonical`
- `metadata_only`
- `retrieval_priority`
- `rate_limit_notes`
- `fair_access_notes`
- `operational_caveats`

### augmentation_submissions
Operator-ingested augmentation submission metadata (sidecar run authority).

Suggested columns:
- `submission_id`
- `received_at`
- `producer_id`
- `layer_type`
- `schema_version`
- `producer_run_id`
- `pipeline_id`
- `model_id`
- `producer_version`
- `item_count`
- `raw_request_path`

### augmentation_items
Per-item augmentation payload rows keyed by canonical filing join key.

Suggested columns:
- `submission_id`
- `item_index`
- `received_at`
- `accession_number`
- `filename`
- `filing_cik`
- `form_type`
- `filing_date`
- `producer_id`
- `layer_type`
- `schema_version`
- `augmentation_type`
- `payload_schema_version`
- `payload_json`

Contracts:
- `accession_number` is the canonical augmentation join key,
- canonical filing content is never mutated or duplicated,
- sidecar rows are additive and lineage-friendly for joins with `filing_resolution_provenance.parquet`.
- raw history retrieval and resolved overlay selection are distinct read views over the same sidecar artifacts.
- lifecycle state affects resolved overlay eligibility but does not remove history rows.

Resolved overlay conventions:
- selection policy id: `latest_per_producer_layer_v1`
- grouping key: `(producer_id, layer_type)`
- winning submission order: `received_at DESC`, tie-break `submission_id ASC`
- selected rows: all rows from each winning submission
- output order: `producer_id ASC`, `layer_type ASC`, `received_at DESC`, `submission_id ASC`, `item_index ASC`

Lightweight augmentation family conventions (guidance, not rigid schema validation):
- `entity_mentions`: span/text mentions with entity labels and optional confidence.
- `entity_links`: mention-to-entity identifiers/aliases with optional resolution confidence.
- `temporal_expressions`: normalized time/date expressions with source spans.
- `event_spans`: trigger/argument spans for event-oriented labels.
- `document_labels`: document-level classifications/scores/tags.

Conventions:
- canonical filing linkage and producer lineage fields stay in sidecar columns,
- family-specific semantics remain in `payload_json`,
- preferred naming pattern is snake_case for `layer_type` and `augmentation_type`.

### augmentation_governance_events
Advisory governance events emitted at ingestion time (audit-oriented only).

Suggested columns:
- `event_time`
- `contract_version_id`
- `submission_id`
- `item_index`
- `accession_number`
- `producer_id`
- `layer_type`
- `augmentation_type`
- `schema_version`
- `family_id`
- `family_inferred`
- `match_status`
- `warning_codes_json`
- `warning_messages_json`

Contracts:
- warning codes are stable machine-facing identifiers,
- governance warnings never invalidate otherwise core-valid augmentation submissions,
- this artifact is not canonical augmentation payload data and should be used for audit/review diagnostics.
- governance summary surfaces are derived deterministically from this append-oriented artifact; no mutable summary table is introduced.
- reviewer export bundles may include bounded governance summaries/details derived from this artifact without creating additional canonical storage artifacts.

Stable warning codes:
- `gov_unknown_family`
- `gov_layer_type_mismatch`
- `gov_augmentation_type_mismatch`
- `gov_missing_recommended_payload_keys`

### augmentation_submission_lifecycle_events
Append-only lifecycle transition events for augmentation submissions.

Suggested columns:
- `event_time`
- `lifecycle_event_id`
- `submission_id`
- `from_state`
- `to_state`
- `reason`
- `changed_by`
- `source`

Stable lifecycle states:
- `active`
- `superseded`
- `withdrawn`
- `disabled`

Contracts:
- lifecycle changes are additive events and do not rewrite submission/item history,
- current lifecycle state is derived from append-only events (default `active` when no event exists),
- resolved overlays consider only lifecycle-eligible submissions (currently `active`),
- lifecycle artifact is audit/control metadata, not canonical augmentation payload data.
- lifecycle is not an approval or sign-off model; approval semantics are intentionally separate/out of scope.

### generalized augmentation event read model (service-layer)
Primary API/CLI event queries are served from a logical unified stream built over existing append-only artifacts:

- `augmentation_governance_events.parquet`
- `augmentation_submission_lifecycle_events.parquet`

Canonical logical fields:

- `event_family` (`governance`, `lifecycle`)
- `event_type`
- `event_source`
- `event_time`
- `event_id` (deterministic)
- `submission_id`
- `accession_numbers` (sorted, deduplicated)
- `producer_id`
- `layer_type`

Deterministic event id contract:

- lifecycle rows: `event_id = lifecycle_event_id`
- governance rows: `event_id = event_time|submission_id|item_index|accession_number|producer_id|layer_type|augmentation_type|schema_version|contract_version_id`

Primary query ordering contract:

1. `event_time DESC`
2. `event_family ASC`
3. `event_id ASC`

Compatibility note:

- governance-specific routes remain transition aliases; the generalized event model is the primary contract.

### augmentation_entity_index
Derived filing-search index over resolved overlay winners for entity families.

Suggested columns:
- `accession_number`
- `submission_id`
- `producer_id`
- `layer_type`
- `augmentation_type`
- `entity_text`
- `entity_type`
- `entity_id`
- `entity_normalized`
- `received_at`
- `filing_cik`
- `form_type`
- `filing_date`

Contracts:
- derived/rebuildable only; not canonical filing payload storage,
- source universe is lifecycle-eligible resolved overlays (winner policy `latest_per_producer_layer_v1`),
- current indexed families are `entity_mentions` and `entity_links`,
- temporal sidecars remain available in history/overlay but are not part of entity search in this phase.
- rebuild remains deterministic for the same sidecar+lifecycle inputs.
- reviewer/operator entity-impact reads are derived from this artifact only and do not modify index rebuild semantics.

### filing_parties
Relationship table between a filing and the relevant actors.

Suggested columns:
- `accession_number`
- `form_type`
- `filing_date`
- `party_role`
- `party_cik`
- `party_name`
- `issuer_cik`
- `issuer_name`
- `source`
- `source_filename`

Initial extraction foundation (current scope):
- supported forms: `SC 13D`, `SC 13D/A`, `SC 13G`, `SC 13G/A`, `3`, `4`, `5`
- currently emitted roles: `subject_company`, `issuer`, `reporting_owner`, `director`, `officer`, `ten_percent_owner`
- identifiers should use canonical normalization where available (e.g., zero-padded CIK)
- unsupported forms should emit no filing-party rows rather than unreliable inferred rows

Persistence contract:
- canonical normalized artifact: `refdata/normalized/filing_parties.parquet`
- upsert/dedupe key: `accession_number`, `party_role`, `party_cik`, `party_name`, `source_filename`
- writes must be deterministic and idempotent across repeated backfill runs

## Entity roles we care about

- issuer
- reporting_owner
- beneficial_owner
- filer
- subject_company
- offeror
- acquiring_person
- manager
- other_included_manager
- insider
- director
- officer

## Reference-file precedence

1. official SEC ticker / exchange / mutual-fund association files
2. SEC `ticker.txt`
3. SEC current all-CIK text file
4. investment company series/class CSV
5. historical EDGAR index-derived entity discovery
6. parsed filing-party extraction

## Output format preference

Use parquet for normalized tables.
CSV exports are optional convenience outputs, not canonical storage.

## Filtering contract

Runtime candidate filtering should resolve identifiers from normalized parquet tables under `refdata/normalized/`.
Use canonical normalized keys only:

- `issuers.issuer_cik` (zero-padded 10-digit CIK)
- `issuers.ticker` (uppercase ticker)
- `entities.entity_cik` (zero-padded 10-digit CIK)

Legacy ticker-list inputs can be accepted as a compatibility bridge, but they must resolve through these canonical parquet keys rather than through `cik_tickers.csv`.
