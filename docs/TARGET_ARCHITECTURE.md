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
