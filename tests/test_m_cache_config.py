from __future__ import annotations

from pathlib import Path

import pytest

from py_sec_edgar.m_cache_config import (
    effective_config_to_app_config,
    load_m_cache_effective_config,
)


def test_m_cache_config_defaults_from_legacy_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("PY_SEC_EDGAR_DOWNLOAD_ROOT", str(tmp_path / "custom" / "Archives"))
    monkeypatch.setenv("PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT", str(tmp_path / "ref_norm"))

    cfg = load_m_cache_effective_config()
    sec = cfg.domains["sec"]

    assert sec.cache_root == str((tmp_path / "custom").resolve())
    assert sec.normalized_refdata_root == str((tmp_path / "ref_norm").resolve())
    assert sec.lookup_root == str((tmp_path / "ref_norm").resolve())
    assert sec.default_resolution_mode == "local_only"


def test_m_cache_config_precedence_cli_path_over_env(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    env_cfg = tmp_path / "env.toml"
    cli_cfg = tmp_path / "cli.toml"

    env_cfg.write_text(
        """
[domains.sec]
cache_root = "env_cache"
normalized_refdata_root = "env_norm"
lookup_root = "env_lookup"
default_resolution_mode = "local_only"
""".strip(),
        encoding="utf-8",
    )
    cli_cfg.write_text(
        """
[domains.sec]
cache_root = "cli_cache"
normalized_refdata_root = "cli_norm"
lookup_root = "cli_lookup"
default_resolution_mode = "local_only"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("M_CACHE_CONFIG", str(env_cfg))
    cfg = load_m_cache_effective_config(project_root=root, config_path=cli_cfg)

    sec = cfg.domains["sec"]
    assert sec.cache_root == "cli_cache"
    assert sec.normalized_refdata_root == "cli_norm"
    assert sec.lookup_root == "cli_lookup"


def test_m_cache_effective_to_app_config_maps_roots(tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
cache_root = "sec_cache_v2"
normalized_refdata_root = "norm_v2"
lookup_root = "norm_v2"
default_resolution_mode = "local_only"
""".strip(),
        encoding="utf-8",
    )
    effective = load_m_cache_effective_config(project_root=tmp_path, config_path=cfg_path)
    app_cfg = effective_config_to_app_config(effective, project_root=tmp_path)

    assert app_cfg.download_root == (tmp_path / "sec_cache_v2" / "Archives").resolve()
    assert app_cfg.normalized_refdata_root == (tmp_path / "norm_v2").resolve()


def test_m_cache_config_validation_rejects_bad_mode(tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
default_resolution_mode = "silent_downgrade"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_m_cache_effective_config(project_root=tmp_path, config_path=cfg_path)


def test_m_cache_config_validation_rejects_bad_provider_policy(tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
default_resolution_mode = "local_only"

[domains.sec.providers.sec]
auth_type = "none"
rate_limit_policy = "nonsense"
direct_resolution_allowed = true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_m_cache_effective_config(project_root=tmp_path, config_path=cfg_path)
