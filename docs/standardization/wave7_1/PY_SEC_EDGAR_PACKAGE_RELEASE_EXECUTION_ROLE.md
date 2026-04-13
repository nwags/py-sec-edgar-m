# `py-sec-edgar-m` Wave 7.1 Package-Release Execution Role

## Purpose

Define this repository's role in package-side RC/stable execution for `m-cache-shared-ext`.

## Role

- Conservative validator/signoff consumer for non-pilot and no-dual-authority safety.
- Participant in shared release execution lifecycle.
- Not a package governance owner or package-wide approval authority.

## Participation Contract

For each RC/stable candidate, this repo is responsible for:

1. consuming the candidate pin,
2. running required repo validation,
3. producing repo signoff evidence,
4. reporting blocker/warning status,
5. issuing repo signoff recommendation (`accept`/`reject` for RC, `promote`/`hold` for stable).

## Boundaries This Repo Must Preserve

- `py-sec-edgar ...` compatibility surface.
- `m-cache sec ...` additive canonical surface.
- `aug` canonical and `augmentations` compatibility alias.
- `py_sec_edgar.wave4_shared` first-hop facade strategy.
- SEC no-dual-authority and non-pilot validate-only safety posture.
