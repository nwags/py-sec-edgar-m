=====
Usage
=====

Refresh normalized SEC reference data:

.. code-block:: console

    py-sec-edgar refdata refresh

Refdata refresh with runtime visibility and logging:

.. code-block:: console

    py-sec-edgar refdata refresh --verbose --log-level INFO --log-file ./refdata-refresh.log

Quiet refdata refresh (minimal completion line only):

.. code-block:: console

    py-sec-edgar refdata refresh --quiet

Refresh EDGAR full index files:

.. code-block:: console

    py-sec-edgar index refresh

Index refresh with operator-facing progress/logging controls:

.. code-block:: console

    py-sec-edgar index refresh --verbose --log-level INFO --log-file ./run.log

`index refresh` prepares the merged index parquet used by backfill (`refdata/merged_idx_files.pq`).

Run selection-only backfill candidate loading:

.. code-block:: console

    py-sec-edgar backfill --no-execute-downloads

Backfill by issuer ticker:

.. code-block:: console

    py-sec-edgar backfill --issuer-ticker AAPL --no-ticker-list-filter

Backfill by entity CIK:

.. code-block:: console

    py-sec-edgar backfill --entity-cik 0000001234 --no-ticker-list-filter

Backfill by form family and date range:

.. code-block:: console

    py-sec-edgar backfill --form-family beneficial_ownership --date-from 2025-01-01 --date-to 2025-03-31 --no-form-list-filter

Run backfill selection and filing downloads in one command:

.. code-block:: console

    py-sec-edgar backfill --execute-downloads --issuer-ticker AAPL --form 8-K --date-from 2025-01-01 --date-to 2025-01-31

Run backfill selection, downloads, and serial extraction:

.. code-block:: console

    py-sec-edgar backfill --execute-downloads --execute-extraction --issuer-cik 0000320193 --form-family current_reports

Run backfill extraction with filing-party persistence:

.. code-block:: console

    py-sec-edgar backfill --execute-extraction --persist-filing-parties --issuer-cik 0000320193 --form-family beneficial_ownership

When persistence is requested but extraction yields zero filing-party rows, no new
`filing_parties.parquet` artifact is created and no persist path is reported.

Emit machine-readable backfill summary JSON (replaces human-readable summary output):

.. code-block:: console

    py-sec-edgar backfill --summary-json --execute-extraction --persist-filing-parties --issuer-cik 0000320193

Backfill with bounded recent activity output:

.. code-block:: console

    py-sec-edgar backfill --execute-downloads --execute-extraction --verbose

Backfill with minimal human-readable output:

.. code-block:: console

    py-sec-edgar backfill --quiet --execute-downloads

Environment path overrides (config/env-first, no path CLI flags required):

.. code-block:: console

    export PY_SEC_EDGAR_PROJECT_ROOT=/mnt/sec-work
    export PY_SEC_EDGAR_DOWNLOAD_ROOT=/mnt/sec-cache/Archives
    export PY_SEC_EDGAR_MERGED_INDEX_PATH=/mnt/sec-artifacts/merged_idx_files.pq
    export PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT=/mnt/sec-artifacts/refdata/normalized

Runtime visibility/logging flags for working commands:

.. code-block:: console

    py-sec-edgar refdata refresh --verbose --log-level INFO --log-file ./refdata.log
    py-sec-edgar index refresh --verbose --log-level INFO --log-file ./index.log
    py-sec-edgar backfill --verbose --log-level INFO --log-file ./backfill.log

`--summary-json` on backfill emits JSON on stdout for automation.

Query persisted filing-party records:

.. code-block:: console

    py-sec-edgar filing-parties query

Query by issuer CIK:

.. code-block:: console

    py-sec-edgar filing-parties query --issuer-cik 0000123456

Query by role and form type:

.. code-block:: console

    py-sec-edgar filing-parties query --role reporting_owner --form-type SC 13D

Query as machine-readable JSON:

.. code-block:: console

    py-sec-edgar filing-parties query --party-cik 0000999999 --json

Limit filing-party query output:

