# User Testing Report: py-sec-edgar-m vs promoted RC9 baseline

- Initial pass date (UTC): 2026-04-13
- Remediation pass date (UTC): 2026-04-13
- Repo: `py-sec-edgar-m`
- Mode: regular user-testing + focused post-user-testing remediation
- Baseline target: promoted RC9

## Remediation scope executed

1. Align shared-package baseline pin to promoted RC9.
2. Keep canonical CLI entrypoints available in active venv.
3. Investigate API smoke bind failure for repo-local vs environment root cause.
4. Improve filing-parties prerequisite/operator messaging.
5. Improve monitor/reconcile download-failure context messaging.
6. Re-run targeted user-testing slice and refresh evidence.

## Post-remediation status by known issue

### 1) Requested/promoted RC9 baseline mismatch
- Previous: `requirements/m_cache_shared_external.txt` pinned to `v0.1.0-rc2`.
- Remediation: updated pin to `v0.1.0-rc9`.
- Current status: **partially resolved**.
- Notes:
  - Pin is now RC9 (repo-local alignment fixed).
  - External install remains environment-limited in this workspace (`pip install -r requirements/m_cache_shared_external.txt` fails due outbound GitHub/DNS restrictions), so runtime package presence cannot be fully validated here.
- Ownership: shared-package + test harness/environment.

### 2) API smoke blocked by bind failure
- Remediation investigation:
  - `python -m py_sec_edgar.service_runtime api` still exits with `could not bind on any address`.
  - Independent socket probe fails with `PermissionError: [Errno 1] Operation not permitted` at socket creation.
- Current status: **environment-limited (not repo-local)**.
- Ownership: test harness/environment.

### 3) Filing-parties query prerequisite/operator ergonomics
- Previous: only reported missing artifact path.
- Remediation: improved error guidance to include explicit next-step command with `--persist-filing-parties`.
- Current status: **resolved**.
- Ownership: docs/operator ergonomics (repo-local message improvement delivered).

### 4) Low-context `Download failed` monitor/reconcile messaging
- Previous: repeated low-information `Download failed` lines.
- Remediation: failure log now includes reason/status/attempt/retry_exhausted/url/filepath.
- Current status: **resolved** for operator clarity.
- Ownership: docs/operator ergonomics + repo-local logging clarity.

## Code changes implemented

1. `requirements/m_cache_shared_external.txt`
   - RC pin updated to `v0.1.0-rc9`.
2. `py_sec_edgar/filing_parties_query.py`
   - missing-artifact message now includes actionable backfill guidance.
3. `py_sec_edgar/download.py`
   - download-failure warning message now includes structured context directly in log text.
4. `tests/test_filing_parties_query_cli.py`
   - assertion updated for enhanced filing-parties guidance.
5. `tests/test_download.py`
   - new test asserts failure logs contain contextual details.
6. `tests/test_wave6_external_shared_facade.py`
   - external pin assertion updated from rc2 to rc9.

## Commands run in remediation pass

1. `. .venv/bin/activate && pip install -r requirements/m_cache_shared_external.txt`
2. `. .venv/bin/activate && pytest -q tests/test_download.py tests/test_filing_parties_query_cli.py`
3. `. .venv/bin/activate && pytest -q tests/test_wave6_external_shared_facade.py tests/test_m_cache_cli.py tests/test_wave4_protocol_readonly.py tests/test_api_augmentations.py`
4. `. .venv/bin/activate && which py-sec-edgar && which m-cache && py-sec-edgar --help && m-cache --help`
5. `cat requirements/m_cache_shared_external.txt`
6. `. .venv/bin/activate && pip show m-cache-shared-ext || true`
7. `. .venv/bin/activate && py-sec-edgar filing-parties query --json`
8. `. .venv/bin/activate && m-cache sec monitor poll --no-warm --summary-json --progress-json --date-from 2026-04-10 --date-to 2026-04-12`
9. `. .venv/bin/activate && m-cache sec reconcile run --summary-json --progress-json --recent-days 1`
10. `. .venv/bin/activate && PY_SEC_EDGAR_API_HOST=127.0.0.1 PY_SEC_EDGAR_API_PORT=19876 python -m py_sec_edgar.service_runtime api` + `curl` smoke
11. `. .venv/bin/activate && python socket bind probe`

## Test/smoke results (remediation)

1. `pytest -q tests/test_download.py tests/test_filing_parties_query_cli.py`
   - **17 passed**
2. `pytest -q tests/test_wave6_external_shared_facade.py tests/test_m_cache_cli.py tests/test_wave4_protocol_readonly.py tests/test_api_augmentations.py`
   - **25 passed**
3. CLI sanity:
   - `py-sec-edgar` present
   - `m-cache` present
4. filing-parties prerequisite messaging:
   - improved actionable guidance confirmed
5. monitor/reconcile failure context:
   - improved contextual `Download failed (...)` output confirmed
6. API smoke:
   - still blocked by environment socket restrictions

## Updated defect classification

1. `baseline_install_blocked_external_access`
- Severity: medium
- Ownership: test harness/environment
- Status: open (environment-limited)

2. `api_socket_bind_blocked_in_workspace`
- Severity: medium
- Ownership: test harness/environment
- Status: open (environment-limited)

3. `filing_parties_missing_artifact_message_low_guidance`
- Severity: low
- Ownership: repo-local/docs ergonomics
- Status: closed

4. `monitor_reconcile_download_failure_low_context`
- Severity: low
- Ownership: repo-local/docs ergonomics
- Status: closed

## Evidence files

### Existing initial-pass artifacts
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/artifacts/*`

### New remediation artifacts
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/baseline_cli_sanity.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/pin_install_attempt.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/pytest_remediation_targeted.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/pytest_user_testing_slice.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/filing_parties_message_check.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/monitor_reconcile_smoke.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/api_smoke_postfix.txt`
- `evidence/candidates/v0.1.0-rc9/consumer/py-sec-edgar-m/remediation_artifacts/socket_bind_probe.txt`

## Final status (post-remediation)

- Repo-local remediation status: **ready** for signoff on addressed operator-surface issues.
- Workspace-wide signoff caveat: **environment-limited** for external shared-package installation and API bind smoke in this sandbox.
