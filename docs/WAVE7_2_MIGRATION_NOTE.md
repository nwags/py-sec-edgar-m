# Wave 7.2 Migration Note (`py-sec-edgar-m`)

Wave 7.2 for this repository is a **minimal companion participation pass** for the first real shared RC cycle.

## Scope (What Wave 7.2 Does)

- Defines minimum local actions to participate in the first real shared RC cycle.
- Defines exact validation/signoff/evidence inputs expected for central-bundle ingestion.
- Defines exact rollback-readiness obligations for this repo's signoff input.

## Explicit Non-Goals (Frozen in Wave 7.2)

- No runtime behavior changes.
- No CLI/API semantic changes.
- No shared public API broadening.
- No cleanup/removal work.

## Safety and Facade Freeze

- `py_sec_edgar.wave4_shared` remains first-hop facade.
- SEC no-dual-authority posture remains unchanged.
- Non-pilot validate-only/non-persisting submit behavior remains unchanged.
- `aug` remains canonical and `augmentations` remains compatibility alias.

## Companion-Only Boundary

This repo provides validator/signoff inputs to the central bundle under:

- `evidence/candidates/<tag>/consumer/py-sec-edgar-m/`

It does not define package-governance ownership or operate a parallel release process.
