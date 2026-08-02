"""Tests for cli.stmem.commands.apikey.

Covers apikey create, revoke, and list commands.
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
class TestApikey:
    """API key management commands."""

    def test_apikey_create(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["apikey", "create", "ws1", "my-key"])
        assert result.exit_code == 0
        assert "created" in result.output.lower()

    def test_apikey_create_with_permissions(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, ["apikey", "create", "ws1", "my-key", "--permissions", '["read","write"]']
        )
        assert result.exit_code == 0

    def test_apikey_revoke(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["apikey", "revoke", "key-1234567890abcdef"])
        assert result.exit_code == 0
        assert "revoked" in result.output.lower()

    def test_apikey_list_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["apikey", "list", "ws1"])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_apikey_list_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        # list_api_keys uses _query which needs SQL response for the
        # second HTTP call. Use side_effect to route calls correctly:
        # call #1 → reducer call (_call → needs status 200)
        # call #2 → _query → _call (reducer) then _sql (needs SQL response)
        def _side_effect(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=make_sql_response([{"id": "k1", "name": "my-key", "permissions": '["read"]'}]),
                )
            return Mock(status_code=200, text="{}")
        mock_client._http.post.side_effect = _side_effect
        result = runner.invoke(cli, ["apikey", "list", "ws1"])
        assert result.exit_code == 0
        assert "my-key" in result.output

    def test_apikey_help(self, runner):
        result = runner.invoke(cli, ["apikey", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "revoke" in result.output
        assert "list" in result.output
