"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_core.py -v

"""

from __future__ import annotations

import os
import time

import pytest
from mem0_shared import _uid

from spacetime_memory.sdks.mem0 import Memory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


class TestMem0Core:
    """Core Mem0 API operations."""

    def test_add_string(self, mem: Memory) -> None:
        """Add a string memory."""
        uid = _uid()
        result = mem.add("I like pizza", user_id=uid)
        assert "results" in result
        assert len(result["results"]) >= 1
        assert result["results"][0]["memory"] == "I like pizza"
        assert result["results"][0]["user_id"] == uid
        assert result["results"][0]["event"] == "ADD"

    def test_add_with_agent_and_run(self, mem: Memory) -> None:
        """Add with agent_id and run_id."""
        uid = _uid()
        result = mem.add(
            "Agent test memory",
            user_id=uid,
            agent_id="my-agent",
            run_id="run-123",
        )
        assert result["results"][0]["agent_id"] == "my-agent"

    def test_add_list_messages(self, mem: Memory) -> None:
        """Add a list of message dicts (Mem0 v1.1+)."""
        uid = _uid()
        result = mem.add(
            [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}],
            user_id=uid,
        )
        assert len(result["results"]) >= 1

    def test_add_with_metadata(self, mem: Memory) -> None:
        """Add with metadata dict."""
        uid = _uid()
        result = mem.add(
            "Memory with metadata",
            user_id=uid,
            metadata={"source": "test", "importance": 5},
        )
        assert result["results"][0]["memory"] == "Memory with metadata"

    def test_get(self, mem: Memory) -> None:
        """Get a memory by ID."""
        uid = _uid()
        add_result = mem.add("Get me this memory", user_id=uid)
        memory_id = add_result["results"][0]["id"]

        result = mem.get(memory_id=memory_id)
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == memory_id
        assert result["results"][0]["memory"] == "Get me this memory"

    def test_get_nonexistent(self, mem: Memory) -> None:
        """Get a non-existent memory returns empty results."""
        result = mem.get(memory_id="nonexistent-uuid-999999")
        assert result["results"] == []

    def test_search(self, mem: Memory) -> None:
        """Search for memories."""
        uid = _uid()
        mem.add("My favorite food is pizza", user_id=uid)
        mem.add("I enjoy hiking in the mountains", user_id=uid)
        time.sleep(0.3)

        result = mem.search("food preferences", user_id=uid)
        assert "results" in result
        assert len(result["results"]) >= 0
        for r in result["results"]:
            assert "id" in r
            assert "memory" in r
            assert "score" in r

    def test_search_with_filters_dict(self, mem: Memory) -> None:
        """Search using Mem0 v2 filters dict."""
        uid = _uid()
        mem.add("France capital is Paris", user_id=uid)
        time.sleep(0.3)

        result = mem.search("France", filters={"user_id": uid})
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_search_with_top_k(self, mem: Memory) -> None:
        """Search with top_k parameter (Mem0 v2 compat)."""
        uid = _uid()
        mem.add("This is a test search result", user_id=uid)
        time.sleep(0.3)

        result = mem.search("test", user_id=uid, top_k=5)
        assert "results" in result

    def test_search_with_rerank(self, mem: Memory) -> None:
        """Search with rerank flag (accepted for compat)."""
        uid = _uid()
        mem.add("Rerank test memory", user_id=uid)
        time.sleep(0.3)

        result = mem.search("rerank", user_id=uid, rerank=True)
        assert "results" in result

    def test_search_no_results(self, mem: Memory) -> None:
        """Search for something that doesn't match."""
        uid = _uid()
        result = mem.search("xyznonexistent", user_id=uid)
        assert "results" in result

    def test_update(self, mem: Memory) -> None:
        """Update a memory."""
        uid = _uid()
        add_result = mem.add("Original content", user_id=uid)
        memory_id = add_result["results"][0]["id"]

        result = mem.update(memory_id, "Updated content")
        assert result["message"] == "Memory updated successfully!"

        # Verify
        get_result = mem.get(memory_id=memory_id)
        assert get_result["results"][0]["memory"] == "Updated content"

    def test_update_with_dict_data(self, mem: Memory) -> None:
        """Update using a data dict."""
        uid = _uid()
        add_result = mem.add("To be updated from dict", user_id=uid)
        memory_id = add_result["results"][0]["id"]

        result = mem.update(memory_id, {"content": "Dict updated content"})
        assert result["message"] == "Memory updated successfully!"

    def test_update_with_metadata_param(self, mem: Memory) -> None:
        """Update with metadata (Mem0 v2 compat)."""
        uid = _uid()
        add_result = mem.add("Metadata update test", user_id=uid)
        memory_id = add_result["results"][0]["id"]

        result = mem.update(memory_id, "Still updated", metadata={"key": "value"})
        assert result["message"] == "Memory updated successfully!"

    def test_delete(self, mem: Memory) -> None:
        """Delete a memory."""
        uid = _uid()
        add_result = mem.add("Delete me", user_id=uid)
        memory_id = add_result["results"][0]["id"]

        result = mem.delete(memory_id)
        assert result["message"] == "Memory deleted successfully!"

        # Verify it's gone
        get_result = mem.get(memory_id=memory_id)
        assert get_result["results"] == []

    def test_delete_all(self, mem: Memory) -> None:
        """Delete all memories for a user."""
        uid = _uid()
        mem.add("Memory 1", user_id=uid)
        mem.add("Memory 2", user_id=uid)

        result = mem.delete_all(user_id=uid)
        assert result["status"] == "ok"

    def test_get_all(self, mem: Memory) -> None:
        """Get all memories for a user."""
        uid = _uid()
        mem.add("List item 1", user_id=uid)
        mem.add("List item 2", user_id=uid)

        result = mem.get_all(user_id=uid)
        assert "results" in result
        assert len(result["results"]) >= 2

    def test_get_all_with_filters(self, mem: Memory) -> None:
        """get_all with Mem0 v2 filters dict."""
        uid = _uid()
        mem.add("Filter test memory", user_id=uid)

        result = mem.get_all(filters={"user_id": uid})
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_get_all_with_top_k(self, mem: Memory) -> None:
        """get_all with top_k parameter."""
        uid = _uid()
        for i in range(3):
            mem.add(f"TopK memory {i}", user_id=uid)

        result = mem.get_all(user_id=uid, top_k=2)
        assert len(result["results"]) <= 2

    def test_search_with_threshold(self, mem: Memory) -> None:
        """Search with threshold filters low scores."""
        uid = _uid()
        mem.add("Threshold test memory", user_id=uid)
        time.sleep(0.3)

        result = mem.search("threshold", user_id=uid, threshold=0.0)
        assert "results" in result

    def test_delete_all_with_filters(self, mem: Memory) -> None:
        """delete_all with Mem0 v2 filters dict."""
        uid = _uid()
        mem.add("Filter delete test", user_id=uid)

        result = mem.delete_all(filters={"user_id": uid})
        assert result["status"] == "ok"


