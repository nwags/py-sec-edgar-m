from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.m_cache_config import MCacheProviderConfig
from py_sec_edgar.provider_registry import materialize_provider_registry, provider_registry_path
from py_sec_edgar.sec_surfaces import default_sec_surfaces


_LIST_FIELDS = [
    "provider_id",
    "domain",
    "content_domain",
    "display_name",
    "provider_type",
    "is_active",
    "fallback_priority",
    "rate_limit_policy",
    "direct_resolution_allowed",
    "supports_direct_resolution",
    "supports_incremental_refresh",
]


def ensure_provider_registry_df(config: AppConfig) -> pd.DataFrame:
    path = provider_registry_path(config)
    if not path.exists():
        materialize_provider_registry(config)
    if not path.exists():
        raise FileNotFoundError(
            f"Provider registry not found: {path}. Run `m-cache sec refdata refresh` or `py-sec-edgar refdata refresh`."
        )
    return pd.read_parquet(path)


def list_providers(
    config: AppConfig,
    *,
    content_domain: str | None = None,
    active_only: bool = False,
    provider_type: str | None = None,
) -> list[dict[str, object]]:
    df = ensure_provider_registry_df(config)
    out = df.copy()

    if content_domain:
        want = str(content_domain).strip().lower()
        out = out[out["content_domain"].astype(str).str.lower() == want]
    if active_only:
        out = out[out["is_active"].astype(bool)]
    if provider_type:
        want = str(provider_type).strip().lower()
        out = out[out["provider_type"].astype(str).str.lower() == want]

    for key in _LIST_FIELDS:
        if key not in out.columns:
            out[key] = None
    out = out[_LIST_FIELDS]
    out = out.sort_values(
        ["domain", "content_domain", "fallback_priority", "provider_id"],
        ascending=[True, True, True, True],
        na_position="last",
    )
    return out.to_dict(orient="records")


def show_provider(
    config: AppConfig,
    *,
    provider_id: str,
    effective_provider: MCacheProviderConfig | None,
) -> dict[str, object]:
    df = ensure_provider_registry_df(config)
    matches = df[df["provider_id"].astype(str) == str(provider_id)]
    if matches.empty:
        raise LookupError(f"Provider not found: {provider_id}")

    row = matches.sort_values(
        ["fallback_priority", "domain", "content_domain"],
        ascending=[True, True, True],
        na_position="last",
    ).iloc[0].to_dict()

    detail = dict(row)

    # Additive Wave 2 effective policy fields.
    detail["default_timeout_seconds"] = int(round(config.request_timeout_connect + config.request_timeout_read))
    detail["quota_window_seconds"] = _quota_window_seconds(str(detail.get("rate_limit_policy") or ""))
    detail["quota_reset_hint"] = _quota_reset_hint(str(detail.get("rate_limit_policy") or ""))
    detail["expected_error_modes"] = ["http_429", "http_5xx", "timeout", "provider_not_configured"]
    detail["user_agent_required"] = True
    detail["contact_requirement"] = "Declared SEC-compliant User-Agent with contact information."
    detail["terms_url"] = "https://www.sec.gov/os/accessing-edgar-data"

    auth_env_var = _none_if_blank(detail.get("auth_env_var"))
    effective_auth_present = True
    if auth_env_var:
        effective_auth_present = bool(str(os.getenv(auth_env_var, "")).strip())
    detail["effective_auth_present"] = effective_auth_present

    effective_enabled = bool(detail.get("is_active", True))
    if effective_provider is not None:
        effective_enabled = bool(effective_enabled and effective_provider.enabled and effective_provider.is_active)
        # Effective overlay should remain inspectable and deterministic.
        detail["auth_type"] = effective_provider.auth_type
        detail["auth_env_var"] = effective_provider.auth_env_var
        detail["rate_limit_policy"] = effective_provider.rate_limit_policy
        detail["soft_limit"] = effective_provider.soft_limit
        detail["hard_limit"] = effective_provider.hard_limit
        detail["burst_limit"] = effective_provider.burst_limit
        detail["retry_budget"] = effective_provider.retry_budget
        detail["backoff_policy"] = effective_provider.backoff_policy
        detail["direct_resolution_allowed"] = effective_provider.direct_resolution_allowed
        detail["browse_discovery_allowed"] = effective_provider.browse_discovery_allowed
        detail["supports_bulk_history"] = effective_provider.supports_bulk_history
        detail["supports_incremental_refresh"] = effective_provider.supports_incremental_refresh
        detail["supports_direct_resolution"] = effective_provider.supports_direct_resolution
        detail["supports_public_resolve_if_missing"] = effective_provider.supports_public_resolve_if_missing
        detail["supports_admin_refresh_if_stale"] = effective_provider.supports_admin_refresh_if_stale
        detail["graceful_degradation_policy"] = effective_provider.graceful_degradation_policy
        detail["free_tier_notes"] = effective_provider.free_tier_notes
        detail["fallback_priority"] = effective_provider.fallback_priority
        detail["notes"] = effective_provider.notes
        if effective_provider.auth_env_var:
            detail["effective_auth_present"] = bool(str(os.getenv(effective_provider.auth_env_var, "")).strip())
    detail["effective_enabled"] = bool(effective_enabled)

    detail["rate_limit_state"] = {
        "provider_id": str(detail.get("provider_id")),
        "rate_limit_policy": str(detail.get("rate_limit_policy") or "unknown"),
        "soft_limit": _as_int_or_none(detail.get("soft_limit")),
        "hard_limit": _as_int_or_none(detail.get("hard_limit")),
        "burst_limit": _as_int_or_none(detail.get("burst_limit")),
        "quota_window_seconds": _quota_window_seconds(str(detail.get("rate_limit_policy") or "")),
        "retry_budget": _as_int_or_none(detail.get("retry_budget")),
        "rate_limited": False,
        "deferred": False,
        "deferred_until": None,
        "message": "No active runtime quota event is recorded for this offline inspection.",
    }

    detail["sec_surfaces"] = [
        {
            "surface_id": surface.surface_id,
            "surface_name": surface.surface_name,
            "base_url": surface.base_url,
            "supports_metadata_resolution": surface.supports_metadata_resolution,
            "supports_content_retrieval": surface.supports_content_retrieval,
            "fair_access_notes": surface.fair_access_notes,
        }
        for surface in default_sec_surfaces()
        if surface.provider_id == str(detail.get("provider_id"))
    ]

    return detail


def effective_provider_cfg(effective_providers: dict[str, MCacheProviderConfig], provider_id: str) -> MCacheProviderConfig | None:
    return effective_providers.get(str(provider_id))


def _quota_window_seconds(rate_limit_policy: str) -> int | None:
    policy = str(rate_limit_policy).strip().lower()
    if policy in {"token_bucket", "custom", "unknown"}:
        return 1
    if policy == "per_minute":
        return 60
    if policy == "per_hour":
        return 3600
    if policy == "per_day":
        return 86400
    return None


def _quota_reset_hint(rate_limit_policy: str) -> str | None:
    policy = str(rate_limit_policy).strip().lower()
    if policy in {"token_bucket", "sliding_window", "fixed_window", "custom"}:
        return "Respect provider policy and retry budget before the next remote attempt."
    if policy == "per_minute":
        return "Quota typically resets each minute."
    if policy == "per_hour":
        return "Quota typically resets each hour."
    if policy == "per_day":
        return "Quota typically resets daily."
    return None


def _none_if_blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
