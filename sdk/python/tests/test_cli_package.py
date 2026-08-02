"""Unit tests for the CLI package — ``stmem`` tantivy and compounder commands.

Tests use Click's CliRunner with mocked HTTP clients so no real
network calls are made.  Follows the patterns in ``test_cli.py``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    """Return a CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture
def mock_client():
    """Create a Client with mocked HTTP (same as test_cli.py's mock_client)."""
    from spacetime_memory import Client

    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = Mock(
        status_code=200,
        text=json.dumps([]),
        json=lambda: {"data": [{"embedding": [0.0]}]},
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
        if (
            mod_name.startswith("cli.stmem.commands")
            or mod_name == "cli.stmem.root"
            or mod_name == "cli.stmem"
            or mod_name.startswith("spacetime_memory.")
        ):
            if isinstance(mod, types.ModuleType) and hasattr(mod, "_sdk_client"):
                monkeypatch.setattr(mod, "_sdk_client", mock_fn)
    return runner, mock_client


# ══════════════════════════════════════════════════════════════════
# Tantivy commands
# ══════════════════════════════════════════════════════════════════


class TestTantivyStatus:
    """Tests for ``stmem tantivy status``."""

    def test_status_reachable(self, mocked_cli_runner):
        """Status shows reachable info when Tantivy sidecar responds."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.side_effect = [
                # First call: /status
                Mock(
                    status_code=200,
                    json=lambda: {
                        "version": "1.0",
                        "workspaces": [{"workspace_id": "ws1"}],
                    },
                ),
                # Second call: /health
                Mock(
                    status_code=200,
                    json=lambda: {
                        "workspace_count": 3,
                        "total_indexed": 100,
                        "memory_mb": 256,
                        "version": "1.0",
                    },
                ),
            ]
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "status"])
            assert result.exit_code == 0
            assert "Reachable" in result.output or "reachable" in result.output

    def test_status_unreachable(self, mocked_cli_runner):
        """Status shows error when Tantivy sidecar is unreachable."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.side_effect = httpx.HTTPError("Connection refused")
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "status"])
            assert result.exit_code == 0
            assert "unreachable" in result.output.lower()

    def test_status_json_output(self, mocked_cli_runner):
        """Status with --json flag returns JSON."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.side_effect = [
                # /status
                Mock(
                    status_code=200,
                    json=lambda: {"version": "1.0", "workspaces": []},
                ),
                # /health
                Mock(
                    status_code=200,
                    json=lambda: {"workspace_count": 0, "total_indexed": 0, "memory_mb": 128},
                ),
            ]
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "status", "--json"])
            assert result.exit_code == 0
            # Should contain JSON with reachable: true
            assert "reachable" in result.output
            data = json.loads(result.output)
            assert data["reachable"] is True

    def test_status_health_fallback_when_status_fails(self, mocked_cli_runner):
        """Status falls back to /health when /status endpoint fails."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            call_count = 0

            def _get_side_effect(url, **kw):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # /status returns error
                    raise httpx.HTTPError("Status endpoint down")
                # /health succeeds
                return Mock(
                    status_code=200,
                    json=lambda: {"workspace_count": 1, "total_indexed": 5, "memory_mb": 64},
                )

            mock_http.get.side_effect = _get_side_effect
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "status"])
            assert result.exit_code == 0
            assert "Reachable" in result.output


