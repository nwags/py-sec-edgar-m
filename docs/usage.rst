=====
Usage
=====

For a concise Wave 1 migration summary, see ``WAVE1_MIGRATION_NOTE.md``.
For Wave 2 provider/rate-limit/resolve/API transparency alignment, see ``WAVE2_MIGRATION_NOTE.md``.
For Wave 3 shared augmentation metadata/contracts alignment, see ``WAVE3_MIGRATION_NOTE.md``.
For Wave 4 shared seams + read-only producer-protocol alignment, see ``WAVE4_MIGRATION_NOTE.md``.
For Wave 5/5.1 shared-package extraction and normalization alignment, see ``WAVE5_MIGRATION_NOTE.md``.
For Wave 7 lifecycle hardening (RC/stable signoff, rollback, deferred cleanup policy), see ``WAVE7_MIGRATION_NOTE.md``.
For Wave 7.1 package-side release-execution hardening (repo participation, blockers, rollback, user-testing start readiness), see ``WAVE7_1_MIGRATION_NOTE.md``.
For Wave 7.2 minimal companion participation in the first real shared RC cycle, see ``WAVE7_2_MIGRATION_NOTE.md``.

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

SEC source/surface registry authority is written by `refdata refresh`:

- `sec_source_surfaces.parquet`

Wave 2 canonical provider and resolve surfaces (additive):

.. code-block:: console

    m-cache sec providers list
    m-cache sec providers show --provider sec
    m-cache sec resolve filing --accession-number 0000320193-25-000010 --resolution-mode resolve_if_missing

Wave 3 canonical additive augmentation metadata/read wrappers:

.. code-block:: console

    m-cache sec aug list-types
    m-cache sec aug inspect-target --accession-number 0000320193-25-000010
    m-cache sec aug status --run-id <run_id>
    m-cache sec aug submit-run --payload-file ./producer_run_submission.json
    m-cache sec aug submit-artifact --payload-file ./producer_artifact_submission.json
    m-cache sec aug events
    m-cache sec aug inspect-runs --accession-number 0000320193-25-000010
    m-cache sec aug inspect-artifacts --accession-number 0000320193-25-000010

Wave 3 authority rule (SEC): sidecar/submission/provenance artifacts remain authoritative;
`augmentation_runs.parquet` and `augmentation_events.parquet` are additive shared metadata companions only.

Wave 4.1 command normalization note:

- canonical family: `inspect-target`, `status`, `submit-run`, `submit-artifact`, `events`
- `status` is a narrow single-run read surface keyed by `run_id` (with `idempotency_key` support when available)
- `submit-run` and `submit-artifact` are validate-only/non-persisting in this non-pilot repo pass
- compatibility surfaces remain available: `inspect-runs`, `inspect-artifacts`

Wave 5/5.1 shared-package note:

- first extraction package is in-repo as `m_cache_shared`,
- `py_sec_edgar.wave4_shared` remains a shim/facade for first-cycle adoption,
- SEC authority/identity/storage/execution internals remain local.

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
- `GET /filings/search` (public entity-aware filing search over derived entity index)
- `GET /filings/{accession_number}` (metadata endpoint; returns when lookup or merged-index metadata resolves accession)
- `GET /filings/{accession_number}/content` (local file hit first; local miss triggers SEC fetch + persist to canonical cache mirror path)
- `GET /filings/{accession_number}/augmentations` (public raw augmentation history)
- `GET /filings/{accession_number}/overlay` (public deterministic resolved overlay view)
- `GET /filings/{accession_number}/augmentation-submissions` (public submission-level review summary)
- `GET /augmentations/events` (public generalized event stream; primary)
- `GET /filings/{accession_number}/events` (public filing-scoped generalized events; primary)
- `GET /augmentations/events/summary` (public deterministic generalized grouped summary; primary)
- `GET /augmentations/submissions` (public cross-accession reviewer submission query)
- `GET /augmentations/submissions/{submission_id}` (public reviewer submission detail)
- `GET /augmentations/submissions/{submission_id}/lifecycle-events` (compatibility alias for lifecycle events)
- `GET /augmentations/submissions/{submission_id}/overlay-impact` (public resolved-overlay contribution diagnostics by accession)
- `GET /augmentations/submissions/{submission_id}/entity-impact` (public derived entity-index contribution rows)
- `GET /augmentations/submissions/{submission_id}/review-bundle` (public compact reviewer/operator export bundle)
- `POST /admin/augmentations/submissions` (authenticated augmentation ingestion)
- `POST /admin/augmentations/submissions/{submission_id}/lifecycle` (authenticated lifecycle transition)

