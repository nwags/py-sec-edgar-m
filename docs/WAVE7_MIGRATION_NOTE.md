# Wave 7 Migration Note (`py-sec-edgar-m`)

Wave 7 for this repository is **lifecycle hardening only**.

## Scope (What Wave 7 Does)

- Adds repo-scoped release lifecycle policy docs for:
  - RC validation/signoff obligations,
  - stable-promotion obligations,
  - evidence artifact requirements,
  - rollback/incident response,
  - deferred cleanup criteria.
- Records this repo's role as a conservative **consumer/validator** of `m-cache-shared-ext`.

## Explicit Non-Goals (Frozen in Wave 7)

- No new extraction scope.
- No runtime behavior changes.
- No CLI/API semantic changes.
- No shared public API broadening.
- No direct-import cleanup wave.
- No shim/fallback removal wave.

## Role and Authority Freeze (Unchanged)

- `py_sec_edgar.wave4_shared` remains the required first-hop facade.
- This repo remains non-pilot for live producer write-path behavior.
- `m-cache sec aug submit-run` and `submit-artifact` remain validate-only/non-persisting.
- No admin-write routing changes.
- No new authority artifacts.
- SEC no-dual-authority posture remains unchanged.

## Compatibility Surface Freeze (Unchanged)

- `py-sec-edgar ...` remains compatibility/operator surface.
- `m-cache sec ...` remains additive canonical surface.
- `aug` remains canonical; `augmentations` remains compatibility alias.

## Deferred Cleanup Policy in This Wave

The following remain explicitly deferred in Wave 7:

- removing legacy env aliases,
- removing flat compatibility shims,
- removing `augmentations` alias,
- externalizing SEC-local authority/identity/storage logic,
- broadening external shared public API.

See `docs/standardization/wave7/` for repo-scoped lifecycle obligations and templates.
