from __future__ import annotations

import json

from click.testing import CliRunner

import py_sec_edgar.cli as cli


def test_reconcile_help_includes_run_command() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["reconcile", "--help"])
    assert result.exit_code == 0
    assert "run" in result.output


def test_reconcile_run_help_includes_expected_options() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["reconcile", "run", "--help"])
    assert result.exit_code == 0
    assert "--recent-days" in result.output
    assert "--date-from" in result.output
    assert "--date-to" in result.output
    assert "--catch-up-warm / --no-catch-up-warm" in result.output
    assert "--refresh-lookup / --no-refresh-lookup" in result.output
    assert "--summary-json" in result.output
    assert "--progress-json" in result.output
    assert "--progress-heartbeat-seconds" in result.output


def test_reconcile_run_summary_json(monkeypatch) -> None:
    runner = CliRunner()
    calls = {}
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run(config, **kwargs):
        calls.update(kwargs)
        return {
            "reconciled_row_count": 2,
            "catch_up_attempted_count": 1,
            "lookup_update_mode": "incremental",
        }

    monkeypatch.setattr(cli, "run_reconciliation", fake_run)

    result = runner.invoke(
        cli.main,
        [
            "reconcile",
            "run",
            "--summary-json",
            "--recent-days",
            "3",
            "--form-type",
            "8-K",
            "--catch-up-warm",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["reconciled_row_count"] == 2
    assert calls["recent_days"] == 3
    assert calls["form_types"] == ["8-K"]
    assert calls["catch_up_warm"] is True


def test_reconcile_run_summary_json_with_progress_json_keeps_stdout_clean(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run(config, **kwargs):
        callback = kwargs.get("progress_callback")
        if callback:
            callback(
                {
                    "phase": "reconcile.run.rows",
                    "counters": {"reconciled_row_count": 1},
                    "detail": "rows_processed",
                    "window_date": "2025-01-15",
                    "window_index": 1,
                    "window_total": 3,
                }
            )
        return {
            "reconciled_row_count": 1,
            "catch_up_attempted_count": 0,
            "catch_up_succeeded_count": 0,
            "catch_up_failed_count": 0,
            "catch_up_skipped_count": 0,
        }

    monkeypatch.setattr(cli, "run_reconciliation", fake_run)
    result = runner.invoke(cli.main, ["reconcile", "run", "--summary-json", "--progress-json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["reconciled_row_count"] == 1

    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert all('"event": "progress"' in line for line in stderr_lines)


def test_reconcile_run_keyboard_interrupt_exits_cleanly(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run(config, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "run_reconciliation", fake_run)
    result = runner.invoke(cli.main, ["reconcile", "run"])
    assert result.exit_code != 0
    assert "Interrupted by user." in result.output
    assert "Traceback" not in result.output


def test_reconcile_run_summary_json_canonical_schema_is_additive(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_run(config, **kwargs):
        return {
            "reconciled_row_count": 1,
            "catch_up_attempted_count": 1,
            "catch_up_succeeded_count": 1,
            "catch_up_failed_count": 0,
            "catch_up_skipped_count": 0,
            "total_elapsed_seconds": 0.2,
        }

    monkeypatch.setattr(cli, "run_reconciliation", fake_run)
    result = runner.invoke(
        cli.main,
        ["reconcile", "run", "--summary-json", "--progress-json", "--output-schema", "canonical"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["domain"] == "sec"
    assert payload["command_path"] == ["py-sec-edgar", "reconcile", "run"]
    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert stderr_lines
    assert json.loads(stderr_lines[0])["domain"] == "sec"
