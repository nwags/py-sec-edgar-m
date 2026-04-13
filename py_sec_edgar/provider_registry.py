from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from py_sec_edgar.config import AppConfig


PROVIDER_REGISTRY_COLUMNS = [
    "provider_id",
    "domain",
    "content_domain",
    "provider_type",
    "display_name",
    "base_url",
    "auth_type",
    "auth_env_var",
    "rate_limit_policy",
    "soft_limit",
    "hard_limit",
    "burst_limit",
    "retry_budget",
    "backoff_policy",
    "direct_resolution_allowed",
    "browse_discovery_allowed",
    "supports_bulk_history",
    "supports_incremental_refresh",
    "supports_direct_resolution",
    "supports_public_resolve_if_missing",
    "supports_admin_refresh_if_stale",
    "graceful_degradation_policy",
    "free_tier_notes",
    "fallback_priority",
    "is_active",
    "notes",
]


@dataclass(frozen=True)
class ProviderRegistryRow:
    provider_id: str
    domain: str
    content_domain: str
    provider_type: str
    display_name: str
    base_url: str | None
    auth_type: str
    auth_env_var: str | None
    rate_limit_policy: str
    soft_limit: int | None
    hard_limit: int | None
    burst_limit: int | None
    retry_budget: int
    backoff_policy: str
    direct_resolution_allowed: bool
    browse_discovery_allowed: bool
    supports_bulk_history: bool
    supports_incremental_refresh: bool
    supports_direct_resolution: bool
    supports_public_resolve_if_missing: bool
    supports_admin_refresh_if_stale: bool
    graceful_degradation_policy: str
    free_tier_notes: str | None
    fallback_priority: int | None
    is_active: bool
    notes: str | None


def provider_registry_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "provider_registry.parquet"


def provider_registry_overrides_parquet_path(config: AppConfig) -> Path:
    return config.refdata_root / "inputs" / "provider_registry_overrides.parquet"


def provider_registry_overrides_csv_path(config: AppConfig) -> Path:
    return config.refdata_root / "inputs" / "provider_registry_overrides.csv"


def default_provider_registry_rows(config: AppConfig) -> list[ProviderRegistryRow]:
    return [
        ProviderRegistryRow(
            provider_id="sec",
            domain="sec",
            content_domain="filing",
            provider_type="official_site",
            display_name="U.S. SEC EDGAR",
            base_url="https://www.sec.gov/",
            auth_type="none",
            auth_env_var=None,
            rate_limit_policy="token_bucket",
            soft_limit=int(max(1, round(config.max_requests_per_second))),
            hard_limit=int(max(1, round(config.max_requests_per_second))),
            burst_limit=1,
            retry_budget=2,
            backoff_policy="exponential",
            direct_resolution_allowed=True,
            browse_discovery_allowed=True,
            supports_bulk_history=True,
            supports_incremental_refresh=True,
            supports_direct_resolution=True,
            supports_public_resolve_if_missing=False,
            supports_admin_refresh_if_stale=False,
            graceful_degradation_policy="defer_and_report",
            free_tier_notes="Use declared SEC-compliant User-Agent and shared request budget.",
            fallback_priority=10,
            is_active=True,
            notes="Wave 1 canonical SEC provider row.",
        )
    ]


def materialize_provider_registry(config: AppConfig) -> tuple[Path, int]:
    base_rows = [asdict(row) for row in default_provider_registry_rows(config)]
    base_df = pd.DataFrame(base_rows)
    base_df = _ensure_columns(base_df)

    merged_df = _apply_local_overrides(config, base_df)
    out_path = provider_registry_path(config)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged_df.to_parquet(out_path, index=False)
    return out_path, int(len(merged_df.index))


def _apply_local_overrides(config: AppConfig, base_df: pd.DataFrame) -> pd.DataFrame:
    parquet_path = provider_registry_overrides_parquet_path(config)
    csv_path = provider_registry_overrides_csv_path(config)

    override_df = None
    if parquet_path.exists():
        override_df = pd.read_parquet(parquet_path)
    elif csv_path.exists():
        override_df = pd.read_csv(csv_path)

    if override_df is None or override_df.empty:
        return _sort_registry_rows(base_df)

    override_df = _ensure_columns(override_df)
    merged = pd.concat([base_df, override_df], ignore_index=True)
    merged["__row_order"] = range(len(merged.index))
    merged = merged.sort_values(["provider_id", "domain", "content_domain", "__row_order"], ascending=[True, True, True, True])
    merged = merged.drop_duplicates(subset=["provider_id", "domain", "content_domain"], keep="last")
    merged = merged.drop(columns=["__row_order"])
    return _sort_registry_rows(merged)


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in PROVIDER_REGISTRY_COLUMNS:
        if column not in out.columns:
            out[column] = None
    return out[PROVIDER_REGISTRY_COLUMNS]


def _sort_registry_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["domain", "content_domain", "fallback_priority", "provider_id"], ascending=[True, True, True, True], na_position="last").reset_index(drop=True)
