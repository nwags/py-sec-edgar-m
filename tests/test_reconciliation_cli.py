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