.. code-block:: console

    py-sec-edgar filing-parties query --limit 10

Select specific output columns:

.. code-block:: console

    py-sec-edgar filing-parties query --role reporting_owner --columns accession_number,party_name,party_role

Limit JSON output:

.. code-block:: console

    py-sec-edgar filing-parties query --json --limit 5

Build local lookup indexes from local artifacts and metadata:

.. code-block:: console

    py-sec-edgar lookup refresh

Build local + merged-index-wide filings lookup indexes:

.. code-block:: console

    py-sec-edgar lookup refresh --include-global-filings

Build lookup indexes with machine-readable summary:

.. code-block:: console

    py-sec-edgar lookup refresh --summary-json

Query local filing lookup rows:

.. code-block:: console

    py-sec-edgar lookup query --cik 0000320193 --form-type SC 13D --date-from 2025-01-01 --date-to 2025-03-31

Query local artifact rows by path substring:

.. code-block:: console

    py-sec-edgar lookup query --scope artifacts --artifact-type extracted --path-contains primary_doc --limit 10

Query lookup output as machine-readable JSON:

.. code-block:: console

    py-sec-edgar lookup query --scope filings --accession-number 0000320193-25-000010 --json

Query merged-index-wide filings lookup (requires global build):

.. code-block:: console

    py-sec-edgar lookup query --scope filings --all --limit 20

Lookup artifacts are written under the configured normalized root:

- `local_lookup_filings.parquet`
- `local_lookup_artifacts.parquet`
- `local_lookup_filings_all.parquet` (only when `--include-global-filings` is used)

API local-first retrieval
-------------------------

The API surface is local-first over existing storage/index artifacts and cache layout.

Create the FastAPI app (factory):

.. code-block:: python

    from py_sec_edgar.api.app import create_app
    app = create_app()

Run with Uvicorn (example):

.. code-block:: console

    uvicorn py_sec_edgar.api.app:create_app --factory --host 0.0.0.0 --port 8000

Current endpoints:

- `GET /health`
- `GET /filings/{accession_number}` (metadata endpoint; returns when lookup or merged-index metadata resolves accession)
- `GET /filings/{accession_number}/content` (local file hit first; local miss triggers SEC fetch + persist to canonical cache mirror path)

Content retrieval contract:

1. check local canonical cache path from filing filename (`<download_root>/<filename>`),
2. if local file exists, serve it directly,
3. if local file is missing and metadata resolves accession, fetch from SEC and persist to canonical path,
4. subsequent requests for that accession are local hits.

Portable service runtime (optional)
-----------------------------------

Host-native CLI/API workflows remain unchanged. Runtime wrapper commands are additive:

.. code-block:: console

    python -m py_sec_edgar.service_runtime api
    python -m py_sec_edgar.service_runtime monitor-once
    python -m py_sec_edgar.service_runtime monitor-loop

Runtime wrapper env controls:

- `PY_SEC_EDGAR_PROJECT_ROOT`
- `PY_SEC_EDGAR_API_HOST`
- `PY_SEC_EDGAR_API_PORT`
- `PY_SEC_EDGAR_MONITOR_INTERVAL_SECONDS`
- `PY_SEC_EDGAR_MONITOR_WARM`
- `PY_SEC_EDGAR_MONITOR_REFRESH_LOOKUP`
- `PY_SEC_EDGAR_MONITOR_FORM_TYPES`
- `PY_SEC_EDGAR_MONITOR_FORM_FAMILIES`
- `PY_SEC_EDGAR_MONITOR_EXECUTE_EXTRACTION`
- `PY_SEC_EDGAR_MONITOR_PERSIST_FILING_PARTIES`
- `PY_SEC_EDGAR_MONITOR_SINGLE_INSTANCE`

`service_runtime` emits stable machine-readable JSON startup summaries with resolved roots/settings.  
`monitor-loop` is continuous, signal-aware, and uses advisory locking by default at:
`<project_root>/.sec_runtime/monitor_loop.lock`.

Monitor poll (one-shot feed-driven warming):

.. code-block:: console

    py-sec-edgar monitor poll --warm --form-family current_reports

