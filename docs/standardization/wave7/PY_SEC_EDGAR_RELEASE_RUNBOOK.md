# `py-sec-edgar-m` RC/Stable Runbook (Wave 7)

## Purpose

Define repo-scoped RC/stable signoff, evidence, and rollback steps for lifecycle hardening.

## RC Signoff Obligations

1. Pin exact candidate RC in `requirements/m_cache_shared_external.txt`.
2. Run required RC validation matrix commands.
3. Confirm no behavior drift:
   - no runtime behavior changes,
   - no CLI/API semantic changes,
   - no shared public API broadening.
4. Confirm boundary freeze:
   - `py_sec_edgar.wave4_shared` remains first-hop facade,
   - non-pilot validate-only submit behavior unchanged,
   - SEC no-dual-authority unchanged.
5. Write signoff evidence artifact.

## Stable Promotion Obligations (This Repo)

A stable promotion is signoff-eligible from this repo only when:

1. RC validation matrix is green for the exact candidate tag.
2. Repo evidence artifact is complete and archived.
3. No unresolved blocker incidents exist for this repo.
4. Maintainer/developer validation remains green.
5. User-testing gate policy is respected:
   - mandatory for compatibility-impacting releases,
   - not mandatory for every routine stable release,
   - never a replacement for maintainer/developer validation or RC matrix validation.

## Evidence Artifact Requirements

For each candidate:

- RC signoff note:
  - `docs/standardization/wave7/evidence/RC_SIGNOFF_<tag>.md`
- Stable signoff note:
  - `docs/standardization/wave7/evidence/STABLE_SIGNOFF_<version>.md`
- Incident note (only if needed):
  - `docs/standardization/wave7/evidence/INCIDENT_<date>_<tag-or-version>.md`

Each signoff note must include:

- candidate tag/version,
- pin used,
- command set and results,
- authority-boundary attestation,
- decision and approver identity,
- rollback readiness statement.

## Rollback Steps (Repo-Scoped)

1. Re-pin to prior known-good tag in `requirements/m_cache_shared_external.txt`.
2. Force local facade mode:
   - `M_CACHE_SHARED_SOURCE=local`
3. Re-run required RC validation matrix commands.
4. Record incident note with:
   - trigger,
   - impact,
   - rollback timestamp,
   - recovery validation result,
   - follow-up owner/actions.

## Rejection Handling

- If RC fails: mark candidate `reject` in RC evidence note.
- Do not promote from this repo.
- Keep rollback guidance and known-good pin visible in incident/signoff notes.
- Re-evaluate only after new candidate tag is available.
