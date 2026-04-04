py-sec-edgar
============

`py-sec-edgar` is an operator-focused, general-purpose SEC EDGAR ingestion and workflow tool.
It acquires, normalizes, stores, and organizes filing data so downstream systems can run
analysis, enrichment, and strategy-specific processing. Special-situations workflows are one
example use case, not the only one.

Overview
========

Current capabilities include:

- reference-data normalization from SEC source files into canonical parquet tables,
- EDGAR index refresh + merged parquet materialization with operator-facing runtime controls,
- backfill candidate selection plus bounded concurrent downloads and optional serial extraction,
- filing-party persistence and query workflows for supported ownership/insider forms,
- local lookup refresh/query artifacts for fast local operator retrieval,
- accession-centered filing-resolution primitives reused by API/monitor/reconciliation flows,
- normalized SEC source/surface registry artifact for explicit provider/surface authority,
- API local-first metadata/content serving with SEC fallback persistence into canonical cache paths,
- authenticated augmentation sidecar ingestion keyed by accession number with optional overlay reads,
- feed-driven monitor poll/loop with incremental lookup registration and persisted event history,
- one-shot feed-plus-index reconciliation with durable discrepancy/event artifacts and optional catch-up warming.

Design Philosophy
=================

This project is:

- ingestion-first and operator-focused,
- designed for reproducible pipelines and predictable filesystem layout,
- focused on acquiring, normalizing, caching, and organizing SEC data.

This project intentionally does not:

- perform deep semantic parsing of filing contents,
- extract full financial statements or ratios,
- replace specialized downstream analysis tools.

Extraction in this repo is:

- limited,
- metadata-oriented,
- focused on entity and relationship signals when extraction is reliable.

Quick Start
===========

Install
-------

.. code-block:: console

    pip install -r requirements.txt
    pip install -e .

Refresh normalized reference data
---------------------------------

.. code-block:: console

    py-sec-edgar refdata refresh

Refresh EDGAR index data
------------------------

.. code-block:: console

    py-sec-edgar index refresh --skip-if-exists --save-idx-as-csv

Run backfill
------------

.. code-block:: console

    py-sec-edgar backfill --execute-downloads --execute-extraction --form-family beneficial_ownership

Query filing-party output
-------------------------

.. code-block:: console

    py-sec-edgar filing-parties query --issuer-cik 0000123456 --json --limit 10

Current CLI Workflow
====================

`py-sec-edgar refdata refresh`
------------------------------

Builds normalized parquet refdata under the configured normalized root.

`py-sec-edgar index refresh`
----------------------------

Downloads/converts index files and materializes merged index parquet used by backfill.

`py-sec-edgar backfill`
-----------------------

Loads candidates from merged index parquet, applies filters, optionally downloads and extracts, and can persist filing-party rows.

`py-sec-edgar filing-parties query`
-----------------------------------

Reads persisted `filing_parties.parquet` and applies query filters for operator inspection or JSON pipelines.

`py-sec-edgar monitor poll`
---------------------------

Runs a one-shot feed poll, filters candidates, warms local cache for new relevant filings, and conditionally refreshes lookup visibility when local artifacts changed.

`py-sec-edgar monitor loop`
---------------------------

Runs a bounded polling loop (`--interval-seconds`, `--max-iterations`) for operator-driven monitoring without daemonization.

API Local-First Retrieval
=========================

The repository includes an additive FastAPI surface under `py_sec_edgar/api/` on top of existing CLI ingestion/storage flows.

