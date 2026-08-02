"""Tests for server/mcp/tools/memories.py — Memory MCP tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreMemory:
    """Tests for the ``store_memory`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_store_memory(self, mock_get_client):
        """store_memory delegates to get_client().store."""
        mock_client = MagicMock()
        expected = {"id": "mem-1", "status": "created"}
        mock_client.store.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import store_memory

        result = store_memory(
            workspace_id="ws-1",
            peer_id="peer-1",
            observer_id="obs-1",
            memory_type="experience",
            content="Hello world",
            summary="A greeting",
            entities_json='["user"]',
            confidence=0.9,
            source_session_id="sess-1",
            source_message_id="msg-1",
            tier="L0",
            images_json="[]",
            images=None,
        )

        mock_client.store.assert_called_once_with(
            workspace_id="ws-1",
            content="Hello world",
            summary="A greeting",
            memory_type="experience",
            peer_id="peer-1",
            observer_id="obs-1",
            entities_json='["user"]',
            confidence=0.9,
            source_session_id="sess-1",
            source_message_id="msg-1",
            tier="L0",
            images=None,
            images_json="[]",
        )
        assert result == expected


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMemories:
    """Tests for the ``search_memories`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_search_memories(self, mock_get_client):
        """search_memories delegates to get_client().search."""
        mock_client = MagicMock()
        expected = [{"id": "m1", "content": "test"}]
        mock_client.search.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import search_memories

        result = search_memories(
            workspace_id="ws-1",
            query_text="hello",
            memory_type="experience",
            tier="L1",
            limit=20,
            rerank=True,
        )

        mock_client.search.assert_called_once_with(
            workspace_id="ws-1",
            query="hello",
            memory_type="experience",
            tier="L1",
            limit=20,
            semantic=True,
            rerank=True,
            entity_types=None,
            before=None,
            after=None,
            return_schema=None,
        )
        assert result == expected

    @patch("server.mcp.tools.memories.get_client")
    def test_search_memories_with_filters(self, mock_get_client):
        """search_memories passes entity_types, before, after, return_schema."""
        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import search_memories

        search_memories(
            workspace_id="ws-1",
            query_text="test",
            entity_types=["memory", "note"],
            before=1000.0,
            after=500.0,
            return_schema="llm",
        )

        mock_client.search.assert_called_once_with(
            workspace_id="ws-1",
            query="test",
            memory_type="",
            tier="",
            limit=50,
            semantic=True,
            rerank=False,
            entity_types=["memory", "note"],
            before=1000.0,
            after=500.0,
            return_schema="llm",
        )


@pytest.mark.unit
class TestHybridSearch:
    """Tests for the ``hybrid_search`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_hybrid_search(self, mock_get_client):
        """hybrid_search delegates to get_client().search."""
        mock_client = MagicMock()
        expected = [{"id": "m1", "score": 0.95}]
        mock_client.search.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import hybrid_search

        result = hybrid_search(
            workspace_id="ws-1",
            query_text="hybrid query",
            memory_type="memory",
            tier="L0",
            limit=10,
            strategies="semantic,keyword",
            rerank=False,
        )

        mock_client.search.assert_called_once_with(
            workspace_id="ws-1",
            query="hybrid query",
            memory_type="memory",
            tier="L0",
            limit=10,
            semantic=True,
            rerank=False,
            entity_types=None,
            before=None,
            after=None,
            return_schema=None,
        )
        assert result == expected


@pytest.mark.unit
class TestSearchWithFilters:
    """Tests for the ``search_with_filters`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_search_with_filters(self, mock_get_client):
        """search_with_filters delegates to get_client().search_with_filters."""
        mock_client = MagicMock()
        expected = [{"id": "m1", "metadata": {"source": "wiki"}}]
        mock_client.search_with_filters.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import search_with_filters

        result = search_with_filters(
            workspace_id="ws-1",
            query="test",
            memory_type="note",
            tier="L1",
            metadata_filter='{"source": "wiki"}',
            location_filter='{"lat": 37.77}',
            limit=10,
            return_schema="llm",
        )

        mock_client.search_with_filters.assert_called_once_with(
            workspace_id="ws-1",
            query="test",
            memory_type="note",
            tier="L1",
            metadata_filter='{"source": "wiki"}',
            location_filter='{"lat": 37.77}',
            limit=10,
            return_schema="llm",
        )
        assert result == expected


# ---------------------------------------------------------------------------
# Single Memory CRUD
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMemory:
    """Tests for the ``get_memory`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_get_memory(self, mock_get_client):
        """get_memory delegates to get_client().get_memory."""
        mock_client = MagicMock()
        expected = [{"id": "mem-1", "content": "test"}]
        mock_client.get_memory.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import get_memory

        result = get_memory(id="mem-001")

        mock_client.get_memory.assert_called_once_with("mem-001")
        assert result == expected