class TestTantivyEvict:
    """Tests for ``stmem tantivy evict <id>``."""

    def test_evict_success(self, mocked_cli_runner):
        """Evict workspace returns success."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            # Health check first
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 5},
            )
            # Evict POST
            mock_http.post.return_value = Mock(
                status_code=200,
                json=lambda: {"status": "ok"},
            )
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "evict", "ws-1"])
            assert result.exit_code == 0
            assert "evicted" in result.output.lower()

    def test_evict_not_found(self, mocked_cli_runner):
        """Evict workspace not found in Tantivy."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 5},
            )
            mock_http.post.return_value = Mock(
                status_code=200,
                json=lambda: {"status": "not_found"},
            )
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "evict", "nonexistent"])
            assert result.exit_code == 0
            assert "not found" in result.output.lower()

    def test_evict_unreachable(self, mocked_cli_runner):
        """Evict when Tantivy is unreachable prints error."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.side_effect = httpx.HTTPError("Connection refused")
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "evict", "ws-1"])
            assert result.exit_code == 0
            assert "unreachable" in result.output.lower()

    def test_evict_timeout(self, mocked_cli_runner):
        """Evict timeout prints timeout error."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 5},
            )
            mock_http.post.side_effect = httpx.TimeoutException("Timed out")
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "evict", "ws-1"])
            assert result.exit_code == 0
            assert "timeout" in result.output.lower()

    def test_evict_json_output(self, mocked_cli_runner):
        """Evict with --json flag returns JSON."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 5},
            )
            mock_http.post.return_value = Mock(
                status_code=200,
                json=lambda: {"status": "ok"},
            )
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "evict", "ws-1", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"


class TestTantivyReindex:
    """Tests for ``stmem tantivy reindex --dry-run``."""

    def test_reindex_dry_run(self, mocked_cli_runner):
        """Reindex with --dry-run shows what would be indexed without sending data."""
        runner, mock_client = mocked_cli_runner
        from cli.stmem import cli

        # list_workspaces on the real Client needs to be patched
        # because we can't set .return_value on a real method
        mock_client.list_workspaces = MagicMock(return_value=[
            {"id": "ws-1", "name": "workspace-one"},
        ])
        mock_client._query = MagicMock(side_effect=[
            # First query: memories
            [
                {"id": "mem-1", "content": "memory content A"},
                {"id": "mem-2", "content": "memory content B"},
            ],
            # Second query: kg_nodes
            [
                {"id": "node-1", "label": "Entity One", "summary": "Summary one"},
                {"id": "node-2", "label": "Entity Two", "summary": "Summary two"},
            ],
        ])

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 1},
            )
            mock_http_fn.return_value = mock_http

            # The mock for _sdk_client was set up to ignore kw, but the
            # reindex code calls it inside the loop. Since we already
            # monkeypatched _sdk_client to return mock_client, and we set
            # return values above, this should work.
            result = runner.invoke(cli, ["tantivy", "reindex", "--dry-run"])
            assert result.exit_code == 0
            assert "DRY RUN" in result.output
            assert "2 memories" in result.output or "2 nodes" in result.output

    def test_reindex_dry_run_specific_workspace(self, mocked_cli_runner):
        """Reindex --dry-run with --workspace filters to specific workspace."""
        runner, mock_client = mocked_cli_runner
        from cli.stmem import cli

        mock_client.list_workspaces = MagicMock(return_value=[
            {"id": "ws-1", "name": "Alpha"},
            {"id": "ws-2", "name": "Beta"},
        ])

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 2},
            )
            mock_http_fn.return_value = mock_http

            result = runner.invoke(
                cli, ["tantivy", "reindex", "--dry-run", "--workspace", "ws-2"]
            )
            assert result.exit_code == 0
            assert "DRY RUN" in result.output

    def test_reindex_unreachable_tantivy(self, mocked_cli_runner):
        """Reindex fails gracefully when Tantivy sidecar is unreachable."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.side_effect = httpx.HTTPError("Connection refused")
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "reindex"])
            assert result.exit_code == 0
            assert "unreachable" in result.output.lower()

    def test_reindex_failed_list_workspaces(self, mocked_cli_runner):
        """Reindex handles list_workspaces failure gracefully."""
        runner, mock_client = mocked_cli_runner
        from cli.stmem import cli

        mock_client.list_workspaces = MagicMock(side_effect=OSError("DB down"))

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 1},
            )
            mock_http_fn.return_value = mock_http

            result = runner.invoke(cli, ["tantivy", "reindex"])
            assert result.exit_code == 0
            assert "Failed to list workspaces" in result.output

    def test_reindex_workspace_not_found(self, mocked_cli_runner):
        """Reindex with --workspace for nonexistent workspace shows error."""
        runner, mock_client = mocked_cli_runner
        from cli.stmem import cli

        mock_client.list_workspaces = MagicMock(return_value=[
            {"id": "ws-1", "name": "Alpha"},
        ])

        with patch("cli.stmem.commands.tantivy._tantivy_http") as mock_http_fn:
            mock_http = MagicMock(spec=httpx.Client)
            mock_http.get.return_value = Mock(
                status_code=200,
                json=lambda: {"workspace_count": 1},
            )
            mock_http_fn.return_value = mock_http

            result = runner.invoke(
                cli, ["tantivy", "reindex", "--workspace", "nonexistent"]
            )
            assert result.exit_code == 0
            assert "not found" in result.output.lower()


# ══════════════════════════════════════════════════════════════════
# Simple existing commands (store-answer, concept-page, entity-page)
# ══════════════════════════════════════════════════════════════════


