You are refactoring a legacy Python repo named `py-sec-edgar`.

Your job is to align the repo with the canonical files in `docs/` and the instructions in `AGENTS.md`.

Do not preserve old behavior if it conflicts with:
- correctness,
- SEC fair-access compliance,
- bounded concurrency,
- the new reference-data model,
- the special-situations hedge-fund use case.

Repository facts:
- The current runtime is effectively serial.
- The current downloader uses random browser user agents and optional rotating proxies.
- The repo currently centers filtering on `refdata/cik_tickers.csv`.
- The default forms list is periodic-report oriented.

Target outcomes:
1. Add a safe concurrent downloader using threads for I/O.
2. Add explicit HTTP status handling, retries, sessions, atomic writes, and a shared rate limiter.
3. Introduce a new reference-data package that normalizes official SEC association files and related SEC reference datasets.
4. Replace ticker-centric assumptions with issuer/entity/filing-party tables.
5. Add a CLI for:
   - refreshing refdata,
   - refreshing indexes,
   - backfilling filings by form family and date range.

Constraints:
- Use Python.
- Keep changes readable and well-factored.
- Add or update tests for each substantive behavior change.
- Update docs as part of the same patch set.
- Prefer parquet for normalized reference outputs.
- Keep extraction serial unless profiling justifies moving it to process-based parallelism later.

Deliver work in phases and explain tradeoffs briefly in commit-style summaries.
