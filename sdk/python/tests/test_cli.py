"""Tests for the stmem CLI using Click's CliRunner.

The CLI creates its own Client internally via ``_make_client()``, so the
``mock_http_client`` fixture is not directly usable.  Instead we
monkeypatch ``stmem._make_client`` to return a pre-mocked Client.
"""

import json
import pytest
from unittest.mock import Mock
from click.testing import CliRunner
from cli.stmem import cli, _make_client
from tests.conftest import make_sql_response


# ------------------------------------------------------------------
# Fixture: CLI runner with a mocked client
# ------------------------------------------------------------------


@pytest.fixture
def runner():
    """Return a CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture
def mock_client():
    """Return a Client whose _http is mocked (same as mock_http_client)."""
    from spacetime_memory import Client
    import httpx
    from unittest.mock import MagicMock

    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = Mock(status_code=200, text=json.dumps([]))
    client._http = mock_http
    return client


@pytest.fixture
def mocked_cli_runner(monkeypatch, runner, mock_client):
    """A CliRunner where the CLI's ``_make_client`` returns a mocked Client."""
    monkeypatch.setattr("cli.stmem._make_client", lambda **kw: mock_client)
    return runner, mock_client


class TestCliHelp:
    """Basic CLI invocation."""

    def test_help_flag(self, runner):
        """--help prints usage and exits with code 0."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # The CLI's help text mentions "manage workspaces"
        assert "spacetime-memory" in result.output.lower()

    def test_no_args_shows_help(self, runner):
        """Invoking without arguments shows help (exit code 2, usage on stderr)."""
        result = runner.invoke(cli, [])
        # Click exits with code 2 when a required command is missing
        assert result.exit_code == 2
        assert "Usage:" in result.output

    def test_workspace_help(self, runner):
        """workspace --help shows subcommands."""
        result = runner.invoke(cli, ["workspace", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "create" in result.output

    def test_memory_help(self, runner):
        """memory --help shows subcommands."""
        result = runner.invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "store" in result.output
        assert "search" in result.output
        assert "list" in result.output


class TestCliWorkspace:
    """CLI workspace commands."""

    def test_workspace_list_empty(self, mocked_cli_runner):
        """workspace list shows '(no workspaces)' when empty."""
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["workspace", "list"])
        assert result.exit_code == 0
        assert "(no workspaces)" in result.output

    def test_workspace_list_with_data(self, mocked_cli_runner):
        """workspace list shows workspace JSON."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"id": "1", "name": "ws1"}]),
        )
        result = runner.invoke(cli, ["workspace", "list"])
        assert result.exit_code == 0
        assert "ws1" in result.output

    def test_workspace_create(self, mocked_cli_runner):
        """workspace create calls the reducer and prints status."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )
        result = runner.invoke(cli, ["workspace", "create", "my-workspace"])
        assert result.exit_code == 0
        assert '"status": "ok"' in result.output


class TestCliMemory:
    """CLI memory commands."""

    def test_memory_store(self, mocked_cli_runner):
        """memory store calls the store_memory reducer."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )
        result = runner.invoke(cli, [
            "memory", "store", "ws1", "hello world",
            "--peer-id", "cli-test",
        ])
        assert result.exit_code == 0
        assert '"status": "ok"' in result.output

    def test_memory_list_empty(self, mocked_cli_runner):
        """memory list shows '(no memories)' when empty."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([]),
        )
        result = runner.invoke(cli, ["memory", "list", "ws1"])
        assert result.exit_code == 0
        assert "(no memories)" in result.output or "no memories" in result.output

    def test_memory_list_with_data(self, mocked_cli_runner):
        """memory list shows memory JSON."""
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"id": "m1", "content": "test"}]),
        )
        result = runner.invoke(cli, ["memory", "list", "ws1"])
        assert result.exit_code == 0
        assert "m1" in result.output

    def test_memory_search_semantic(self, mocked_cli_runner):
        """memory search works (even if it returns empty results)."""
        runner, mock_client = mocked_cli_runner

        # Need proper embedding response for semantic search
        def side_effect(*args, **kwargs):
            if "/embed" in args[0]:
                emb = Mock(status_code=200)
                emb.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
                return emb
            resp = Mock(status_code=200)
            resp.text = json.dumps([])
            return resp

        mock_client._http.post.side_effect = side_effect

        result = runner.invoke(cli, [
            "memory", "search", "ws1", "test query",
        ])
        assert result.exit_code == 0
        assert "(no results)" in result.output or "no results" in result.output
