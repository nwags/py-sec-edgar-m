# AGENTS.md

## Mission

Refactor `py-sec-edgar` from a legacy ticker-filtered filing downloader into a special-situations EDGAR ingestion tool for an AI-native hedge fund workflow.

The new system must prioritize:
1. correctness and repeatability,
2. SEC-compliant access behavior,
3. broad entity coverage beyond listed issuers,
4. fast bounded-concurrency downloads,
5. explicit schemas for issuer/entity/filing-party data,
6. reproducible local development in VS Code.

## Non-negotiables

- Do **not** preserve legacy behavior if it conflicts with correctness, SEC fairness, or the target hedge-fund use case.
- Do **not** use random browser user agents by default.
- Do **not** use rotating proxies by default.
- Do **not** exceed the configured global SEC request budget.
- Do **not** assume every relevant filer has a ticker.
- Do **not** center the data model on `cik_tickers.csv`.
- Prefer typed, testable, single-purpose modules over hidden side effects in `__init__.py`.
- Prefer explicit CLI commands over implicit behavior in `python -m py_sec_edgar`.

## Source of truth hierarchy

If there is conflict, use this order:

1. `docs/TARGET_ARCHITECTURE.md`
2. `docs/REFDATA_SCHEMA.md`
3. `docs/SEC_DATA_SOURCES.md`
4. `docs/SPECIAL_SITUATIONS_UNIVERSE.md`
5. tests
6. legacy code

## Current repo realities to correct

- The current runtime is effectively serial.
- The current downloader logic is not safe enough for SEC production use.
- The current reference-data model is too ticker-centric.
- The current settings default to periodic-report forms instead of special-situations / ownership / insider forms.

## Required architectural direction

Implement a staged pipeline:

1. build or refresh reference data,
2. build filing candidate universe from EDGAR indexes,
3. filter candidates by form/date/entity rules,
4. download complete submissions with bounded thread concurrency,
5. optionally extract/parse with separate CPU-oriented workers,
6. emit normalized metadata tables for downstream NLP/event extraction.

## Required runtime principles

- Separate network I/O from CPU parsing.
- Use a shared rate limiter across all workers.
- Use persistent HTTP sessions.
- Write files atomically.
- Record HTTP status and failure reasons.
- Make every step resumable and idempotent.

## Expected new repo capabilities

- Refresh SEC association/reference files from official SEC endpoints.
- Maintain issuer, entity, alias, and filing-party tables.
- Support forms relevant to:
  - beneficial ownership,
  - insider transactions,
  - proxies,
  - mergers / exchange offers / tender offers,
  - holdings,
  - current reports,
  - exempt offerings.
- Make it easy to run targeted backfills by form family, date range, issuer CIK, reporting-owner CIK, or manager name.

## What agents should modify first

1. Introduce new canonical docs in `docs/`.
2. Add a download script for SEC reference data.
3. Add a new reference-data builder module.
4. Replace legacy downloader internals with session + rate-limit + retries.
5. Add concurrent download orchestration.
6. Add tests for retry, filtering, and refdata normalization.
7. Only then deprecate legacy paths.

## What agents should not waste time on

- cosmetic doc rewrites,
- preserving obsolete proxy workflows,
- keeping the current `settings.py` shape if a cleaner config object is better,
- preserving the exact old CSV schema.

## Delivery standard

Every meaningful change should include:
- code,
- tests,
- doc updates,
- a short migration note when behavior changes.
