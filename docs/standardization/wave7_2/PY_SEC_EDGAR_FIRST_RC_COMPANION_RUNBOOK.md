# `py-sec-edgar-m` Wave 7.2 Companion Runbook (First Real Shared RC)

## Purpose

Define the minimum participation actions for this repo in the first real shared RC cycle.

## Minimum Local RC-Consumption Step (Portable)

Use a configurable sibling-source path in the active virtualenv and consume it via `PYTHONPATH`:

```bash
# inside py-sec-edgar-m repo
source .venv/bin/activate
M_CACHE_SHARED_EXT_SRC="${M_CACHE_SHARED_EXT_SRC:-../m-cache-shared-ext}"
export PYTHONPATH="$M_CACHE_SHARED_EXT_SRC${PYTHONPATH:+:$PYTHONPATH}"
```

Required evidence note:

- record the actual local RC-consumption method/path used (for example `PYTHONPATH` + `../m-cache-shared-ext`) in `SIGNOFF.md`.

## Shared RC Pin Confirmation

1. Confirm candidate tag from the central candidate metadata.
2. Confirm local repo pin references the same candidate in `requirements/m_cache_shared_external.txt`.
3. Set `pin_confirmed=true` only when candidate tag alignment is exact.

## Exact Validation Commands

Run these commands for companion signoff input:

```bash
pytest -q
pytest -q tests/test_wave6_external_shared_facade.py tests/test_m_cache_cli.py tests/test_wave4_protocol_readonly.py tests/test_api_augmentations.py
M_CACHE_SHARED_SOURCE=external pytest -q tests/test_wave6_external_shared_facade.py
```

## Central Bundle Input Location (Exact)

Emit this repo's inputs under:

- `evidence/candidates/<tag>/consumer/py-sec-edgar-m/SIGNOFF.json`
- `evidence/candidates/<tag>/consumer/py-sec-edgar-m/SIGNOFF.md`

These are central-bundle ingestion inputs, not a separate SEC-local release flow.
