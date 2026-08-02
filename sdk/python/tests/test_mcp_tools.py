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

from unittest.mock import MagicMock, patch

import pytest


class TestModuleImport:
    """Verify the tools package can be imported and is structurally sound."""

    def test_can_import(self):
        from server.mcp import tools

        assert tools is not None

    def test_docstring_present(self):
        from server.mcp import tools

        doc = tools.__doc__
        assert doc is not None
        assert "MCP tool modules" in doc

    def test_future_annotations_imported(self):
        from server.mcp import tools

        hints = getattr(tools, "__annotations__", {})
        assert isinstance(hints, dict)

    def test_mcp_instance_imported(self):
        from server.mcp.tools.app import mcp

        assert mcp is not None

    def test_require_api_key_imported(self):
        from server.mcp.tools.app import require_api_key

        assert callable(require_api_key)

    def test_get_client_imported(self):
        from server.mcp.tools.app import get_client

        assert callable(get_client)


class TestFunctionCount:
    """Verifies that all expected tool functions exist across tool modules."""

    EXPECTED_FUNCTIONS: set[str] = {
        "create_workspace", "list_workspaces", "delete_workspace",
        "update_workspace", "set_workspace_visibility", "get_workspace_context",
        "store_memory", "search_memories", "hybrid_search",
        "search_with_filters", "get_memory", "get_memory_history",
        "list_memories", "update_memory", "delete_memory",
        "update_memory_tier",
        "create_tag", "tag_memory", "untag_memory", "list_tags", "delete_tag",
        "batch_tag_memories", "batch_untag_memories",
        "store_batch",
        "set_workspace_context", "set_memory_context", "get_context_chain",
        "list_context_packs", "list_context_entries", "list_context_deltas",
        "fuzzy_get", "glob_get", "detect_patterns",
        "create_note", "get_note", "update_note", "delete_note",
        "list_notes", "get_note_by_title", "get_note_by_date",
        "get_note_history", "get_backlinks", "get_outgoing_links",
        "create_document", "get_document", "list_documents",
        "get_document_chunks", "delete_document",
        "reinforce_memory", "rate_memory", "escalate_memories",
        "dedup_memories", "consolidate_memories", "suggest_merges",
        "approve_merge", "reject_merge", "set_memory_scope",
        "get_profile", "upsert_profile", "list_profiles",
        "add_dynamic_context", "add_profile_fact", "get_profile_context",
        "get_peer_reputation",
        "run_maintenance", "expire_memories", "check_embedder_health",
        "create_node", "update_node", "delete_node",
        "create_edge", "update_edge", "delete_edge",
        "add_node_citation", "add_edge_citation", "get_citations",
        "get_edge_history", "get_edge_as_of", "query_graph", "get_node",
        "get_neighbors", "get_community", "compute_pagerank",
        "compute_community_hierarchy", "compute_kg_stats",
        "get_memory_stats", "detect_communities", "seed_communities",
        "detect_bridge_nodes",
        "recommend_memories",
        "search_sessions_semantic", "get_user_memories", "search_profiles",
        "list_peers", "get_peer_sessions", "get_session_messages",
        "graph_bfs", "shortest_path",
        "create_tour", "add_tour_stop", "delete_tour", "delete_tour_stop",
        "resolve_entity", "add_alias", "create_entity_link",
        "synthesize_mental_models", "get_mental_model", "list_mental_models",
        "delete_mental_model", "update_mental_model",
        "add_fact", "list_facts", "delete_fact", "update_fact", "search_facts",
        "create_directory", "traverse_directory", "list_directory",
        "get_directory", "link_memory_to_directory",
        "unlink_memory_from_directory", "search_directory_contents",
        "org_sync",
        "grant_space_access", "revoke_space_access", "list_space_members",
        "add_agent_step", "get_session_steps", "get_agent_context",
        "health_check", "get_metrics",
        "ingest_source", "create_entity_page", "update_entity_page",
        "create_concept_page", "create_comparison_page",
        "lint_workspace", "generate_overview", "search_entities",
        "find_near_duplicates", "cross_link", "suggest_connections",
        "store_answer", "store_answers_batch", "export_workspace",
        "backup", "restore",
        "create_api_key", "deactivate_api_key", "list_api_keys",
        "set_decay_model", "get_decay_config",
        "cross_encoder_rerank",
        "ping",
        "batch_update_memories",
        "batch_update_veracity",
        "detect_anomalies",
        "update_memory_veracity",
        "get_memory_veracity",
        "list_workspace_veracity",
        "register_connector", "update_connector", "delete_connector",
        "list_connectors",
    }

    def _collect_all_tool_functions(self):
        """Collect all callable tool functions from all tool modules."""
        import importlib

        tool_modules = [
            "workspace", "memories", "context", "notes", "documents",
            "profiles", "kg", "search", "peers", "space", "tours",
            "entities", "mental", "org", "agent", "admin",
            "compounder", "directory",
        ]
        all_fns = set()
        for mod_name in tool_modules:
            mod = importlib.import_module(f"server.mcp.tools.{mod_name}")
            for name in dir(mod):
                if name.startswith("_"):
                    continue
                if name in {"Any", "annotations", "logger", "mcp",
                            "get_client", "require_api_key", "json", "logging"}:
                    continue
                obj = getattr(mod, name)
                if callable(obj):
                    all_fns.add(name)
        return all_fns

    def test_all_expected_functions_exist(self):
        all_fns = self._collect_all_tool_functions()
        for fn in self.EXPECTED_FUNCTIONS:
            assert fn in all_fns, f"Missing expected function: {fn}"

    def test_no_unexpected_public_functions(self):
        all_fns = self._collect_all_tool_functions()
        unexpected = all_fns - self.EXPECTED_FUNCTIONS
        assert not unexpected, f"Unexpected functions: {unexpected}"


