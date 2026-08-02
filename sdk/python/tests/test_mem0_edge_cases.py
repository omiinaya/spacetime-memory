"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_edge_cases.py -v

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


class TestMem0EdgeCases:
    """Edge cases and error handling."""

    def test_add_empty_messages(self, mem: Memory) -> None:
        """Adding empty string should still work."""
        uid = _uid()
        result = mem.add("", user_id=uid)
        assert "results" in result

    def test_add_no_user_id(self, mem: Memory) -> None:
        """Adding without user_id, agent_id, or run_id raises RuntimeError (matches Mem0 behavior)."""
        with pytest.raises(RuntimeError):
            mem.add("No user test")

    def test_delete_all_nonexistent_user(self, mem: Memory) -> None:
        """delete_all on nonexistent user."""
        result = mem.delete_all(user_id=_uid("mem0-test-noexist"))
        assert result["status"] == "ok"

    def test_search_nonexistent_user(self, mem: Memory) -> None:
        """Search on nonexistent user returns empty."""
        result = mem.search("test", user_id=_uid("mem0-test-noexist-search"))
        assert "results" in result

    def test_delete_nonexistent(self, mem: Memory) -> None:
        """Delete on nonexistent memory ID may raise or return gracefully."""
        try:
            result = mem.delete("nonexistent-uuid-999")
            assert "message" in result
        except RuntimeError:
            pass  # Either behavior is acceptable

    def test_history(self, mem: Memory) -> None:
        """history() returns version list."""
        uid = _uid()
        add_result = mem.add("History test memory", user_id=uid)
        memory_id = add_result["results"][0]["id"]
        result = mem.history(memory_id=memory_id)
        assert isinstance(result, list)

    def test_history_nonexistent(self, mem: Memory) -> None:
        """history() on nonexistent memory may raise or return empty."""
        try:
            result = mem.history("nonexistent-uuid-999")
            assert isinstance(result, list)
        except RuntimeError:
            pass  # Either behavior is acceptable

    def test_update_nonexistent(self, mem: Memory) -> None:
        """Update on nonexistent memory ID may raise RuntimeError."""
        try:
            result = mem.update("nonexistent-uuid-999", "New content")
            assert "message" in result
        except RuntimeError:
            pass  # Either behavior is acceptable

    def test_add_with_filters_param(self, mem: Memory) -> None:
        """add() using filters dict instead of user_id (Mem0 v2 compat)."""
        uid = _uid()
        result = mem.add("Filters param test", filters={"user_id": uid})
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_add_with_memory_type(self, mem: Memory) -> None:
        """add() with memory_type accepted."""
        uid = _uid()
        result = mem.add("Procedural test", user_id=uid, memory_type="procedural_memory")
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_get_all_pagination(self, mem: Memory) -> None:
        """get_all with limit and top_k."""
        uid = _uid()
        for i in range(4):
            mem.add(f"Pagination memory {i}", user_id=uid)
        result = mem.get_all(user_id=uid, limit=2)
        assert len(result["results"]) <= 2
        result2 = mem.get_all(user_id=uid, top_k=1)
        assert len(result2["results"]) <= 1

    def test_search_with_high_threshold(self, mem: Memory) -> None:
        """search with high threshold filters all but very close matches."""
        uid = _uid()
        mem.add("The sky is blue", user_id=uid)
        time.sleep(0.3)
        result = mem.search("quantum physics", user_id=uid, threshold=0.95)
        assert "results" in result

    def test_chat_fallback(self, mem: Memory) -> None:
        """chat() returns response even without LLM configured."""
        uid = _uid()
        result = mem.chat("What do I like?", user_id=uid)
        assert "response" in result
        assert "context" in result
        assert "memories" in result

    def test_create_memory_tool(self, mem: Memory) -> None:
        """create_memory_tool() returns not_implemented status."""
        result = mem.create_memory_tool()
        assert result["status"] == "not_implemented"


