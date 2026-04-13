# Consumer Signoff Input

- candidate tag: `v0.1.0-rc2`
- repo: `py-sec-edgar-m`
- release role: `Consumer Validator/Signoff Contributor`

## RC Consumption

- consumption method: `M_CACHE_SHARED_EXT_SRC="${M_CACHE_SHARED_EXT_SRC:-../m-cache-shared-ext}"; export PYTHONPATH="$M_CACHE_SHARED_EXT_SRC${PYTHONPATH:+:$PYTHONPATH}"`
- actual source path used: `../m-cache-shared-ext`
- active virtualenv: `/home/nick/Code/py-sec-edgar-m/.venv`

## Validation Commands Run

- `pytest -q` -> `290 passed, 1 warning`
- `pytest -q tests/test_wave6_external_shared_facade.py tests/test_m_cache_cli.py tests/test_wave4_protocol_readonly.py tests/test_api_augmentations.py` -> `25 passed`
- `M_CACHE_SHARED_SOURCE=external pytest -q tests/test_wave6_external_shared_facade.py` -> `5 passed`

## Rollback Readiness Check

- known-good rollback target identified: `v0.1.0-rc1`
- fallback mode confirmed: `M_CACHE_SHARED_SOURCE=local pytest -q tests/test_wave6_external_shared_facade.py::test_wave6_facade_falls_back_to_local_shared_package` -> `1 passed`
- required validation commands runnable after rollback: yes
- unresolved rollback blockers: none

## Safety Attestation

- `py_sec_edgar.wave4_shared` first-hop facade unchanged: yes
- non-pilot validate-only behavior unchanged: yes
- SEC no-dual-authority unchanged: yes
- `aug` canonical and `augmentations` alias unchanged: yes

## Signoff Outcome

- pin_confirmed: `true`
- validation_status: `passed`
- signoff_state: `pass`
- blockers: `[]`
- warnings: `[]`
- rollback_ready: `true`