Wave 2 additive API transparency on existing endpoints:

- `GET /filings/{accession_number}` returns additive `resolution_meta` and supports optional explicit content-resolution probing (`resolve_content=true`, `resolution_mode=...`, optional `provider=...`).
- `GET /filings/{accession_number}/content` preserves default response shape/status behavior and emits additive `X-M-Cache-*` resolution/provider/rate-limit headers.

Content retrieval contract:

1. check local canonical cache path from filing filename (`<download_root>/<filename>`),
2. if local file exists, serve it directly,
3. if local file is missing and metadata resolves accession, fetch from SEC and persist to canonical path,
4. subsequent requests for that accession are local hits.

Remote API resolution attempts are durably recorded in:

- `filing_resolution_provenance.parquet`

Augmentation sidecars
---------------------

Augmentation ingestion is external-producer-oriented and additive only; canonical filing content is unchanged.

Enable operator ingestion key:

.. code-block:: console

    export PY_SEC_EDGAR_AUGMENTATION_API_KEY=replace-with-operator-key

Authenticated ingestion request:

.. code-block:: console

    curl -sS -X POST "http://127.0.0.1:8000/admin/augmentations/submissions" \
      -H "Content-Type: application/json" \
      -H "X-API-Key: $PY_SEC_EDGAR_AUGMENTATION_API_KEY" \
      -d '{"producer_id":"ext-annotator","layer_type":"entities","schema_version":"v1","items":[{"accession_number":"0000320193-25-000010","augmentation_type":"entity_tag","payload":{"entities":[{"text":"Apple","type":"ORG"}]}}]}'

Public additive reads:

.. code-block:: console

    curl -sS "http://127.0.0.1:8000/filings/0000320193-25-000010/augmentations"
    curl -sS "http://127.0.0.1:8000/filings/0000320193-25-000010/overlay"
    curl -sS "http://127.0.0.1:8000/filings/search?entity_text=apple"
    curl -sS "http://127.0.0.1:8000/filings/0000320193-25-000010/augmentation-submissions"
    curl -sS "http://127.0.0.1:8000/augmentations/events?producer_id=ext-annotator&event_family=governance"
    curl -sS "http://127.0.0.1:8000/filings/0000320193-25-000010/events"
    curl -sS "http://127.0.0.1:8000/augmentations/events/summary?group_by=event_family&group_by=event_type"
    curl -sS "http://127.0.0.1:8000/augmentations/governance-events?producer_id=ext-annotator"  # compatibility alias
    curl -sS "http://127.0.0.1:8000/augmentations/submissions?layer_type=entities&has_governance_warnings=true"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions?submission_id=<submission_id>"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions?accession_number=0000320193-25-000010"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions/<submission_id>"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions/<submission_id>/lifecycle-events"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions/<submission_id>/overlay-impact"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions/<submission_id>/entity-impact"
    curl -sS "http://127.0.0.1:8000/augmentations/submissions/<submission_id>/review-bundle"
    curl -sS "http://127.0.0.1:8000/filings/0000320193-25-000010?include_augmentations=true&augmentation_view=history"
    curl -sS "http://127.0.0.1:8000/filings/0000320193-25-000010?include_augmentations=true&augmentation_view=resolved"

Lifecycle transition (admin):

.. code-block:: console

    curl -sS -X POST "http://127.0.0.1:8000/admin/augmentations/submissions/<submission_id>/lifecycle" \
      -H "Content-Type: application/json" \
      -H "X-API-Key: $PY_SEC_EDGAR_AUGMENTATION_API_KEY" \
      -d '{"to_state":"disabled","reason":"bad_run","changed_by":"ops","source":"manual_review"}'

Resolved overlay selection policy:

- policy id: `latest_per_producer_layer_v1`
- latest means `received_at DESC`, tie-break `submission_id ASC`
- selection scope is one winning submission per `(producer_id, layer_type)` bucket
- raw history remains available separately via `/filings/{accession_number}/augmentations`

Shared history/overlay query filters:

- `augmentation_type`
- `schema_version`
- `received_at_from`
- `received_at_to`
- `include_submission_metadata=true`
- `lifecycle_state`

Timestamp filtering:

- accepted input format: RFC3339/ISO-8601 (`Z` or explicit offset accepted),
- bounds are inclusive (`received_at >= received_at_from`, `received_at <= received_at_to`),
- invalid timestamp input returns HTTP `422`.

Governance time filters:

- `event_time_from` and `event_time_to` are the canonical governance timestamp filters,
- `received_at_from` and `received_at_to` remain backward-compatible aliases for governance reads.

Recommended sidecar family naming conventions (guidance):

