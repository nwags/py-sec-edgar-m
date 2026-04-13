# Wave 1 Migration Note (`py-sec-edgar-m`)

This note summarizes Wave 1 contract alignment for this repository only.

## What Became Canonical in Wave 1

- Canonical additive command surface: `m-cache sec ...`
- Canonical short augmentation family name: `aug`
- Canonical shared config file: `m-cache.toml`
- Canonical shared provider registry artifact: `refdata/normalized/provider_registry.parquet`
- Canonical shared resolution-event artifact: `refdata/normalized/resolution_events.parquet`

## What Remains Aliased or Compatibility-Preserved

- Operator compatibility surface remains: `py-sec-edgar ...`
- Augmentation family alias remains valid: `augmentations` (with `aug` canonical)
- Existing SEC-specific artifacts and SEC identity semantics are preserved.

## Legacy vs Canonical Output Defaults

- `py-sec-edgar ...` keeps legacy machine-output defaults.
- Canonical machine output on legacy commands is additive via:
  - `--output-schema canonical`
- `m-cache sec ...` Wave 1 wrappers default to canonical summary/progress machine shapes.

## Config Loading and Precedence

Wave 1 canonical config loading precedence:

1. explicit CLI `--config PATH`
2. `M_CACHE_CONFIG` environment variable
3. `./m-cache.toml`
4. legacy environment mapping
5. built-in defaults

Legacy SEC env/config compatibility is preserved through mapping into canonical fields.

## Provider Registry Materialization

- `refdata refresh` now also materializes `refdata/normalized/provider_registry.parquet`.
- SEC is represented as a provider row with canonical policy/capability fields.
- Local override inputs are supported via:
  - `refdata/inputs/provider_registry_overrides.parquet`
  - `refdata/inputs/provider_registry_overrides.csv`
- `sec_source_surfaces.parquet` remains the SEC-specific companion source/surface authority artifact.

## Resolution Provenance Artifacts (Shared vs SEC-Specific)

Wave 1 uses an additive two-artifact approach:

- Shared/canonical: `resolution_events.parquet`
- SEC-specific companion: `filing_resolution_provenance.parquet`

Current status in Wave 1:

- `resolution_events.parquet` is the cross-repo shared comparison surface.
- `filing_resolution_provenance.parquet` is a sanctioned domain-specific companion artifact for SEC operational detail and existing consumers.
- Broad historical provenance rewrite/migration is out of scope for Wave 1.

## Reserved for Later Waves

The following are intentionally reserved and not expanded in this wave:

- deeper shared-family implementations beyond Wave 1 wrappers/stubs,
- cross-repo shared-package extraction,
- broad provenance/event historical migration,
- domain-model flattening of SEC-specific identities or augmentation semantics.
