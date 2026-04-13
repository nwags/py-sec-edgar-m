from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import tomllib

from py_sec_edgar.config import AppConfig


_ALLOWED_RESOLUTION_MODES = {"local_only", "resolve_if_missing", "refresh_if_stale"}
_ALLOWED_AUTH_TYPES = {
    "none",
    "api_key_header",
    "api_key_query",
    "bearer_token",
    "basic_auth",
    "session_cookie",
    "custom",
}
_ALLOWED_RATE_POLICIES = {
    "unknown",
    "fixed_window",
    "sliding_window",
    "token_bucket",
    "per_minute",
    "per_hour",
    "per_day",
    "custom",
}


@dataclass(frozen=True)
class MCacheGlobalConfig:
    app_root: str = "."
    log_level: str = "INFO"
    default_summary_json: bool = False
    default_progress_json: bool = False
    default_progress_heartbeat_seconds: float = 0.0


@dataclass(frozen=True)
class MCacheProviderConfig:
    enabled: bool = True
    auth_type: str = "none"
    auth_env_var: str | None = None
    rate_limit_policy: str = "token_bucket"
    soft_limit: int | None = 5
    hard_limit: int | None = 5
    burst_limit: int | None = 1
    retry_budget: int = 2
    backoff_policy: str = "exponential"
    direct_resolution_allowed: bool = True
    browse_discovery_allowed: bool = True
    supports_bulk_history: bool = True
    supports_incremental_refresh: bool = True
    supports_direct_resolution: bool = True
    supports_public_resolve_if_missing: bool = False
    supports_admin_refresh_if_stale: bool = False
    graceful_degradation_policy: str = "defer_and_report"
    free_tier_notes: str | None = "Respect SEC fair-access policy and configured shared request budget."
    fallback_priority: int | None = 10
    is_active: bool = True
    notes: str | None = "Canonical SEC provider row for Wave 1."


@dataclass(frozen=True)
class MCacheDomainConfig:
    enabled: bool = True
    cache_root: str = ".sec_cache"
    normalized_refdata_root: str = "refdata/normalized"
    lookup_root: str = "refdata/normalized"
    default_resolution_mode: str = "local_only"
    providers: dict[str, MCacheProviderConfig] = field(default_factory=dict)
    runtime: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MCacheEffectiveConfig:
    global_config: MCacheGlobalConfig
    domains: dict[str, MCacheDomainConfig]
    source_path: str | None


def load_m_cache_effective_config(
    *,
    project_root: Path | str | None = None,
    config_path: Path | str | None = None,
) -> MCacheEffectiveConfig:
    root = _resolve_project_root(project_root)
    selected_path = _resolve_config_path(root=root, config_path=config_path)

    file_payload: dict[str, object] = {}
    if selected_path is not None and selected_path.exists():
        file_payload = tomllib.loads(selected_path.read_text(encoding="utf-8"))

    global_cfg = MCacheGlobalConfig(
        app_root=str(root),
        log_level=str(_read_nested(file_payload, ["global", "log_level"], "INFO")),
        default_summary_json=bool(_read_nested(file_payload, ["global", "default_summary_json"], False)),
        default_progress_json=bool(_read_nested(file_payload, ["global", "default_progress_json"], False)),
        default_progress_heartbeat_seconds=float(
            _read_nested(file_payload, ["global", "default_progress_heartbeat_seconds"], 0.0)
        ),
    )

    sec_cfg = _build_sec_domain_config(root=root, file_payload=file_payload)
    effective = MCacheEffectiveConfig(
        global_config=global_cfg,
        domains={"sec": sec_cfg},
        source_path=str(selected_path) if selected_path is not None and selected_path.exists() else None,
    )
    validate_m_cache_effective_config(effective)
    return effective


def validate_m_cache_effective_config(effective: MCacheEffectiveConfig) -> None:
    sec_cfg = effective.domains.get("sec")
    if sec_cfg is None:
        raise ValueError("Effective config must include domains.sec.")
    if sec_cfg.enabled:
        if not str(sec_cfg.cache_root).strip():
            raise ValueError("domains.sec.cache_root is required when sec domain is enabled.")
        if not str(sec_cfg.normalized_refdata_root).strip():
            raise ValueError("domains.sec.normalized_refdata_root is required when sec domain is enabled.")
    if sec_cfg.default_resolution_mode not in _ALLOWED_RESOLUTION_MODES:
        raise ValueError(
            "domains.sec.default_resolution_mode must be one of: "
            f"{', '.join(sorted(_ALLOWED_RESOLUTION_MODES))}."
        )

    for provider_id, provider in sec_cfg.providers.items():
        if provider.auth_type not in _ALLOWED_AUTH_TYPES:
            raise ValueError(
                f"domains.sec.providers.{provider_id}.auth_type must be one of: "
                f"{', '.join(sorted(_ALLOWED_AUTH_TYPES))}."
            )
        if provider.rate_limit_policy not in _ALLOWED_RATE_POLICIES:
            raise ValueError(
                f"domains.sec.providers.{provider_id}.rate_limit_policy must be one of: "
                f"{', '.join(sorted(_ALLOWED_RATE_POLICIES))}."
            )


def effective_config_to_app_config(
    effective: MCacheEffectiveConfig,
    *,
    project_root: Path | str | None = None,
) -> AppConfig:
    root = _resolve_project_root(project_root)
    base = AppConfig.from_project_root(root, use_env_overrides=False)
    sec_cfg = effective.domains["sec"]

    cache_root = _resolve_root_path(root, sec_cfg.cache_root)
    normalized_refdata_root = _resolve_root_path(root, sec_cfg.normalized_refdata_root)
    merged_index_path = _legacy_merged_index_from_normalized(root=root, normalized_refdata_root=normalized_refdata_root)

    return replace(
        base,
        project_root=root,
        normalized_refdata_root=normalized_refdata_root,
        download_root=(cache_root / "Archives").resolve(),
        merged_index_path=merged_index_path.resolve(),
    )


