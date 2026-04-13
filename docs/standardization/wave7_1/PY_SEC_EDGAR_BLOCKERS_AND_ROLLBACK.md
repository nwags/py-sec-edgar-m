# `py-sec-edgar-m` Blocker Taxonomy and Rollback Obligations (Wave 7.1)

## Blocker Taxonomy

### `blocking_authority_drift`

Any change that weakens SEC no-dual-authority or non-pilot validate-only behavior.

### `blocking_behavior_drift`

Any runtime, CLI/API semantic, or compatibility-surface drift.

### `blocking_validation_failure`

Any failure in required RC/stable validation command sets.

### `warning_evidence_incomplete`

Evidence formatting/completeness issue that does not hide a safety/behavior failure.
Must be resolved before promotion decision finalization.

## RC/Stable Blocking Rule

- Any `blocking_*` status yields repo decision `reject` (RC) or `hold` (stable).
- Promotion recommendation from this repo requires `blocker_status=none`.

## Rollback Steps (Repo)

1. Re-pin to prior known-good stable tag.
2. Force local facade mode with `M_CACHE_SHARED_SOURCE=local`.
3. Re-run required validation commands.
4. Publish incident/recovery evidence using required handoff fields.
5. Keep repo decision at `hold` until blockers are resolved and revalidated.
