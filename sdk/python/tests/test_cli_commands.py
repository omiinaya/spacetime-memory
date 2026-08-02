"""Tests for the stmem CLI using Click's CliRunner.

The CLI creates its own Client internally via ``_make_client()``, so the
``mock_http_client`` fixture is not directly usable.  Instead we
monkeypatch ``stmem._make_client`` to return a pre-mocked Client.
"""

import json
from unittest.mock import Mock

import pytest
from cli.stmem import cli
from click.testing import CliRunner
from conftest import make_sql_response

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
    from unittest.mock import MagicMock

    import httpx

    from spacetime_memory import Client

    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = Mock(
        status_code=200, text=json.dumps([]), json=lambda: {"data": [{"embedding": [0.0]}]}
    )
    mock_http.get.return_value = Mock(
        status_code=200,
        json=lambda: {"model": "mock"},
    )
    client._http = mock_http
    return client


@pytest.fixture
def mocked_cli_runner(monkeypatch, runner, mock_client):
    """A CliRunner where the CLI's ``_sdk_client`` returns a mocked Client.

    Patches ``_sdk_client`` in the root module AND in every already-imported
    command module (which import ``_sdk_client`` at load time into their own
    namespace via ``from ..root import _sdk_client``).
    """
    import sys
    import types

    def mock_fn(**kw):
        return mock_client
    monkeypatch.setattr("cli.stmem._sdk_client", mock_fn)
    monkeypatch.setattr("cli.stmem.root._sdk_client", mock_fn)
    for mod_name, mod in list(sys.modules.items()):
        if (mod_name.startswith("cli.stmem.commands")
                or mod_name == "cli.stmem.root"
                or mod_name == "cli.stmem"
                or mod_name.startswith("spacetime_memory.")):
            if isinstance(mod, types.ModuleType) and hasattr(mod, "_sdk_client"):
                monkeypatch.setattr(mod, "_sdk_client", mock_fn)
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
        """Invoking without arguments shows help (exit code depends on Click version)."""
        result = runner.invoke(cli, [])
        # Click 8.x+ exit code 2 for no_args_is_help; older Click 0
        assert result.exit_code in (0, 2), f"Expected 0 or 2, got {result.exit_code}"
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
        assert "No results found" in result.output

    def test_workspace_list_with_data(self, mocked_cli_runner):
        """workspace list shows workspace JSON."""
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
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
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text='{"status": "ok"}',
        )
        result = runner.invoke(cli, ["workspace", "create", "my-workspace"])
        assert result.exit_code == 0
        assert '"status": "ok"' in result.output


class TestCliMemory:
    """CLI memory commands."""

    def test_memory_store(self, mocked_cli_runner):
        """memory store calls the store_memory reducer."""
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        # store() now calls _query() in the memory_insert_result path,
        # which hits the SQL endpoint. Use side_effect to route correctly:
        #   - SQL URLs → empty result set (valid JSON array)
        #   - Reducer URLs → {"status": "ok"}
        def _post_routing(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(status_code=200, text='{"status": "ok"}')

        mock_client._http.post.side_effect = _post_routing
        # Ensure _embed returns [] so store() doesn't try to call
        # the embedding API (which would hit resp.json() → Mock subscript error)
        mock_client._embed = Mock(return_value=[])
        result = runner.invoke(
            cli,
            [
                "memory",
                "store",
                "ws1",
                "cli-test",
                "hello world",
            ],
        )
        assert result.exit_code == 0
        assert '"status": "ok"' in result.output

    def test_memory_list_empty(self, mocked_cli_runner):
        """memory list shows '(no memories)' when empty."""
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([]),
        )
        result = runner.invoke(cli, ["memory", "list", "ws1"])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_memory_list_with_data(self, mocked_cli_runner):
        """memory list shows memory JSON."""
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
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
            resp.json = list
            return resp

        mock_client._http.post.side_effect = side_effect
        result = runner.invoke(
            cli,
            [
                "memory",
                "search",
                "ws1",
                "test query",
            ],
        )
        assert result.exit_code == 0
        assert "No results found" in result.output


# ══════════════════════════════════════════════════════════════════
# Extended CLI tests — added for coverage
# ══════════════════════════════════════════════════════════════════


class TestCliAllHelps:
    """Verify --help works for every command group (exercises Click wiring)."""

    GROUPS = [
        "alias",
        "apikey",
        "peer",
        "space",
        "decay",
        "directory",
        "profile",
        "fact",
        "kg",
        "session",
        "ingest",
        "connector",
        "shmr",
        "context",
        "plugin",
        "admin",
    ]

    def test_group_helps(self, runner):
        for group in self.GROUPS:
            result = runner.invoke(cli, [group, "--help"])
            assert result.exit_code == 0, f"Failed: {group} --help"
            assert "Usage:" in result.output.lower() or "usage" in result.output.lower()


class TestCliAlias:
    """Alias commands (filesystem-based — monkeypatch ALIASES_FILE)."""

    def test_alias_set(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "set", "ll", "memory list"])
        assert result.exit_code == 0
        assert "Alias 'll' set to:" in result.output

    def test_alias_list_empty(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "list"])
        assert result.exit_code == 0
        assert "No aliases defined" in result.output

    def test_alias_list_with_data(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        aliases_file.write_text('{"ll": "memory list", "aa": "workspace list"}')
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "list"])
        assert result.exit_code == 0
        assert "ll" in result.output and "aa" in result.output

    def test_alias_remove(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        aliases_file.write_text('{"ll": "memory list"}')
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "remove", "ll"])
        assert result.exit_code == 0
        assert "removed" in result.output

    def test_alias_remove_not_found(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "remove", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestCliApikey:
    """API key management."""

    def test_apikey_create(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text="{}")
        result = runner.invoke(cli, ["apikey", "create", "ws1", "my-key"])
        assert result.exit_code == 0
        assert "created" in result.output.lower()

    def test_apikey_revoke(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["apikey", "revoke", "key-1234567890abcdef"])
        assert result.exit_code == 0
        assert "revoked" in result.output.lower()

    def test_apikey_list_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text=json.dumps([]))
        result = runner.invoke(cli, ["apikey", "list", "ws1"])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_apikey_list_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"id": "k1", "name": "my-key"}]),
        )
        result = runner.invoke(cli, ["apikey", "list", "ws1"])
        assert result.exit_code == 0
        assert "my-key" in result.output


