# `py-sec-edgar-m` Wave 7 Governance Role

## Purpose

Record this repository's Wave 7 role in the external package lifecycle without redefining external governance.

## Role Statement

- This repo is a conservative **consumer/validator** for `m-cache-shared-ext` RC/stable promotion.
- This repo is **not** a co-owner or approver of external package governance policy beyond repo-scoped signoff obligations.

## Policy Boundaries

- External governance source-of-truth remains the external package governance process.
- Repo-local Wave 7 docs define only:
  - how `py-sec-edgar-m` validates RC/stable candidates,
  - what evidence this repo must provide,
  - what triggers rollback or release blocking for this repo.

## Public API Boundary Rule (Wave 7)

- Use strict first-public-API v1 subset only.
- No shared public API broadening in this wave.

## Required Facade/Fallback Freeze

- `py_sec_edgar.wave4_shared` remains required first-hop facade.
- No direct-import cleanup in this wave.
- No shim/fallback removals in this wave.
