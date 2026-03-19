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
