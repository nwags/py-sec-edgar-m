# Wave 4 Migration Note (`py-sec-edgar-m`)

This pass adds Wave 4.1 shared-seam and canonical naming normalization while keeping producer write-path behavior non-executing.

## Implemented Now (This Repo)

- Local shared-seam modules for extractable Wave 4 boundaries:
  - shared outer models/enums
  - schema/validator helpers
  - metadata packers
  - target/source-version helper plumbing
- Producer target descriptor exposure for filing text targets:
  - API: `GET /filings/{accession_number}/augmentation-target-descriptor`
  - CLI read surface remains additive via `m-cache sec aug inspect-target`
- Canonical `m-cache sec aug` family normalization (additive, compatibility-first):
  - `inspect-target`
  - `status` (narrow single-run status read surface)
  - `submit-run` (validate-only, non-persisting)
  - `submit-artifact` (validate-only, non-persisting)
  - `events` (timeline/audit read surface)
- Compatibility surfaces intentionally preserved:
  - `inspect-runs` for richer listing/query,
  - `inspect-artifacts` for artifact inspection.
- Deterministic filing `source_text_version` (`sha256:...`) and additive `augmentation_stale` reporting.
- Read-back enrichment on shared augmentation run/artifact metadata with producer fields already present in SEC authority (`producer_version`, `producer_run_id`, `pipeline_id`, `model_id`, `payload_schema_version`).

## Explicitly Not Implemented In This Pass

`py-sec-edgar-m` is **not** one of the first Wave 4 producer-protocol write-path pilot repos.

No new protocol write path was added here:
- no new protocol submission endpoint family,
- no live protocol CLI write path (new submit commands are validate-only and non-persisting),
- no new protocol persistence layer/inbox.

Producer write-path pilot work remains reserved for the next pass after pilot repos validate the protocol.

## Authority Mapping (No Dual Authority)

- SEC sidecar/submission/provenance artifacts remain the sole operational authority:
  - `augmentation_submissions.parquet`
  - `augmentation_items.parquet`
  - `augmentation_governance_events.parquet`
  - `augmentation_submission_lifecycle_events.parquet`
  - SEC companion provenance artifacts
- Shared `augmentation_runs.parquet` and `augmentation_events.parquet` remain additive metadata projections over SEC-authoritative artifacts.
- No competing authority store was introduced.

## Payload Ownership Rule

- Payload schema ownership remains external/service-owned.
- Repo-side Wave 4 validation is outer-envelope focused only; payload bodies are not interpreted as a shared schema.