- `entity_mentions`
- `entity_links`
- `temporal_expressions`
- `event_spans`
- `document_labels`

Sidecar artifacts are persisted under normalized root:

- `augmentation_submissions.parquet`
- `augmentation_items.parquet`
- `augmentation_governance_events.parquet`
- `augmentation_submission_lifecycle_events.parquet`
- `augmentation_entity_index.parquet` (derived/rebuildable filing-search index)
- `augmentation_raw_requests/{submission_id}.json`

Advisory governance semantics:

- contract id: `augmentation_family_conventions_v1`,
- family conventions are guidance for producer ergonomics and review diagnostics,
- governance warnings do not reject otherwise valid submissions,
- stable warning codes:
  - `gov_unknown_family`
  - `gov_layer_type_mismatch`
  - `gov_augmentation_type_mismatch`
  - `gov_missing_recommended_payload_keys`

Lifecycle semantics:

- stable states:
  - `active`
  - `superseded`
  - `withdrawn`
  - `disabled`
- lifecycle transitions are append-only and auditable,
- lifecycle is an operational control state and is distinct from review/approval semantics,
- history reads remain available for all states by default,
- resolved overlay selection order is:
  1. apply request filters,
  2. resolve current lifecycle state,
  3. exclude non-`active` submissions,
  4. apply `latest_per_producer_layer_v1`.

Overlay-impact reason codes (stable):

- `selected`
- `lifecycle_ineligible`
- `superseded_by_winner`
- `no_eligible_rows`

Reviewer playbook:

1. inspect cross-accession submissions (`GET /augmentations/submissions`, optional `submission_id`/`accession_number` filters),
2. inspect generalized events (`GET /augmentations/events`, `GET /filings/{accession_number}/events`),
3. inspect generalized event summary (`GET /augmentations/events/summary`),
4. inspect impact on resolved overlay and entity search (`GET /augmentations/submissions/{submission_id}/overlay-impact`, `GET /augmentations/submissions/{submission_id}/entity-impact`, `GET /filings/search`),
5. export compact review snapshot (`GET /augmentations/submissions/{submission_id}/review-bundle`).

Correction note:

- Prior governance-specific endpoint design was too narrow and has been corrected in this phase.

Generalized event error contract:

- redesigned event endpoints and compatibility event aliases return:
  `{"error":{"code":"...","message":"...","details":{...}}}`

Reviewer/operator CLI wrappers:

.. code-block:: console

    py-sec-edgar augmentations submission <submission_id>
    py-sec-edgar augmentations events --event-family governance
    py-sec-edgar augmentations events-summary --group-by event_family --group-by event_type
    py-sec-edgar augmentations filing-events <accession_number>
    py-sec-edgar augmentations lifecycle-events <submission_id>
    py-sec-edgar augmentations governance-summary <submission_id>
    py-sec-edgar augmentations governance-events <submission_id>
    py-sec-edgar augmentations overlay-impact <submission_id>
    py-sec-edgar augmentations entity-impact <submission_id>
    py-sec-edgar augmentations review-bundle <submission_id>
    py-sec-edgar augmentations review-bundle <submission_id> --json

Entity-aware filing search:

- query surface: `GET /filings/search`,
- source: `augmentation_entity_index.parquet` (derived from resolved overlays only),
- lifecycle effect: only active submissions are eligible to contribute,
- supported entity families for indexing in this phase:
  - `entity_mentions`
  - `entity_links`
- matching:
  - `entity_normalized` is exact,
  - `entity_text` is case-insensitive substring over normalized values,
  - filing filters (`cik`, `form_type`, `filing_date_from`, `filing_date_to`) compose with AND,
- result ordering: `filing_date DESC`, then `accession_number ASC`.

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
- `filing_resolution_provenance.parquet` (cross-flow remote resolution provenance)

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

- `lookup refresh`, `monitor poll`, `reconcile run`, and `python -m py_sec_edgar.service_runtime monitor-once` support optional `--progress-json` to emit compact NDJSON progress events to stderr,
- machine progress is event-driven by default in `--progress-json` mode (no periodic liveness heartbeat unless explicitly requested),
- optional machine liveness heartbeat is enabled with `--progress-heartbeat-seconds FLOAT`; omitted or `0` disables it, positive values emit liveness only after idle periods,
- each machine progress event includes `event`, `phase`, `elapsed_seconds`, `counters` and only includes optional `detail`/`window_date`/`window_index`/`window_total` when meaningful,
- without `--progress-json`, existing human heartbeat/progress behavior remains unchanged in TTY mode,
- `--summary-json` remains clean JSON-only stdout for final summaries,
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