- `GET /health`
- `GET /filings/{accession_number}`
- `GET /filings/search`
- `GET /filings/{accession_number}/content`
- `GET /filings/{accession_number}/augmentations`
- `GET /filings/{accession_number}/overlay`
- `GET /filings/{accession_number}/augmentation-submissions`
- `GET /augmentations/events` (primary generalized event stream)
- `GET /filings/{accession_number}/events` (primary filing-scoped generalized events)
- `GET /augmentations/events/summary` (primary generalized grouped summary)
- `GET /augmentations/submissions`
- `GET /augmentations/submissions/{submission_id}`
- `GET /augmentations/submissions/{submission_id}/lifecycle-events` (compatibility alias)
- `GET /augmentations/submissions/{submission_id}/overlay-impact`
- `GET /augmentations/submissions/{submission_id}/entity-impact`
- `GET /augmentations/submissions/{submission_id}/review-bundle`
- `POST /admin/augmentations/submissions` (operator API key required)
- `POST /admin/augmentations/submissions/{submission_id}/lifecycle` (operator API key required)

Current API behavior is local-first:

1. use local lookup/index metadata,
2. serve local cached filing content when present,
3. on local content miss, fetch filing content from SEC and persist it into the existing cache mirror path under `.sec_cache/Archives/...`,
4. subsequent requests for that accession are served from local cache.

The API patch does not replace storage layout or CLI ingestion behavior.

Augmentation sidecar model:

- canonical filing content remains immutable and canonical,
- augmentation payloads are additive sidecars keyed by `accession_number`,
- ingestion is authenticated with `X-API-Key` against `PY_SEC_EDGAR_AUGMENTATION_API_KEY`,
- public filing reads remain unchanged by default; overlays are opt-in,
- raw history view: `GET /filings/{accession_number}/augmentations`,
- resolved overlay view: `GET /filings/{accession_number}/overlay` (deterministic latest submission per `(producer_id, layer_type)` using `received_at DESC`, `submission_id ASC`).
- entity-aware filing search: `GET /filings/search` (derived from resolved overlay winners only; lifecycle-aware and entity-family-scoped).
- submission-summary view: `GET /filings/{accession_number}/augmentation-submissions` for producer/run/layer inspection.
- generalized event inspection views (primary):
  - cross-accession: `GET /augmentations/events`
  - filing-scoped: `GET /filings/{accession_number}/events`
  - grouped summary: `GET /augmentations/events/summary`
- cross-accession reviewer submission views:
  - list/filter: `GET /augmentations/submissions` (supports `submission_id` and `accession_number` filters)
  - detail: `GET /augmentations/submissions/{submission_id}`
  - lifecycle history: `GET /augmentations/submissions/{submission_id}/lifecycle-events`
  - resolved-overlay impact: `GET /augmentations/submissions/{submission_id}/overlay-impact`
  - entity-index impact: `GET /augmentations/submissions/{submission_id}/entity-impact`
  - compact export bundle: `GET /augmentations/submissions/{submission_id}/review-bundle`

Advisory governance contract:

- contract id: `augmentation_family_conventions_v1`,
- conventions are advisory only (no submission rejection from convention mismatch),
- stable governance warning codes:
  - `gov_unknown_family`
  - `gov_layer_type_mismatch`
  - `gov_augmentation_type_mismatch`
  - `gov_missing_recommended_payload_keys`
- governance events are persisted to `augmentation_governance_events.parquet` for audit/review support.
- lifecycle and governance validation errors expose stable machine-readable codes in API responses.
- compatibility aliases (transition only, not primary):
  - `GET /filings/{accession_number}/governance-events`
  - `GET /augmentations/governance-events`
  - `GET /augmentations/governance-events/summary`
  - `GET /augmentations/submissions/{submission_id}/lifecycle-events`

Correction note:

- Prior governance-specific endpoint design was too narrow and has been corrected in this phase.

Submission lifecycle control:

- lifecycle states (stable machine contract):
  - `active`
  - `superseded`
  - `withdrawn`
  - `disabled`
- lifecycle transitions are append-only audit events (`augmentation_submission_lifecycle_events.parquet`),
- current lifecycle state is derived from append-only events (default `active` when no lifecycle events exist),
- raw augmentation history remains immutable/append-only,
- resolved overlay eligibility uses lifecycle state and only `active` submissions can win.
- lifecycle is an operational control contract and is intentionally distinct from any approval semantics.

