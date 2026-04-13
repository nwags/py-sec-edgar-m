from __future__ import annotations

import json
from pathlib import Path


def parse_json_input_payload(
    *,
    payload_json: str | None,
    payload_file: Path | None,
) -> dict[str, object]:
    if bool(payload_json) == bool(payload_file):
        raise ValueError("Provide exactly one of --payload-json or --payload-file.")
    try:
        if payload_json:
            value = json.loads(payload_json)
        else:
            assert payload_file is not None
            value = json.loads(payload_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Payload must be a JSON object.")
    return value


# Compatibility alias retained for the Wave 5.1 normalization cycle.
def load_json_object_input(
    *,
    payload_json: str | None,
    payload_file: Path | None,
) -> dict[str, object]:
    return parse_json_input_payload(payload_json=payload_json, payload_file=payload_file)


__all__ = ["parse_json_input_payload", "load_json_object_input"]
