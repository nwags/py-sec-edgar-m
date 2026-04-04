# TARGET_ARCHITECTURE.md

## Goal

Turn `py-sec-edgar` into a resumable EDGAR ingestion engine optimized for special situations and insider-signal discovery.

## Target package layout

```text
py_sec_edgar/
  cli.py
  config.py
  http.py
  rate_limit.py
  models.py
  index_loader.py
  filters.py
  downloader.py
  extractor.py
  api/
    __init__.py
    app.py
    models.py
    service.py
  refdata/
    __init__.py
    sources.py
    builder.py
    normalize.py
    schema.py
  pipelines/
    backfill.py
    refdata_refresh.py
  storage/
    paths.py
    writes.py
```

## Execution model

### Stage 1: Reference data refresh
Fetch and normalize official SEC association files and selected SEC datasets into versioned local files.

### Stage 2: Index ingestion
Download and parse EDGAR full-index and optionally daily-index files into a unified parquet dataset.

### Stage 3: Candidate selection
Filter index rows by:
- form family,
- date range,
- issuer CIKs,
- entity CIKs,
- ticker lists,
- custom predicates.

Normalized parquet refdata under `refdata/normalized/` is the authoritative lookup source for ticker/CIK/entity resolution in this stage.

### Stage 4: Download
Use a bounded `ThreadPoolExecutor` for filing downloads.
This stage is I/O-bound and must be globally rate-limited.

### Stage 5: Extract / parse
If enabled, use a separate CPU-oriented stage for parsing or extracting document sections.
This can remain serial initially and later move to `ProcessPoolExecutor` if profiling justifies it.

### Stage 6: API local-first serving
Expose a metadata-first API layer over existing local artifacts:
- lookup by accession through local lookup/index metadata,
- serve local submission content first,
- on local miss, fetch from SEC and persist into the existing cache layout so subsequent requests are local hits.

Resolution semantics are accession-centered and explicit:
- canonical filing key: `accession_number`,
- metadata surface order: `local_lookup_filings` then merged index metadata,
- canonical remote content surface: SEC Archives submission `.txt`.

### Stage 7: Feed-driven monitoring + cache warming
Run feed-aware polling to detect new candidate filings, warm local cache in canonical mirror paths, and update lookup visibility when local artifacts changed (incremental registration by default, full refresh fallback only when incremental is unsafe/incomplete).
Monitoring state and event history should remain operationally coherent so reported actions match persisted artifacts.

### Stage 7.5: Feed-plus-index reconciliation
Provide one-shot reconciliation between feed visibility, merged-index visibility, and local cache presence for bounded windows, with durable discrepancy/event artifacts and optional catch-up warming into canonical mirror paths.
Canonical warm targets should resolve to raw submission `.txt` paths when deterministically derivable from feed/index context.
Catch-up should stay operator-safe by default: attempt only strong canonical targets, and persist explicit skip reasons for weak candidates.

### Stage 8: Portable service runtime wrapper
Provide optional runtime scaffolding for long-running API and monitor worker processes via one shared service image and compose wiring, while preserving host-native execution paths and storage semantics.
Service runtime should emit machine-readable startup/iteration summaries and use advisory single-instance locking for monitor-loop safety on shared storage.
Operator-facing long-running commands should provide stderr heartbeat/progress in human mode, support optional compact NDJSON progress telemetry on stderr for machine parsing, and preserve clean Ctrl+C interruption handling without traceback and stable final summary JSON on stdout.

### Stage 9: External augmentation sidecars (authenticated ingestion, optional overlay reads)
Support external augmentation producers without mutating canonical filing storage:
- authenticated operator write surface for augmentation submissions keyed by `accession_number`,
- additive sidecar persistence for submission metadata and payload rows,
- separate read views:
  - raw history view for operator/audit (`/filings/{accession_number}/augmentations`),
  - resolved deterministic overlay view for consumers (`/filings/{accession_number}/overlay`),
  - submission-summary view for reviewer/producer comparison (`/filings/{accession_number}/augmentation-submissions`),
  - generalized event inspection views (`/augmentations/events`, `/filings/{accession_number}/events`),
  - generalized grouped event summary (`/augmentations/events/summary`),
  - cross-accession reviewer submission query (`/augmentations/submissions`),
  - reviewer submission detail/lifecycle reads (`/augmentations/submissions/{submission_id}`, lifecycle compatibility alias `/augmentations/submissions/{submission_id}/lifecycle-events`),
  - reviewer/operator impact/export reads (`/augmentations/submissions/{submission_id}/overlay-impact`, `/augmentations/submissions/{submission_id}/entity-impact`, `/augmentations/submissions/{submission_id}/review-bundle`),
- clear lineage fields for producer/run/version provenance.

