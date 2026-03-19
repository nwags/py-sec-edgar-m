py-sec-edgar
============

`py-sec-edgar` is an operator-focused, general-purpose SEC EDGAR ingestion and workflow tool.
It acquires, normalizes, stores, and organizes filing data so downstream systems can run
analysis, enrichment, and strategy-specific processing. Special-situations workflows are one
example use case, not the only one.

Overview
========

Current capabilities include:

- reference-data normalization from SEC source files,
- EDGAR index refresh + merged parquet materialization,
- candidate selection and filing downloads,
- optional serial extraction and filing-party persistence/query.

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

Runtime Visibility and Logging
==============================

Commands that perform runtime work (`refdata refresh`, `index refresh`, `backfill`) support:

- `--verbose` for bounded recent activity output,
- `--quiet` for minimal completion output,
- `--log-level` for console verbosity,
- `--log-file` for optional file logging.

`backfill --summary-json` outputs machine-readable JSON on stdout.
Human-oriented progress/activity output is kept separate so JSON mode stays script-friendly.

Data / Artifact Layout
======================

Default paths (relative to project root):

- Download/cache root: `.sec_cache/Archives`
- Merged index parquet: `refdata/merged_idx_files.pq`
- Normalized parquet root: `refdata/normalized`
- Extracted filing content: alongside downloaded submission files in the cache tree.

Environment Overrides
=====================

You can override runtime roots without changing code:

- `PY_SEC_EDGAR_PROJECT_ROOT`
- `PY_SEC_EDGAR_DOWNLOAD_ROOT`
- `PY_SEC_EDGAR_MERGED_INDEX_PATH`
- `PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT`

Operator Notes
==============

- Local/dev default: `.sec_cache` under project root keeps working state easy to inspect and clean.
- Production/staging: prefer mounted storage paths via env overrides so cache and artifacts are durable and explicit.
- Recommended order for repeatable operations:

  1. `py-sec-edgar refdata refresh`
  2. `py-sec-edgar index refresh --skip-if-exists --save-idx-as-csv`
  3. `py-sec-edgar backfill ...`
  4. `py-sec-edgar filing-parties query ...`

Roadmap (Prioritized)
=====================

Priority 1 — Core Reliability & Usability
-----------------------------------------

- Expand testing coverage (pipeline, regression, fixtures).
- Faster content lookup (indexing over downloaded and normalized artifacts).

Priority 2 — Monitoring / Incremental Ingestion
------------------------------------------------

- RSS-based ingestion.
- Incremental updates without full reruns.
- Value:
  - faster awareness of new filings,
  - lower-latency ingestion,
  - reduced need for repeated large pulls.
- RSS complements index-based ingestion rather than replacing it.

Priority 3 — Ingestion Efficiency & Scale
-----------------------------------------

- Improve ingestion efficiency holistically, not just by adding threads.
- Evaluate concurrency, batching strategies, and elimination of redundant work.
- Use SEC bulk distribution mechanisms where applicable.
- Prefer bulk access paths over parallel scraping when bulk is more appropriate.

Priority 4 — Limited Metadata Extraction
----------------------------------------

- Filing/entity/relationship/subject metadata only.
- Deep extraction remains out of scope.

Future (Back Burner)
--------------------

- Workflow expansion.
- Rich query surfaces.
- Advanced downstream workflows.

Attribution
===========

This repo is based on the original `py-sec-edgar` project by Ryan S. McCoy:

- https://github.com/ryansmccoy/py-sec-edgar

This repository extends and refactors that foundation for current operator-focused SEC ingestion workflows.
Original licensing, attribution, and legal notices are preserved.
