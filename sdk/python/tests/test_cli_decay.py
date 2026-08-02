"""Tests for cli.stmem.commands.decay.

Covers decay set-linear, set-weibull, show, and run commands.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest
from cli.stmem import cli
from click.testing import CliRunner
from conftest import make_sql_response


@pytest.fixture
def runner():
    return CliRunner()


@pytest.mark.unit
class TestDecay:
    """Decay configuration commands."""

    def test_decay_set_linear(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, ["decay", "set-linear", "ws1", "--rate", "0.01", "--max-days", "60"]
        )
        assert result.exit_code == 0
        assert "Linear decay" in result.output

    def test_decay_set_linear_defaults(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["decay", "set-linear", "ws1"])
        assert result.exit_code == 0

    def test_decay_set_weibull(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["decay", "set-weibull", "ws1", "-k", "0.5", "-l", "45"])
        assert result.exit_code == 0
        assert "Weibull decay" in result.output

    def test_decay_set_weibull_defaults(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["decay", "set-weibull", "ws1"])
        assert result.exit_code == 0
        assert "Weibull" in result.output

    def test_decay_show_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        # get_decay_config calls _call then _sql → _sql needs parser to return []
        result = runner.invoke(cli, ["decay", "show", "ws1"])
        assert result.exit_code == 0
        assert "No decay config" in result.output

    def test_decay_show_with_config(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        # Route: first call = reducer, second = SQL (for get_decay_config)
        def _side_effect(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=make_sql_response([{"decay_model": "linear", "decay_rate": 0.005}]),
                )
            return Mock(status_code=200, text="{}")
        mock_client._http.post.side_effect = _side_effect
        result = runner.invoke(cli, ["decay", "show", "ws1"])
        assert result.exit_code == 0
        assert "linear" in result.output

    def test_decay_run_linear(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        def _side_effect(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=make_sql_response([{"decay_model": "linear", "decay_rate": 0.005}]),
                )
            return Mock(status_code=200, text="{}")
        mock_client._http.post.side_effect = _side_effect
        result = runner.invoke(cli, ["decay", "run", "ws1"])
        assert result.exit_code == 0
        assert "decay cycle complete" in result.output

    def test_decay_run_weibull(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        def _side_effect(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=make_sql_response([
                        {"decay_model": "weibull", "weibull_shape": 0.6, "weibull_scale": 30.0}
                    ]),
                )
            return Mock(status_code=200, text="{}")
        mock_client._http.post.side_effect = _side_effect
        result = runner.invoke(cli, ["decay", "run", "ws1"])
        assert result.exit_code == 0
        assert "weibull decay cycle complete" in result.output.lower()

    def test_decay_missing_workspace_id(self, runner):
        result = runner.invoke(cli, ["decay", "show"])
        assert result.exit_code != 0
        assert "Error" in result.output or "Usage:" in result.output

    def test_decay_help(self, runner):
        result = runner.invoke(cli, ["decay", "--help"])
        assert result.exit_code == 0
        assert "set-linear" in result.output
        assert "set-weibull" in result.output
        assert "show" in result.output
        assert "run" in result.output
