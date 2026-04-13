# `py-sec-edgar-m` Signoff Mapping and Rollback Readiness (Wave 7.2)

## `SIGNOFF.json` Contract (Exact Fields)

Machine-readable companion output must include exactly:

1. `candidate_tag`
2. `repo`
3. `release_role`
4. `pin_confirmed`
5. `validation_status`
6. `signoff_state`
7. `blockers`
8. `warnings`
9. `rollback_ready`

## `signoff_state` Vocabulary (Exact)

Use only:

- `pass`
- `warn`
- `block`

No alternate terminal vocabulary is allowed.

## Exact Signoff Mapping

- `pass` when all required validation commands pass, `pin_confirmed=true`, `blockers=[]`, and `rollback_ready=true`.
- `warn` when required validations pass and no blockers exist, but non-blocking warnings remain; `rollback_ready` must still be `true`.
- `block` when any required validation fails, any blocker exists, pin is not confirmed, safety-boundary attestation fails, or rollback readiness is not demonstrated.

Recommended `validation_status` values for this repo input:

- `passed` when required validation command set is green,
- `failed` when any required validation command fails.

## Exact Rollback-Readiness Conditions

Set `rollback_ready=true` only when all are true:

1. known-good rollback target is identified,
2. fallback mode is confirmed (`M_CACHE_SHARED_SOURCE=local`),
3. required validation commands are runnable after rollback,
4. no unresolved rollback blocker remains.

Otherwise set `rollback_ready=false` and `signoff_state=block`.
