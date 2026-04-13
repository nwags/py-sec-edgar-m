# `py-sec-edgar-m` Deferred Cleanup Register (Wave 7)

## Wave 7 Rule

Wave 7 is lifecycle hardening only. No cleanup/removal execution is performed here.

## Explicitly Deferred Items

1. Remove legacy env aliases (`PY_SEC_EDGAR_WAVE6_SHARED_SOURCE`, `PY_SEC_EDGAR_WAVE6_EXTERNAL_ROOT`).
2. Remove flat compatibility shims under `m_cache_shared/*`.
3. Remove `augmentations` compatibility alias.
4. Direct-import cleanup away from `py_sec_edgar.wave4_shared` first-hop facade.
5. Externalize SEC-local filing identity, authority routing, source-text-version derivation, provenance/storage/execution internals.
6. Broaden external shared public API beyond strict v1 subset.

## Earliest Retirement Criteria

All must be true before any cleanup wave is considered:

1. Multiple stable release cycles complete successfully.
2. Cross-repo RC validation remains consistently green.
3. Compatibility-impacting user-testing gate has passed when applicable.
4. Rollback confidence remains high and repeatedly demonstrated.
5. SEC authority boundaries remain safe under proposed cleanup.

## Additional SEC Conservatism Rule

SEC remains the most conservative shim-retirement case due to authority-boundary safety properties.