Monitor poll with machine-readable summary:

.. code-block:: console

    py-sec-edgar monitor poll --summary-json

Bounded monitor loop:

.. code-block:: console

    py-sec-edgar monitor loop --interval-seconds 30 --max-iterations 10

Reconcile feed/index/local visibility (one-shot):

.. code-block:: console

    py-sec-edgar reconcile run --recent-days 7

Reconcile with optional catch-up warming and machine-readable summary:

.. code-block:: console

    py-sec-edgar reconcile run --recent-days 7 --catch-up-warm --summary-json

Monitor state artifacts (configured normalized root):

- `monitor_seen_accessions.parquet`
- `monitor_events.parquet`

Lookup visibility update after monitor warming is conditional:

- when monitor actions changed local visibility, monitor performs incremental lookup registration for warmed filings by default,
- full `lookup refresh` rebuild is only a fallback when incremental registration is unsafe/incomplete,
- when refresh is disabled or no local visibility changed, lookup update is skipped with explicit summary/event reasons.

`local_lookup_filings_all.parquet` remains full-refresh-only (`lookup refresh --include-global-filings`) and is not incrementally maintained by monitor.

Reconciliation discrepancy/event artifacts (configured normalized root):

- `reconciliation_discrepancies.parquet`
- `reconciliation_events.parquet`

Reconciliation catch-up behavior:

- default is classify-and-record only (`--no-catch-up-warm`),
- optional `--catch-up-warm` writes missing raw submissions to canonical mirror paths,
- catch-up attempts now prefer strong canonical targets and explicitly skip weak/non-deterministic candidates with recorded reasons,
- successful catch-up lookup visibility uses incremental registration first, with full lookup refresh only as fallback when incremental registration is unsafe/incomplete.

Bugfix notes:

- reconciliation date-window filtering now compares using one consistent tz-naive strategy,
- feed entries resolving to SEC filing index pages are canonicalized to raw submission `.txt` warm targets when deterministically derivable,
- API filing lookup semantics remain exact-accession only (no fuzzy fallback added).

Monitor correctness hardening:

- event history persists explicit skip outcomes (`normalization_skipped`, `lookup_refresh_skipped`) in addition to warm outcomes,
- seen-state supports cache self-healing: if an accession is already seen but its canonical local file is missing, monitor can re-attempt warm for that accession.

Operator progress and interruption behavior:

- `lookup refresh`, `monitor poll`, `reconcile run`, and `python -m py_sec_edgar.service_runtime monitor-once` emit periodic human heartbeat/progress to stderr in TTY mode,
- `--summary-json` remains clean JSON-only stdout (heartbeat disabled),
- Ctrl+C now exits these flows cleanly with a short interruption message and no traceback.

Portable service runtime (optional)
-----------------------------------

Host-native CLI workflows remain unchanged. Compose is additive runtime scaffolding.

Service runtime entrypoints:

.. code-block:: console

    python -m py_sec_edgar.service_runtime api
    python -m py_sec_edgar.service_runtime monitor-once
    python -m py_sec_edgar.service_runtime monitor-loop

Compose usage:

.. code-block:: console

    docker compose up api
    docker compose up monitor
    docker compose up

Runtime env vars used by service wrapper:

- `PY_SEC_EDGAR_PROJECT_ROOT`
- `PY_SEC_EDGAR_API_HOST`
- `PY_SEC_EDGAR_API_PORT`
- `PY_SEC_EDGAR_MONITOR_INTERVAL_SECONDS`
- `PY_SEC_EDGAR_MONITOR_WARM`
- `PY_SEC_EDGAR_MONITOR_REFRESH_LOOKUP`
- `PY_SEC_EDGAR_MONITOR_FORM_TYPES`
- `PY_SEC_EDGAR_MONITOR_FORM_FAMILIES`
- `PY_SEC_EDGAR_MONITOR_EXECUTE_EXTRACTION`
- `PY_SEC_EDGAR_MONITOR_PERSIST_FILING_PARTIES`

Persistent storage remains outside container layers using mounted host paths.