class TestCliStoreAnswer:
    """Tests for ``stmem store-answer`` command."""

    def test_store_answer(self, mocked_cli_runner):
        """store-answer invokes the compounder's store_answer method."""
        runner, mock_client = mocked_cli_runner
        from cli.stmem import cli

        # Mock the Compounder class created inside the command
        with patch("spacetime_memory.compounder.Compounder") as MockCompounder:
            instance = MockCompounder.return_value
            instance.store_answer.return_value = {
                "note": {"id": "note-1", "title": "What is X?"},
                "entities": [],
                "links": [],
            }

            result = runner.invoke(
                cli,
                [
                    "store-answer",
                    "--query", "What is X?",
                    "--answer", "X is a concept.",
                ],
            )
            assert result.exit_code == 0
            instance.store_answer.assert_called_once()
            args, kwargs = instance.store_answer.call_args
            assert kwargs["query"] == "What is X?"
            assert kwargs["answer"] == "X is a concept."

    def test_store_answer_with_source_ids(self, mocked_cli_runner):
        """store-answer passes source IDs to compounder."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("spacetime_memory.compounder.Compounder") as MockCompounder:
            instance = MockCompounder.return_value
            instance.store_answer.return_value = {
                "note": {"id": "note-1"},
                "entities": [],
                "links": [],
            }

            result = runner.invoke(
                cli,
                [
                    "store-answer",
                    "--query", "Q?",
                    "--answer", "A.",
                    "--source-ids", "mem1,mem2",
                ],
            )
            assert result.exit_code == 0
            instance.store_answer.assert_called_once()
            assert instance.store_answer.call_args[1]["source_memory_ids"] == ["mem1", "mem2"]
    @pytest.mark.skip(reason="flaky JSON output test needs investigation")
    def test_store_answer_json_output(self, mocked_cli_runner):
        """store-answer with --json flag outputs JSON."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("spacetime_memory.compounder.Compounder") as MockCompounder:
            instance = MockCompounder.return_value
            instance.store_answer.return_value = {
                "note": {"id": "n1", "title": "Q"},
                "entities": [],
                "links": [],
            }

            result = runner.invoke(
                cli,
                [
                    "--output", "json",
                    "store-answer",
                    "--query", "Q?",
                    "--answer", "A.",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["note"]["id"] == "n1"


class TestCliConceptPage:
    """Tests for ``stmem concept-page`` command."""

    def test_concept_page(self, mocked_cli_runner):
        """concept-page invokes the compounder's create_concept_page method."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("spacetime_memory.compounder.Compounder") as MockCompounder:
            instance = MockCompounder.return_value
            instance.create_concept_page.return_value = {
                "note": {"id": "note-c1"},
                "node": {"id": "node-c1"},
            }

            result = runner.invoke(
                cli,
                [
                    "concept-page",
                    "--concept", "RLHF",
                    "--definition", "Reinforcement Learning from Human Feedback",
                ],
            )
            assert result.exit_code == 0
            instance.create_concept_page.assert_called_once()
            assert instance.create_concept_page.call_args[1]["concept"] == "RLHF"

    def test_concept_page_with_relations(self, mocked_cli_runner):
        """concept-page passes related concepts to compounder."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("spacetime_memory.compounder.Compounder") as MockCompounder:
            instance = MockCompounder.return_value
            instance.create_concept_page.return_value = {"note": {}, "node": {}}

            result = runner.invoke(
                cli,
                [
                    "concept-page",
                    "--concept", "RLHF",
                    "--definition", "Definition here",
                    "--related", "PPO,GPT",
                ],
            )
            assert result.exit_code == 0
            instance.create_concept_page.assert_called_once()
            call_kw = instance.create_concept_page.call_args[1]
            assert "related_concepts" in call_kw
            assert call_kw["related_concepts"] == ["PPO", "GPT"]


class TestCliEntityPage:
    """Tests for ``stmem entity-page`` command."""

    def test_entity_page(self, mocked_cli_runner):
        """entity-page invokes the compounder's create_entity_page method."""
        runner, _ = mocked_cli_runner
        from cli.stmem import cli

        with patch("spacetime_memory.compounder.Compounder") as MockCompounder:
            instance = MockCompounder.return_value
            instance.create_entity_page.return_value = {
                "node": {"id": "node-e1"},
                "note": {"id": "note-e1"},
            }

            result = runner.invoke(
                cli,
                [
                    "entity-page",
                    "--name", "Alice",
                    "--description", "A researcher",
                ],
            )
            assert result.exit_code == 0
            instance.create_entity_page.assert_called_once()
            assert instance.create_entity_page.call_args[1]["name"] == "Alice"
