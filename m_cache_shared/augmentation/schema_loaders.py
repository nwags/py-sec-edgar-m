from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json_schema(*, wave: int, schema_filename: str) -> dict[str, Any]:
    schema_path = (
        _repo_root()
        / "docs"
        / "standardization"
        / f"m_cache_reference_pack_v{int(wave)}"
        / "schemas"
        / str(schema_filename)
    )
    if not schema_path.exists():
        raise FileNotFoundError(f"Shared schema not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


# Compatibility aliases retained for the Wave 5.1 normalization cycle.
def load_shared_schema(*, wave: int, schema_filename: str) -> dict[str, Any]:
    return load_json_schema(wave=wave, schema_filename=schema_filename)


def load_wave4_schema(schema_filename: str) -> dict[str, Any]:
    return load_json_schema(wave=4, schema_filename=schema_filename)


def load_wave5_schema(schema_filename: str) -> dict[str, Any]:
    return load_json_schema(wave=5, schema_filename=schema_filename)


__all__ = [
    "load_json_schema",
    "load_shared_schema",
    "load_wave4_schema",
    "load_wave5_schema",
]
