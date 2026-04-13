from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
import pandas as pd

import py_sec_edgar.cli as cli
from py_sec_edgar.augmentation_sidecars import persist_augmentation_submission
from py_sec_edgar.config import load_config
from py_sec_edgar.lookup import local_lookup_filings_path


class _DummyConfig:
    pass


def _patch_m_cache_config(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_m_cache_effective_config", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(cli, "effective_config_to_app_config", lambda effective: _DummyConfig())


def test_m_cache_help_and_sec_families_visible(monkeypatch) -> None:
    _patch_m_cache_config(monkeypatch)
    runner = CliRunner()

    top = runner.invoke(cli.m_cache_main, ["--help"])
    sec = runner.invoke(cli.m_cache_main, ["sec", "--help"])

    assert top.exit_code == 0
    assert "sec" in top.output

    assert sec.exit_code == 0
    assert "refdata" in sec.output
    assert "lookup" in sec.output
    assert "monitor" in sec.output
    assert "reconcile" in sec.output
    assert "aug" in sec.output
    assert "augmentations" in sec.output
    assert "providers" in sec.output
    assert "resolve" in sec.output
    assert "storage" in sec.output
    assert "audit" in sec.output
    assert "api" in sec.output


def test_m_cache_lookup_refresh_emits_canonical_summary_and_progress(monkeypatch) -> None:
    _patch_m_cache_config(monkeypatch)
    runner = CliRunner()

    def fake_refresh(config, **kwargs):
        callback = kwargs.get("progress_callback")
        if callback:
            callback({"phase": "lookup.refresh.build", "counters": {"filings_row_count": 2}, "detail": "building"})
        return {
            "placement_row_count": 4,
            "local_placement_row_count": 3,
            "filings_row_count": 2,
            "artifacts_row_count": 6,
            "elapsed_seconds": 0.12,
        }

    monkeypatch.setattr(cli, "refresh_local_lookup_indexes", fake_refresh)

    result = runner.invoke(cli.m_cache_main, ["sec", "lookup", "refresh"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout.strip())
    assert payload["domain"] == "sec"
    assert payload["command_path"] == ["m-cache", "sec", "lookup", "refresh"]
    assert payload["counters"]["candidate_count"] == 4
    assert payload["counters"]["succeeded_count"] == 2

    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(stderr_lines) >= 2
    first = json.loads(stderr_lines[0])
    last = json.loads(stderr_lines[-1])
    assert first["event"] == "started"
    assert first["domain"] == "sec"
    assert first["command_path"] == ["m-cache", "sec", "lookup", "refresh"]
    assert last["event"] in {"completed", "interrupted"}


def test_aug_aliases_exist_for_legacy_and_m_cache(monkeypatch) -> None:
    _patch_m_cache_config(monkeypatch)
    runner = CliRunner()

    legacy_aug = runner.invoke(cli.main, ["aug", "--help"])
    legacy_augmentations = runner.invoke(cli.main, ["augmentations", "--help"])
    mcache_aug = runner.invoke(cli.m_cache_main, ["sec", "aug", "--help"])
    mcache_augmentations = runner.invoke(cli.m_cache_main, ["sec", "augmentations", "--help"])

    assert legacy_aug.exit_code == 0
    assert legacy_augmentations.exit_code == 0
    assert "events" in legacy_aug.output
    assert "events" in legacy_augmentations.output

    assert mcache_aug.exit_code == 0
    assert mcache_augmentations.exit_code == 0
    assert "events" in mcache_aug.output
    assert "events" in mcache_augmentations.output
    assert "list-types" in mcache_aug.output
    assert "inspect-target" in mcache_aug.output
    assert "status" in mcache_aug.output
    assert "submit-run" in mcache_aug.output
    assert "submit-artifact" in mcache_aug.output
    assert "inspect-runs" in mcache_aug.output
    assert "inspect-artifacts" in mcache_aug.output


def test_m_cache_aug_wave3_read_wrappers(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
cache_root = ".sec_cache"
normalized_refdata_root = "refdata/normalized"
lookup_root = "refdata/normalized"
default_resolution_mode = "local_only"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    config.ensure_runtime_dirs()
    pd.DataFrame(
        [
            {
                "CIK": "320193",
                "Form Type": "8-K",
                "Date Filed": "2025-01-15",
                "Filename": "edgar/data/320193/0000320193-25-000010.txt",
            }
        ]
    ).to_parquet(config.merged_index_path, index=False)
    persist_augmentation_submission(
        config,
        producer_id="ext-annotator",
        layer_type="entities",
        schema_version="v1",
        producer_run_id="run-1",
        pipeline_id="pipe-1",
        model_id="model-1",
        producer_version="1.2.3",
        items=[
            {
                "accession_number": "0000320193-25-000010",
                "augmentation_type": "entity_mentions",
                "payload": {"mentions": [{"text": "Apple"}]},
                "payload_schema_version": "ps1",
            }
        ],
        raw_request={"seed": True},
    )

    runner = CliRunner()
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))

    list_types = runner.invoke(
        cli.m_cache_main,
        ["sec", "--config", str(cfg_path), "aug", "list-types", "--json"],
    )
    assert list_types.exit_code == 0
    list_payload = json.loads(list_types.stdout)
    assert {row["augmentation_type"] for row in list_payload["types"]} == {
        "entity_tagging",
        "temporal_expression_tagging",
    }

    inspect_target = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "aug",
            "inspect-target",
            "--accession-number",
            "0000320193-25-000010",
            "--json",
        ],
    )
    assert inspect_target.exit_code == 0
    target_payload = json.loads(inspect_target.stdout)
    assert target_payload["augmentation_meta"]["augmentation_available"] is True
    assert "entity_tagging" in target_payload["augmentation_meta"]["augmentation_types_present"]

    inspect_runs = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "aug",
            "inspect-runs",
            "--accession-number",
            "0000320193-25-000010",
            "--json",
        ],
    )
    assert inspect_runs.exit_code == 0
    runs_payload = json.loads(inspect_runs.stdout)
    assert len(runs_payload["runs"]) >= 1
    assert runs_payload["runs"][0]["augmentation_type"] == "entity_tagging"
    assert runs_payload["runs"][0]["producer_version"] == "1.2.3"
    assert runs_payload["runs"][0]["producer_run_id"] == "run-1"
    assert str(runs_payload["runs"][0]["source_text_version"]).startswith("sha256:")

    inspect_artifacts = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "augmentations",
            "inspect-artifacts",
            "--accession-number",
            "0000320193-25-000010",
            "--json",
        ],
    )
    assert inspect_artifacts.exit_code == 0
    artifacts_payload = json.loads(inspect_artifacts.stdout)
    assert len(artifacts_payload["artifacts"]) >= 1
    assert artifacts_payload["artifacts"][0]["augmentation_type"] == "entity_tagging"
    assert artifacts_payload["artifacts"][0]["producer_version"] == "1.2.3"
    assert artifacts_payload["artifacts"][0]["payload_schema_version"] == "ps1"
    assert str(artifacts_payload["artifacts"][0]["source_text_version"]).startswith("sha256:")

    status = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "aug",
            "status",
            "--run-id",
            str(runs_payload["runs"][0]["run_id"]),
            "--json",
        ],
    )
    assert status.exit_code == 0
    status_payload = json.loads(status.stdout)
    assert status_payload["status"]["run_id"] == runs_payload["runs"][0]["run_id"]
    assert status_payload["status"]["canonical_key"] == "0000320193-25-000010"
    assert status_payload["status"]["status"] in {"completed", "skipped"}
    assert status_payload["status"]["idempotency_key"]

    status_idempotency = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "aug",
            "status",
            "--idempotency-key",
            str(runs_payload["runs"][0]["run_id"]),
            "--json",
        ],
    )
    assert status_idempotency.exit_code == 0
    status_idempotency_payload = json.loads(status_idempotency.stdout)
    assert status_idempotency_payload["status"]["run_id"] == runs_payload["runs"][0]["run_id"]