Reviewer playbook:

1. inspect submissions: `GET /augmentations/submissions`,
2. inspect generalized events: `GET /augmentations/events` and `/filings/{accession_number}/events`,
3. inspect generalized event summary: `GET /augmentations/events/summary`,
4. inspect overlay/entity impact: `GET /augmentations/submissions/{submission_id}/overlay-impact` and `/augmentations/submissions/{submission_id}/entity-impact`,
5. export compact review bundle: `GET /augmentations/submissions/{submission_id}/review-bundle`.

Metadata endpoint overlay modes:

- `include_augmentations=true` + `augmentation_view=history` (default) returns raw augmentation history rows,
- `include_augmentations=true` + `augmentation_view=resolved` returns resolved overlay rows.

History and overlay read filters (shared):

- `augmentation_type`
- `schema_version`
- `received_at_from`
- `received_at_to`
- `include_submission_metadata`
- `lifecycle_state`

`received_at` filters accept RFC3339/ISO-8601 timestamps (including `Z`/offset) and use inclusive bounds:
`received_at >= received_at_from` and `received_at <= received_at_to`.
Generalized event endpoints support canonical aliases `event_time_from` / `event_time_to` with `received_at_*` retained for compatibility.
Overlay impact uses stable reason codes: `selected`, `lifecycle_ineligible`, `superseded_by_winner`, `no_eligible_rows`.

Reviewer/operator CLI wrappers:

- `py-sec-edgar augmentations submission <submission_id>`
- `py-sec-edgar augmentations events`
- `py-sec-edgar augmentations events-summary`
- `py-sec-edgar augmentations filing-events <accession_number>`
- `py-sec-edgar augmentations lifecycle-events <submission_id>`
- `py-sec-edgar augmentations governance-summary <submission_id>`
- `py-sec-edgar augmentations governance-events <submission_id>`
- `py-sec-edgar augmentations overlay-impact <submission_id>`
- `py-sec-edgar augmentations entity-impact <submission_id>`
- `py-sec-edgar augmentations review-bundle <submission_id>`

Lifecycle-aware overlay selection order:

1. apply request filters,
2. resolve current lifecycle state per submission,
3. exclude non-`active` submissions,
4. apply existing winner policy (`latest_per_producer_layer_v1`).

Entity-aware filing search:

- derived artifact: `augmentation_entity_index.parquet`,
- source universe: resolved overlay winners only (no raw-history mutation),
- lifecycle-aware eligibility: only active submissions contribute,
- current search families: `entity_mentions`, `entity_links`,
- temporal sidecars remain ingestible/visible but are not indexed for search in this phase.

Deferred in this phase: in-repo tagging/model inference, ontology/entity-graph construction, and multi-tenant auth.

Filing resolution model formalization:

- canonical filing key is `accession_number`,
- metadata resolution is local lookup first, merged index fallback second,
- canonical remote content surface is SEC Archives submission `.txt`,
- remote resolution outcomes are persisted to canonical local paths and recorded in normalized provenance artifacts.

Monitoring state artifacts
==========================

Monitor artifacts are stored under the configured normalized root:

- `monitor_seen_accessions.parquet`
- `monitor_events.parquet`

Lookup visibility update after monitor warming is conditional:

- when local visibility changed, monitor attempts incremental lookup registration for warmed filings by default,
- full `lookup refresh` rebuild is used only as a safety fallback when incremental registration is unsafe/incomplete,
- when local visibility did not change (or refresh is disabled), lookup update is explicitly skipped and reported.

Monitor hardening notes:

- monitor event history persists operational skip actions (including normalization skips and lookup-refresh skips) so persisted history matches reported activity,
- previously seen accessions with missing local files are eligible for self-healing re-warm attempts instead of being permanently suppressed by seen-state.
- `local_lookup_filings_all.parquet` remains maintained only by explicit full lookup refresh flows (`lookup refresh --include-global-filings`), not by monitor incremental updates.

