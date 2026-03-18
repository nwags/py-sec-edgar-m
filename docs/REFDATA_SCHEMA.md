# REFDATA_SCHEMA.md

## Why the old schema is insufficient

`cik_tickers.csv` assumes the world is made of listed issuers with tickers.
That fails for many EDGAR actors that matter for 13D/G, 13F, Form 4, tender offers, activist campaigns, SPVs, insiders, funds, and acquirers.

## Canonical normalized tables

### issuers
Publicly relevant issuers.

Suggested columns:
- `issuer_cik`
- `ticker`
- `issuer_name`
- `exchange`
- `sic`
- `is_mutual_fund`
- `is_etf`
- `source`
- `source_updated_at`

### entities
All EDGAR filing entities, including non-ticker actors.

Suggested columns:
- `entity_cik`
- `entity_name`
- `entity_type`
- `has_ticker`
- `ticker`
- `is_individual`
- `is_fund`
- `is_manager`
- `is_issuer`
- `source`
- `source_updated_at`

### entity_aliases
Name harmonization table.

Suggested columns:
- `entity_cik`
- `alias_name`
- `alias_type`
- `normalized_alias`
- `source`

### series_classes
Fund / series / class mappings.

Suggested columns:
- `fund_cik`
- `series_id`
- `series_name`
- `class_id`
- `class_name`
- `class_ticker`
- `source`

### filing_parties
Relationship table between a filing and the relevant actors.

Suggested columns:
- `accession_number`
- `form_type`
- `filing_date`
- `party_role`
- `party_cik`
- `party_name`
- `issuer_cik`
- `issuer_name`
- `source`
- `source_filename`

Initial extraction foundation (current scope):
- supported forms: `SC 13D`, `SC 13D/A`, `SC 13G`, `SC 13G/A`, `3`, `4`, `5`
- currently emitted roles: `subject_company`, `issuer`, `reporting_owner`, `director`, `officer`, `ten_percent_owner`
- identifiers should use canonical normalization where available (e.g., zero-padded CIK)
- unsupported forms should emit no filing-party rows rather than unreliable inferred rows

Persistence contract:
- canonical normalized artifact: `refdata/normalized/filing_parties.parquet`
- upsert/dedupe key: `accession_number`, `party_role`, `party_cik`, `party_name`, `source_filename`
- writes must be deterministic and idempotent across repeated backfill runs

## Entity roles we care about

- issuer
- reporting_owner
- beneficial_owner
- filer
- subject_company
- offeror
- acquiring_person
- manager
- other_included_manager
- insider
- director
- officer

## Reference-file precedence

1. official SEC ticker / exchange / mutual-fund association files
2. SEC `ticker.txt`
3. SEC current all-CIK text file
4. investment company series/class CSV
5. historical EDGAR index-derived entity discovery
6. parsed filing-party extraction

## Output format preference

Use parquet for normalized tables.
CSV exports are optional convenience outputs, not canonical storage.

## Filtering contract

Runtime candidate filtering should resolve identifiers from normalized parquet tables under `refdata/normalized/`.
Use canonical normalized keys only:

- `issuers.issuer_cik` (zero-padded 10-digit CIK)
- `issuers.ticker` (uppercase ticker)
- `entities.entity_cik` (zero-padded 10-digit CIK)

Legacy ticker-list inputs can be accepted as a compatibility bridge, but they must resolve through these canonical parquet keys rather than through `cik_tickers.csv`.