def test_m_cache_aug_submit_commands_are_validate_only_and_non_persisting(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
cache_root = ".sec_cache"
normalized_refdata_root = "refdata/normalized"
lookup_root = "refdata/normalized"
default_resolution_mode = "local_only"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    config.ensure_runtime_dirs()
    runner = CliRunner()
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))

    run_payload = {
        "run_id": "run-1",
        "domain": "sec",
        "resource_family": "filing",
        "canonical_key": "0000320193-25-000010",
        "augmentation_type": "entity_tagging",
        "source_text_version": "sha256:abc",
        "producer_kind": "hybrid",
        "producer_name": "producer-x",
        "producer_version": "1.0.0",
        "payload_schema_name": "com.example.entity",
        "payload_schema_version": "2026-04-10",
        "status": "completed",
        "success": True,
        "reason_code": "completed",
    }
    run_result = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "aug",
            "submit-run",
            "--payload-json",
            json.dumps(run_payload),
            "--json",
        ],
    )
    assert run_result.exit_code == 0
    run_response = json.loads(run_result.stdout)
    assert run_response["mode"] == "validate_only"
    assert run_response["persisted"] is False
    assert run_response["non_pilot"] is True
    assert run_response["run"]["run_id"] == "run-1"

    artifact_payload = {
        "domain": "sec",
        "resource_family": "filing",
        "canonical_key": "0000320193-25-000010",
        "augmentation_type": "entity_tagging",
        "source_text_version": "sha256:abc",
        "producer_name": "producer-x",
        "producer_version": "1.0.0",
        "payload_schema_name": "com.example.entity",
        "payload_schema_version": "2026-04-10",
        "payload": {"annotations": [{"span_start": 0, "span_end": 5}]},
        "success": True,
    }
    artifact_result = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "aug",
            "submit-artifact",
            "--payload-json",
            json.dumps(artifact_payload),
            "--json",
        ],
    )
    assert artifact_result.exit_code == 0
    artifact_response = json.loads(artifact_result.stdout)
    assert artifact_response["mode"] == "validate_only"
    assert artifact_response["persisted"] is False
    assert artifact_response["non_pilot"] is True
    assert artifact_response["artifact"]["canonical_key"] == "0000320193-25-000010"

    assert not (config.normalized_refdata_root / "producer_protocol_inbox.parquet").exists()
    assert not (config.normalized_refdata_root / "producer_submissions.parquet").exists()