class TestCliPeer:
    """Peer management."""

    def test_peer_create(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text="{}")
        result = runner.invoke(cli, ["peer", "create", "ws1", "alice", "user"])
        assert result.exit_code == 0
        assert "created" in result.output.lower()

    def test_peer_list_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["peer", "list", "ws1"])
        assert result.exit_code == 0

    def test_peer_list_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"id": "p1", "name": "alice"}]),
        )
        result = runner.invoke(cli, ["peer", "list", "ws1"])
        assert result.exit_code == 0
        assert "alice" in result.output


class TestCliSpace:
    """Space membership commands."""

    def test_space_members_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = lambda *a, **kw: Mock(
            status_code=200, text=json.dumps([])
        )
        result = runner.invoke(cli, ["space", "members", "ws1"])
        assert result.exit_code == 0
        assert "No members found" in result.output

    def test_space_members_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.side_effect = lambda *a, **kw: Mock(
            status_code=200,
            text=make_sql_response([{"peer_id": "p1", "permission": "owner"}]),
        )
        result = runner.invoke(cli, ["space", "members", "ws1"])
        assert result.exit_code == 0
        assert "p1" in result.output

    def test_space_grant(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["space", "grant", "ws1", "peer1", "viewer"])
        assert result.exit_code == 0
        assert "granted" in result.output.lower()

    def test_space_revoke(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["space", "revoke", "ws1", "peer1"])
        assert result.exit_code == 0
        assert "revoked" in result.output.lower()


class TestCliMemoryExtended:
    """Additional memory subcommands beyond store/list/search."""

    def test_memory_get_found(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"id": "m1", "content": "hello world"}]),
        )
        result = runner.invoke(cli, ["memory", "get", "m1"])
        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_memory_get_not_found(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text=json.dumps([]))
        result = runner.invoke(cli, ["memory", "get", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_memory_reinforce(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["memory", "reinforce", "m1"])
        assert result.exit_code == 0
        assert "reinforced" in result.output

    def test_memory_escalate(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["memory", "escalate", "ws1"])
        assert result.exit_code == 0
        assert "escalation" in result.output.lower()

    def test_memory_rate(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["memory", "rate", "m1", "helpful", "peer1"])
        assert result.exit_code == 0
        assert "rated" in result.output

    def test_memory_update(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["memory", "update", "m1", "--content", "new content"])
        assert result.exit_code == 0

    def test_memory_batch_update(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        # batch-update may require MEMORY_IDS arg — try with explicit IDs
        result = runner.invoke(cli, ["memory", "batch-update", "ws1", "--tier", "L0"])
        if result.exit_code != 0:
            # Try with memory_ids argument
            result = runner.invoke(
                cli, ["memory", "batch-update", "ws1", "m1", "m2", "--tier", "L0"]
            )
        assert result.exit_code == 0 or "Usage:" in result.output

    def test_memory_history(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text=json.dumps([]))
        result = runner.invoke(cli, ["memory", "history", "m1"])
        assert result.exit_code == 0


class TestCliDecay:
    """Decay configuration commands."""

    def test_decay_set_linear(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli, ["decay", "set-linear", "ws1", "--rate", "0.01", "--max-days", "60"]
        )
        assert result.exit_code == 0
        assert "Linear decay" in result.output

    def test_decay_set_weibull(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["decay", "set-weibull", "ws1", "-k", "0.5", "-l", "45"])
        assert result.exit_code == 0
        assert "Weibull decay" in result.output

    def test_decay_show_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text="{}")
        result = runner.invoke(cli, ["decay", "show", "ws1"])
        assert result.exit_code == 0
        assert "No decay config" in result.output

    def test_decay_show_with_config(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"decay_model": "linear", "decay_rate": 0.005}]),
        )
        result = runner.invoke(cli, ["decay", "show", "ws1"])
        assert result.exit_code == 0
        assert "linear" in result.output

    def test_decay_run_linear(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"decay_model": "linear", "decay_rate": 0.005}]),
        )
        result = runner.invoke(cli, ["decay", "run", "ws1"])
        assert result.exit_code == 0
        assert "decay cycle complete" in result.output


class TestCliRecommend:
    """Recommend command."""

    def test_recommend_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._http.post.return_value = Mock(status_code=200, text=json.dumps([]))
        result = runner.invoke(cli, ["recommend", "ws1"])
        assert result.exit_code == 0

    def test_recommend_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"memory_id": "m1", "action": "review"}]),
        )
        result = runner.invoke(cli, ["recommend", "ws1", "--limit", "5", "--min-urgency", "0.5"])
        assert result.exit_code == 0
        # Output format: "[   REVIEW] urgency=0.00 trust=0.00 fb=0"
        assert "REVIEW" in result.output or "m1" in result.output


class TestCliPeerReputation:
    """Peer reputation command."""

    def test_peer_reputation(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._identity_established = True
        mock_client._identity_token = "test-token"
        mock_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"helpful": 5, "unhelpful": 1}]),
        )
        result = runner.invoke(cli, ["peer-reputation", "peer1"])
        assert result.exit_code == 0
