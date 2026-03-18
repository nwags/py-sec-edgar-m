=====
Usage
=====

Refresh normalized SEC reference data:

.. code-block:: console

    py-sec-edgar refdata refresh

Refresh EDGAR full index files:

.. code-block:: console

    py-sec-edgar index refresh

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
