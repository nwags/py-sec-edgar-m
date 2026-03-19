# CODEX_TASKLIST.md

## Primary objective

Refactor the legacy repo into a special-situations EDGAR ingestion engine with safe concurrency and a new reference-data model.

## Phase 1
- Add these canonical docs to the repo.
- Add `scripts/fetch_sec_reference_data.sh`.
- Add `py_sec_edgar/config.py`.
- Add tests for config loading.

## Phase 2
- Replace downloader internals with:
  - `requests.Session`
  - explicit retries
  - atomic writes
  - status-code checks
  - declared `User-Agent`
- Remove random browser user-agent rotation from default path.
- Keep old proxy support only behind an explicit opt-in compatibility flag.

## Phase 3
- Add a shared rate limiter.
- After rate limiting is stable, add threaded concurrent download orchestration.
- Keep extraction serial at first.
- Expose worker-count and rate-limit config on the CLI.

## Phase 4
- Build `py_sec_edgar/refdata/` package.
- Add normalizers for:
  - company_tickers
  - company_tickers_exchange
  - company_tickers_mf
  - ticker.txt
  - cik-lookup-data.txt
  - investment-company-series-class CSV
- Emit normalized parquet tables defined in `docs/REFDATA_SCHEMA.md`.

## Phase 5
- Replace ticker-centric filtering with entity-aware filtering.
- Support query/filter by:
  - form family,
  - issuer ticker,
  - issuer CIK,
  - entity CIK,
  - date range.

## Phase 6
- Add tests:
  - retry logic
  - status-code handling
  - rate limiting
  - refdata normalization
  - candidate filtering
  - resumable downloads

## Acceptance criteria

- A user can refresh SEC reference data from official sources.
- A user can run a special-situations backfill without editing code.
- Downloads are faster than the legacy serial path.
- Request behavior remains SEC-compliant.
- The repo no longer depends on `cik_tickers.csv` as its canonical entity model.

## Migration notes (Patch Set 1)

- Added typed config and explicit `py-sec-edgar refdata refresh` CLI workflow.
- Added entity-aware normalized parquet outputs under `refdata/normalized/`.
- Added canonical `reference_file_manifest.parquet` with source metadata and hashes.
- Legacy live-network tests are quarantined pending downloader correctness refactor.

## Migration notes (Downloader correctness patch)

- Refactored downloader internals to use persistent `requests.Session`, explicit status handling, bounded retries, and atomic writes.
- Removed random browser user-agent rotation from default path; default behavior now uses declared config user-agent.
- Kept proxy behavior as explicit opt-in compatibility mode only.

## Migration notes (Legacy caller routing cleanup patch)

- Routed remaining legacy monthly/XBRL network call paths in `feeds.py` through `ProxyRequest` safe methods (`GET_FILE` / `GET_RESPONSE`).
- Removed direct `requests.get(...)` usage from runtime module paths.
- Updated touched legacy path attributes to current config shim names (`MONTHLY_DIR`, `FILING_DIR`) in those flows.

## Migration notes (Legacy runtime/config drift cleanup patch)

- Cleaned daily/monthly legacy runtime paths in `feeds.py` to use current config names (`DAILY_INDEX_DIR`, `MONTHLY_DIR`, `FILING_DIR`) in touched flows.
- Fixed control-flow bug in daily update logic (`consecutive_days_same` initialization and update path behavior).
- Added graceful guard in monthly parsing flow when legacy ticker config paths are missing instead of failing at runtime.

## Migration notes (Shared rate limiter patch)

- Added process-shared request limiter module and integrated it into downloader outbound request paths.
- `ProxyRequest.GET_FILE` and `ProxyRequest.GET_RESPONSE` now both pass through one shared limiter driven by typed config `max_requests_per_second`.
- No threads/rate-limit + concurrency coupling was introduced in this patch.

## Migration notes (Bounded threaded download orchestration patch)

- Added bounded `ThreadPoolExecutor` download orchestration for the full-index quarterly download stage.
- Worker count is config-driven from typed config (`download_workers`) with bounded lower limit of 1.
- Each threaded task constructs its own downloader instance/session while still using the shared process-wide rate limiter.
- Downloader correctness semantics (retries, status handling, atomic writes, failure recording) remain unchanged.

## Migration notes (CLI expansion patch)

- Added explicit CLI commands for `index refresh` and `backfill` in addition to `refdata refresh`.
- Wired new commands to explicit pipeline entrypoints (`pipelines/index_refresh.py`, `pipelines/backfill.py`) using typed config loading.
- Kept filtering semantics unchanged in this phase; CLI expansion is wiring-only.

## Migration notes (Entity-aware filtering patch)

- Added dedicated filtering module (`py_sec_edgar/filters.py`) that loads canonical normalized parquet refdata (`issuers.parquet`, `entities.parquet`) from `refdata/normalized/`.
- Updated `feeds.load_filings_feed()` to use normalized parquet as the operational authority for ticker/CIK/entity resolution.
- Kept a narrow legacy compatibility bridge for ticker-list filtering by resolving ticker list inputs through normalized parquet keys instead of treating `refdata/cik_tickers.csv` as canonical.