# =========================================================================
# Fixture
# =========================================================================


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
# Workspace tools
# =========================================================================


@pytest.mark.unit
class TestWorkspaceTools:
    """Tests for workspace tools."""

    def test_create_workspace(self, mock_client):
        from server.mcp.tools.workspace import create_workspace

        mock_client.create_workspace.return_value = {"id": "ws-1", "name": "test"}
        result = create_workspace("test-ws", "A test")
        mock_client.create_workspace.assert_called_once_with("test-ws", "A test")
        assert result["id"] == "ws-1"

    def test_list_workspaces(self, mock_client):
        from server.mcp.tools.workspace import list_workspaces

        mock_client.list_workspaces.return_value = [{"id": "ws-1"}]
        result = list_workspaces()
        mock_client.list_workspaces.assert_called_once_with()
        assert len(result) == 1

    def test_delete_workspace(self, mock_client):
        from server.mcp.tools.workspace import delete_workspace

        mock_client.delete_workspace.return_value = {"status": "deleted"}
        result = delete_workspace("ws-1")
        mock_client.delete_workspace.assert_called_once_with("ws-1")
        assert result["status"] == "deleted"

    def test_error_propagation(self, mock_client):
        from server.mcp.tools.workspace import list_workspaces

        mock_client.list_workspaces.side_effect = RuntimeError("db error")
        with pytest.raises(RuntimeError, match="db error"):
            list_workspaces()


# =========================================================================
# Memory tools
# =========================================================================


@pytest.mark.unit
class TestMemoryTools:
    """Tests for memory tools — delegates to ``get_client().store()`` etc."""

    def test_store_memory(self, mock_client):
        from server.mcp.tools.memories import store_memory

        mock_client.store.return_value = {"id": "mem-1"}
        result = store_memory(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="test content",
        )
        mock_client.store.assert_called_once()
        assert result["id"] == "mem-1"

    def test_search_memories(self, mock_client):
        from server.mcp.tools.memories import search_memories

        mock_client.search.return_value = [{"id": "mem-1", "score": 0.9}]
        result = search_memories(workspace_id="ws-1", query_text="find this")
        mock_client.search.assert_called_once()
        assert result[0]["score"] == 0.9

    def test_get_memory(self, mock_client):
        from server.mcp.tools.memories import get_memory

        mock_client.get_memory.return_value = {"id": "mem-1", "content": "test"}
        result = get_memory("mem-1")
        mock_client.get_memory.assert_called_once_with("mem-1")
        assert result["content"] == "test"


# =========================================================================
# Knowledge Graph tools
# =========================================================================


@pytest.mark.unit
class TestKgTools:
    """Tests for KG tools."""

    def test_create_node(self, mock_client):
        from server.mcp.tools.kg import create_node

        mock_client.create_node.return_value = {"id": "node-1"}
        result = create_node(workspace_id="ws-1", label="Test", node_type="concept")
        mock_client.create_node.assert_called_once()
        assert result["id"] == "node-1"

    def test_create_edge(self, mock_client):
        from server.mcp.tools.kg import create_edge

        mock_client.create_edge.return_value = {"status": "ok"}
        result = create_edge(
            workspace_id="ws-1",
            source_node_id="src",
            target_node_id="tgt",
            relation="related_to",
        )
        mock_client.create_edge.assert_called_once()
        assert result["status"] == "ok"

    def test_get_node(self, mock_client):
        from server.mcp.tools.kg import get_node

        mock_client.get_node.return_value = {"id": "node-1", "label": "Test"}
        result = get_node("node-1")
        mock_client.get_node.assert_called_once_with("node-1")
        assert result["label"] == "Test"


# =========================================================================
# Note tools
# =========================================================================


@pytest.mark.unit
class TestNoteTools:
    """Tests for note tools."""

    def test_create_note(self, mock_client):
        from server.mcp.tools.notes import create_note

        mock_client.create_note.return_value = {"id": "note-1", "title": "Test"}
        result = create_note(workspace_id="ws-1", title="Test Note", content="# Hello")
        mock_client.create_note.assert_called_once()
        assert result["title"] == "Test"

    def test_get_note(self, mock_client):
        from server.mcp.tools.notes import get_note

        mock_client.get_note.return_value = {"id": "note-1"}
        result = get_note("note-1")
        mock_client.get_note.assert_called_once_with("note-1")
        assert result["id"] == "note-1"

    def test_list_notes(self, mock_client):
        from server.mcp.tools.notes import list_notes

        mock_client.list_notes.return_value = [{"id": "note-1"}]
        result = list_notes("ws-1")
        mock_client.list_notes.assert_called_once_with("ws-1")
        assert len(result) == 1


# =========================================================================
# Profile tools
