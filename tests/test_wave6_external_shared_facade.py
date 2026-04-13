from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from py_sec_edgar.wave4_shared import _shared_backend


def test_wave6_facade_falls_back_to_local_shared_package(monkeypatch) -> None:
    monkeypatch.setenv("M_CACHE_SHARED_SOURCE", "auto")
    monkeypatch.setenv("M_CACHE_SHARED_EXTERNAL_ROOT", "definitely_missing_shared_pkg.augmentation")
    _shared_backend.reset_shared_backend_for_tests()

    import py_sec_edgar.wave4_shared.validators as validators

    importlib.reload(validators)
    payload = validators.validate_producer_target_descriptor(
        {
            "domain": "sec",
            "resource_family": "filing",
            "canonical_key": "0000320193-25-000010",
            "text_source": "api:/filings/0000320193-25-000010/content",
            "source_text_version": "sha256:abc",
        }
    )
    assert payload["domain"] == "sec"
    assert _shared_backend.active_shared_backend_root() == "m_cache_shared.augmentation"


def test_wave6_facade_uses_shadow_safe_external_namespace_when_available(
    tmp_path, monkeypatch
) -> None:
    pkg_root = tmp_path / "m_cache_shared_ext" / "augmentation"
    pkg_root.mkdir(parents=True)
    (tmp_path / "m_cache_shared_ext" / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "enums.py").write_text(
        "\n".join(
            [
                "class AugmentationType(str):",
                "    pass",
                "",
                "class ProducerKind(str):",
                "    pass",
                "",
                "class RunStatus(str):",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pkg_root / "models.py").write_text(
        "\n".join(
            [
                "class ProducerTargetDescriptor:",
                "    pass",
                "",
                "class ProducerRunSubmission:",
                "    pass",
                "",
                "class ProducerArtifactSubmission:",
                "    pass",
                "",
                "class RunStatusView:",
                "    pass",
                "",
                "class EventsViewRow:",
                "    pass",
                "",
                "class ApiAugmentationMeta:",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pkg_root / "schema_loaders.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "def load_json_schema(*, wave: int, schema_filename: str) -> dict[str, object]:",
                "    return {\"backend\": \"external\", \"wave\": wave, \"schema\": schema_filename}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pkg_root / "validators.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "def _mark(payload: dict[str, object]) -> dict[str, object]:",
                "    out = dict(payload)",
                "    out[\"backend\"] = \"external\"",
                "    return out",
                "",
                "def validate_producer_target_descriptor(payload: dict[str, object]) -> dict[str, object]:",
                "    return _mark(payload)",
                "",
                "def validate_producer_run_submission(payload: dict[str, object]) -> dict[str, object]:",
                "    return _mark(payload)",
                "",
                "def validate_producer_artifact_submission(payload: dict[str, object]) -> dict[str, object]:",
                "    return _mark(payload)",
                "",
                "def validate_run_submission_envelope(payload: dict[str, object]) -> dict[str, object]:",
                "    return _mark(payload)",
                "",
                "def validate_artifact_submission_envelope(payload: dict[str, object]) -> dict[str, object]:",
                "    return _mark(payload)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pkg_root / "packers.py").write_text(
        "\n".join(
            [
                "def pack_run_status_view(**kwargs: object) -> dict[str, object]:",
                "    return dict(kwargs)",
                "",
                "def pack_events_view(**kwargs: object) -> dict[str, object]:",
                "    return dict(kwargs)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pkg_root / "cli_helpers.py").write_text(
        "\n".join(
            [
                "def parse_json_input_payload(*, payload_json=None, payload_file=None) -> dict[str, object]:",
                "    return {\"backend\": \"external\"}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in list(sys.modules):
        if name == "m_cache_shared_ext" or name.startswith("m_cache_shared_ext."):
            sys.modules.pop(name, None)
    monkeypatch.setenv("M_CACHE_SHARED_SOURCE", "external")
    monkeypatch.setenv("M_CACHE_SHARED_EXTERNAL_ROOT", "m_cache_shared_ext.augmentation")
    _shared_backend.reset_shared_backend_for_tests()

    import py_sec_edgar.wave4_shared.validators as validators

    importlib.reload(validators)
    schema = validators.load_wave4_schema("producer-target-descriptor.schema.json")
    payload = validators.validate_producer_run_submission({"run_id": "run-1"})

    assert schema["backend"] == "external"
    assert schema["wave"] == 4
    assert payload["backend"] == "external"
    assert _shared_backend.active_shared_backend_root() == "m_cache_shared_ext.augmentation"


def test_wave6_external_mode_fails_loudly_when_external_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("M_CACHE_SHARED_SOURCE", "external")
    monkeypatch.setenv("M_CACHE_SHARED_EXTERNAL_ROOT", "definitely_missing_shared_pkg.augmentation")
    _shared_backend.reset_shared_backend_for_tests()
    import py_sec_edgar.wave4_shared.validators as validators

    with pytest.raises(ImportError):
        importlib.reload(validators)


def test_wave6_canonical_env_wins_over_legacy_alias(monkeypatch) -> None:
    monkeypatch.setenv("M_CACHE_SHARED_SOURCE", "local")
    monkeypatch.setenv("PY_SEC_EDGAR_WAVE6_SHARED_SOURCE", "external")
    monkeypatch.setenv("M_CACHE_SHARED_EXTERNAL_ROOT", "definitely_missing_shared_pkg.augmentation")
    monkeypatch.setenv("PY_SEC_EDGAR_WAVE6_EXTERNAL_ROOT", "another_missing_pkg.augmentation")
    _shared_backend.reset_shared_backend_for_tests()
    import py_sec_edgar.wave4_shared.validators as validators

    importlib.reload(validators)
    payload = validators.validate_producer_target_descriptor(
        {
            "domain": "sec",
            "resource_family": "filing",
            "canonical_key": "0000320193-25-000010",
            "text_source": "api:/filings/0000320193-25-000010/content",
            "source_text_version": "sha256:abc",
        }
    )
    assert payload["domain"] == "sec"
    assert _shared_backend.active_shared_backend_root() == "m_cache_shared.augmentation"


def test_wave6_external_pin_file_is_explicit_git_tag() -> None:
    lines = [
        line.strip()
        for line in (
            (Path("requirements") / "m_cache_shared_external.txt").read_text(encoding="utf-8")
            .splitlines()
        )
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines
    assert lines[0].startswith("m-cache-shared-ext @ git+")
    assert "@v0.1.0-rc2" in lines[0]
