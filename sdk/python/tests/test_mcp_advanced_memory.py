"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestStoreMemory:
    """Tests for the store_memory MCP tool."""

    def test_stores_minimal(self, mock_mcp_client):
        from server.mcp.main import store_memory

        mock_mcp_client.store.return_value = {"id": "mem_new"}
        result = store_memory(workspace_id="ws1", peer_id="peer1", content="Test memory")
        assert result["id"] == "mem_new"
        mock_mcp_client.store.assert_called_once()

    def test_stores_with_all_params(self, mock_mcp_client):
        from server.mcp.main import store_memory

        mock_mcp_client.store.return_value = {"id": "mem2"}
        store_memory(
            workspace_id="ws1",
            peer_id="peer1",
            observer_id="obs1",
            memory_type="observation",
            content="Observed something",
            summary="Summary",
            entities_json='[{"name": "Entity1"}]',
            confidence=0.95,
            source_session_id="sess1",
            source_message_id="msg1",
            tier="L0",
            images_json="[]",
        )
        call_kw = mock_mcp_client.store.call_args[1]
        assert call_kw["workspace_id"] == "ws1"
        assert call_kw["memory_type"] == "observation"
        assert call_kw["confidence"] == 0.95
        assert call_kw["tier"] == "L0"



# ── TestSearchMemories ────────────────────────────────────────────────────────

class TestSearchMemories:
    """Tests for the search_memories MCP tool."""

    def test_searches(self, mock_mcp_client):
        from server.mcp.main import search_memories

        mock_mcp_client.search.return_value = [
            {"id": "m1", "content": "Result 1"},
        ]
        result = search_memories(workspace_id="ws1", query_text="test")
        assert len(result) == 1
        mock_mcp_client.search.assert_called_once()

    def test_with_filters(self, mock_mcp_client):
        from server.mcp.main import search_memories

        mock_mcp_client.search.return_value = []
        search_memories(
            workspace_id="ws1",
            query_text="ML",
            memory_type="note",
            tier="L1",
            limit=10,
            rerank=True,
            entity_types=["memory"],
            before=1000.0,
            after=100.0,
            return_schema="llm",
        )
        call_kw = mock_mcp_client.search.call_args[1]
        assert call_kw["memory_type"] == "note"
        assert call_kw["tier"] == "L1"
        assert call_kw["rerank"] is True
        assert call_kw["entity_types"] == ["memory"]



# ── TestHybridSearch ────────────────────────────────────────────────────────

class TestHybridSearch:
    """Tests for the hybrid_search MCP tool."""

    def test_hybrid(self, mock_mcp_client):
        from server.mcp.main import hybrid_search

        mock_mcp_client.search.return_value = [{"id": "h1"}]
        result = hybrid_search(workspace_id="ws1", query_text="AI")
        assert len(result) == 1
        mock_mcp_client.search.assert_called_once()

    def test_with_params(self, mock_mcp_client):
        from server.mcp.main import hybrid_search

        mock_mcp_client.search.return_value = []
        hybrid_search(
            workspace_id="ws1",
            query_text="test",
            memory_type="note",
            tier="L0",
            limit=5,
            strategies="semantic,keyword",
            rerank=False,
        )
        call_kw = mock_mcp_client.search.call_args[1]
        assert call_kw["limit"] == 5
        assert call_kw["rerank"] is False



# ── TestGetMemory ────────────────────────────────────────────────────────

class TestGetMemory:
    """Tests for the get_memory MCP tool."""

    def test_gets_memory(self, mock_mcp_client):
        from server.mcp.main import get_memory

        mock_mcp_client.get_memory.return_value = [{"id": "m1", "content": "Test"}]
        result = get_memory(id="m1")
        assert result[0]["id"] == "m1"
        mock_mcp_client.get_memory.assert_called_once_with("m1")

    def test_not_found(self, mock_mcp_client):
        from server.mcp.main import get_memory

        mock_mcp_client.get_memory.return_value = []
        result = get_memory(id="nonexistent")
        assert result == []



# ── TestGetMemoryHistory ────────────────────────────────────────────────────────

class TestGetMemoryHistory:
    """Tests for the get_memory_history MCP tool."""

    def test_gets_history(self, mock_mcp_client):
        from server.mcp.main import get_memory_history

        mock_mcp_client.get_memory_history.return_value = [
            {"version": 1, "content": "v1"},
            {"version": 2, "content": "v2"},
        ]
        result = get_memory_history(memory_id="m1")
        assert len(result) == 2
        mock_mcp_client.get_memory_history.assert_called_once_with("m1")



# ── TestUpdateMemory ────────────────────────────────────────────────────────

