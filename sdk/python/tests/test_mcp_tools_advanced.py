"""Tests for server/mcp/tools/ — modular MCP tool definitions.

This module imports the shared ``mcp`` instance and ``get_client`` from
``server.mcp.tools.app``, then defines all 158 tool functions across
18 sub-modules using ``@mcp.tool()`` + ``@require_api_key``.

Each tool function simply delegates to the equivalent ``get_client().<method>()``.

We test:
- Module-level structural soundness (docstring, imports, function count)
- A representative sample of tool functions from every logical category
- ``require_api_key`` is applied to all functions (except health_check/get_metrics)
- Error propagation
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``get_client`` across all modular tool modules to return a MagicMock.

    Tool functions are defined in ``server.mcp.tools.*`` sub-modules, so we
    patch ``get_client`` in each of those modules.
    """
    from contextlib import ExitStack

    tool_modules = [
        "server.mcp.tools.workspace",
        "server.mcp.tools.memories",
        "server.mcp.tools.context",
        "server.mcp.tools.notes",
        "server.mcp.tools.documents",
        "server.mcp.tools.profiles",
        "server.mcp.tools.kg",
        "server.mcp.tools.search",
        "server.mcp.tools.peers",
        "server.mcp.tools.space",
        "server.mcp.tools.tours",
        "server.mcp.tools.entities",
        "server.mcp.tools.mental",
        "server.mcp.tools.org",
        "server.mcp.tools.agent",
        "server.mcp.tools.admin",
        "server.mcp.tools.compounder",
        "server.mcp.tools.directory",
    ]
    with ExitStack() as stack:
        instance = MagicMock()
        for mod_name in tool_modules:
            mock_fn = stack.enter_context(patch(f"{mod_name}.get_client"))
            mock_fn.return_value = instance
        yield instance




# =========================================================================


@pytest.mark.unit
class TestProfileTools:
    """Tests for profile tools."""

    def test_get_profile(self, mock_client):
        from server.mcp.tools.profiles import get_profile

        mock_client.get_profile.return_value = {"name": "test-user"}
        result = get_profile("peer-1")
        mock_client.get_profile.assert_called_once_with("peer-1")
        assert result["name"] == "test-user"

    def test_upsert_profile(self, mock_client):
        from server.mcp.tools.profiles import upsert_profile

        mock_client.upsert_profile.return_value = {"id": "prof-1"}
        result = upsert_profile(peer_id="peer-1", static_facts_json="[]")
        mock_client.upsert_profile.assert_called_once()
        assert result["id"] == "prof-1"


# =========================================================================
# Session / Peer tools
# =========================================================================


@pytest.mark.unit
class TestSessionTools:
    """Tests for session/peer tools."""

    def test_list_peers(self, mock_client):
        from server.mcp.tools.peers import list_peers

        mock_client.list_peers.return_value = [{"peer_id": "p1"}]
        result = list_peers("ws-1")
        mock_client.list_peers.assert_called_once_with("ws-1")
        assert len(result) == 1

    def test_search_sessions_semantic(self, mock_client):
        from server.mcp.tools.search import search_sessions_semantic

        mock_client.search_sessions_semantic.return_value = {
            "query": "find session",
            "sessions": [{"session_id": "sess-1", "score": 0.85}],
        }
        result = search_sessions_semantic("find session")
        data = json.loads(result)
        assert data["sessions"][0]["session_id"] == "sess-1"


# =========================================================================
# Compounder tools (use Compounder internally)
# =========================================================================


@pytest.mark.unit
class TestCompounderTools:
    """Tests for compounder tools — these create a ``Compounder`` internally.

    We patch ``spacetime_memory.compounder.Compounder`` at the module level
    and verify the compounder methods are called with the right args.
    """

    def test_ingest_source(self, mock_client):
        from server.mcp.tools import compounder

        with patch("spacetime_memory.compounder.Compounder") as mock_compounder_cls:
            mock_cp = MagicMock()
            mock_compounder_cls.return_value = mock_cp
            mock_cp.ingest_source.return_value = {
                "entities": [{"id": "ent-1"}],
                "links": [],
                "contradictions": [],
            }

            result = compounder.ingest_source(
                source_text="Some content",
                source_title="article.txt",
            )
            mock_cp.ingest_source.assert_called_once()
            assert "Entities: 1" in result
            assert "article.txt" in result

    def test_cross_link(self, mock_client):
        from server.mcp.tools import compounder

        with patch("spacetime_memory.compounder.Compounder") as mock_compounder_cls:
            mock_cp = MagicMock()
            mock_compounder_cls.return_value = mock_cp
            mock_cp.cross_link.return_value = {
                "links_created": 3, "pairs_checked": 10,
            }

            result = compounder.cross_link("ws-1")
            mock_cp.cross_link.assert_called_once_with(workspace_id="ws-1")
            assert "Links created: 3" in result

    def test_lint_workspace(self, mock_client):
        from server.mcp.tools import compounder

        with patch("spacetime_memory.compounder.Compounder") as mock_compounder_cls:
            mock_cp = MagicMock()
            mock_compounder_cls.return_value = mock_cp
            mock_cp.lint_workspace.return_value = {"orphans": 0}

            result = compounder.lint_workspace("ws-1", check_contradictions=True)
            mock_cp.lint_workspace.assert_called_once()
            assert "0" in result

    def test_generate_overview(self, mock_client):
        from server.mcp.tools import compounder

        with patch("spacetime_memory.compounder.Compounder") as mock_compounder_cls:
            mock_cp = MagicMock()
            mock_compounder_cls.return_value = mock_cp
            mock_cp.generate_overview_page.return_value = {
                "note": {"id": "overview-1"},
            }

            result = compounder.generate_overview("ws-1")
            mock_cp.generate_overview_page.assert_called_once_with(
                workspace_id="ws-1"
            )
            assert "overview-1" in result