Reconciliation artifacts
========================

Reconciliation artifacts are stored under the configured normalized root:

- `reconciliation_discrepancies.parquet`
- `reconciliation_events.parquet`
- `filing_resolution_provenance.parquet`

Reconciliation is one-shot and operator-oriented:

- compares feed visibility, merged-index visibility, and local canonical cache presence,
- records discrepancy classifications durably,
- optionally performs catch-up warming into canonical mirror paths,
- updates lookup visibility via incremental registration by default, with full lookup refresh fallback only when incremental registration is unsafe/incomplete.
- catch-up warming now defaults to conservative, canonical-target eligibility and records explicit skip reasons for weak candidates.

Recent bugfix notes:

- reconciliation date-window filtering now uses consistent tz-naive comparisons (fixes mixed tz-aware/naive crashes),
- feed-derived monitor/reconciliation warming now canonicalizes SEC `-index.htm` style links to raw submission `.txt` targets when deterministically derivable,
- API accession semantics are unchanged (exact lookup, 404 when accession is not present in local lookup/index metadata).

Runtime Visibility and Logging
==============================

Commands that perform runtime work (`refdata refresh`, `index refresh`, `backfill`) support:

- `--verbose` for bounded recent activity output,
- `--quiet` for minimal completion output,
- `--log-level` for console verbosity,
- `--log-file` for optional file logging.

`backfill --summary-json` outputs machine-readable JSON on stdout.
Human-oriented progress/activity output is kept separate so JSON mode stays script-friendly.

Operator-readiness hardening:

- long-running `lookup refresh`, `monitor poll`, `reconcile run`, and `service_runtime monitor-once` support optional `--progress-json` for compact NDJSON progress events on stderr,
- machine progress is event-driven by default in `--progress-json` mode (no periodic liveness heartbeat by default),
- optional liveness heartbeat is explicit via `--progress-heartbeat-seconds FLOAT`; omitted or `0` disables, positive values emit heartbeat only after idle periods,
- each machine progress event keeps the stable compact schema: `event`, `phase`, `elapsed_seconds`, `counters` (with optional `detail`, `window_date`, `window_index`, `window_total` only when meaningful),
- without `--progress-json`, human heartbeat/progress behavior remains unchanged in TTY mode,
- final `--summary-json` output remains clean JSON on stdout,
- Ctrl+C interruption now exits cleanly without Python traceback for those operator-facing flows.

Data / Artifact Layout
======================

Default paths (relative to project root):

- Download/cache root: `.sec_cache/Archives`
- Merged index parquet: `refdata/merged_idx_files.pq`
- Normalized parquet root: `refdata/normalized`
- Extracted filing content: alongside downloaded submission files in the cache tree.

Additional normalized artifacts in the current resolution model:

- `sec_source_surfaces.parquet` (SEC provider/surface registry authority)
- `filing_resolution_provenance.parquet` (cross-flow remote resolution provenance)
- `augmentation_submissions.parquet` (augmentation submission/run metadata)
- `augmentation_items.parquet` (augmentation payload rows by accession)
- `augmentation_governance_events.parquet` (advisory governance diagnostics; audit-oriented)
- `augmentation_submission_lifecycle_events.parquet` (append-only submission lifecycle transitions)
- `augmentation_raw_requests/{submission_id}.json` (raw ingestion request bodies)

Environment Overrides
=====================

You can override runtime roots without changing code:

- `PY_SEC_EDGAR_PROJECT_ROOT`
- `PY_SEC_EDGAR_DOWNLOAD_ROOT`
- `PY_SEC_EDGAR_MERGED_INDEX_PATH`
- `PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT`
- `PY_SEC_EDGAR_AUGMENTATION_API_KEY` (enables authenticated augmentation ingestion endpoint)

