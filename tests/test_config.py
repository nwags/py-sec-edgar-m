from pathlib import Path
import importlib
import warnings

from py_sec_edgar.config import load_config


def test_load_config_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.project_root == tmp_path.resolve()
    assert config.raw_refdata_root == tmp_path.resolve() / "refdata" / "sec_sources"
    assert config.normalized_refdata_root == tmp_path.resolve() / "refdata" / "normalized"


def test_ensure_runtime_dirs(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config.ensure_runtime_dirs()

    assert config.refdata_root.exists()
    assert config.raw_refdata_root.exists()
    assert config.normalized_refdata_root.exists()


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
