from __future__ import annotations

from pathlib import Path


def _block(text: str, key: str) -> str:
    marker = f"{key}:"
    start = text.find(marker)
    assert start != -1, f"Missing block: {key}"
    lines = text[start:].splitlines()
    indent = None
    out = []
    for i, line in enumerate(lines):
        if i == 0:
            out.append(line)
            continue
        if not line.strip():
            out.append(line)
            continue
        if indent is None:
            indent = len(line) - len(line.lstrip(" "))
        current_indent = len(line) - len(line.lstrip(" "))
        if current_indent < indent:
            break
        out.append(line)
    return "\n".join(out)


def test_compose_yaml_exists() -> None:
    assert Path("compose.yaml").exists()


def test_compose_has_api_and_monitor_services() -> None:
    text = Path("compose.yaml").read_text(encoding="utf-8")
    assert "services:" in text
    assert "\n  api:" in text
    assert "\n  monitor:" in text


def test_compose_configures_persistent_mounts_for_both_services() -> None:
    text = Path("compose.yaml").read_text(encoding="utf-8")
    api_block = _block(text, "  api")
    monitor_block = _block(text, "  monitor")
    assert "${PY_SEC_EDGAR_HOST_DATA_ROOT:-.}:/workspace" in api_block
    assert "${PY_SEC_EDGAR_HOST_DATA_ROOT:-.}:/workspace" in monitor_block


def test_compose_project_root_env_is_aligned_with_workspace_mount() -> None:
    text = Path("compose.yaml").read_text(encoding="utf-8")
    api_block = _block(text, "  api")
    monitor_block = _block(text, "  monitor")
    assert "PY_SEC_EDGAR_PROJECT_ROOT: /workspace" in api_block
    assert "PY_SEC_EDGAR_PROJECT_ROOT: /workspace" in monitor_block


def test_compose_points_commands_to_service_runtime_wrapper() -> None:
    text = Path("compose.yaml").read_text(encoding="utf-8")
    assert '"python", "-m", "py_sec_edgar.service_runtime", "api"' in text
    assert '"python", "-m", "py_sec_edgar.service_runtime", "monitor-loop"' in text


def test_compose_api_has_port_mapping_and_monitor_has_no_ports() -> None:
    text = Path("compose.yaml").read_text(encoding="utf-8")
    api_block = _block(text, "  api")
    monitor_block = _block(text, "  monitor")
    assert "ports:" in api_block
    assert "${PY_SEC_EDGAR_API_PORT:-8000}:${PY_SEC_EDGAR_API_PORT:-8000}" in api_block
    assert "ports:" not in monitor_block


def test_compose_api_healthcheck_is_python_based() -> None:
    text = Path("compose.yaml").read_text(encoding="utf-8")
    api_block = _block(text, "  api")
    assert "healthcheck:" in api_block
    assert "- CMD" in api_block
    assert "- python" in api_block
    assert "/health" in api_block
