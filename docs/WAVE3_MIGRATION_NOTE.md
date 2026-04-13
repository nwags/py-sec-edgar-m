# Wave 3 Migration Note (`py-sec-edgar-m`)

This note summarizes the Wave 3 closure changes for shared augmentation metadata/contracts while preserving SEC augmentation authority.

## What Became Canonical in Wave 3

- Canonical shared augmentation metadata companions are now materialized additively:
  - `refdata/normalized/augmentation_runs.parquet`
  - `refdata/normalized/augmentation_events.parquet`
- Canonical shared `m-cache sec aug` read vocabulary now includes thin wrappers:
  - `m-cache sec aug list-types`
  - `m-cache sec aug inspect-target --accession-number <id>`
  - `m-cache sec aug inspect-runs ...`
  - `m-cache sec aug inspect-artifacts ...`
  - `m-cache sec aug events ...`
- Additive API augmentation transparency on existing endpoints:
  - `GET /filings/{accession_number}` includes `augmentation_meta`
  - `GET /filings/{accession_number}/content` includes additive `X-M-Cache-Augmentation-*` headers

## Compatibility and Source of Truth Boundaries

- `py-sec-edgar ...` remains the compatibility/operator surface.
- `m-cache sec ...` remains the additive canonical surface.
- `aug` remains canonical and `augmentations` remains the backward-compatible alias.
- Existing SEC augmentation artifacts remain the single authority:
  - `augmentation_submissions.parquet`
  - `augmentation_items.parquet`
  - `augmentation_governance_events.parquet`
  - `augmentation_submission_lifecycle_events.parquet`
  - SEC companion provenance artifacts
- `augmentation_runs.parquet` and `augmentation_events.parquet` are additive shared companions derived from SEC-authoritative artifacts; they do not replace SEC-native authority.

### SEC `augmentation_artifacts` equivalent (operator shorthand)

SEC does not use one single `augmentation_artifacts.parquet` file.  
The SEC-local equivalent is the authoritative sidecar set:

- artifact payload rows: `augmentation_items.parquet`
- submission/run envelope authority: `augmentation_submissions.parquet`
- governance/lifecycle/provenance companions:
  - `augmentation_governance_events.parquet`
  - `augmentation_submission_lifecycle_events.parquet`
  - SEC-specific companion provenance artifacts

Wave 3 shared companions (`augmentation_runs.parquet`, `augmentation_events.parquet`) are metadata projections over this SEC-local authority.

## Shared vs Domain-Local Schema Rule

- Wave 3 standardizes outer metadata/contracts only (run/event/artifact/API metadata).
- SEC payload bodies remain domain-local and service-local.
- No universal payload-body schema is enforced in this wave.

## Preserved SEC Semantics

- No changes to accession identity semantics.
- No changes to filing identity semantics.
- No changes to filing-party behavior.
- No changes to augmentation overlay/lifecycle/governance execution semantics.
- No redesign of `/augmentations/...` API families.

## Reserved for Later Waves

- Any universal augmentation payload-body schema.
- Broad augmentation execution redesign across repos.
- Extraction of SEC adapters/resolvers/operational loops/augmentation execution internals into shared packages.
- Replacement of SEC-specific companion provenance with forced generic internals.
