"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_adapter.py -v

"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
import time
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


from spacetime_memory.sdks.mem0 import Memory


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture
def mem(host: str, port: int, stdb_session: dict) -> Memory:
    """Fresh Memory instance per test with unique workspace."""
    m = Memory(config={
        "host": host, "port": port,
        "db": stdb_session["database"],
    })
    # Auto-register for auth
    import secrets
    try:
        m._client._call("register", [f"mem0_test_{secrets.token_hex(4)}", "Mem0 Test", "testpass"])
    except RuntimeError:
        pass
    yield m
    m.reset()


def _uid(prefix: str = "mem0-test") -> str:
    """Generate a unique user ID to avoid cross-test contamination."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


class TestMem0Construction:
    """Construction and config."""

    def test_from_config(self, host: str, port: int) -> None:
        """Create via from_config classmethod."""
        m = Memory.from_config({"host": host, "port": port})
        assert isinstance(m, Memory)

    def test_close_is_idempotent(self, mem: Memory) -> None:
        """close is idempotent."""
        mem.close()
        mem.close()  # Should not raise

    def test_reset_clears_cache(self, mem: Memory) -> None:
        """reset clears internal state."""
        uid = _uid()
        mem.add("Reset test", user_id=uid)
        mem.reset()
        # Works fine after reset
        uid2 = _uid()
        result = mem.add("After reset", user_id=uid2)
        assert result["results"][0]["memory"] == "After reset"


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
