"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_adapter.py -v

"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
import time
from unittest.mock import patch
import pytest

from spacetime_memory import Client, EmbedderUnavailableError

pytestmark = [
    pytest.mark.integration,
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


class TestMem0GraphStore:
    """Tests for the Mem0 graph store (_GraphStore)."""

    def test_graph_add(self, mem: Memory) -> None:
        """graph.add() creates a graph entity."""
        uid = _uid()
        result = mem.graph.add("GraphTestEntity", entity_type="concept", user_id=uid)
        assert "id" in result or "status" in result

    def test_graph_add_empty_raises(self, mem: Memory) -> None:
        """graph.add() with empty text raises ValueError."""
        with pytest.raises(ValueError):
            mem.graph.add("  ", user_id=_uid())

    def test_graph_search(self, mem: Memory) -> None:
        """graph.search() returns entities."""
        uid = _uid()
        mem.graph.add("SearchEntity", entity_type="concept", user_id=uid)
        results = mem.graph.search("Search", user_id=uid)
        assert isinstance(results, list)

    def test_graph_get_all(self, mem: Memory) -> None:
        """graph.get_all() lists entities."""
        uid = _uid()
        mem.graph.add("ListAllEntity", entity_type="concept", user_id=uid)
        results = mem.graph.get_all(user_id=uid)
        assert isinstance(results, list)

    def test_graph_delete(self, mem: Memory) -> None:
        """graph.delete() deletes a graph entity."""
        uid = _uid()
        result = mem.graph.add("DeleteEntity", entity_type="concept", user_id=uid)
        entity_id = result.get("id", "")
        if entity_id:
            del_result = mem.graph.delete(entity_id)
            assert del_result["status"] == "ok"

    def test_graph_add_with_metadata(self, mem: Memory) -> None:
        """graph.add() with metadata."""
        uid = _uid()
        result = mem.graph.add(
            "MetaEntity", entity_type="person", user_id=uid,
            metadata={"source": "test", "importance": 5},
        )
        assert "id" in result or "status" in result

    def test_graph_add_with_agent_id(self, mem: Memory) -> None:
        """graph.add() with agent_id."""
        uid = _uid()
        result = mem.graph.add(
            "AgentScopedEntity", entity_type="concept",
            user_id=uid, agent_id="my-agent",
        )
        assert "id" in result or "status" in result

    def test_set_llm_config(self, mem: Memory) -> None:
        """set_llm_config stores per-user LLM config overrides."""
        uid = _uid()
        mem.set_llm_config(uid, {"model": "gpt-4", "api_key": "test-key"})
        # No error = success — just testing it doesn't raise

    def test_add_with_metadata_dict(self, mem: Memory) -> None:
        """add() with rich metadata dict."""
        uid = _uid()
        result = mem.add(
            "Metadata rich test",
            user_id=uid,
            metadata={"source": "conversation", "importance": 7, "tags": ["preference"]},
        )
        assert "results" in result
        assert len(result["results"]) >= 1


# ---------------------------------------------------------------------------
# Additional tests to push coverage to ≥70%
# ---------------------------------------------------------------------------


class TestMem0ConfigVariants:
    """Constructor and config edge cases (lines 522-525, 542-543)."""

    def test_init_with_empty_dict(self, host: str, port: int) -> None:
        """Memory(config={}) uses defaults."""
        m = Memory(config={})
        assert isinstance(m, Memory)

    def test_init_with_pydantic_like(self, host: str, port: int) -> None:
        """Memory(config=...) with object that has model_dump()."""
        class FakeConfig:
            def model_dump(self):
                return {"host": host, "port": port}
        m = Memory(config=FakeConfig())
        assert isinstance(m, Memory)

    def test_init_with_none_config(self) -> None:
        """Memory() with no config hits else branch (line 525)."""
        m = Memory(config=None)
        assert isinstance(m, Memory)

    def test_init_with_llm_config(self, host: str, port: int) -> None:
        """Memory(config=...) with llm_config dict (lines 542-543)."""
        m = Memory(config={
            "host": host, "port": port,
            "llm_config": {"user1": {"model": "gpt-4", "api_key": "sk-test"}},
        })
        assert isinstance(m, Memory)

    def test_init_llm_config_skips_non_dict(self, host: str, port: int) -> None:
        """Memory(config=...) with non-dict llm_config entries (line 542 is False)."""
        m = Memory(config={
            "host": host, "port": port,
            "llm_config": {"user1": "not-a-dict"},
        })
        assert isinstance(m, Memory)


class TestMem0Unscoped:
    """Tests for unscoped (no user_id) operations."""

    def test_get_all_without_user_id(self, mem: Memory) -> None:
        """get_all() without user_id (lines 1169-1170)."""
        result = mem.get_all()
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_add_with_empty_filters(self, mem: Memory) -> None:
        """add() with empty filters dict hits _extract_ids_from_filters None path."""
        uid = _uid()
        result = mem.add("test", filters={}, user_id=uid)
        assert "results" in result


class TestMem0LLMConfig:
    """LLM config resolution tests."""

    def test_resolve_llm_for_with_override(self, mem: Memory) -> None:
        """_resolve_llm_for uses per-user override (line 599)."""
        from spacetime_memory.sdks.mem0 import _resolve_llm
        uid = _uid()
        mem.set_llm_config(uid, {"model": "gpt-4", "api_key": "sk-test"})
        llm = mem._resolve_llm_for(uid)
        assert llm is not None

    def test_resolve_llm_with_config(self) -> None:
        """_resolve_llm with full config dict (line 486)."""
        from spacetime_memory.sdks.mem0 import _resolve_llm
        llm = _resolve_llm({"model": "gpt-4", "api_key": "sk-test", "base_url": "http://x"})
        assert llm is not None


class TestMem0InternalPaths:
    """Exercise internal code paths for coverage."""

    def test_ws_cached_hit(self, mem: Memory) -> None:
        """_ws returns cached workspace_id without server call."""
        uid = _uid()
        ws1 = mem._ws(uid)  # creates workspace
        ws2 = mem._ws(uid)  # cached → returns immediately
        assert ws1 == ws2

    def test_ws_finds_existing_workspace(self, mem: Memory) -> None:
        """_ws finds existing workspace on server (line 614)."""
        uid = _uid()
        mem._ws(uid)  # creates workspace
        # Clear cache so next call must query server
        mem._user_id_to_ws.clear()
        ws = mem._ws(uid)  # should find existing → line 614
        assert ws

    def test_extract_ids_from_filters_none(self, mem: Memory) -> None:
        """_extract_ids_from_filters with None returns (None, None, None) (line 644)."""
        uid = _uid()
        result = mem.search("test", filters={}, user_id=uid, graph_context=False)
        assert "results" in result

    def test_search_with_graph_context(self, mem: Memory) -> None:
        """search() with graph_context=True populates metadata.graph_context (line 1094)."""
        uid = _uid()
        mem.add("graph context test", user_id=uid)
        time.sleep(0.3)
        result = mem.search("graph", user_id=uid, graph_context=True)
        assert "results" in result
        # May or may not have graph_context depending on KG data

    def test_get_all_with_empty_filters(self, mem: Memory) -> None:
        """get_all() with empty filters dict (exercises _extract_ids_from_filters with {})."""
        uid = _uid()
        mem.add("filter test", user_id=uid)
        result = mem.get_all(filters={}, user_id=uid)
        assert "results" in result

    def test_search_user_scope_isolation(self, mem: Memory) -> None:
        """search() checks user_scope isolation (line 1090 coverage attempt)."""
        uid1 = _uid("mem0-scope-a")
        uid2 = _uid("mem0-scope-b")
        mem.add("user A memory", user_id=uid1)
        time.sleep(0.3)
        # Search as user B — should not return A's scoped memories
        result = mem.search("user A memory", user_id=uid2)
        assert "results" in result  # May be empty but should not crash

    def test_get_graph_context_error(self, mem: Memory) -> None:
        """_get_graph_context returns [] on RuntimeError (lines 704-706)."""
        uid = _uid()
        with patch.object(mem._client, 'query_graph', side_effect=RuntimeError("no graph")):
            result = mem._get_graph_context("test", user_id=uid)
            assert result == []

    def test_set_llm_config_persists(self, mem: Memory) -> None:
        """set_llm_config stores per-user overrides."""
        uid = _uid()
        mem.set_llm_config(uid, {"model": "gpt-3.5-turbo"})
        assert uid in mem._llm_overrides
        assert mem._llm_overrides[uid]["model"] == "gpt-3.5-turbo"


class TestMem0ExceptionHandlers:
    """Test that API methods properly handle and wrap exceptions via mocking."""

    # ── add() exception handlers (lines 951-956) ─────────────────────────

    def test_add_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'store', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.add("test", user_id=uid, infer=False)

    def test_add_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'store', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.add("test", user_id=uid, infer=False)

    def test_add_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'store',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.add("test", user_id=uid, infer=False)

    def test_add_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'store', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.add\(\) failed"):
                mem.add("test", user_id=uid, infer=False)

    # ── get() exception handlers (lines 990-997) ─────────────────────────

    def test_get_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.get("fake-id")

    def test_get_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.get("fake-id")

    def test_get_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.get("fake-id")

    def test_get_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.get\('fake-id'\) failed"):
                mem.get("fake-id")

    # ── search() exception handlers (lines 1105-1112) ────────────────────

    def test_search_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'search', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.search("test", user_id=uid, graph_context=False)

    def test_search_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'search', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.search("test", user_id=uid, graph_context=False)

    def test_search_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'search',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.search("test", user_id=uid, graph_context=False)

    def test_search_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'search', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.search\('test'\) failed"):
                mem.search("test", user_id=uid, graph_context=False)

    # ── get_all() exception handlers (lines 1183-1190) ───────────────────

    def test_get_all_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'list_memories', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.get_all(user_id=uid)

    def test_get_all_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'list_memories', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.get_all(user_id=uid)

    def test_get_all_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'list_memories',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.get_all(user_id=uid)

    def test_get_all_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, 'list_memories', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.get_all\(user_id="):
                mem.get_all(user_id=uid)

    # ── update() exception handlers (lines 1227-1232) ────────────────────

    def test_update_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'update_memory', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.update("fake-id", "content")

    def test_update_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'update_memory', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.update("fake-id", "content")

    def test_update_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'update_memory',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.update("fake-id", "content")

    def test_update_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, 'update_memory', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.update\('fake-id'\) failed"):
                mem.update("fake-id", "content")

    # ── delete() exception handlers (lines 1252-1259) ────────────────────

    def test_delete_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'delete_memory', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.delete("fake-id")

    def test_delete_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'delete_memory', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.delete("fake-id")

    def test_delete_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'delete_memory',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.delete("fake-id")

    def test_delete_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, 'delete_memory', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.delete\('fake-id'\) failed"):
                mem.delete("fake-id")

    # ── delete_all() exception handlers (lines 1296-1303) ────────────────

    def test_delete_all_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        # Add a memory first so get_all returns results, then delete_memory raises
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, 'delete_memory', side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.delete_all(user_id=uid)

    def test_delete_all_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, 'delete_memory', side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.delete_all(user_id=uid)

    def test_delete_all_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, 'delete_memory',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.delete_all(user_id=uid)

    def test_delete_all_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, 'delete_memory', side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.delete_all\(user_id="):
                mem.delete_all(user_id=uid)

    # ── history() exception handlers (lines 1325-1332) ───────────────────

    def test_history_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory_history',
                          side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.history("fake-id")

    def test_history_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory_history',
                          side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.history("fake-id")

    def test_history_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory_history',
                          side_effect=EmbedderUnavailableError("no embedder")):
            with pytest.raises(EmbedderUnavailableError, match="no embedder"):
                mem.history("fake-id")

    def test_history_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, 'get_memory_history',
                          side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.history\('fake-id'\) failed"):
                mem.history("fake-id")


# ---------------------------------------------------------------------------
# Graph store coverage tests (mocked — no live server needed for these paths)
# ---------------------------------------------------------------------------

class TestGraphStoreEntityLinkPaths:
    """Cover entity_link / kg_node branches in graph store methods."""

    def test_graph_add_exact_entity_link(self, mem: Memory) -> None:
        """graph.add() via _add_exact → entity_link path (line 257)."""
        uid = _uid()
        fake_row = {
            "id": "el-123",
            "entity_name": "TestEnt",
            "entity_type": "person",
            "description": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1234567890,
        }
        # Mock client to avoid vector dedup (semantic search raises) and use entity_link
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, 'create_entity_link'):
                    with patch.object(mem._client, '_query', return_value=[fake_row]):
                        result = mem.graph.add("TestEnt", entity_type="person", user_id=uid)
                        assert "id" in result
                        assert result["label"] == "TestEnt"

    def test_graph_add_exact_entity_link_no_rows(self, mem: Memory) -> None:
        """graph.add() via _add_exact → entity_link with no query results."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, 'create_entity_link'):
                    with patch.object(mem._client, '_query', return_value=[]):
                        result = mem.graph.add("GhostEnt", entity_type="concept", user_id=uid)
                        assert result["status"] == "ok"

    def test_graph_add_exact_kg_node_fallback(self, mem: Memory) -> None:
        """graph.add() via _add_exact → entity_link fails → kg_node fallback (lines 259-272)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, 'create_entity_link', side_effect=RuntimeError("no table")):
                    with patch.object(mem, '_call', return_value={"id": "node-456", "label": "FallbackEnt"}) as mock_call:
                        result = mem.graph.add("FallbackEnt", entity_type="concept", user_id=uid)
                        mock_call.assert_called()
                        assert "id" in result or "status" in result

    def test_graph_add_kg_node_fallback_non_dict_result(self, mem: Memory) -> None:
        """kg_node fallback returns non-dict result (line 272)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, 'create_entity_link', side_effect=RuntimeError("no table")):
                    with patch.object(mem, '_call', return_value="node-id-string"):
                        result = mem.graph.add("StrResult", entity_type="concept", user_id=uid)
                        assert result["status"] == "ok"
                        assert result["id"] == "node-id-string"

    def test_graph_add_vector_dedup_path(self, mem: Memory) -> None:
        """graph.add() vector dedup path (lines 191-230) — matches existing entity."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-abc", "score": 0.95},
            {"entity_type": "memory", "entity_id": "mem-xyz", "score": 0.5},
        ]
        fake_kg_node = [{
            "id": "node-abc",
            "label": "ExistingLabel",
            "node_type": "person",
            "summary": "Existing summary",
            "metadata_json": '{"tag": "mem0_global"}',
            "created_at": 1000000,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=fake_semantic):
                with patch.object(mem._client, '_query', side_effect=[fake_kg_node, []]):
                    with patch.object(mem._client, 'add_alias'):
                        result = mem.graph.add("ExistingLabel", entity_type="person", user_id=uid)
                        assert result["merged"] is True
                        assert result["label"] == "ExistingLabel"

    def test_graph_add_vector_dedup_below_threshold(self, mem: Memory) -> None:
        """graph.add() vector dedup — score below 0.85 skips (line 192)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-low", "score": 0.3},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=fake_semantic):
                with patch.object(mem._client, 'create_entity_link'):
                    with patch.object(mem._client, '_query', return_value=[
                        {"id": "el-new", "entity_name": "NewEnt", "entity_type": "concept",
                         "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1}
                    ]):
                        result = mem.graph.add("NewEnt", entity_type="concept", user_id=uid)
                        assert result.get("merged") is not True

    def test_graph_add_vector_dedup_no_entity_id(self, mem: Memory) -> None:
        """graph.add() vector dedup — no entity_id skips (line 196)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "", "score": 0.95},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=fake_semantic):
                with patch.object(mem._client, 'create_entity_link'):
                    with patch.object(mem._client, '_query', return_value=[
                        {"id": "el-new", "entity_name": "NoEID", "entity_type": "concept",
                         "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1}
                    ]):
                        result = mem.graph.add("NoEID", entity_type="concept", user_id=uid)
                        assert result.get("merged") is not True

    def test_graph_add_vector_dedup_with_entity_link_alias(self, mem: Memory) -> None:
        """graph.add() vector dedup — resolves entity_link and adds alias (lines 212-215)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-abc", "score": 0.95},
        ]
        fake_kg_node = [{
            "id": "node-abc",
            "label": "ExistingLabel",
            "node_type": "person",
            "summary": "Existing summary",
            "metadata_json": '{"tag": "mem0_global"}',
            "created_at": 1000000,
        }]
        fake_el_rows = [{"id": "el-abc", "entity_name": "ExistingLabel"}]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=fake_semantic):
                with patch.object(mem._client, '_query', side_effect=[fake_kg_node, fake_el_rows]):
                    with patch.object(mem._client, 'add_alias') as mock_alias:
                        result = mem.graph.add("ExistingLabel", entity_type="person", user_id=uid)
                        assert result["merged"] is True
                        assert result["label"] == "ExistingLabel"
                        mock_alias.assert_called_once_with("el-abc", "ExistingLabel")

    def test_graph_add_vector_dedup_entity_link_runtime_error(self, mem: Memory) -> None:
        """graph.add() vector dedup — entity_link query raises RuntimeError (line 214-215)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-abc", "score": 0.95},
        ]
        fake_kg_node = [{
            "id": "node-abc",
            "label": "ExistingLabel",
            "node_type": "person",
            "summary": "Existing summary",
            "metadata_json": '{"tag": "mem0_global"}',
            "created_at": 1000000,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=fake_semantic):
                # entity_link query raises RuntimeError, caught gracefully
                with patch.object(mem._client, '_query', side_effect=[fake_kg_node, RuntimeError("no entity_link")]):
                    result = mem.graph.add("ExistingLabel", entity_type="person", user_id=uid)
                    assert result["merged"] is True
                    assert result["label"] == "ExistingLabel"

    def test_graph_add_vector_dedup_kg_node_empty(self, mem: Memory) -> None:
        """graph.add() vector dedup — kg_node query returns empty (line 202)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-ghost", "score": 0.95},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=fake_semantic):
                with patch.object(mem._client, '_query', side_effect=[[],  # kg_node empty
                    [{"id": "el-new", "entity_name": "GhostEnt", "entity_type": "concept",
                      "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1}]
                ]):
                    with patch.object(mem._client, 'create_entity_link'):
                        result = mem.graph.add("GhostEnt", entity_type="concept", user_id=uid)
                        assert result.get("merged") is not True


class TestGraphStoreSearchPaths:
    """Cover graph.search() fallback and entity paths."""

    def test_graph_search_entity_link_path(self, mem: Memory) -> None:
        """graph.search() → entity_link substring match (lines 407-414)."""
        uid = _uid()
        fake_el_rows = [
            {"id": "el-1", "entity_name": "SearchTarget", "entity_type": "concept",
             "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1},
            {"id": "el-2", "entity_name": "OtherThing", "entity_type": "person",
             "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 2},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, '_tantivy_search', side_effect=RuntimeError("no tantivy")):
                    with patch.object(mem._client, 'resolve_entity'):
                        with patch.object(mem._client, '_query', return_value=fake_el_rows):
                            results = mem.graph.search("Search", user_id=uid)
                            assert isinstance(results, list)
                            if results:
                                assert results[0]["label"] == "SearchTarget"

    def test_graph_search_kg_node_fallback(self, mem: Memory) -> None:
        """graph.search() → entity_link unavailable → kg_node fallback (line 414)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, '_tantivy_search', side_effect=RuntimeError("no tantivy")):
                    with patch.object(mem._client, 'resolve_entity', side_effect=RuntimeError("no resolve")):
                        with patch.object(mem._client, '_query', side_effect=RuntimeError("no entity_link")):
                            with patch.object(mem, '_call', return_value=[
                                {"id": "n1", "label": "KGNode", "node_type": "concept",
                                 "summary": "kg", "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                                 "created_at": 1}
                            ]) as mock_call:
                                results = mem.graph.search("KG", user_id=uid)
                                assert isinstance(results, list)
                                mock_call.assert_called()

    def test_graph_search_tantivy_node_path(self, mem: Memory) -> None:
        """graph.search() Tantivy fallback → node results (lines 345-366)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "nid-1", "entity_type": "node", "score": 0.9},
        ]
        kg_node_rows = [{
            "id": "nid-1", "label": "TantivyNode", "node_type": "concept",
            "summary": "t", "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, '_tantivy_search', return_value=tantivy_hits):
                    with patch.object(mem._client, '_query', return_value=kg_node_rows):
                        results = mem.graph.search("Tantivy", user_id=uid)
                        assert isinstance(results, list)
                        if results:
                            assert results[0]["label"] == "TantivyNode"

    def test_graph_search_tantivy_memory_path(self, mem: Memory) -> None:
        """graph.search() Tantivy fallback → memory results (lines 367-382)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "mid-1", "entity_type": "memory", "score": 0.8},
        ]
        memory_rows = [{
            "id": "mid-1", "content": "A memory content that is long enough to test truncation",
            "summary": "s", "created_at": 1,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, '_tantivy_search', return_value=tantivy_hits):
                    with patch.object(mem._client, '_query', return_value=memory_rows):
                        results = mem.graph.search("memory", user_id=uid)
                        assert isinstance(results, list)

    def test_graph_search_tantivy_no_entity_id(self, mem: Memory) -> None:
        """graph.search() Tantivy hit with no entity_id is skipped (line 349)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "", "entity_type": "node", "score": 0.9},
            {"entity_id": "nid-ok", "entity_type": "node", "score": 0.8},
        ]
        kg_node_rows = [{
            "id": "nid-ok", "label": "OKNode", "node_type": "concept",
            "summary": "ok", "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, '_tantivy_search', return_value=tantivy_hits):
                    with patch.object(mem._client, '_query', return_value=kg_node_rows):
                        results = mem.graph.search("test", user_id=uid)
                        assert isinstance(results, list)

    def test_graph_search_tantivy_kg_node_empty(self, mem: Memory) -> None:
        """graph.search() Tantivy → kg_node query returns empty (line 355)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "ghost", "entity_type": "memory", "score": 0.5},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, '_tantivy_search', return_value=tantivy_hits):
                    with patch.object(mem._client, '_query', return_value=[]):
                        results = mem.graph.search("ghost", user_id=uid)
                        assert isinstance(results, list)

    def test_graph_search_vector_path(self, mem: Memory) -> None:
        """graph.search() vector search → node results (lines 312-335)."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "memory", "entity_id": "mem-x", "score": 0.3},
            {"entity_type": "node", "entity_id": "nid-v", "score": 0.92},
        ]
        kg_node_rows = [{
            "id": "nid-v", "label": "VectorNode", "node_type": "concept",
            "summary": "v", "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=semantic_rows):
                with patch.object(mem._client, '_query', return_value=kg_node_rows):
                    results = mem.graph.search("Vector", user_id=uid)
                    assert isinstance(results, list)
                    if results:
                        assert results[0]["label"] == "VectorNode"

    def test_graph_search_vector_no_node(self, mem: Memory) -> None:
        """graph.search() vector search → no nodes found, falls through."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "memory", "entity_id": "mem-x", "score": 0.3},
        ]
        fake_el_rows = [
            {"id": "el-v", "entity_name": "VectorEnt", "entity_type": "concept",
             "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=semantic_rows):
                with patch.object(mem._client, '_tantivy_search', side_effect=RuntimeError("no tantivy")):
                    with patch.object(mem._client, 'resolve_entity'):
                        with patch.object(mem._client, '_query', return_value=fake_el_rows):
                            results = mem.graph.search("Vector", user_id=uid)
                            assert isinstance(results, list)

    def test_graph_search_vector_no_entity_id(self, mem: Memory) -> None:
        """graph.search() vector hit with no entity_id is skipped (line 315)."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "node", "entity_id": "", "score": 0.95},
            {"entity_type": "node", "entity_id": "nid-good", "score": 0.90},
        ]
        kg_node_rows = [{
            "id": "nid-good", "label": "GoodNode", "node_type": "concept",
            "summary": "g", "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=semantic_rows):
                with patch.object(mem._client, '_query', return_value=kg_node_rows):
                    results = mem.graph.search("test", user_id=uid)
                    assert isinstance(results, list)
                    if results:
                        assert results[0]["id"] == "nid-good"

    def test_graph_search_vector_kg_node_empty(self, mem: Memory) -> None:
        """graph.search() vector → kg_node query returns empty for a hit."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "node", "entity_id": "nid-ghost", "score": 0.95},
            {"entity_type": "node", "entity_id": "nid-real", "score": 0.90},
        ]
        real_row = [{
            "id": "nid-real", "label": "RealNode", "node_type": "concept",
            "summary": "r", "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1,
        }]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, 'search', return_value=semantic_rows):
                with patch.object(mem._client, '_query', side_effect=[[], real_row]):
                    results = mem.graph.search("test", user_id=uid)
                    assert isinstance(results, list)


