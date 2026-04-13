# Wave 2 Migration Note (`py-sec-edgar-m`)

This note summarizes Wave 2 provider/rate-limit/resolve/API-semantic alignment for this repository.

## What Became Canonical in Wave 2

- Canonical provider inspection surface:
  - `m-cache sec providers list`
  - `m-cache sec providers show --provider <provider_id>`
- Canonical resolve surface:
  - `m-cache sec resolve filing --accession-number <id> --resolution-mode <mode>`
- Canonical shared resolution-mode vocabulary:
  - `local_only`
  - `resolve_if_missing`
  - `refresh_if_stale` (explicitly unsupported on this path in Wave 2; transparent failure)
- Additive API resolution transparency on existing endpoints:
  - `GET /filings/{accession_number}` includes `resolution_meta` (local-by-default, optional explicit content-resolution probe)
  - `GET /filings/{accession_number}/content` emits additive `X-M-Cache-*` resolution/provider/rate-limit headers and returns structured `resolution_meta` in error payloads.

## Compatibility and Aliases Preserved

- Operator compatibility surface remains: `py-sec-edgar ...`
- Canonical additive surface remains: `m-cache sec ...`
- `aug` remains canonical and `augmentations` remains the backward-compatible alias.
- Legacy `py-sec-edgar ...` machine-output defaults remain unchanged unless explicit additive selectors are used.

## Provider, Rate-Limit, and Degradation Visibility

- Provider inspection remains offline/deterministic via local normalized authority (`provider_registry.parquet` plus effective config overlay).
- Provider details now include additive effective-policy fields (`effective_enabled`, `effective_auth_present`, rate-limit state snapshot, expected error/degradation metadata).
- Canonical resolve/output metadata explicitly surfaces:
  - `provider_requested`
  - `provider_used`
  - `remote_attempted`
  - `rate_limited`
  - `retry_count`
  - `served_from`
  - `reason_code`
  - `deferred_until` (nullable)
- `resolution_events.parquet` remains the shared/canonical comparison surface and now carries additive provider/rate-limit/defer fields where available.

## SEC-Specific Provenance Companion Strategy (Still Additive)

- Shared canonical artifact: `refdata/normalized/resolution_events.parquet`
- SEC-specific companion artifact: `refdata/normalized/filing_resolution_provenance.parquet`

Wave 2 keeps this strategy unchanged:
- no forced replacement of SEC companion provenance,
- no broad historical rewrite/migration,
- additive field enrichment only.

## Not Introduced in Wave 2

- No cross-repo shared-package extraction.
- No SEC augmentation architecture redesign.
- No broad monitor/reconcile/backfill internal redesign.
- No mandatory new dedicated `/filings/{accession_number}/resolve` endpoint; additive transparency was implemented on existing endpoints.