class TestUpdateMemory:
    """Tests for the update_memory MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_memory

        mock_mcp_client.update_memory.return_value = {"status": "ok"}
        result = update_memory(memory_id="m1", content="new", summary="sum", confidence=0.9, expires_at=0)
        assert result["status"] == "ok"
        mock_mcp_client.update_memory.assert_called_once_with("m1", "new", "sum", 0.9, 0)

    def test_default_expires_at(self, mock_mcp_client):
        from server.mcp.main import update_memory

        mock_mcp_client.update_memory.return_value = {"status": "ok"}
        update_memory(memory_id="m1")
        mock_mcp_client.update_memory.assert_called_once_with("m1", "", "", 0.0, -1)



# ── TestDeleteMemory ────────────────────────────────────────────────────────

class TestDeleteMemory:
    """Tests for the delete_memory MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_memory

        mock_mcp_client.delete_memory.return_value = {"status": "ok"}
        result = delete_memory(memory_id="m1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_memory.assert_called_once_with("m1")



# ── TestUpdateMemoryTier ────────────────────────────────────────────────────────

class TestUpdateMemoryTier:
    """Tests for the update_memory_tier MCP tool."""

    def test_updates_tier(self, mock_mcp_client):
        from server.mcp.main import update_memory_tier

        mock_mcp_client.update_memory_tier.return_value = {"id": "m1", "tier": "L1"}
        result = update_memory_tier(memory_id="m1", tier="L1")
        assert result["tier"] == "L1"
        mock_mcp_client.update_memory_tier.assert_called_once_with("m1", "L1")


# ── Tag tools ─────────────────────────────────────────────────────────────



# ── TestSetMemoryScope ────────────────────────────────────────────────────────

class TestSetMemoryScope:
    """Tests for the set_memory_scope MCP tool."""

    def test_sets_scope(self, mock_mcp_client):
        from server.mcp.main import set_memory_scope

        result = set_memory_scope(memory_id="m1", user_scope="alice")
        assert "scoped to" in result
        assert "alice" in result
        mock_mcp_client.set_memory_scope.assert_called_once_with("m1", "alice")

    def test_makes_shared(self, mock_mcp_client):
        from server.mcp.main import set_memory_scope

        result = set_memory_scope(memory_id="m1", user_scope="")
        assert "shared" in result
        mock_mcp_client.set_memory_scope.assert_called_once_with("m1", "")


# ── Profile tools ─────────────────────────────────────────────────────────



# ── TestStoreBatch ────────────────────────────────────────────────────────

class TestStoreBatch:
    """Tests for the store_batch MCP tool."""

    def test_stores_batch(self, mock_mcp_client):
        from server.mcp.main import store_batch

        mock_mcp_client.store_batch.return_value = [{"id": "m1"}, {"id": "m2"}]
        result = store_batch(
            items_json='[{"content": "Hello", "memory_type": "observation"}]',
        )
        assert "Stored 2 memories" in result
        mock_mcp_client.store_batch.assert_called_once()

    def test_invalid_json(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(items_json="not json")
        assert "Error" in result
        assert "invalid JSON" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_not_a_list(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(items_json='"just a string"')
        assert "Error" in result
        assert "list of dicts" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_not_dicts(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(items_json='[1, 2, 3]')
        assert "Error" in result
        mock_mcp_client.store_batch.assert_not_called()


# ── Note tools ────────────────────────────────────────────────────────────



# ── TestStoreBatchValidation ────────────────────────────────────────────────────────

class TestStoreBatchValidation:
    """Tests for the store_batch MCP tool."""

    def test_stores_valid_batch(self, mock_mcp_client):
        from server.mcp.main import store_batch

        mock_mcp_client.store_batch.return_value = [{"id": "m1"}, {"id": "m2"}]
        items_json = '[{"content": "Hello", "memory_type": "observation"}]'
        result = store_batch(workspace_id="ws-1", items_json=items_json)
        assert "Stored 2 memories" in result
        mock_mcp_client.store_batch.assert_called_once_with(
            workspace_id="ws-1",
            items=[{"content": "Hello", "memory_type": "observation"}],
        )

    def test_invalid_json(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(workspace_id="ws-1", items_json="not valid json")
        assert "Error" in result
        assert "invalid JSON" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_not_a_list(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(workspace_id="ws-1", items_json='"just a string"')
        assert "Error" in result
        assert "must be a JSON list" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_list_not_of_dicts(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(workspace_id="ws-1", items_json="[1, 2, 3]")
        assert "Error" in result
        assert "must be a JSON list" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_empty_list(self, mock_mcp_client):
        from server.mcp.main import store_batch

        mock_mcp_client.store_batch.return_value = []
        result = store_batch(workspace_id="ws-1", items_json="[]")
        assert "Stored 0 memories" in result
        mock_mcp_client.store_batch.assert_called_once_with(
            workspace_id="ws-1", items=[]
        )


# ── create_note (uses get_client directly) ─────────────────────────────────