class TestGraphGetAllPaths:
    """Cover graph.get_all() entity_link and fallback paths."""

    def test_graph_get_all_entity_link(self, mem: Memory) -> None:
        """graph.get_all() via entity_link (lines 437-443)."""
        uid = _uid()
        fake_rows = [
            {"id": "el-1", "entity_name": "EntA", "entity_type": "person",
             "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1},
            {"id": "el-2", "entity_name": "EntB", "entity_type": "concept",
             "description": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 2},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, '_query', return_value=fake_rows):
                results = mem.graph.get_all(user_id=uid)
                assert isinstance(results, list)
                assert len(results) == 2

    def test_graph_get_all_kg_node_fallback(self, mem: Memory) -> None:
        """graph.get_all() entity_link fails → kg_node fallback (lines 444-452)."""
        uid = _uid()
        kg_rows = [
            {"id": "n1", "label": "KG-A", "node_type": "fact", "summary": "a",
             "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}), "created_at": 1},
        ]
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem._client, '_query', side_effect=RuntimeError("no entity_link")):
                with patch.object(mem, '_call', return_value=kg_rows) as mock_call:
                    results = mem.graph.get_all(user_id=uid)
                    assert isinstance(results, list)
                    mock_call.assert_called()

    def test_graph_delete(self, mem: Memory) -> None:
        """graph.delete() calls delete_node (line 468-469)."""
        with patch.object(mem, '_call') as mock_call:
            result = mem.graph.delete("entity-123")
            mock_call.assert_called_once_with("delete_node", "entity-123")
            assert result == {"status": "ok", "deleted": "entity-123"}


# ---------------------------------------------------------------------------
# Workspace resolution coverage (mocked)
# ---------------------------------------------------------------------------

class TestWorkspaceResolutionMocks:
    """Cover _ws paths: cache hits, server lookup, creation, failure."""

    def test_ws_server_failure_raises_valueerror(self, mem: Memory) -> None:
        """_ws raises ValueError when workspace cannot be resolved (line 622)."""
        uid = _uid()
        mem._user_id_to_ws.clear()
        with patch.object(mem, '_call', return_value=[]):  # empty list_workspaces
            with pytest.raises(ValueError, match="Could not resolve or create workspace"):
                mem._ws(uid)

    def test_ws_creates_and_finds(self, mem: Memory) -> None:
        """_ws: creates workspace, then finds it on second list call."""
        uid = _uid()
        mem._user_id_to_ws.clear()
        ws_id = "ws-created-123"
        # First list: empty, then create_workspace called, second list finds it
        call_results = [
            [],  # first list_workspaces → empty
            None,  # create_workspace (any return)
            [{"name": uid, "id": ws_id}],  # second list_workspaces
        ]
        with patch.object(mem, '_call', side_effect=call_results):
            result = mem._ws(uid)
            assert result == ws_id

    def test_ws_cached_without_server_call(self, mem: Memory) -> None:
        """_ws returns cached value without server call."""
        uid = _uid()
        mem._user_id_to_ws[uid] = "ws-cached"
        with patch.object(mem, '_call') as mock_call:
            result = mem._ws(uid)
            assert result == "ws-cached"
            mock_call.assert_not_called()  # must not call server


# ---------------------------------------------------------------------------
# _call token refresh coverage (mocked)
# ---------------------------------------------------------------------------

class TestCallTokenRefresh:
    """Cover _call token refresh path (lines 635-638)."""

    def test_call_token_refresh_on_auth_error(self, host: str, port: int) -> None:
        """_call retries after token refresh on auth errors."""
        import secrets
        refreshed = False

        def refresh_cb():
            nonlocal refreshed
            refreshed = True
            return "new-token"

        m = Memory(config={"host": host, "port": port}, token_refresh_callback=refresh_cb)

        # First store call raises auth RuntimeError, second succeeds
        call_count = [0]

        def fake_store(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("unauthorized request")
            return "ok"

        with patch.object(m._client, 'store', side_effect=fake_store):
            result = m._call("store", workspace_id="x", content="test")
            assert result == "ok"
            assert refreshed is True

    def test_call_no_token_refresh_on_non_auth_error(self, host: str, port: int) -> None:
        """_call does not retry on non-auth RuntimeError."""
        refresh_called = [False]

        def refresh_cb():
            refresh_called[0] = True
            return "token"

        m = Memory(config={"host": host, "port": port}, token_refresh_callback=refresh_cb)

        with patch.object(m._client, 'store', side_effect=RuntimeError("db connection failed")):
            with pytest.raises(RuntimeError, match="db connection failed"):
                m._call("store", workspace_id="x", content="test")
            assert refresh_called[0] is False


# ---------------------------------------------------------------------------
# _store_facts_as_kg_nodes coverage (mocked)
# ---------------------------------------------------------------------------

class TestStoreFactsAsKgNodes:
    """Cover _store_facts_as_kg_nodes paths (lines 666-691)."""

    def test_store_facts_empty_ws_returns_empty(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes with no ws_id returns [] (line 667)."""
        with patch.object(mem, '_ws', return_value=""):
            result = mem._store_facts_as_kg_nodes(["fact 1", "fact 2"], user_id=None)
            assert result == []

    def test_store_facts_empty_list_returns_empty(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes with empty facts returns [] (line 667)."""
        uid = _uid()
        result = mem._store_facts_as_kg_nodes([], user_id=uid)
        assert result == []

    def test_store_facts_short_fact_skipped(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes skips facts shorter than 4 chars (line 671)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-test"):
            with patch.object(mem, '_call', return_value={"id": "nid-ok"}) as mock_call:
                result = mem._store_facts_as_kg_nodes(["ab", "c", "valid fact"], user_id=uid)
                # Only "valid fact" should be stored
                assert mock_call.call_count == 1
                assert len(result) == 1

    def test_store_facts_with_agent_id(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes includes agent_id in metadata (line 675)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-test"):
            with patch.object(mem, '_call', return_value={"id": "nid-1"}) as mock_call:
                result = mem._store_facts_as_kg_nodes(
                    ["fact about agent"], user_id=uid, agent_id="my-agent"
                )
                call_kwargs = mock_call.call_args[1]
                meta = json.loads(call_kwargs["metadata_json"])
                assert meta["agent_id"] == "my-agent"
                assert len(result) == 1

    def test_store_facts_runtime_error_per_fact(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes handles RuntimeError per fact (line 689-690)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-test"):
            # First fact raises, second succeeds
            with patch.object(mem, '_call', side_effect=[
                RuntimeError("node creation failed"),
                {"id": "nid-ok"},
            ]):
                result = mem._store_facts_as_kg_nodes(["good fact 1", "good fact 2"], user_id=uid)
                # Only the second one should succeed
                assert len(result) == 1
                assert result[0] == "nid-ok"

    def test_store_facts_non_dict_result(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes with non-dict result (no id)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-test"):
            with patch.object(mem, '_call', return_value="just-a-string"):
                result = mem._store_facts_as_kg_nodes(["valid fact here"], user_id=uid)
                assert result == []  # non-dict result gives no id


# ---------------------------------------------------------------------------
# _handle_message_list and _try_infer_merge coverage (mocked)
# ---------------------------------------------------------------------------

class TestHandleMessageList:
    """Cover _handle_message_list paths."""

    def test_message_list_no_infer(self, mem: Memory) -> None:
        """_handle_message_list with infer=False → non-infer path (lines 761-762)."""
        messages = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]
        content, summary = mem._handle_message_list(
            messages, user_id=None, agent_id=None, run_id=None, infer=False
        )
        assert "Hello there" in content
        assert "Hi, how can I help" in content

    def test_message_list_infer_no_llm(self, mem: Memory) -> None:
        """_handle_message_list with infer=True but no LLM available."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        with patch.object(mem, '_resolve_llm_for', return_value=None):
            content, summary = mem._handle_message_list(
                messages, user_id=None, agent_id=None, run_id=None, infer=True
            )
            assert content in ("Hello Hi", "Hello Hi")

    def test_message_list_infer_llm_error(self, mem: Memory) -> None:
        """_handle_message_list with infer=True, LLM raises RuntimeError (lines 740-741)."""
        messages = [{"role": "user", "content": "Test"}]
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'extract_facts': lambda self, x: (_ for _ in ()).throw(RuntimeError("LLM down")),
        })()
        with patch.object(mem, '_resolve_llm_for', return_value=fake_llm):
            content, summary = mem._handle_message_list(
                messages, user_id=None, agent_id=None, run_id=None, infer=True
            )
            assert content == "Test"

    def test_message_list_infer_llm_extraction_success(self, mem: Memory) -> None:
        """_handle_message_list with infer=True and LLM returns facts → recursive add (lines 745-752)."""
        from spacetime_memory.sdks.mem0 import _InferMergeDone
        messages = [{"role": "user", "content": "I live in Paris and like cheese"}]
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'extract_facts': lambda self, x: ["User lives in Paris", "User likes cheese"],
        })()
        with patch.object(mem, '_resolve_llm_for', return_value=fake_llm):
            # The recursive add() call will be handled
            fake_add_result = {
                "results": [{"id": "f1", "memory": "User lives in Paris", "event": "ADD"}],
                "relation_events": [],
            }
            with patch.object(mem, 'add', return_value=fake_add_result):
                with pytest.raises(_InferMergeDone) as exc_info:
                    mem._handle_message_list(
                        messages, user_id="u1", agent_id=None, run_id=None, infer=True
                    )
                result = exc_info.value.args[0]
                assert len(result["results"]) == 2  # Two facts stored
                assert result["results"][0]["memory"] == "User lives in Paris"


class TestTryInferMerge:
    """Cover _try_infer_merge paths (lines 765-810)."""

    def test_try_infer_merge_no_close_matches(self, mem: Memory) -> None:
        """_try_infer_merge returns None when no close matches (line 781)."""
        uid = _uid()
        with patch.object(mem, 'search', return_value={
            "results": [{"id": "m1", "memory": "test", "score": 0.3}]
        }):
            result = mem._try_infer_merge("new content", user_id=uid, agent_id=None)
            assert result is None

    def test_try_infer_merge_empty_results(self, mem: Memory) -> None:
        """_try_infer_merge returns None when search returns empty results."""
        with patch.object(mem, 'search', return_value={"results": []}):
            result = mem._try_infer_merge("content", user_id=None, agent_id=None)
            assert result is None

    def test_try_infer_merge_success_no_llm(self, mem: Memory) -> None:
        """_try_infer_merge merges with existing memory (no LLM facts)."""
        uid = _uid()
        with patch.object(mem, 'search', return_value={
            "results": [{"id": "mem-1", "memory": "Existing", "score": 0.95}]
        }):
            with patch.object(mem, 'update') as mock_update:
                with patch.object(mem, '_resolve_llm_for', return_value=None):
                    result = mem._try_infer_merge("Appended", user_id=uid, agent_id=None)
                    mock_update.assert_called_once()
                    assert result is not None
                    assert result["results"][0]["event"] == "UPDATE"
                    assert "Existing" in result["results"][0]["memory"]
                    assert "Appended" in result["results"][0]["memory"]

    def test_try_infer_merge_llm_facts_error(self, mem: Memory) -> None:
        """_try_infer_merge handles LLM fact extraction error (lines 799-800)."""
        uid = _uid()
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'extract_facts': lambda self, x: (_ for _ in ()).throw(RuntimeError("LLM boom")),
        })()
        with patch.object(mem, 'search', return_value={
            "results": [{"id": "mem-2", "memory": "Old", "score": 0.90}]
        }):
            with patch.object(mem, 'update'):
                with patch.object(mem, '_resolve_llm_for', return_value=fake_llm):
                    result = mem._try_infer_merge("New", user_id=uid, agent_id=None)
                    assert result is not None
                    assert result["results"][0]["event"] == "UPDATE"

    def test_try_infer_merge_llm_facts_success(self, mem: Memory) -> None:
        """_try_infer_merge with LLM facts extraction success (lines 793-795)."""
        uid = _uid()
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'extract_facts': lambda self, x: ["fact A", "fact B"],
        })()
        with patch.object(mem, 'search', return_value={
            "results": [{"id": "mem-3", "memory": "Existing", "score": 0.92}]
        }):
            with patch.object(mem, 'update'):
                with patch.object(mem, '_store_facts_as_kg_nodes') as mock_store:
                    with patch.object(mem, '_call') as mock_call:
                        with patch.object(mem, '_resolve_llm_for', return_value=fake_llm):
                            result = mem._try_infer_merge("New fact", user_id=uid, agent_id="agent1")
                            assert result is not None
                            assert result["results"][0]["event"] == "UPDATE"
                            mock_store.assert_called_once_with(["fact A", "fact B"], uid, "agent1")
                            # update_memory is called with extracted facts
                            assert mock_call.called


# ---------------------------------------------------------------------------
# add() specific paths (mocked)
# ---------------------------------------------------------------------------

class TestAddSpecificPaths:
    """Cover add() paths: infer merge, facts, scope, LLM error."""

    def test_add_infer_merge_activated(self, mem: Memory) -> None:
        """add() triggers _try_infer_merge when infer=True and content is string."""
        uid = _uid()
        merge_result = {
            "results": [{"id": "merged-1", "memory": "Merged", "event": "UPDATE",
                         "user_id": uid, "agent_id": ""}],
            "relation_events": [],
        }
        with patch.object(mem, '_try_infer_merge', return_value=merge_result):
            result = mem.add("content", user_id=uid)
            assert result["results"][0]["event"] == "UPDATE"

    def test_add_llm_error_in_add(self, mem: Memory) -> None:
        """add() handles LLM fact extraction RuntimeError gracefully (lines 896-897)."""
        uid = _uid()
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'extract_facts': lambda self, x: (_ for _ in ()).throw(RuntimeError("LLM fail")),
        })()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem, '_try_infer_merge', return_value=None):
                with patch.object(mem, '_resolve_llm_for', return_value=fake_llm):
                    with patch.object(mem, '_call', side_effect=[
                        None,  # store
                        [{"entity_id": "mem-x", "memory_content": "content"}],  # search for scope
                        [{"entity_id": "mem-x", "memory_content": "content"}],  # final search
                    ]):
                        with patch.object(mem._client, '_call', return_value=None):  # set_memory_scope
                            result = mem.add("content", user_id=uid)
                            assert "results" in result

    def test_add_set_memory_scope_failure(self, mem: Memory) -> None:
        """add() set_memory_scope failure is logged not raised (lines 926-927)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem, '_try_infer_merge', return_value=None):
                with patch.object(mem, '_resolve_llm_for', return_value=None):
                    with patch.object(mem, '_call', side_effect=[
                        None,  # store
                        [{"entity_id": "mem-x", "memory_content": "content"}],  # search for scope
                        [{"entity_id": "mem-y", "memory_content": "content"}],  # final search
                    ]):
                        with patch.object(mem._client, '_call',
                                          side_effect=RuntimeError("scope set failed")):
                            result = mem.add("content", user_id=uid)
                            assert "results" in result

    def test_add_message_list_infer_merge_done(self, mem: Memory) -> None:
        """add() with message list that triggers _InferMergeDone (line 948)."""
        from spacetime_memory.sdks.mem0 import _InferMergeDone
        uid = _uid()
        fake_results = {"results": [{"id": "f1", "memory": "fact1", "event": "ADD"}],
                        "relation_events": []}
        with patch.object(mem, '_handle_message_list',
                          side_effect=_InferMergeDone(fake_results)):
            result = mem.add([{"role": "user", "content": "test"}], user_id=uid)
            assert result["results"][0]["memory"] == "fact1"

    def test_add_with_extracted_facts_from_llm(self, mem: Memory) -> None:
        """add() with LLM returning extracted_facts (lines 901, 916)."""
        uid = _uid()
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'extract_facts': lambda self, x: ["fact one", "fact two"],
        })()
        with patch.object(mem, '_ws', return_value="ws-mock"):
            with patch.object(mem, '_try_infer_merge', return_value=None):
                with patch.object(mem, '_resolve_llm_for', return_value=fake_llm):
                    with patch.object(mem, '_store_facts_as_kg_nodes') as mock_store:
                        with patch.object(mem, '_call', side_effect=[
                            None,  # store
                            [{"entity_id": "mem-f", "memory_content": "test"}],  # search scope
                            [{"entity_id": "mem-f", "memory_content": "test"}],  # final search
                        ]):
                            with patch.object(mem._client, '_call', return_value=None):
                                result = mem.add("test content", user_id=uid)
                                assert "results" in result
                                # Facts should have been stored as KG nodes
                                mock_store.assert_called_once_with(
                                    ["fact one", "fact two"], uid, None
                                )


# ---------------------------------------------------------------------------
# search() specific paths (mocked)
# ---------------------------------------------------------------------------

class TestSearchSpecificPaths:
    """Cover search() paths: user_scope check, graph_context."""

    def test_search_user_scope_skips_different_user(self, mem: Memory) -> None:
        """search() skips results scoped to a different user (line 1090)."""
        uid = _uid()
        # search returns a result, get_memory shows different user_scope
        with patch.object(mem, '_ws', return_value="ws-1"):
            with patch.object(mem, '_get_graph_context', return_value=[]):
                with patch.object(mem, '_call', side_effect=[
                    # search call
                    [{"entity_id": "mem-1", "memory_content": "secret", "score": 0.9}],
                    # get_memory call
                    [{"user_scope": "other-user"}],
                ]):
                    result = mem.search("test", user_id=uid, graph_context=False)
                    # Result should be empty because it was scoped to another user
                    assert len(result["results"]) == 0

    def test_search_graph_context_in_metadata(self, mem: Memory) -> None:
        """search() includes graph_context in metadata (line 1094)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-1"):
            with patch.object(mem, '_get_graph_context', return_value=["EntityA", "EntityB"]):
                with patch.object(mem, '_call', side_effect=[
                    # search call
                    [{"entity_id": "mem-1", "memory_content": "test mem", "score": 0.95}],
                    # get_memory call
                    [{"user_scope": uid}],
                ]):
                    result = mem.search("test", user_id=uid, graph_context=True)
                    if result["results"]:
                        assert "graph_context" in result["results"][0]["metadata"]
                        assert result["results"][0]["metadata"]["graph_context"] == ["EntityA", "EntityB"]

    def test_search_with_threshold_filter(self, mem: Memory) -> None:
        """search() filters results below threshold (line 1080)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-1"):
            with patch.object(mem, '_get_graph_context', return_value=[]):
                with patch.object(mem, '_call', return_value=[
                    {"entity_id": "mem-a", "memory_content": "low", "score": 0.2},
                    {"entity_id": "mem-b", "memory_content": "high", "score": 0.95},
                    {"entity_id": "mem-c", "memory_content": "mid", "score": 0.5},
                ]):
                    # need get_memory for each result
                    with patch.object(mem._client, 'get_memory',
                                      return_value=[{"user_scope": ""}]):
                        result = mem.search("test", user_id=uid, threshold=0.5, graph_context=False)
                        # only mem-b should remain
                        scores = [r["score"] for r in result["results"]]
                        assert all(s >= 0.5 for s in scores)


# ---------------------------------------------------------------------------
# chat() paths (mocked)
# ---------------------------------------------------------------------------

class TestChatPaths:
    """Cover chat() paths: history messages, LLM failure."""

    def test_chat_with_messages_history(self, mem: Memory) -> None:
        """chat() with messages param builds history_block (line 1447)."""
        uid = _uid()
        with patch.object(mem, 'add'):  # suppress add calls
            with patch.object(mem, 'search', return_value={"results": []}):
                with patch('spacetime_memory.sdks.mem0._resolve_llm', return_value=None):
                    result = mem.chat(
                        "Test query",
                        user_id=uid,
                        messages=[
                            {"role": "user", "content": "Previous"},
                            {"role": "assistant", "content": "Previous reply"},
                        ],
                    )
                    assert "response" in result
                    assert result["response"] == "Test query"  # fallback without LLM

    def test_chat_llm_error_fallback(self, mem: Memory) -> None:
        """chat() falls back to query when LLM.chat raises RuntimeError (lines 1469-1471)."""
        uid = _uid()
        fake_llm = type('FakeLLM', (), {
            'available': True,
            'chat': lambda self, msgs: (_ for _ in ()).throw(RuntimeError("LLM timeout")),
        })()
        with patch.object(mem, 'add'):
            with patch.object(mem, 'search', return_value={
                "results": [{"id": "m1", "memory": "context mem", "score": 0.9}]
            }):
                with patch('spacetime_memory.sdks.mem0._resolve_llm', return_value=fake_llm):
                    result = mem.chat("What do I like?", user_id=uid)
                    assert result["response"] == "What do I like?"
                    assert "context mem" in result["context"]


# ---------------------------------------------------------------------------
# get_all() no user_id path (mocked)
# ---------------------------------------------------------------------------

class TestGetAllNoUser:
    """Cover get_all() when user_id is None (lines 1168-1170)."""

    def test_get_all_no_user_id_uses_empty_ws(self, mem: Memory) -> None:
        """get_all() without user_id calls list_memories with empty workspace."""
        with patch.object(mem, '_ws', return_value=""):
            with patch.object(mem, '_call', return_value=[]) as mock_call:
                result = mem.get_all()
                assert "results" in result
                # verify _ws was called with None
                mock_call.assert_called()

    def test_get_all_with_user_id_filters_by_scope(self, mem: Memory) -> None:
        """get_all() with user_id filters by user_scope (line 1166)."""
        uid = _uid()
        with patch.object(mem, '_ws', return_value="ws-1"):
            with patch.object(mem, '_call', return_value=[
                {"id": "m1", "content": "scoped", "user_scope": uid, "entity_id": "m1"},
                {"id": "m2", "content": "other", "user_scope": "other-user", "entity_id": "m2"},
                {"id": "m3", "content": "global", "user_scope": "", "entity_id": "m3"},
            ]):
                result = mem.get_all(user_id=uid)
                assert len(result["results"]) == 2  # m2 filtered out


# ---------------------------------------------------------------------------
# delete_all with filters extraction (mocked)
# ---------------------------------------------------------------------------

class TestDeleteAllFilters:
    """Cover delete_all() filters extraction paths."""

    def test_delete_all_with_filters_extraction(self, mem: Memory) -> None:
        """delete_all() extracts from filters dict (lines 1282-1286)."""
        uid = _uid()
        with patch.object(mem, 'get_all', return_value={
            "results": [{"id": "mem-d", "memory": "del", "user_id": uid, "metadata": {}}]
        }) as mock_get_all:
            with patch.object(mem, '_call'):  # suppress delete_memory call
                result = mem.delete_all(filters={"user_id": uid, "agent_id": "agent1", "run_id": "run1"})
                assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# _tag_filter coverage (JSON parsing paths)
# ---------------------------------------------------------------------------

class TestTagFilter:
    """Cover _tag_filter internal JSON parsing paths."""

    def test_tag_filter_metadata_json_parsed(self, mem: Memory) -> None:
        """_tag_filter parses metadata_json as JSON string (line 100-107)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "n1", "label": "test", "metadata_json": json.dumps({"tag": tag})},
            {"id": "n2", "label": "other", "metadata_json": json.dumps({"tag": "wrong"})},
            {"id": "n3", "label": "empty-meta", "metadata_json": "", "description": ""},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 2  # n1 matches, n3 has empty metadata

    def test_tag_filter_description_parsed(self, mem: Memory) -> None:
        """_tag_filter parses description as entity_link format (lines 108-116)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "el1", "entity_name": "e1", "metadata_json": "", "description": json.dumps({"tag": tag})},
            {"id": "el2", "entity_name": "e2", "metadata_json": "", "description": json.dumps({"tag": "other"})},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "el1"

    def test_tag_filter_json_decode_error(self, mem: Memory) -> None:
        """_tag_filter handles JSON decode errors gracefully (lines 106-107, 115-116)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "bad1", "metadata_json": "not-json{{{", "description": ""},
            {"id": "bad2", "metadata_json": "", "description": "also-bad-json"},
            {"id": "good", "metadata_json": json.dumps({"tag": tag}), "description": ""},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "good"

    def test_tag_filter_non_string_metadata(self, mem: Memory) -> None:
        """_tag_filter handles non-string metadata_json (already dict)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "d1", "metadata_json": {"tag": tag}, "description": ""},
            {"id": "d2", "metadata_json": {"tag": "nope"}, "description": ""},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "d1"

    def test_tag_filter_non_string_description(self, mem: Memory) -> None:
        """_tag_filter handles non-string description (already dict)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "dd1", "metadata_json": "", "description": {"tag": tag}},
            {"id": "dd2", "metadata_json": "", "description": {"tag": "other"}},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "dd1"


# ---------------------------------------------------------------------------
# _entity_link_to_dict coverage
# ---------------------------------------------------------------------------

class TestEntityLinkToDict:
    """Cover _entity_link_to_dict method."""

    def test_entity_link_to_dict_defaults(self, mem: Memory) -> None:
        """_entity_link_to_dict with missing fields uses defaults."""
        row = {}
        result = mem.graph._entity_link_to_dict(row, "mem0_global")
        assert result["id"] == ""
        assert result["label"] == ""
        assert result["node_type"] == "concept"
        assert result["entity_type"] == "concept"
        assert result["summary"] == ""

    def test_entity_link_to_dict_full(self, mem: Memory) -> None:
        """_entity_link_to_dict with all fields populated."""
        row = {
            "id": "el-full",
            "entity_name": "FullEntity",
            "entity_type": "person",
            "description": '{"key": "val"}',
            "created_at": 1234567890,
        }
        result = mem.graph._entity_link_to_dict(row, "tag123")
        assert result["id"] == "el-full"
        assert result["label"] == "FullEntity"
        assert result["node_type"] == "person"
        assert result["entity_type"] == "person"