Portable Runtime (Optional Compose)
===================================

Host-native workflows remain supported and unchanged. Docker Compose is an optional runtime wrapper.

Service runtime entrypoints:

- `python -m py_sec_edgar.service_runtime api`
- `python -m py_sec_edgar.service_runtime monitor-once`
- `python -m py_sec_edgar.service_runtime monitor-loop`

Service runtime JSON observability:

- service startup emits stable JSON with resolved runtime roots/settings,
- monitor loop emits per-iteration JSON summaries,
- lock refusal emits stable JSON (`event=monitor_lock_refused`) for easy log assertions.

Monitor loop safety defaults:

- continuous interval polling with signal-aware shutdown,
- single-instance advisory lock enabled by default at `<project_root>/.sec_runtime/monitor_loop.lock`,
- lock refusal is based on advisory lock acquisition failure, not stale-file presence.

Compose services (one image, two processes):

- `api` runs the FastAPI service
- `monitor` runs continuous monitor worker loop

Compose quick-start examples:

.. code-block:: console

    docker compose up api
    docker compose up monitor
    docker compose up

Persistence model:

- Image layers remain code/runtime only.
- SEC artifacts and parquet outputs live in mounted host storage (`PY_SEC_EDGAR_HOST_DATA_ROOT`, mounted to `/workspace`).
- In-container runtime root is stable (`PY_SEC_EDGAR_PROJECT_ROOT=/workspace`).

Operator Notes
==============

- Local/dev default: `.sec_cache` under project root keeps working state easy to inspect and clean.
- Production/staging: prefer mounted storage paths via env overrides so cache and artifacts are durable and explicit.
- Recommended order for repeatable operations:

  1. `py-sec-edgar refdata refresh`
  2. `py-sec-edgar index refresh --skip-if-exists --save-idx-as-csv`
  3. `py-sec-edgar backfill ...`
  4. `py-sec-edgar filing-parties query ...`

Roadmap and Next Priorities
===========================

Current Status
--------------

The project is now in a post-feature operator-polish phase for the core ingestion stack:

- reliability and regression coverage are materially stronger than earlier roadmap stages,
- local lookup refresh/query and API local-first retrieval with SEC fallback persistence are implemented,
- feed-driven monitor poll/loop, incremental lookup registration, and reconciliation with optional catch-up are implemented,
- portable service runtime entrypoints and machine-readable runtime summaries are implemented,
- machine progress JSON and `--summary-json` stdout contracts are already in place for operator-facing commands.

Next Priorities
---------------

1. Ingestion efficiency and scale

- continue reducing redundant work and improving bounded concurrency throughput,
- favor SEC-appropriate bulk/distribution paths when they are a better fit than additional parallel scraping.

2. Telemetry and operator UX polish

- keep machine telemetry compact, stable, and event-driven,
- continue improving progress/event clarity, fallback/skip diagnostics, and service-runtime observability.

3. Reliability and regression hardening

- expand regression fixtures around monitor/reconciliation/lookup interactions and failure paths,
- keep resumability, idempotence, and output-contract stability first-class in new changes.

4. Limited metadata extraction expansion

- extend only high-confidence metadata extraction where reliability is demonstrable,
- keep deep semantic parsing and full financial modeling out of scope for this repository.

5. Storage-tier and distributed-awareness readiness

- preserve canonical path/storage contracts and derived-vs-durable-state boundaries,
- guide near-term decisions with `docs/FUTURE_DISTRIBUTED_STORAGE_PRINCIPLES.md` while remaining local-first by default.

Attribution
===========

This repo is based on the original `py-sec-edgar` project by Ryan S. McCoy:

- https://github.com/ryansmccoy/py-sec-edgar

This repository extends and refactors that foundation for current operator-focused SEC ingestion workflows.
Original licensing, attribution, and legal notices are preserved.
