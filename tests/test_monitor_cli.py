from __future__ import annotations

import json

from click.testing import CliRunner

import py_sec_edgar.cli as cli


def test_monitor_help_includes_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["monitor", "--help"])
    assert result.exit_code == 0
    assert "poll" in result.output
    assert "loop" in result.output


def test_monitor_poll_help_includes_expected_options() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["monitor", "poll", "--help"])
    assert result.exit_code == 0
    assert "--warm / --no-warm" in result.output
    assert "--summary-json" in result.output
    assert "--progress-json" in result.output
    assert "--refresh-lookup / --no-refresh-lookup" in result.output
    assert "--execute-extraction / --no-execute-extraction" in result.output
    assert "--persist-filing-parties / --no-persist-filing-parties" in result.output


def test_monitor_loop_help_includes_expected_options() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["monitor", "loop", "--help"])
    assert result.exit_code == 0
    assert "--interval-seconds" in result.output
    assert "--max-iterations" in result.output
    assert "--summary-json" in result.output


def test_monitor_poll_summary_json(monkeypatch) -> None:
    runner = CliRunner()
    calls = {}
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_poll(config, **kwargs):
        calls.update(kwargs)
        return {"detected_candidate_count": 1, "warm_succeeded_count": 1}

    monkeypatch.setattr(cli, "run_monitor_poll", fake_poll)
    result = runner.invoke(cli.main, ["monitor", "poll", "--summary-json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["detected_candidate_count"] == 1
    assert calls["refresh_lookup"] is True


def test_monitor_poll_summary_json_with_progress_json_keeps_stdout_clean(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_poll(config, **kwargs):
        return {
            "detected_candidate_count": 3,
            "filtered_candidate_count": 2,
            "warm_attempted_count": 2,
            "warm_succeeded_count": 1,
            "warm_failed_count": 1,
        }

    monkeypatch.setattr(cli, "run_monitor_poll", fake_poll)
    result = runner.invoke(cli.main, ["monitor", "poll", "--summary-json", "--progress-json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["detected_candidate_count"] == 3



def test_monitor_loop_summary_json(monkeypatch) -> None:
    runner = CliRunner()
    calls = {}
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_loop(config, **kwargs):
        calls.update(kwargs)
        return {"iterations_run": 2, "total_warm_succeeded_count": 1}

    monkeypatch.setattr(cli, "run_monitor_loop", fake_loop)
    result = runner.invoke(
        cli.main,
        ["monitor", "loop", "--summary-json", "--interval-seconds", "0", "--max-iterations", "2"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["iterations_run"] == 2
    assert calls["max_iterations"] == 2


def test_monitor_poll_keyboard_interrupt_exits_cleanly(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: object())

    def fake_poll(config, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "run_monitor_poll", fake_poll)
    result = runner.invoke(cli.main, ["monitor", "poll"])
    assert result.exit_code != 0
    assert "Interrupted by user." in result.output
    assert "Traceback" not in result.output
