# `py-sec-edgar-m` RC Validation Matrix (Wave 7)

## Purpose

Define repo-specific RC validation and signoff obligations for `m-cache-shared-ext` candidates.

## Validation Role

- Role: conservative consumer/validator signoff.
- Not in scope: external package governance ownership or approval authority.

## Required RC Validation Commands

- `pytest -q`
- `pytest -q tests/test_wave6_external_shared_facade.py tests/test_m_cache_cli.py tests/test_wave4_protocol_readonly.py tests/test_api_augmentations.py`

## Required Pass Criteria

1. Canonical external pin is present and points to the candidate RC tag in `requirements/m_cache_shared_external.txt`.
2. Strict v1 facade contract remains valid through `py_sec_edgar.wave4_shared`.
3. Source modes are valid and unchanged:
   - `M_CACHE_SHARED_SOURCE=local`
   - `M_CACHE_SHARED_SOURCE=auto`
   - `M_CACHE_SHARED_SOURCE=external` (fail-loud semantics when unavailable still enforced).
4. No CLI/API drift:
   - `py-sec-edgar ...` compatibility surface unchanged,
   - `m-cache sec ...` additive canonical surface unchanged,
   - `aug` canonical + `augmentations` compatibility alias unchanged.
5. SEC authority boundaries unchanged:
   - non-pilot validate-only/non-persisting submit behavior unchanged,
   - no admin-write routing changes,
   - no new authority artifacts,
   - no-dual-authority posture unchanged.

## Blockers (RC Rejection for This Repo)

- Any test failure in required command set.
- Any observed runtime/CLI/API semantic drift.
- Any authority-boundary drift (pilot/non-pilot or no-dual-authority violations).
- Any accidental dependency on non-public external symbols.

## Required Evidence Artifact

Create and store:

- `docs/standardization/wave7/evidence/RC_SIGNOFF_<tag>.md`

Minimum fields:

- RC tag and pin string used,
- validation command outputs (pass/fail summary),
- source-mode checks summary (`local`, `auto`, `external`),
- explicit authority-boundary attestation,
- blocker list (or `none`),
- signoff decision: `accept` or `reject`.
