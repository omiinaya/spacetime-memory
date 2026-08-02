"""Tests for cli.stmem.commands.tag.

Covers tag list, delete, batch-tag, and batch-untag commands.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from cli.stmem import cli
from click.testing import CliRunner
from conftest import make_sql_response


@pytest.fixture
def runner():
    return CliRunner()


def _sql_routing_side_effect(sql_response_text: str):
    """Build a side_effect for _http.post that routes SQL vs reducer calls.

    Returns 200 for all calls, but SQL endpoints get real SQL wire-format
    responses while reducer calls just get empty JSON.
    """
    def side_effect(url, *args, **kwargs):
        url_str = str(url)
        if "/sql" in url_str:
            return Mock(status_code=200, text=sql_response_text)
        return Mock(status_code=200, text="{}")
    return side_effect


@pytest.mark.unit
class TestTag:
    """Tag management commands."""

    def test_tag_list_empty(self, mocked_cli_runner):
        """tag list shows 'no tags' when the workspace has none."""
        runner, mock_client = mocked_cli_runner
        # list_tags calls _call then _query → _sql
        # Default mock returns text=json.dumps([]) for all URLs,
        # so _sql returns [] and _query returns []
        result = runner.invoke(cli, ["tag", "list", "ws1"])
        assert result.exit_code == 0
        assert "No tags found" in result.output

    def test_tag_list_with_data(self, mocked_cli_runner):
        """tag list shows tags in table format."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _sql_routing_side_effect(
            make_sql_response([{"id": "t1", "row_json": json.dumps({
                "id": "t1", "name": "important", "color": "#ff0000", "created_at": "2024-01-01"
            })}])
        )
        result = runner.invoke(cli, ["tag", "list", "ws1"])
        assert result.exit_code == 0
        assert "important" in result.output

    def test_tag_list_json(self, mocked_cli_runner):
        """tag list --json outputs raw JSON."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _sql_routing_side_effect(
            make_sql_response([{"id": "t1", "row_json": json.dumps({
                "id": "t1", "name": "important", "color": "#ff0000"
            })}])
        )
        result = runner.invoke(cli, ["tag", "list", "ws1", "--json"])
        assert result.exit_code == 0
        assert "important" in result.output

    def test_tag_list_default_workspace(self, mocked_cli_runner):
        """tag list uses 'default' workspace when none specified."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _sql_routing_side_effect(
            json.dumps([])
        )
        result = runner.invoke(cli, ["tag", "list"])
        assert result.exit_code == 0
        assert "No tags found" in result.output

    def test_tag_delete_confirmed(self, mocked_cli_runner):
        """tag delete --yes skips confirmation and deletes."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["tag", "delete", "t1", "-y"])
        assert result.exit_code == 0
        assert "deleted" in result.output.lower()

    def test_tag_delete_without_yes_confirmed(self, mocked_cli_runner, monkeypatch):
        """tag delete without -y prompts and proceeds on confirmation."""
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("click.confirm", lambda msg, default: True)
        result = runner.invoke(cli, ["tag", "delete", "t1"])
        assert result.exit_code == 0
        assert "deleted" in result.output.lower()

    def test_tag_delete_cancelled(self, mocked_cli_runner, monkeypatch):
        """tag delete without -y cancels when user says no."""
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("click.confirm", lambda msg, default: False)
        result = runner.invoke(cli, ["tag", "delete", "t1"])
        assert result.exit_code == 0
        assert "Cancelled" in result.output

    def test_tag_batch_tag_success(self, mocked_cli_runner):
        """tag batch-tag attaches a tag to multiple memories."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["tag", "batch-tag", "t1", "m1,m2,m3"])
        assert result.exit_code == 0
        assert "Tagged" in result.output

    def test_tag_batch_tag_empty_ids(self, mocked_cli_runner):
        """tag batch-tag with empty memory IDs shows warning."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["tag", "batch-tag", "t1", ""])
        assert result.exit_code == 0
        assert "No memory IDs provided" in result.output

    def test_tag_batch_untag_success(self, mocked_cli_runner):
        """tag batch-untag removes a tag from multiple memories."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["tag", "batch-untag", "t1", "m1,m2,m3"])
        assert result.exit_code == 0
        assert "Untagged" in result.output

    def test_tag_batch_untag_empty_ids(self, mocked_cli_runner):
        """tag batch-untag with empty memory IDs shows warning."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["tag", "batch-untag", "t1", ""])
        assert result.exit_code == 0
        assert "No memory IDs provided" in result.output

    def test_tag_help(self, runner):
        result = runner.invoke(cli, ["tag", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "delete" in result.output
        assert "batch-tag" in result.output
        assert "batch-untag" in result.output