def _build_sec_domain_config(*, root: Path, file_payload: dict[str, object]) -> MCacheDomainConfig:
    sec_payload = _read_nested(file_payload, ["domains", "sec"], {})
    if not isinstance(sec_payload, dict):
        sec_payload = {}

    cache_root_default = _default_cache_root_from_legacy_env(root)
    normalized_refdata_default = str(
        (Path(os.getenv("PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT", "")).expanduser().resolve())
        if os.getenv("PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT")
        else (root / "refdata" / "normalized").resolve()
    )

    sec_cfg = MCacheDomainConfig(
        enabled=bool(sec_payload.get("enabled", True)),
        cache_root=str(sec_payload.get("cache_root", cache_root_default)),
        normalized_refdata_root=str(sec_payload.get("normalized_refdata_root", normalized_refdata_default)),
        lookup_root=str(sec_payload.get("lookup_root", sec_payload.get("normalized_refdata_root", normalized_refdata_default))),
        default_resolution_mode=str(sec_payload.get("default_resolution_mode", "local_only")),
        providers=_build_sec_provider_configs(sec_payload),
        runtime=dict(sec_payload.get("runtime", {})) if isinstance(sec_payload.get("runtime", {}), dict) else {},
    )

    return sec_cfg


def _build_sec_provider_configs(sec_payload: dict[str, object]) -> dict[str, MCacheProviderConfig]:
    providers_payload = sec_payload.get("providers", {})
    if not isinstance(providers_payload, dict):
        providers_payload = {}
    if not providers_payload:
        return {"sec": MCacheProviderConfig()}

    providers: dict[str, MCacheProviderConfig] = {}
    for provider_id, raw_value in providers_payload.items():
        if not isinstance(raw_value, dict):
            continue
        providers[str(provider_id)] = MCacheProviderConfig(
            enabled=bool(raw_value.get("enabled", True)),
            auth_type=str(raw_value.get("auth_type", "none")),
            auth_env_var=_none_if_blank(raw_value.get("auth_env_var")),
            rate_limit_policy=str(raw_value.get("rate_limit_policy", "token_bucket")),
            soft_limit=_as_int_or_none(raw_value.get("soft_limit")),
            hard_limit=_as_int_or_none(raw_value.get("hard_limit")),
            burst_limit=_as_int_or_none(raw_value.get("burst_limit")),
            retry_budget=int(raw_value.get("retry_budget", 2)),
            backoff_policy=str(raw_value.get("backoff_policy", "exponential")),
            direct_resolution_allowed=bool(raw_value.get("direct_resolution_allowed", True)),
            browse_discovery_allowed=bool(raw_value.get("browse_discovery_allowed", True)),
            supports_bulk_history=bool(raw_value.get("supports_bulk_history", True)),
            supports_incremental_refresh=bool(raw_value.get("supports_incremental_refresh", True)),
            supports_direct_resolution=bool(raw_value.get("supports_direct_resolution", True)),
            supports_public_resolve_if_missing=bool(raw_value.get("supports_public_resolve_if_missing", False)),
            supports_admin_refresh_if_stale=bool(raw_value.get("supports_admin_refresh_if_stale", False)),
            graceful_degradation_policy=str(raw_value.get("graceful_degradation_policy", "defer_and_report")),
            free_tier_notes=_none_if_blank(raw_value.get("free_tier_notes")),
            fallback_priority=_as_int_or_none(raw_value.get("fallback_priority")),
            is_active=bool(raw_value.get("is_active", True)),
            notes=_none_if_blank(raw_value.get("notes")),
        )
    return providers or {"sec": MCacheProviderConfig()}


def _resolve_project_root(project_root: Path | str | None) -> Path:
    if project_root is not None:
        return Path(project_root).expanduser().resolve()
    env_root = os.getenv("PY_SEC_EDGAR_PROJECT_ROOT")
    if env_root and env_root.strip():
        return Path(env_root.strip()).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _resolve_config_path(*, root: Path, config_path: Path | str | None) -> Path | None:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()

    env_path = os.getenv("M_CACHE_CONFIG")
    if env_path and env_path.strip():
        return Path(env_path.strip()).expanduser().resolve()

    default_path = root / "m-cache.toml"
    return default_path


def _read_nested(payload: dict[str, object], path: list[str], default: object) -> object:
    cursor: object = payload
    for key in path:
        if not isinstance(cursor, dict):
            return default
        if key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


def _default_cache_root_from_legacy_env(root: Path) -> str:
    raw_download_root = os.getenv("PY_SEC_EDGAR_DOWNLOAD_ROOT")
    if raw_download_root and raw_download_root.strip():
        return str(_cache_root_from_download_root(Path(raw_download_root.strip()).expanduser()).resolve())
    return str((root / ".sec_cache").resolve())


def _cache_root_from_download_root(download_root: Path) -> Path:
    if download_root.name == "Archives":
        return download_root.parent
    return download_root


def _resolve_root_path(project_root: Path, configured_path: str) -> Path:
    path = Path(configured_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _legacy_merged_index_from_normalized(*, root: Path, normalized_refdata_root: Path) -> Path:
    env_merged_path = os.getenv("PY_SEC_EDGAR_MERGED_INDEX_PATH")
    if env_merged_path and env_merged_path.strip():
        return Path(env_merged_path.strip()).expanduser().resolve()
    # Keep legacy artifact location stable for existing internals.
    return (root / "refdata" / "merged_idx_files.pq").resolve()


def _none_if_blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return int(text)
