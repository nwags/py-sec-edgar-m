# `py-sec-edgar-m` User-Testing Start Readiness (Wave 7.1)

## Policy

Comprehensive cross-application user testing starts only when all start-gate conditions are met.

User testing remains:

- post-Wave-7.1 stabilization,
- pre-cleanup / pre-shim-retirement,
- never a replacement for maintainer/developer validation or RC matrix validation.

## Required Start-Gate Conditions

1. Wave 7.1 implementation is complete for this repo.
2. One shared RC execution cycle has completed across all four repos.
3. Central evidence bundle flow is working end-to-end.
4. Rollback path has been verified with reproducible recovery evidence.
5. No open blocking release-lifecycle incident remains.

## Repo Readiness Output

This repo's readiness note must report:

- `ready_for_user_testing`: `true|false`,
- unmet conditions (if any),
- latest candidate reference,
- evidence references used for gate determination.
