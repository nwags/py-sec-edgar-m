from pathlib import Path
import importlib
import warnings

from py_sec_edgar.config import get_canonical_raw_refdata_root, load_config


def test_load_config_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.project_root == tmp_path.resolve()
    assert config.raw_refdata_root == tmp_path.resolve() / "refdata" / "sec_sources"
    assert config.canonical_raw_refdata_root == get_canonical_raw_refdata_root()
    assert config.normalized_refdata_root == tmp_path.resolve() / "refdata" / "normalized"


def test_canonical_raw_refdata_root_is_deterministic_and_cwd_independent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    canonical = get_canonical_raw_refdata_root()
    assert canonical == (Path(__file__).resolve().parents[1] / "refdata" / "sec_sources").resolve()


def test_ensure_runtime_dirs(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config.ensure_runtime_dirs()

    assert config.refdata_root.exists()
    assert config.raw_refdata_root.exists()
    assert config.normalized_refdata_root.exists()
    assert config.download_root.exists()
    assert config.merged_index_path.parent.exists()


def test_load_config_path_overrides_from_env(monkeypatch, tmp_path: Path) -> None:
    download_root = tmp_path / "custom_cache" / "Archives"
    normalized_root = tmp_path / "custom_refdata" / "normalized"
    merged_path = tmp_path / "custom_refdata" / "merged" / "merged_idx_files.pq"

    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("PY_SEC_EDGAR_DOWNLOAD_ROOT", str(download_root))
    monkeypatch.setenv("PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT", str(normalized_root))
    monkeypatch.setenv("PY_SEC_EDGAR_MERGED_INDEX_PATH", str(merged_path))

    config = load_config()
    assert config.project_root == tmp_path.resolve()
    assert config.download_root == download_root.resolve()
    assert config.normalized_refdata_root == normalized_root.resolve()
    assert config.merged_index_path == merged_path.resolve()


def test_load_config_explicit_root_ignores_env_path_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path / "ignored_project_root"))
    monkeypatch.setenv("PY_SEC_EDGAR_DOWNLOAD_ROOT", str(tmp_path / "ignored_download" / "Archives"))
    monkeypatch.setenv("PY_SEC_EDGAR_NORMALIZED_REFDATA_ROOT", str(tmp_path / "ignored_refdata" / "normalized"))
    monkeypatch.setenv("PY_SEC_EDGAR_MERGED_INDEX_PATH", str(tmp_path / "ignored_refdata" / "merged_idx_files.pq"))

    explicit_root = tmp_path / "explicit_root"
    config = load_config(explicit_root)

    assert config.project_root == explicit_root.resolve()
    assert config.download_root == (explicit_root.resolve() / ".sec_cache" / "Archives")
    assert config.normalized_refdata_root == (explicit_root.resolve() / "refdata" / "normalized")
    assert config.merged_index_path == (explicit_root.resolve() / "refdata" / "merged_idx_files.pq")


def test_load_config_explicit_root_ignores_project_root_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path / "from_env"))
    explicit_root = tmp_path / "from_explicit_arg"

    config = load_config(project_root=explicit_root)
    assert config.project_root == explicit_root.resolve()


def test_lazy_config_proxy_is_memoized_mutable_and_warning_is_bounded() -> None:
    settings = importlib.import_module("py_sec_edgar.settings")
    settings = importlib.reload(settings)
    settings._reset_config_for_tests()

    assert settings._is_config_initialized() is False

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        # First access initializes once and warns once.
        _ = settings.CONFIG.TEST_MODE
        assert settings._is_config_initialized() is True
        first_obj = settings.get_config()

        # Repeated access reuses the same object and does not re-warn.
        _ = settings.CONFIG.TEST_MODE
        second_obj = settings.get_config()
        assert id(first_obj) == id(second_obj)

        # Writes through proxy persist.
        settings.CONFIG.TEST_MODE = True
        assert settings.CONFIG.TEST_MODE is True
        assert settings.get_config().TEST_MODE is True

        warnings_only = [w for w in captured if issubclass(w.category, DeprecationWarning)]
        assert len(warnings_only) == 1

    # Reset should clear both singleton and warning state for deterministic tests.
    settings._reset_config_for_tests()
    assert settings._is_config_initialized() is False
    with warnings.catch_warnings(record=True) as captured_after_reset:
        warnings.simplefilter("always")
        _ = settings.CONFIG.TEST_MODE
        warnings_only = [w for w in captured_after_reset if issubclass(w.category, DeprecationWarning)]
        assert len(warnings_only) == 1
