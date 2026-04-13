from __future__ import annotations

from pathlib import Path

import pandas as pd

from py_sec_edgar.config import load_config
from py_sec_edgar.provider_registry import materialize_provider_registry, provider_registry_path


CANONICAL_COLUMNS = {
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
}


def test_provider_registry_materialization_has_canonical_fields(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    cfg.ensure_runtime_dirs()

    out_path, row_count = materialize_provider_registry(cfg)
    assert out_path == provider_registry_path(cfg)
    assert out_path.exists()
    assert row_count >= 1

    df = pd.read_parquet(out_path)
    assert CANONICAL_COLUMNS.issubset(set(df.columns))
    sec = df[df["provider_id"].astype(str) == "sec"].iloc[0]
    assert sec["domain"] == "sec"
    assert sec["content_domain"] == "filing"


def test_provider_registry_overrides_are_applied(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    override_dir = cfg.refdata_root / "inputs"
    override_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "provider_id": "sec",
                "domain": "sec",
                "content_domain": "filing",
                "display_name": "SEC override",
                "rate_limit_policy": "custom",
                "direct_resolution_allowed": True,
                "browse_discovery_allowed": True,
                "supports_bulk_history": True,
                "supports_incremental_refresh": True,
                "supports_direct_resolution": True,
                "supports_public_resolve_if_missing": False,
                "supports_admin_refresh_if_stale": False,
                "graceful_degradation_policy": "defer_and_report",
                "is_active": True,
                "provider_type": "official_site",
                "auth_type": "none",
            }
        ]
    ).to_csv(override_dir / "provider_registry_overrides.csv", index=False)

    out_path, _ = materialize_provider_registry(cfg)
    df = pd.read_parquet(out_path)
    sec = df[df["provider_id"].astype(str) == "sec"].iloc[0]
    assert sec["display_name"] == "SEC override"
    assert sec["rate_limit_policy"] == "custom"