def test_m_cache_providers_list_and_show(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
cache_root = ".sec_cache"
normalized_refdata_root = "refdata/normalized"
lookup_root = "refdata/normalized"
default_resolution_mode = "local_only"

[domains.sec.providers.sec]
enabled = true
auth_type = "none"
rate_limit_policy = "custom"
soft_limit = 10
hard_limit = 10
burst_limit = 1
retry_budget = 2
direct_resolution_allowed = true
browse_discovery_allowed = true
supports_bulk_history = true
supports_incremental_refresh = true
supports_direct_resolution = true
supports_public_resolve_if_missing = false
supports_admin_refresh_if_stale = false
graceful_degradation_policy = "defer_and_report"
fallback_priority = 10
is_active = true
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))

    list_result = runner.invoke(cli.m_cache_main, ["sec", "--config", str(cfg_path), "providers", "list"])
    assert list_result.exit_code == 0
    rows = json.loads(list_result.stdout)
    assert rows
    assert rows[0]["provider_id"] == "sec"
    assert rows[0]["rate_limit_policy"] in {"custom", "token_bucket"}

    show_result = runner.invoke(
        cli.m_cache_main,
        ["sec", "--config", str(cfg_path), "providers", "show", "--provider", "sec"],
    )
    assert show_result.exit_code == 0
    payload = json.loads(show_result.stdout)
    assert payload["provider_id"] == "sec"
    assert "effective_auth_present" in payload
    assert "effective_enabled" in payload
    assert "rate_limit_state" in payload
    assert payload["rate_limit_state"]["provider_id"] == "sec"


def test_m_cache_resolve_filing_modes(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "m-cache.toml"
    cfg_path.write_text(
        """
[domains.sec]
cache_root = ".sec_cache"
normalized_refdata_root = "refdata/normalized"
lookup_root = "refdata/normalized"
default_resolution_mode = "local_only"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    config.ensure_runtime_dirs()
    pd.DataFrame(
        [
            {
                "accession_number": "0000320193-25-000010",
                "filename": "edgar/data/320193/0000320193-25-000010.txt",
                "submission_exists": False,
                "submission_path_count": 0,
            }
        ]
    ).to_parquet(local_lookup_filings_path(config), index=False)

    runner = CliRunner()
    monkeypatch.setenv("PY_SEC_EDGAR_PROJECT_ROOT", str(tmp_path))

    local_only = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "resolve",
            "filing",
            "--accession-number",
            "0000320193-25-000010",
            "--resolution-mode",
            "local_only",
        ],
    )
    assert local_only.exit_code == 0
    payload = json.loads(local_only.stdout)
    assert payload["resolution_mode"] == "local_only"
    assert payload["remote_attempted"] is False
    assert payload["reason_code"] == "local_miss"

    unsupported = runner.invoke(
        cli.m_cache_main,
        [
            "sec",
            "--config",
            str(cfg_path),
            "resolve",
            "filing",
            "--accession-number",
            "0000320193-25-000010",
            "--resolution-mode",
            "refresh_if_stale",
        ],
    )
    assert unsupported.exit_code != 0
    assert "not implemented" in unsupported.output
