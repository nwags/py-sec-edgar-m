# Wave 7.1 Migration Note (`py-sec-edgar-m`)

Wave 7.1 for this repository is **package-side release-execution hardening only**.

## Scope (What Wave 7.1 Does)

- Defines this repo's participation in package-side RC/stable execution for `m-cache-shared-ext`.
- Defines repo-side validation/signoff/evidence obligations.
- Defines repo-side blocker taxonomy and rollback obligations.
- Defines readiness criteria for entering the comprehensive cross-application user-testing program.

## Explicit Non-Goals (Frozen in Wave 7.1)

- No runtime behavior changes.
- No CLI/API semantic changes.
- No shared public API broadening.
- No cleanup/removal work in this pass.

## Role Boundary

- This repo remains a conservative validator/signoff consumer.
- This repo does **not** define package governance ownership or package-wide approval authority.
- Repo artifacts remain participation-focused (validation/signoff/blocker/rollback obligations only).

## Safety Freeze (Unchanged)

- `py_sec_edgar.wave4_shared` remains the first-hop facade.
- `m-cache sec aug submit-run` and `submit-artifact` remain validate-only/non-persisting.
- SEC no-dual-authority posture remains unchanged.
- SEC-local authority/identity/provenance/storage/execution internals remain local.

## Cleanup Freeze (Unchanged)

Still deferred in Wave 7.1:

- env alias removal,
- flat shim removal,
- `augmentations` alias removal,
- direct-import cleanup,
- SEC-local externalization,
- shared public API expansion.

See `docs/standardization/wave7_1/` for repo-side Wave 7.1 execution obligations.
