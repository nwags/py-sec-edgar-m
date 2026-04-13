from __future__ import annotations

import importlib
import os
from types import ModuleType

_SHARED_SOURCE_ENV = "M_CACHE_SHARED_SOURCE"
_EXTERNAL_ROOT_ENV = "M_CACHE_SHARED_EXTERNAL_ROOT"
_LEGACY_SHARED_SOURCE_ENV = "PY_SEC_EDGAR_WAVE6_SHARED_SOURCE"
_LEGACY_EXTERNAL_ROOT_ENV = "PY_SEC_EDGAR_WAVE6_EXTERNAL_ROOT"
_EXTERNAL_ROOT_DEFAULT = "m_cache_shared_ext.augmentation"
_LOCAL_ROOT = "m_cache_shared.augmentation"
_VALID_SOURCES = {"auto", "external", "local"}
_REQUIRED_EXTERNAL_SYMBOLS = {
    "enums": ("AugmentationType", "ProducerKind", "RunStatus"),
    "models": (
        "ProducerTargetDescriptor",
        "ProducerRunSubmission",
        "ProducerArtifactSubmission",
        "RunStatusView",
        "EventsViewRow",
        "ApiAugmentationMeta",
    ),
    "validators": (
        "validate_producer_target_descriptor",
        "validate_producer_run_submission",
        "validate_producer_artifact_submission",
        "validate_run_submission_envelope",
        "validate_artifact_submission_envelope",
    ),
    "schema_loaders": ("load_json_schema",),
    "packers": ("pack_run_status_view", "pack_events_view"),
    "cli_helpers": ("parse_json_input_payload",),
}

_SELECTED_ROOT: str | None = None
_MODULE_CACHE: dict[str, ModuleType] = {}
_VALIDATED_EXTERNAL_ROOTS: set[str] = set()


def _read_env(primary_name: str, legacy_name: str, default: str) -> str:
    primary = os.getenv(primary_name)
    if primary is not None and primary.strip():
        return primary.strip()
    legacy = os.getenv(legacy_name)
    if legacy is not None and legacy.strip():
        return legacy.strip()
    return default


def _source_mode() -> str:
    raw = _read_env(_SHARED_SOURCE_ENV, _LEGACY_SHARED_SOURCE_ENV, "auto").lower()
    return raw if raw in _VALID_SOURCES else "auto"


def _external_root() -> str:
    return _read_env(_EXTERNAL_ROOT_ENV, _LEGACY_EXTERNAL_ROOT_ENV, _EXTERNAL_ROOT_DEFAULT)


def _verify_external_contract(root: str) -> None:
    if root in _VALIDATED_EXTERNAL_ROOTS:
        return
    for submodule_name, required_symbols in _REQUIRED_EXTERNAL_SYMBOLS.items():
        module_path = f"{root}.{submodule_name}"
        module = importlib.import_module(module_path)
        missing = [symbol for symbol in required_symbols if not hasattr(module, symbol)]
        if missing:
            missing_joined = ", ".join(missing)
            raise ImportError(
                f"External shared backend '{root}' is missing strict-v1 symbols in "
                f"'{module_path}': {missing_joined}"
            )
    _VALIDATED_EXTERNAL_ROOTS.add(root)


def _candidate_roots() -> tuple[str, ...]:
    if _SELECTED_ROOT is not None:
        return (_SELECTED_ROOT,)

    mode = _source_mode()
    external_root = _external_root()
    if mode == "local":
        return (_LOCAL_ROOT,)
    if mode == "external":
        return (external_root,)
    return (external_root, _LOCAL_ROOT)


def import_shared_submodule(submodule_name: str) -> ModuleType:
    if submodule_name in _MODULE_CACHE:
        return _MODULE_CACHE[submodule_name]

    errors: list[str] = []
    mode = _source_mode()
    for root in _candidate_roots():
        module_path = f"{root}.{submodule_name}"
        try:
            if root != _LOCAL_ROOT:
                _verify_external_contract(root)
            module = importlib.import_module(module_path)
        except (ImportError, ModuleNotFoundError) as exc:
            errors.append(f"{module_path}: {exc}")
            if mode == "external":
                break
            continue
        global _SELECTED_ROOT
        _SELECTED_ROOT = root
        _MODULE_CACHE[submodule_name] = module
        return module

    details = "; ".join(errors) if errors else "no import candidates"
    raise ImportError(
        f"Unable to import shared submodule '{submodule_name}' from external/local backends ({details})."
    )


def active_shared_backend_root() -> str | None:
    return _SELECTED_ROOT


def reset_shared_backend_for_tests() -> None:
    global _SELECTED_ROOT
    _SELECTED_ROOT = None
    _MODULE_CACHE.clear()
    _VALIDATED_EXTERNAL_ROOTS.clear()
