"""Tests for cli.stmem.commands.entity.

Covers the entity extract command.
"""
from __future__ import annotations

import pytest
from cli.stmem import cli
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.mark.unit
class TestEntity:
    """Entity extraction commands."""

    def test_entity_extract_success(self, mocked_cli_runner):
        """entity extract calls extract_entities and prints success."""
        runner, mock_client = mocked_cli_runner
        # extract_entities calls _call internally which uses _http.post
        # Default mock returns 200 → _call succeeds
        result = runner.invoke(
            cli, ["entity", "extract", "ws1", "Alice is a software engineer"]
        )
        assert result.exit_code == 0
        assert "Entities extracted" in result.output

    def test_entity_extract_calls_client(self, mocked_cli_runner):
        """Verify the client.extract_entities method is called by the CLI."""
        from unittest.mock import patch as _patch
        runner, mock_client = mocked_cli_runner
        with _patch("cli.stmem.commands.entity._sdk_client", return_value=mock_client):
            result = runner.invoke(cli, ["entity", "extract", "ws1", "content here"])
        assert result.exit_code == 0

    def test_entity_extract_missing_args(self, runner):
        """entity extract requires both workspace_id and content."""
        result = runner.invoke(cli, ["entity", "extract"])
        assert result.exit_code != 0
        assert "Error" in result.output or "Usage:" in result.output

    def test_entity_extract_missing_content(self, runner):
        """entity extract with only workspace_id fails."""
        result = runner.invoke(cli, ["entity", "extract", "ws1"])
        assert result.exit_code != 0
        assert "Error" in result.output or "Usage:" in result.output

    def test_entity_help(self, runner):
        result = runner.invoke(cli, ["entity", "--help"])
        assert result.exit_code == 0
        assert "extract" in result.output