Correction note:
- prior governance-specific endpoint emphasis was too narrow and is replaced by the generalized event model above as the primary read contract.

Resolved overlay policy (`latest_per_producer_layer_v1`):
- group candidate rows by `(producer_id, layer_type)`,
- select winning submission per group by `received_at DESC`, tie-break `submission_id ASC`,
- include all item rows from each selected submission,
- return rows in deterministic order: `producer_id ASC`, `layer_type ASC`, `received_at DESC`, `submission_id ASC`, `item_index ASC`.

Governance layer:
- code-backed advisory contract registry (`augmentation_family_conventions_v1`) for augmentation families,
- non-blocking ingestion checks emit warning codes/events without rejecting otherwise valid submissions,
- governance events persist in normalized audit artifact (`augmentation_governance_events.parquet`) and are not canonical augmentation data.
- governance summary reads are deterministic derived aggregations over governance events (no mutable summary state).
- reviewer export/read bundles remain compact and bounded by default; they are read-side projections and do not introduce new canonical storage.

Submission lifecycle layer:
- lifecycle states are explicit machine-facing values: `active`, `superseded`, `withdrawn`, `disabled`,
- lifecycle transitions are append-only events (`augmentation_submission_lifecycle_events.parquet`),
- lifecycle current state is derived from append-only events (default `active` when no lifecycle events exist),
- raw augmentation history is unchanged by lifecycle transitions,
- resolved overlay selection is lifecycle-aware and considers only eligible active submissions.
- lifecycle is operational control metadata and is not an approval status model.

Out of scope for this stage: in-repo tagging model logic, full ontology/entity-graph systems, and multi-tenant auth/permissions.

### Stage 10: Entity-aware filing search (derived resolved-overlay index)
Add a rebuildable derived entity index for filing search without changing canonical filing storage or ingestion contracts:
- derived artifact: `augmentation_entity_index.parquet`,
- source data: resolved overlay winners (`latest_per_producer_layer_v1`) with lifecycle eligibility (`active`),
- entity extraction scope: `entity_mentions` and `entity_links` families only,
- search surface: filing-level query returning distinct `accession_number` results with deterministic ordering.

Out of scope for this stage: temporal-expression search, ontology/graph resolution, fuzzy matching, and background indexing workers.

## Storage model

### Raw SEC mirror
Mirror the SEC archive layout for downloaded complete submissions.

### Normalized metadata
Maintain separate normalized tables under `refdata/normalized/`:

- `issuers.parquet`
- `entities.parquet`
- `entity_aliases.parquet`
- `filing_parties.parquet`
- `series_classes.parquet`
- `reference_file_manifest.parquet`

`reference_file_manifest.parquet` is canonical and must include source file hashes and provenance metadata.

### API lookup/caching artifacts
API lookup and serving should reuse existing storage conventions:
- merged index parquet,
- lookup parquet (`local_lookup_filings.parquet`, `local_lookup_artifacts.parquet`),
- raw SEC mirror under `.sec_cache/Archives/...`,
- extracted artifact directories beside submissions.
- filing-resolution provenance artifact under normalized root (`filing_resolution_provenance.parquet`).
- augmentation sidecar artifacts under normalized root:
  - `augmentation_submissions.parquet`
  - `augmentation_items.parquet`
  - `augmentation_governance_events.parquet`
  - `augmentation_submission_lifecycle_events.parquet`
  - `augmentation_entity_index.parquet` (derived/rebuildable)
  - raw request JSON under `augmentation_raw_requests/`.

Canonical filing payloads must remain immutable; augmentation data is additive only.

### SEC source/surface authority
Maintain explicit SEC provider/surface registry metadata under normalized refdata (`sec_source_surfaces.parquet`) with:
- provider id/type,
- surface id/name/base URL,
- retrieval capability flags (historical/recent discovery, metadata resolution, content retrieval),
- retrieval priority,
- auth/rate-limit/fair-access notes and operational caveats.

## Concurrency rules

- Never allow unbounded parallelism.
- Use one shared rate limiter for the whole process.
- Default total request rate must stay comfortably below SEC’s published maximum.
- Make worker count configurable independently from request rate.

## HTTP rules

- Use one declared SEC-compliant `User-Agent`.
- Reuse `requests.Session`.
- Retry only on transient failures.
- Treat 403, 404, 429, and 5xx explicitly.
- Do not save error pages as filings.

## Configuration rules

Replace ad hoc globals with a typed config object that includes:

- `user_agent`
- `request_timeout_connect`
- `request_timeout_read`
- `max_requests_per_second`
- `download_workers`
- `extract_workers`
- `download_root`
- `refdata_root`
- `index_start_date`
- `index_end_date`
- `forms`
- `extract_filing_contents`

## Compatibility policy

Backward compatibility is nice but optional.
Correctness, observability, and the new data model matter more.
