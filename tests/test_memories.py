"""Tests for server/mcp/tools/memories.py - Memory MCP tools."""
import pytest
from server.mcp.tools.memories import (
    get_memory, search_memories, delete_memory, update_memory,
    batch_update_memories, batch_tag_memories, batch_untag_memories,
    create_tag, delete_tag, tag_memory, untag_memory,
    store_memory, list_memories, get_memory_history,
    hybrid_search, search_with_filters,
    update_memory_veracity, batch_update_veracity,
    get_memory_veracity, list_workspace_veracity,
    detect_anomalies,
)


class TestMemoriesModule:
    """Test suite for memories.py - verify all expected exports exist."""

    def test_get_memory_exists(self):
        assert callable(get_memory)

    def test_search_memories_exists(self):
        assert callable(search_memories)

    def test_delete_memory_exists(self):
        assert callable(delete_memory)

    def test_update_memory_exists(self):
        assert callable(update_memory)

    def test_batch_update_memories_exists(self):
        assert callable(batch_update_memories)

    def test_batch_tag_memories_exists(self):
        assert callable(batch_tag_memories)

    def test_batch_untag_memories_exists(self):
        assert callable(batch_untag_memories)

    def test_create_tag_exists(self):
        assert callable(create_tag)

    def test_delete_tag_exists(self):
        assert callable(delete_tag)

    def test_tag_memory_exists(self):
        assert callable(tag_memory)

    def test_untag_memory_exists(self):
        assert callable(untag_memory)

    def test_store_memory_exists(self):
        assert callable(store_memory)

    def test_list_memories_exists(self):
        assert callable(list_memories)

    def test_get_memory_history_exists(self):
        assert callable(get_memory_history)

    def test_hybrid_search_exists(self):
        assert callable(hybrid_search)

    def test_search_with_filters_exists(self):
        assert callable(search_with_filters)

    def test_update_memory_veracity_exists(self):
        assert callable(update_memory_veracity)

    def test_batch_update_veracity_exists(self):
        assert callable(batch_update_veracity)

    def test_get_memory_veracity_exists(self):
        assert callable(get_memory_veracity)

    def test_list_workspace_veracity_exists(self):
        assert callable(list_workspace_veracity)

    def test_detect_anomalies_exists(self):
        assert callable(detect_anomalies)