## Migration notes (Backfill selection surface upgrade patch)

- Extended `run_backfill()` to accept and pass through entity-aware selection inputs: issuer tickers/CIKs, entity CIKs, forms, form families, and date range.
- Expanded `py-sec-edgar backfill` CLI options to expose those selectors directly for operator use without code edits.
- Added explicit precedence guards so legacy `ticker_list_filter`/`form_list_filter` are automatically disabled when explicit entity-aware selector inputs are provided.

## Migration notes (Backfill execution upgrade patch)

- Upgraded `run_backfill()` from selection-only behavior to an explicit two-stage flow: candidate selection plus optional download execution.
- Reused existing bounded threaded downloader orchestration (`run_bounded_downloads`) and existing downloader safety semantics (session, retries, explicit status handling, atomic writes, shared limiter).
- Added operator-facing `--execute-downloads` control on `py-sec-edgar backfill` and structured execution summary output (`download_attempted_count`, `download_succeeded_count`, `download_failed_count`, failure details).

## Migration notes (Backfill extraction-stage integration patch)

- Added an explicit optional serial extraction stage to `run_backfill()` after selection/download stages.
- Added operator-facing `--execute-extraction` control (default off) on `py-sec-edgar backfill`.
- Backfill summary now includes extraction-stage counts and structured extraction failure details (`extraction_attempted_count`, `extraction_succeeded_count`, `extraction_failed_count`, `extraction_failures`).

## Migration notes (Filing-party extraction foundation patch)

- Added a dedicated filing-party extraction module (`py_sec_edgar/filing_parties.py`) with an explicit normalized output contract.
- Implemented first reliable form-scoped parser support for `SC 13D`, `SC 13D/A`, `SC 13G`, and `SC 13G/A` using SEC-header party blocks.
- Integrated filing-party extraction into the optional extraction stage in `run_backfill()` and added structured filing-party summary fields/failure reporting.

## Migration notes (Forms 3/4/5 filing-party extraction patch)

- Extended unified filing-party extraction to support Forms `3`, `4`, and `5` from structured ownership XML.
- Added explicit role extraction for `reporting_owner`, `issuer`, `director`, `officer`, and `ten_percent_owner` when ownership relationship flags are present.
- Preserved 13D/13G SEC-header extraction behavior and kept the same backfill result surface for filing-party records.

## Migration notes (Normalized filing-party persistence patch)

- Added deterministic parquet upsert helper for filing-party records and canonicalized persistence to `refdata/normalized/filing_parties.parquet`.
- Added idempotent dedupe key: `accession_number`, `party_role`, `party_cik`, `party_name`, `source_filename`.
- Added optional backfill persistence wiring (`persist_filing_parties`) with explicit summary fields (`filing_party_persisted_count`, `filing_party_persist_path`).

## Migration notes (CLI filing-party persistence plumbing patch)

- Added operator-facing backfill CLI flag `--persist-filing-parties/--no-persist-filing-parties`.
- Wired CLI option through to `run_backfill(...)` persistence control without changing parser or pipeline semantics.
- Added concise CLI summary surfacing filing-party persistence counts and persisted parquet path when present.

## Migration notes (Backfill summary JSON + warning cleanup patch)

- Added backfill CLI `--summary-json` mode that emits deterministic JSON output instead of human-readable summary lines.
- Added concise filing-party persistence summary fields to CLI output path (`filing_party_record_count`, `filing_party_persisted_count`, optional `filing_party_persist_path`).
- Tightened dependency declarations for `requests`/`chardet` compatibility and reduced non-essential deprecated lazy `CONFIG` usage in feed-related tests.

## Migration notes (Filing-party query/read surface patch)

- Added operator-facing CLI read surface: `py-sec-edgar filing-parties query`.
- Query reads canonical artifact `refdata/normalized/filing_parties.parquet` and supports filters for issuer CIK, party CIK, role, form type, filing date range, and accession number.
- Added deterministic `--json` output mode and concise human-readable terminal output for operator workflows.

## Migration notes (Filing-party query ergonomics patch)

- Added `--limit` to `filing-parties query`; applies after filtering and deterministic sorting for both human-readable and JSON output.
- Added optional `--columns` (comma-separated) to select output fields for both human-readable and JSON output.
- Added explicit column validation with clear CLI errors for invalid column requests.

## Migration notes (feeds.py hardening pass)

- Added explicit guards for missing merged-index artifact and missing required index columns in `load_filings_feed()`.
- Hardened legacy ticker bridge loading with clear file-presence checks and predictable empty-list behavior.
- Fixed fragile IDX conversion row filter and added required-column validation/empty-input handling for index merge flows.
- Tightened monthly/index runtime paths with clearer warnings for missing local inputs and per-file flatten failures.

## Migration notes (Runtime hardening + dev artifact cleanup patch)

