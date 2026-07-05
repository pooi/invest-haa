import json

from typer.testing import CliRunner

from invest_haa.cli import app


def cli_env(tmp_path):
    return {
        "TOSS_CLIENT_ID": "test-client",
        "TOSS_CLIENT_SECRET": "test-secret",
        "TOSS_ACCOUNT_SEQ": "1",
        "CAPITAL_CEILING_USD": "10000",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test/test/test",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'cli.sqlite3'}",
        "LIVE_TRADING": "false",
    }


def test_runs_command_returns_json_without_api_call(tmp_path):
    result = CliRunner().invoke(app, ["runs"], env=cli_env(tmp_path))
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_plan_rejects_invalid_signal_month_before_api_call(tmp_path):
    result = CliRunner().invoke(
        app,
        ["plan", "--signal-month", "not-a-month"],
        env=cli_env(tmp_path),
    )
    assert result.exit_code == 2
    assert "signal-month must be YYYY-MM" in result.output


def test_show_run_reports_missing_id(tmp_path):
    result = CliRunner().invoke(app, ["show-run", "missing"], env=cli_env(tmp_path))
    assert result.exit_code == 1
    assert "run not found" in result.output
