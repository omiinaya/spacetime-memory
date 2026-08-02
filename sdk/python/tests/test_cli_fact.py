"""Tests for cli.stmem.commands.fact.

Covers fact add, list, search, get, update, and delete commands.
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


def _make_fact_sql_side_effect(json_data_for_sql: str = "[]"):
    """Build a side_effect for _http.post that routes SQL vs reducer calls.

    Reducer calls just need HTTP 200; SQL calls need proper SpacetimeDB
    SQL wire-format responses.
    """
    def side_effect(url, *args, **kwargs):
        url_str = str(url)
        if "/sql" in url_str:
            return Mock(
                status_code=200,
                text=make_sql_response([{"json_data": json_data_for_sql}]),
            )
        return Mock(status_code=200, text="{}")
    return side_effect


@pytest.mark.unit
class TestFact:
    """Fact management commands."""

    def test_fact_add_success(self, mocked_cli_runner):
        """fact add creates a new fact."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, ["fact", "add", "ws1", "peer1", "Alice likes coffee"]
        )
        assert result.exit_code == 0
        assert "Fact added" in result.output

    def test_fact_add_with_options(self, mocked_cli_runner):
        """fact add accepts optional type, category, confidence, source, tier."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, [
                "fact", "add", "ws1", "peer1", "Bob hates spam",
                "--type", "static",
                "--category", "preference",
                "--confidence", "0.9",
                "--source", "manual",
                "--tier", "L0",
            ]
        )
        assert result.exit_code == 0
        assert "Fact added" in result.output

    def test_fact_list_empty(self, mocked_cli_runner):
        """fact list with no facts shows empty table."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _make_fact_sql_side_effect("[]")
        result = runner.invoke(cli, ["fact", "list", "ws1"])
        assert result.exit_code == 0

    def test_fact_list_with_filters(self, mocked_cli_runner):
        """fact list passes filter options to _call."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _make_fact_sql_side_effect("[]")
        result = runner.invoke(
            cli, ["fact", "list", "ws1", "--peer", "peer1", "--type", "dynamic", "--tier", "L1"]
        )
        assert result.exit_code == 0

    def test_fact_list_watch(self, mocked_cli_runner):
        """fact list --watch starts a watch loop (we trigger KeyboardInterrupt)."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _make_fact_sql_side_effect("[]")
        import threading
        import time

        def _interrupt():
            time.sleep(0.2)
            import os
            os.kill(os.getpid(), 2)  # SIGINT

        t = threading.Thread(target=_interrupt, daemon=True)
        t.start()
        result = runner.invoke(cli, ["fact", "list", "ws1", "--watch"])
        # Should not crash — KeyboardInterrupt is caught and loop exits
        assert result.exit_code in (0, -2)

    def test_fact_search_success(self, mocked_cli_runner):
        """fact search finds facts by content."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _make_fact_sql_side_effect(
            json.dumps([{"id": "f1", "content": "likes coffee"}])
        )
        result = runner.invoke(cli, ["fact", "search", "ws1", "coffee"])
        assert result.exit_code == 0

    def test_fact_search_empty(self, mocked_cli_runner):
        """fact search with no results shows empty table."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = _make_fact_sql_side_effect("[]")
        result = runner.invoke(cli, ["fact", "search", "ws1", "nothing"])
        assert result.exit_code == 0

    def test_fact_get_found(self, mocked_cli_runner):
        """fact get retrieves a single fact by ID."""
        runner, mock_client = mocked_cli_runner
        fact_data = {"id": "f1", "content": "test fact", "peer_id": "p1"}
        # fact_get uses _sql_param which needs SQL response format
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([fact_data]),
        )
        result = runner.invoke(cli, ["fact", "get", "f1"])
        assert result.exit_code == 0
        assert "f1" in result.output or "test fact" in result.output

    def test_fact_get_not_found(self, mocked_cli_runner):
        """fact get shows 'not found' when no matching fact."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(
            status_code=200, text=json.dumps([]),
        )
        result = runner.invoke(cli, ["fact", "get", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_fact_update_success(self, mocked_cli_runner):
        """fact update modifies a fact's fields."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, ["fact", "update", "f1", "--content", "new content", "--confidence", "0.95"]
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_fact_update_with_tier(self, mocked_cli_runner):
        """fact update with tier and category."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, ["fact", "update", "f1", "--tier", "L0", "--category", "behavior"]
        )
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_fact_delete_success(self, mocked_cli_runner):
        """fact delete deactivates a fact."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["fact", "delete", "f1"])
        assert result.exit_code == 0
        assert "deactivated" in result.output.lower()

    def test_fact_missing_args(self, runner):
        """fact commands fail gracefully with missing arguments."""
        result = runner.invoke(cli, ["fact", "add"])
        assert result.exit_code != 0
        result = runner.invoke(cli, ["fact", "list"])
        assert result.exit_code != 0

    def test_fact_help(self, runner):
        result = runner.invoke(cli, ["fact", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "list" in result.output
        assert "search" in result.output
        assert "get" in result.output
        assert "update" in result.output
        assert "delete" in result.output