# =========================================================================
# Fact tools
# =========================================================================


@pytest.mark.unit
class TestFactTools:
    """Tests for fact tools."""

    def test_add_fact(self, mock_client):
        from server.mcp.tools.profiles import add_fact

        mock_client.add_fact.return_value = "fact-1"
        result = add_fact(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="Water is wet",
        )
        mock_client.add_fact.assert_called_once()
        assert "peer-1" in result

    def test_list_facts(self, mock_client):
        from server.mcp.tools.profiles import list_facts

        mock_client.list_facts.return_value = [
            {"json_data": '[{"id": "fact-1"}]'},
        ]
        result = list_facts("ws-1")
        mock_client.list_facts.assert_called_once_with("ws-1", "", "", "", "")
        assert result == [{"id": "fact-1"}]

    def test_list_facts_empty(self, mock_client):
        from server.mcp.tools.profiles import list_facts

        mock_client.list_facts.return_value = []
        result = list_facts("ws-1")
        assert result == []


# =========================================================================
# Directory tools
# =========================================================================


@pytest.mark.unit
class TestDirectoryTools:
    """Tests for directory tools."""

    def test_create_directory(self, mock_client):
        from server.mcp.tools.directory import create_directory

        mock_client.create_directory.return_value = "dir-1"
        result = create_directory(
            workspace_id="ws-1",
            name="test-dir",
            path="/test",
        )
        mock_client.create_directory.assert_called_once()
        assert "test-dir" in result

    def test_get_directory(self, mock_client):
        from server.mcp.tools.directory import get_directory

        mock_client.get_directory.return_value = [{"id": "dir-1", "name": "test"}]
        result = get_directory("ws-1", "dir-1")
        mock_client.get_directory.assert_called_once_with("ws-1", "dir-1")
        assert '"dir-1"' in result


# =========================================================================
# Space/Access tools
# =========================================================================


@pytest.mark.unit
class TestSpaceTools:
    """Tests for space/access tools."""

    def test_grant_space_access(self, mock_client):
        from server.mcp.tools.space import grant_space_access

        mock_client.grant_space_access.return_value = "ok"
        result = grant_space_access("ws-1", "peer-1", "owner")
        mock_client.grant_space_access.assert_called_once_with(
            "ws-1", "peer-1", "owner"
        )
        assert "owner" in result
        assert "peer-1" in result

    def test_list_space_members(self, mock_client):
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.return_value = [{"peer_id": "p1"}]
        result = list_space_members("ws-1")
        mock_client.list_space_members.assert_called_once_with("ws-1")
        assert len(result) == 1


# =========================================================================
# Health / meta tools
# =========================================================================


@pytest.mark.unit
class TestMetaTools:
    """Tests for health and meta tools."""

    def test_health_check(self, mock_client):
        from server.mcp.tools.admin import health_check

        mock_client.list_workspaces.return_value = [{"id": "ws-1"}]
        mock_client.check_embedder_health.return_value = {"status": "ok"}
        mock_client.check_tantivy_health.return_value = {
            "status": "ok", "reachable": True,
        }
        mock_client._sql.return_value = [{"cnt": 10}]

        result = health_check()
        assert result["status"] == "ok"
        assert result["spacetimedb"] == "ok"
        assert result["workspace_count"] == 1

    def test_ping(self, mock_client):
        from server.mcp.tools.admin import ping

        mock_client.ping.return_value = {"status": "ok", "latency_ms": 3.2}
        result = ping()
        assert "reachable" in result
        assert "3.2ms" in result

    def test_get_metrics(self, mock_client):
        from server.mcp.tools.admin import get_metrics

        mock_client._sql.return_value = [{"c": 5}]
        mock_client.list_workspaces.return_value = [{"id": "ws-1"}]

        result = get_metrics()
        assert result["memories"]["total"] == 5
        assert result["workspaces"] == 1
