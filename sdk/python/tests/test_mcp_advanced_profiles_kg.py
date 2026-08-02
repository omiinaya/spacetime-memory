"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestGetProfile:
    """Tests for the get_profile MCP tool."""

    def test_gets_profile(self, mock_mcp_client):
        from server.mcp.main import get_profile

        mock_mcp_client.get_profile.return_value = [
            {"peer_id": "p1", "name": "Alice"},
        ]
        result = get_profile(peer_id="p1")
        assert result[0]["name"] == "Alice"
        mock_mcp_client.get_profile.assert_called_once_with("p1")



# ── TestUpsertProfile ────────────────────────────────────────────────────────

class TestUpsertProfile:
    """Tests for the upsert_profile MCP tool."""

    def test_upserts(self, mock_mcp_client):
        from server.mcp.main import upsert_profile

        mock_mcp_client.upsert_profile.return_value = {"status": "ok"}
        result = upsert_profile(
            peer_id="p1",
            static_facts_json='[{"key": "expertise", "value": "AI"}]',
        )
        assert result["status"] == "ok"
        mock_mcp_client.upsert_profile.assert_called_once_with(
            "p1",
            '[{"key": "expertise", "value": "AI"}]',
            "[]",
            "{}",
            "[]",
        )


# ── Knowledge Graph tools ─────────────────────────────────────────────────



# ── TestCreateNode ────────────────────────────────────────────────────────

class TestCreateNode:
    """Tests for the create_node MCP tool."""

    def test_creates_node(self, mock_mcp_client):
        from server.mcp.main import create_node

        mock_mcp_client.create_node.return_value = {"id": "node1"}
        result = create_node(
            workspace_id="ws1",
            label="AI",
            node_type="concept",
            summary="Artificial Intelligence",
        )
        assert result["id"] == "node1"
        mock_mcp_client.create_node.assert_called_once_with(
            "ws1", "AI", "concept", "Artificial Intelligence", "{}"
        )



# ── TestDeleteNode ────────────────────────────────────────────────────────

class TestDeleteNode:
    """Tests for the delete_node MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_node

        mock_mcp_client.delete_node.return_value = {"status": "ok"}
        result = delete_node(node_id="n1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_node.assert_called_once_with("n1")



# ── TestUpdateEdge ────────────────────────────────────────────────────────

class TestUpdateEdge:
    """Tests for the update_edge MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_edge

        mock_mcp_client.update_edge.return_value = {"status": "ok"}
        result = update_edge(edge_id="e1", relation="related_to", weight=0.5)
        assert result["status"] == "ok"
        mock_mcp_client.update_edge.assert_called_once_with(
            "e1", "related_to", 0.5, "{}"
        )

    def test_with_metadata(self, mock_mcp_client):
        from server.mcp.main import update_edge

        mock_mcp_client.update_edge.return_value = {"status": "ok"}
        update_edge(
            edge_id="e1",
            relation="informed_by",
            metadata_json='{"source": "paper"}',
        )
        mock_mcp_client.update_edge.assert_called_once_with(
            "e1", "informed_by", 1.0, '{"source": "paper"}'
        )



# ── TestDeleteEdge ────────────────────────────────────────────────────────

class TestDeleteEdge:
    """Tests for the delete_edge MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_edge

        mock_mcp_client.delete_edge.return_value = {"status": "ok"}
        result = delete_edge(edge_id="e1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_edge.assert_called_once_with("e1")



# ── TestGetEdgeHistory ────────────────────────────────────────────────────────

class TestGetEdgeHistory:
    """Tests for the get_edge_history MCP tool."""

    def test_gets_history(self, mock_mcp_client):
        from server.mcp.main import get_edge_history

        mock_mcp_client.get_edge_history.return_value = [
            {"version": 1, "relation": "r1"},
        ]
        result = get_edge_history(edge_group_id="eg1")
        assert len(result) == 1
        mock_mcp_client.get_edge_history.assert_called_once_with("eg1")


# ── get_memory_stats ──────────────────────────────────────────────────────



# ── TestGetMemoryStats ────────────────────────────────────────────────────────

class TestGetMemoryStats:
    """Tests for the get_memory_stats MCP tool."""

    def test_returns_stats(self, mock_mcp_client):
        from server.mcp.main import get_memory_stats

        mock_mcp_client.get_memory_stats.return_value = {
            "workspace_id": "ws1",
            "total_memories": 100,
            "active_memories": 80,
        }
        result = get_memory_stats(workspace_id="ws1")
        import json

        parsed = json.loads(result)
        assert parsed["total_memories"] == 100
        mock_mcp_client.get_memory_stats.assert_called_once_with("ws1")

    def test_no_stats(self, mock_mcp_client):
        from server.mcp.main import get_memory_stats

        mock_mcp_client.get_memory_stats.return_value = None
        result = get_memory_stats(workspace_id="empty")
        import json

        parsed = json.loads(result)
        assert "error" in parsed


# ── Misc tools ────────────────────────────────────────────────────────────



# ── TestExpireMemories ────────────────────────────────────────────────────────

class TestExpireMemories:
    """Tests for the expire_memories MCP tool."""

    def test_expires(self, mock_mcp_client):
        from server.mcp.main import expire_memories

        mock_mcp_client.expire_memories.return_value = {"status": "ok"}
        result = expire_memories()
        assert result["status"] == "ok"
        mock_mcp_client.expire_memories.assert_called_once_with()
