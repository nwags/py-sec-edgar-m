# Wave 5 Migration Note (`py-sec-edgar-m`)

This pass introduces the first in-repo `m_cache_shared` extraction cut while preserving standalone runtime behavior and SEC authority boundaries.

## Implemented Now (This Repo)

- Added in-repo shared package `m_cache_shared` for the minimal Wave 5 extraction slice:
  - protocol models and enums/vocabularies,
  - schema loaders and outer-envelope validators,
  - pure metadata packers/builders,
  - thin JSON payload helper plumbing.
- Converted `py_sec_edgar.wave4_shared` into a shim/facade over extracted shared symbols for the first adoption cycle.
- Kept CLI/API handlers local while adopting shared helpers behind local wrappers.

## Explicitly Preserved in Wave 5

- `py-sec-edgar ...` remains compatibility/operator surface.
- `m-cache sec ...` remains additive canonical surface.
- `aug` remains canonical and `augmentations` remains compatibility alias.
- `submit-run` and `submit-artifact` remain validate-only and non-persisting.
- Payload schemas remain producer/service-owned; shared validation is outer-envelope only.

## Explicitly Not Extracted in This Pass

- Target descriptor building and source-text-version derivation helpers.
- Filing identity/path derivation.
- Authority routing and execution behavior.
- Shared run/event projection logic derived from SEC authority.
- SEC sidecar/submission/provenance internals and all storage authority behavior.

## Authority Mapping (No Dual Authority)

- SEC sidecar/submission/provenance artifacts remain the sole operational authority:
  - `augmentation_submissions.parquet`
  - `augmentation_items.parquet`
  - `augmentation_governance_events.parquet`
  - `augmentation_submission_lifecycle_events.parquet`
  - SEC companion provenance artifacts
- Shared run/event views remain additive projections only.
- No second authority mechanism/store was introduced.

## Wave 5.1 Normalization Update (Layout/Exports/Tests/Docs Only)

### 1) Canonical Package Layout

- `m_cache_shared` now normalizes to canonical nested augmentation layout:
  - `m_cache_shared/augmentation/enums.py`
  - `m_cache_shared/augmentation/models.py`
  - `m_cache_shared/augmentation/validators.py`
  - `m_cache_shared/augmentation/schema_loaders.py`
  - `m_cache_shared/augmentation/packers.py`
  - `m_cache_shared/augmentation/cli_helpers.py`
- Flat `m_cache_shared/*` modules remain as thin re-export compatibility shims for this normalization cycle.

### 2) Canonical Shared Exports

- Canonical shared export surface is `m_cache_shared.augmentation` with normalized names:
  - models: `ProducerTargetDescriptor`, `ProducerRunSubmission`, `ProducerArtifactSubmission`, `RunStatusView`, `EventsViewRow`, `ApiAugmentationMeta`
  - enums/vocab: `AugmentationType`, `ProducerKind`, `RunStatus`
  - validators: `validate_producer_target_descriptor`, `validate_producer_run_submission`, `validate_producer_artifact_submission`, `validate_run_submission_envelope`, `validate_artifact_submission_envelope`
  - schema loader: `load_json_schema`
  - packers: `pack_run_status_view`, `pack_events_view`, `pack_additive_augmentation_meta`
  - CLI helper: `parse_json_input_payload`
- Existing Wave 5 names remain as compatibility aliases in this pass.

### 3) What Remained Local

- Filing identity and source-text-version derivation helpers remain local.
- SEC authority routing, sidecar/submission/provenance storage, and projection logic remain local.
- CLI/API handlers remain local.

### 4) Role Behavior Unchanged

- Repo remains non-pilot for live producer write-path behavior.
- `submit-run` / `submit-artifact` remain validate-only and non-persisting.
- No admin-write routing changes, no new authority artifacts, no CLI/API semantic changes.

### 5) Compatibility Shims Retained

- `m_cache_shared/*` flat modules retained as thin re-export shims.
- `py_sec_edgar.wave4_shared` retained as facade/shim where still needed.

## Wave 6.1 External-Convergence Normalization (Facade-First, Non-Behavioral)

This repo remains fully standalone and backward compatible while converging to one cross-repo external package identity and shim contract.

### 1) Canonical External Identity and Pin

- Canonical external identity is now:
  - distribution: `m-cache-shared-ext`
  - import root: `m_cache_shared_ext.augmentation`
  - shared RC tag: `v0.1.0-rc1`
- Centralized pin file remains:
  - `requirements/m_cache_shared_external.txt`
- Pin format is explicit Git-tag VCS:
  - `m-cache-shared-ext @ git+https://github.com/m-cache/m_cache_shared_ext.git@v0.1.0-rc1`
- `setup.py` keeps optional extra exposure:
  - `pip install .[external-shared]`

### 2) Canonical Shim/Fallback Contract via `wave4_shared`

- `py_sec_edgar.wave4_shared._shared_backend` remains mandatory first-hop facade.
- Application code continues importing through `py_sec_edgar.wave4_shared`; broad direct-import rewrites are deferred.
- Canonical primary env contract:
  - `M_CACHE_SHARED_SOURCE=auto|external|local`
  - `M_CACHE_SHARED_EXTERNAL_ROOT` (default `m_cache_shared_ext.augmentation`)
- One-cycle compatibility aliases retained:
  - `PY_SEC_EDGAR_WAVE6_SHARED_SOURCE`
  - `PY_SEC_EDGAR_WAVE6_EXTERNAL_ROOT`
- Precedence rule:
  - canonical `M_CACHE_SHARED_*` values win whenever both canonical and legacy env names are set.

### 3) Source-Mode Semantics (Convergence Contract)

- `auto`: attempt external first, verify strict-v1 shared symbol contract, then fall back to local `m_cache_shared.augmentation` if external is unavailable/incomplete.
- `external`: require external root and strict-v1 contract; fail loudly if unavailable/incomplete/wrong.
- `local`: bypass external and use local in-repo shared implementation.
- No module-shadowing or import-precedence tricks are relied upon.
- One backend root is selected per process to prevent mixed-source loading.

### 4) Public API Boundary and Local Ownership Unchanged

- Externalized-through-facade scope stays strict-common v1 only:
  - models/enums, outer-envelope validators, `load_json_schema`, `pack_run_status_view`, `pack_events_view`, `parse_json_input_payload`.
- Non-v1 and compatibility scope intentionally remains local:
  - additive meta packer boundary (`pack_additive_augmentation_meta` / `build_augmentation_meta_additive`),
  - Wave 5.1 compatibility alias naming layers and flat-module shims,
  - SEC identity/authority/provenance/storage/execution internals.

### 5) Rollback and Deprecation

- Fast rollback options (no CLI/API redesign):
  1. repin `requirements/m_cache_shared_external.txt` to an earlier tag,
  2. set `M_CACHE_SHARED_SOURCE=local` to force local seam usage.
- Legacy `PY_SEC_EDGAR_WAVE6_*` env names are compatibility-only for one stabilization cycle and are planned for removal in a later wave after convergence validation.