- Updated quarterly date generation to current pandas-compatible quarterly frequency alias while preserving quarter-folder semantics.
- Hardened `index refresh` path so existing `.idx` files without `.csv` companions are converted before merge, ensuring merged parquet generation for backfill preconditions.
- Added actionable CLI error for missing merged index artifact in backfill flows: run `py-sec-edgar index refresh` first.
- Standardized local coverage/dev artifact hygiene around `htmlcov/` and `coverage_*/` cleanup/ignore paths.

## Migration notes (Patch 23A runtime UX + path configurability)

- Added operator-facing per-command runtime controls on `index refresh` and `backfill`: `--verbose`, `--quiet`, `--log-level`, and `--log-file`.
- Added bounded recent-activity rendering for verbose runs while preserving stable summary output in normal mode.
- Preserved `--summary-json` machine mode with JSON-only stdout; activity/log output routes to stderr and/or log file.
- Added typed config env overrides for runtime paths (`PY_SEC_EDGAR_DOWNLOAD_ROOT`, `PY_SEC_EDGAR_MERGED_INDEX_PATH`, `PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT`) with backward-compatible defaults.

## Migration notes (Operator hardening: filing-party extraction + refdata UX)

- Added runtime UX parity flags to `py-sec-edgar refdata refresh` (`--verbose`, `--quiet`, `--log-level`, `--log-file`) with stable summary output and bounded verbose activity output.
- Hardened SC 13D/A and SC 13G/A filing-party header parsing for real SEC header subsection variants (`COMPANY DATA:`, `FILING VALUES:`) so trustworthy role rows are emitted instead of zero-row misses.
- Added coherent filing-party stage counters in backfill summaries/JSON, including `filing_party_candidate_count`, `filing_party_attempted_count`, `filing_party_zero_record_count`, and invariant-coherent successful/failed filing counts.
- Kept normalized-input missing errors as `FileNotFoundError` while improving message content to include configured root path and explicit `py-sec-edgar refdata refresh` remediation guidance.

## Migration notes (Docs and tooling modernization patch)

- Rewrote the top-level README as the current operator entrypoint with working CLI quick-start, runtime visibility flags, data/artifact layout, and environment overrides.
- Aligned Sphinx docs (`index`, `installation`, `usage`, and included README) with the current staged CLI workflow and artifact model.
- Modernized docs/build tooling in root `Makefile`, `docs/conf.py`, `readthedocs.yml`, and `tox.ini` for current Python/Sphinx usage.
- Removed stale Travis CI configuration (`.travis.yml`) as legacy/unused infrastructure.

## Migration notes (Extraction compatibility/runtime hardening patch)

- Added regression coverage to keep extraction header parsing compatible with current pandas releases (no `pandas.np` usage).
- Added extraction-path stdout-noise guard coverage to keep CLI summary output clean and script-safe.
- Tightened backfill persistence reporting so `filing_party_persist_path` is only surfaced when a filing-party parquet artifact actually exists.

## Migration notes (Alternate-root raw refdata bootstrap hardening patch)

- `refdata refresh` now resolves raw SEC source inputs with a deterministic fallback chain: configured `<project_root>/refdata/sec_sources` first, then canonical bundled `refdata/sec_sources`.
- Fallback is limited to raw-source bootstrap for `refdata refresh`; runtime artifact destinations (download/cache root, merged index path, normalized output root) remain bound to configured runtime paths.
- Missing raw inputs now fail with a clearer actionable error listing checked roots and remediation guidance.

## Migration notes (README positioning + roadmap cleanup patch)

- Repositioned README framing from special-situations-first to general-purpose EDGAR ingestion/operator workflow, with special situations called out as one example use case.
- Added explicit design-philosophy boundaries (ingestion-focused, metadata-oriented extraction, downstream-analysis handoff).
- Replaced legacy TODO list and historical performance blocks with a structured prioritized roadmap.

## Migration notes (Local lookup/indexing patch)

- Added operator-facing local lookup index artifacts under `refdata/normalized/`:
  - `local_lookup_filings.parquet`
  - `local_lookup_artifacts.parquet`
- Added `py-sec-edgar lookup refresh` to deterministically rebuild local lookup artifacts from merged index metadata, local download/extracted paths, and optional `filing_parties.parquet`.
- Added `py-sec-edgar lookup query` for fast local operator lookup across filings/artifacts with bounded human-readable output and `--json` machine mode.

## Migration notes (Lookup hardening patch)

- Hardened default lookup refresh/query behavior to be local-first for filings scope: `local_lookup_filings.parquet` now contains only local-present filings, deduped by accession (fallback filename).
- Added deterministic filings rollup fields (`submission_path_count`, local extracted-file rollups, and max-preserved filing-party counts) with stable representative field selection.
- Preserved path-granular artifact inventory under `local_lookup_artifacts.parquet`.
- Added explicit merged-index-wide filings inventory opt-in via `py-sec-edgar lookup refresh --include-global-filings` and query access via `py-sec-edgar lookup query --scope filings --all`.