@pytest.mark.unit
class TestGetMemoryHistory:
    """Tests for the ``get_memory_history`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_get_memory_history(self, mock_get_client):
        """get_memory_history delegates to get_client().get_memory_history."""
        mock_client = MagicMock()
        expected = [{"version": 1, "content": "v1"}, {"version": 2, "content": "v2"}]
        mock_client.get_memory_history.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import get_memory_history

        result = get_memory_history(memory_id="mem-001")

        mock_client.get_memory_history.assert_called_once_with("mem-001")
        assert result == expected


@pytest.mark.unit
class TestListMemories:
    """Tests for the ``list_memories`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_list_memories(self, mock_get_client):
        """list_memories delegates to get_client().list_memories."""
        mock_client = MagicMock()
        expected = [{"id": "m1", "content": "test"}]
        mock_client.list_memories.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import list_memories

        result = list_memories(
            workspace_id="ws-1", memory_type="experience", limit=25
        )

        mock_client.list_memories.assert_called_once_with(
            "ws-1", "experience", 25
        )
        assert result == expected


@pytest.mark.unit
class TestUpdateMemory:
    """Tests for the ``update_memory`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_update_memory(self, mock_get_client):
        """update_memory delegates to get_client().update_memory."""
        mock_client = MagicMock()
        expected = {"id": "mem-1", "status": "updated"}
        mock_client.update_memory.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import update_memory

        result = update_memory(
            memory_id="mem-001",
            content="new content",
            summary="new summary",
            confidence=0.95,
            expires_at=-1,
        )

        mock_client.update_memory.assert_called_once_with(
            "mem-001", "new content", "new summary", 0.95, -1
        )
        assert result == expected


@pytest.mark.unit
class TestDeleteMemory:
    """Tests for the ``delete_memory`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_delete_memory(self, mock_get_client):
        """delete_memory delegates to get_client().delete_memory."""
        mock_client = MagicMock()
        expected = {"status": "deleted"}
        mock_client.delete_memory.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import delete_memory

        result = delete_memory(memory_id="mem-001")

        mock_client.delete_memory.assert_called_once_with("mem-001")
        assert result == expected


@pytest.mark.unit
class TestUpdateMemoryTier:
    """Tests for the ``update_memory_tier`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_update_memory_tier(self, mock_get_client):
        """update_memory_tier delegates to get_client().update_memory_tier."""
        mock_client = MagicMock()
        expected = {"id": "mem-1", "tier": "L2"}
        mock_client.update_memory_tier.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import update_memory_tier

        result = update_memory_tier(memory_id="mem-001", tier="L2")

        mock_client.update_memory_tier.assert_called_once_with("mem-001", "L2")
        assert result == expected


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateTag:
    """Tests for the ``create_tag`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_create_tag(self, mock_get_client):
        """create_tag delegates to get_client().create_tag."""
        mock_client = MagicMock()
        expected = {"id": "tag-1", "name": "important"}
        mock_client.create_tag.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import create_tag

        result = create_tag(
            workspace_id="ws-1", name="important", color="#FF0000"
        )

        mock_client.create_tag.assert_called_once_with(
            "ws-1", "important", "#FF0000"
        )
        assert result == expected


@pytest.mark.unit
class TestTagMemory:
    """Tests for the ``tag_memory`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_tag_memory(self, mock_get_client):
        """tag_memory delegates to get_client().tag_memory."""
        mock_client = MagicMock()
        expected = {"status": "ok"}
        mock_client.tag_memory.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import tag_memory

        result = tag_memory(memory_id="mem-1", tag_id="tag-1")

        mock_client.tag_memory.assert_called_once_with("mem-1", "tag-1")
        assert result == expected


@pytest.mark.unit
class TestUntagMemory:
    """Tests for the ``untag_memory`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_untag_memory(self, mock_get_client):
        """untag_memory delegates to get_client().untag_memory."""
        mock_client = MagicMock()
        expected = {"status": "ok"}
        mock_client.untag_memory.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import untag_memory

        result = untag_memory(memory_id="mem-1", tag_id="tag-1")

        mock_client.untag_memory.assert_called_once_with("mem-1", "tag-1")
        assert result == expected


@pytest.mark.unit
class TestListTags:
    """Tests for the ``list_tags`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_list_tags(self, mock_get_client):
        """list_tags delegates to get_client().list_tags."""
        mock_client = MagicMock()
        expected = [{"id": "tag-1", "name": "urgent"}]
        mock_client.list_tags.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import list_tags

        result = list_tags(workspace_id="ws-1")

        mock_client.list_tags.assert_called_once_with("ws-1")
        assert result == expected


