# `py-sec-edgar-m` Validation, Signoff, and Evidence Obligations (Wave 7.1)

## Required Validation Commands

- `pytest -q`
- `pytest -q tests/test_wave6_external_shared_facade.py tests/test_m_cache_cli.py tests/test_wave4_protocol_readonly.py tests/test_api_augmentations.py`

## Required Validation Assertions

1. Strict-v1 facade contract remains valid via `py_sec_edgar.wave4_shared`.
2. Source-mode behavior remains intact (`local`, `auto`, `external`).
3. Non-pilot validate-only submit behavior remains unchanged.
4. No-dual-authority safety remains unchanged.
5. CLI/API semantics remain unchanged for compatibility and additive canonical surfaces.
6. `aug` remains canonical and `augmentations` remains compatibility alias.

## Repo Signoff Obligations

RC candidate signoff must include:

- candidate tag and pin used,
- command set and result summaries,
- explicit authority/safety attestation,
- blocker taxonomy outcome,
- repo decision (`accept` or `reject`).

Stable candidate signoff must include:

- promoted version and source RC,
- confirmation that required RC validations and repo obligations were met,
- blocker status (`none` required for promote),
- rollback-readiness attestation,
- repo decision (`promote` or `hold`).

## Evidence and Handoff Contract (Flexible)

This repo defines required evidence fields and handoff fields, not rigid package-side storage conventions.

Required handoff fields:

- `candidate_id` (tag/version),
- `repo_id` (`py-sec-edgar-m`),
- `validation_commands_run`,
- `validation_result_summary`,
- `authority_boundary_attestation`,
- `blocker_status` (`none`/`present`),
- `blocker_codes` (if present),
- `signoff_decision`,
- `rollback_readiness`,
- `evidence_reference` (path/URL agreed by release execution process).