@pytest.mark.unit
class TestDeleteTag:
    """Tests for the ``delete_tag`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_delete_tag(self, mock_get_client):
        """delete_tag calls get_client().delete_tag and returns confirmation."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import delete_tag

        result = delete_tag(tag_id="tag-001")

        mock_client.delete_tag.assert_called_once_with("tag-001")
        assert result == {"status": "ok", "deleted_tag_id": "tag-001"}


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchTagMemories:
    """Tests for the ``batch_tag_memories`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_tag_memories(self, mock_get_client):
        """batch_tag_memories delegates to get_client().batch_tag_memories."""
        mock_client = MagicMock()
        expected = {"status": "ok", "tagged": 3}
        mock_client.batch_tag_memories.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_tag_memories

        result = batch_tag_memories(
            tag_id="tag-1",
            memory_ids_json='["mem-1", "mem-2", "mem-3"]',
        )

        mock_client.batch_tag_memories.assert_called_once_with(
            "tag-1", ["mem-1", "mem-2", "mem-3"]
        )
        assert result == expected


@pytest.mark.unit
class TestBatchUntagMemories:
    """Tests for the ``batch_untag_memories`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_untag_memories(self, mock_get_client):
        """batch_untag_memories delegates to get_client().batch_untag_memories."""
        mock_client = MagicMock()
        expected = {"status": "ok", "untagged": 2}
        mock_client.batch_untag_memories.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_untag_memories

        result = batch_untag_memories(
            tag_id="tag-1",
            memory_ids_json='["mem-1", "mem-2"]',
        )

        mock_client.batch_untag_memories.assert_called_once_with(
            "tag-1", ["mem-1", "mem-2"]
        )
        assert result == expected


@pytest.mark.unit
class TestStoreBatch:
    """Tests for the ``store_batch`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_store_batch(self, mock_get_client):
        """store_batch delegates to get_client().store_batch."""
        mock_client = MagicMock()
        mock_client.store_batch.return_value = [{"id": "m1"}, {"id": "m2"}]
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import store_batch

        items_json = '[{"content": "first", "memory_type": "experience"}, {"content": "second"}]'
        result = store_batch(
            items_json=items_json, workspace_id="ws-1"
        )

        mock_client.store_batch.assert_called_once_with(
            workspace_id="ws-1",
            items=[{"content": "first", "memory_type": "experience"}, {"content": "second"}],
        )
        assert "Stored 2 memories" in result

    @patch("server.mcp.tools.memories.get_client")
    def test_store_batch_invalid_json(self, mock_get_client):
        """store_batch returns error message for invalid JSON."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import store_batch

        result = store_batch(items_json="not valid json")

        assert "Error: invalid JSON" in result
        mock_client.store_batch.assert_not_called()

    @patch("server.mcp.tools.memories.get_client")
    def test_store_batch_non_list(self, mock_get_client):
        """store_batch returns error message for non-list JSON."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import store_batch

        result = store_batch(items_json='"just a string"')

        assert "Error: items_json must be a JSON list of dicts" in result
        mock_client.store_batch.assert_not_called()


@pytest.mark.unit
class TestBatchUpdateMemories:
    """Tests for the ``batch_update_memories`` tool."""

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_update_memories(self, mock_get_client):
        """batch_update_memories delegates to get_client().batch_update_memories."""
        mock_client = MagicMock()
        mock_client.batch_update_memories.return_value = {
            "status": "ok",
            "updated": 2,
            "errors": [],
        }
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_update_memories

        result = batch_update_memories(
            workspace_id="ws-1",
            memory_ids_json='["mem-1", "mem-2"]',
            updates_json='{"summary": "Updated", "confidence": 0.95}',
        )

        mock_client.batch_update_memories.assert_called_once_with(
            workspace_id="ws-1",
            memory_ids=["mem-1", "mem-2"],
            updates={"summary": "Updated", "confidence": 0.95},
        )
        assert "Batch update complete" in result
        assert "2" in result

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_update_memories_invalid_ids_json(self, mock_get_client):
        """batch_update_memories returns error for invalid memory_ids_json."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_update_memories

        result = batch_update_memories(
            workspace_id="ws-1",
            memory_ids_json="not-json",
            updates_json='{"summary": "x"}',
        )

        assert "Error: memory_ids_json must be a valid JSON array" in result
        mock_client.batch_update_memories.assert_not_called()

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_update_memories_invalid_updates_json(self, mock_get_client):
        """batch_update_memories returns error for invalid updates_json."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_update_memories

        result = batch_update_memories(
            workspace_id="ws-1",
            memory_ids_json='["mem-1"]',
            updates_json="not-json",
        )

        assert "Error: updates_json must be a valid JSON object" in result
        mock_client.batch_update_memories.assert_not_called()

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_update_memories_non_list_ids(self, mock_get_client):
        """batch_update_memories returns error when ids is not a list."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_update_memories

        result = batch_update_memories(
            workspace_id="ws-1",
            memory_ids_json='"not-a-list"',
            updates_json='{"summary": "x"}',
        )

        assert "Error: memory_ids_json must be a JSON array" in result
        mock_client.batch_update_memories.assert_not_called()

    @patch("server.mcp.tools.memories.get_client")
    def test_batch_update_memories_non_dict_updates(self, mock_get_client):
        """batch_update_memories returns error when updates is not a dict."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.memories import batch_update_memories

        result = batch_update_memories(
            workspace_id="ws-1",
            memory_ids_json='["mem-1"]',
            updates_json='"not-a-dict"',
        )

        assert "Error: updates_json must be a JSON object" in result
        mock_client.batch_update_memories.assert_not_called()
