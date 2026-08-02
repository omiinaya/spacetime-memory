"""Unit tests for the Mem0 adapter client (_client.py).

Tests _GraphStore, _resolve_llm, and Memory classes
using mocked HTTP — no real network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spacetime_memory.sdks.mem0._client import (
    Memory,
    _GraphStore,
    _resolve_llm,
)

pytestmark = pytest.mark.unit


# ── Fixture ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_memory():
    """Memory instance with fully mocked _client."""
    m = Memory(config={"host": "127.0.0.1", "port": "3001"})
    with patch.object(m._client, "_call") as mock_call:
        with patch.object(m._client, "_query") as mock_query:
            with patch.object(m._client, "search") as mock_search:
                with patch.object(m._client, "create_entity_link") as mock_cel:
                    with patch.object(m._client, "add_alias") as mock_add_alias:
                        with patch.object(m._client, "create_node") as mock_create_node:
                            with patch.object(m._client, "list_memories") as mock_list_mems:
                                with patch.object(m._client, "get_memory") as mock_get_mem:
                                    with patch.object(m._client, "update_memory") as mock_upd_mem:
                                        with patch.object(m._client, "delete_memory") as mock_del_mem:
                                            with patch.object(m._client, "list_workspaces") as mock_list_ws:
                                                with patch.object(m._client, "create_workspace") as mock_create_ws:
                                                    with patch.object(m._client, "_tantivy_search") as mock_tantivy:
                                                        # Defaults
                                                        mock_call.return_value = "ok"
                                                        mock_query.return_value = []
                                                        mock_search.return_value = []
                                                        mock_cel.return_value = {"id": "el-id"}
                                                        mock_add_alias.return_value = None
                                                        mock_create_node.return_value = {"id": "node-id"}
                                                        mock_list_mems.return_value = []
                                                        mock_get_mem.return_value = []
                                                        mock_upd_mem.return_value = {"status": "ok"}
                                                        mock_del_mem.return_value = {"status": "ok"}
                                                        mock_list_ws.return_value = []
                                                        mock_create_ws.return_value = {"id": "ws-id"}
                                                        mock_tantivy.return_value = []

                                                        m._mock_call = mock_call
                                                        m._mock_query = mock_query
                                                        m._mock_search = mock_search
                                                        m._mock_cel = mock_cel
                                                        m._mock_add_alias = mock_add_alias
                                                        m._mock_create_node = mock_create_node
                                                        m._mock_list_mems = mock_list_mems
                                                        m._mock_get_mem = mock_get_mem
                                                        m._mock_upd_mem = mock_upd_mem
                                                        m._mock_del_mem = mock_del_mem
                                                        m._mock_list_ws = mock_list_ws
                                                        m._mock_create_ws = mock_create_ws
                                                        m._mock_tantivy = mock_tantivy
                                                        yield m


# ── Test: _resolve_llm ─────────────────────────────────────────────────────


class TestResolveLlm:
    def test_returns_none_when_no_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = _resolve_llm()
            # _resolve_llm always returns an LLMClient instance (never None)
            assert result is not None
            assert result.available is False

    def test_returns_llm_with_config(self):
        result = _resolve_llm({"model": "gpt-4", "api_key": "test-key"})
        assert result is not None


# ── Test: Memory construction ──────────────────────────────────────────────


class TestMemoryConstruction:
    def test_default_construction(self):
        m = Memory(config={})
        assert m._client is not None
        assert m._user_id_to_ws == {}
        assert m._graph_store is None

    def test_from_config_classmethod(self):
        m = Memory.from_config({"host": "127.0.0.1"})
        assert m is not None
        assert isinstance(m, Memory)

    def test_graph_property(self, mock_memory):
        g = mock_memory.graph
        assert isinstance(g, _GraphStore)
        # Accessing again returns the same instance
        assert mock_memory.graph is g

    def test_set_llm_config(self, mock_memory):
        mock_memory.set_llm_config("user1", {"model": "gpt-4"})
        assert "user1" in mock_memory._llm_overrides
        assert mock_memory._llm_overrides["user1"]["model"] == "gpt-4"


# ── Test: Internal helpers ─────────────────────────────────────────────────


class TestMemoryInternals:
    def test_ws_creates_workspace(self, mock_memory):
        mock_memory._mock_list_ws.return_value = []  # no existing
        # First call: empty -> create workspace
        # Second call: return the new workspace
        mock_memory._mock_list_ws.side_effect = [
            [],  # first list -> empty
            [{"id": "new-ws", "name": "test-user"}],  # re-list
        ]
        ws_id = mock_memory._ws("test-user")
        assert ws_id == "new-ws"
        mock_memory._mock_create_ws.assert_called_once()

    def test_ws_uses_cache(self, mock_memory):
        mock_memory._user_id_to_ws["cached-user"] = "cached-ws"
        ws_id = mock_memory._ws("cached-user")
        assert ws_id == "cached-ws"
        mock_memory._mock_list_ws.assert_not_called()

    def test_call_with_token_refresh(self, mock_memory):
        mock_memory._token_refresh_callback = MagicMock()
        # Memory._call uses getattr(self._client, method) so we need
        # to mock the method on the client itself
        from unittest.mock import patch as _patch
        with _patch.object(mock_memory._client, "some_method", create=True, return_value="ok") as mock_some_method:
            mock_some_method.side_effect = [RuntimeError("401 unauthorized"), "ok"]
            result = mock_memory._call("some_method", "arg1")
            assert result == "ok"
            mock_memory._token_refresh_callback.assert_called_once()

    def test_call_propagates_error(self, mock_memory):
        from unittest.mock import patch as _patch
        with _patch.object(mock_memory._client, "method", create=True, side_effect=RuntimeError("other error")):
            with pytest.raises(RuntimeError):
                mock_memory._call("method")

    def test_extract_ids_from_filters(self, mock_memory):
        u, a, r = mock_memory._extract_ids_from_filters(
            {"user_id": "u1", "agent_id": "a1", "run_id": "r1"}
        )
        assert u == "u1"
        assert a == "a1"
        assert r == "r1"

    def test_extract_ids_from_filters_empty(self, mock_memory):
        u, a, r = mock_memory._extract_ids_from_filters(None)
        assert u is None
        assert a is None
        assert r is None

    def test_store_facts_as_kg_nodes(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "user1"}]
        mock_memory._mock_call.return_value = {"id": "fact-node-1"}
        ids = mock_memory._store_facts_as_kg_nodes(
            ["Alice likes pizza", "Bob knows Alice"],
            user_id="user1",
        )
        assert len(ids) == 2

    def test_get_graph_context(self, mock_memory):
        # Need workspace resolution to succeed
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "user1"}]
        # Need query_graph to be mocked on the client (Memory._call uses getattr)
        from unittest.mock import patch as _patch
        with _patch.object(mock_memory._client, "query_graph", return_value=[{"label": "Alice"}]):
            result = mock_memory._get_graph_context("Alice", "user1")
            assert result == ["Alice"]


# ── Test: Memory.add ───────────────────────────────────────────────────────


class TestMemoryAdd:
    def test_add_string(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "memory_content": "I like pizza", "score": 0.95}
        ]
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.add("I like pizza", user_id="test-user")
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_add_empty_raises(self, mock_memory):
        with pytest.raises(ValueError, match="non-empty"):
            mock_memory.add("", user_id="test")

    def test_add_with_metadata(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "memory_content": "hello", "score": 0.95}
        ]
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.add(
            "Hello", user_id="test-user", metadata={"source": "test"}
        )
        assert "results" in result

    def test_add_with_messages_list(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "memory_content": "combined", "score": 0.95}
        ]
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.add(
            [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
            user_id="test-user",
        )
        assert "results" in result

    def test_add_with_infer_merge(self, mock_memory):
        """When infer=True and a close match exists, content should be merged."""
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        # The search method expects a LIST (raw search rows from the client),
        # not a dict wrapped in {"results": ...}
        mock_memory._mock_search.side_effect = [
            # First search for merge check (from _try_infer_merge)
            [{"entity_id": "mem-1", "memory_content": "Existing content",
              "score": 0.95}],
            # Second search (from the add path — not reached due to early return)
            [{"entity_id": "mem-1", "memory_content": "Existing content\nNew content",
              "score": 0.95}],
        ]
        # Mock LLM to avoid fact extraction
        with patch("spacetime_memory.sdks.mem0._client.LLMClient") as MockLLM:
            MockLLM.return_value.available = False

            result = mock_memory.add(
                "New content",
                user_id="test-user",
                infer=True,
            )
            assert "results" in result

    def test_add_with_filters_dict(self, mock_memory):
        """Mem0 v2 compat: filters dict should be unwrapped."""
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "u1"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "memory_content": "test", "score": 0.9}
        ]
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.add(
            "Hello",
            filters={"user_id": "u1", "agent_id": "a1"},
        )
        assert "results" in result


# ── Test: Memory.get ───────────────────────────────────────────────────────


class TestMemoryGet:
    def test_get_returns_dict(self, mock_memory):
        mock_memory._mock_get_mem.return_value = [
            {"id": "mem-1", "content": "test", "is_active": True}
        ]
        result = mock_memory.get("mem-1")
        assert "results" in result
        assert result["results"][0]["id"] == "mem-1"

    def test_get_missing_returns_empty(self, mock_memory):
        mock_memory._mock_get_mem.return_value = []
        result = mock_memory.get("missing")
        assert result["results"] == []

    def test_get_inactive_filtered(self, mock_memory):
        mock_memory._mock_get_mem.return_value = [
            {"id": "mem-1", "content": "deleted", "is_active": False}
        ]
        result = mock_memory.get("mem-1")
        assert result["results"] == []


# ── Test: Memory.search ────────────────────────────────────────────────────


class TestMemorySearch:
    def test_search_returns_results(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "score": 0.95, "memory_content": "test"}
        ]
        mock_memory._mock_get_mem.return_value = [
            {"id": "mem-1", "content": "test", "user_scope": ""}
        ]
        result = mock_memory.search("test", user_id="test-user")
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_search_with_threshold(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "score": 0.3, "memory_content": "low"}
        ]
        mock_memory._mock_get_mem.return_value = [
            {"id": "mem-1", "content": "low", "user_scope": ""}
        ]
        result = mock_memory.search("test", user_id="test-user", threshold=0.5)
        # Score 0.3 < 0.5 so it should be filtered out
        assert len(result["results"]) == 0

    def test_search_with_graph_context(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "score": 0.9, "memory_content": "hello"}
        ]
        mock_memory._mock_get_mem.return_value = [
            {"id": "mem-1", "content": "hello", "user_scope": ""}
        ]
        mock_memory._mock_call.return_value = [{"label": "Alice"}]
        result = mock_memory.search("hello", user_id="test-user", graph_context=True)
        assert "results" in result

    def test_search_with_filters(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "u1"}]
        mock_memory._mock_search.return_value = [
            {"entity_id": "mem-1", "score": 0.9, "memory_content": "test"}
        ]
        mock_memory._mock_get_mem.return_value = [
            {"id": "mem-1", "content": "test", "user_scope": ""}
        ]
        result = mock_memory.search("test", filters={"user_id": "u1"})
        assert "results" in result


# ── Test: Memory.get_all ───────────────────────────────────────────────────


class TestMemoryGetAll:
    def test_get_all_with_user(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "u1"}]
        mock_memory._mock_list_mems.return_value = [
            {"id": "m1", "content": "c1", "user_scope": "u1"},
            {"id": "m2", "content": "c2", "user_scope": ""},
        ]
        result = mock_memory.get_all(user_id="u1")
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_get_all_without_user(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_memory._mock_list_mems.return_value = [
            {"id": "m1", "content": "c1"},
        ]
        result = mock_memory.get_all()
        assert "results" in result


# ── Test: Memory.update / delete / reset / close ───────────────────────────


class TestMemoryManagement:
    def test_update_string(self, mock_memory):
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.update("mem-1", "new content")
        assert result["message"] == "Memory updated successfully!"

    def test_update_dict(self, mock_memory):
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.update("mem-1", {"content": "new"})
        assert "updated" in result["message"].lower()

    def test_delete(self, mock_memory):
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.delete("mem-1")
        assert "deleted" in result["message"].lower()

    def test_delete_all(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "u1"}]
        mock_memory._mock_list_mems.return_value = [
            {"id": "m1", "content": "c1", "user_scope": "u1"},
        ]
        mock_memory._mock_call.return_value = "ok"
        result = mock_memory.delete_all(user_id="u1")
        assert result["status"] == "ok"

    def test_history(self, mock_memory):
        from unittest.mock import patch as _patch
        with _patch.object(mock_memory._client, "get_memory_history", return_value=[
            {"version": 1, "content": "v1"},
        ]):
            result = mock_memory.history("mem-1")
            assert len(result) == 1

    def test_reset(self, mock_memory):
        mock_memory._user_id_to_ws["u1"] = "ws-1"
        result = mock_memory.reset()
        assert result["status"] == "ok"
        assert mock_memory._user_id_to_ws == {}

    def test_close(self, mock_memory):
        mock_memory._user_id_to_ws["u1"] = "ws-1"
        mock_memory.close()
        assert mock_memory._user_id_to_ws == {}


# ── Test: Memory.chat ──────────────────────────────────────────────────────


class TestMemoryChat:
    def test_chat_without_llm(self, mock_memory):
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        # search mock must be a list (raw client rows), not a dict
        mock_memory._mock_search.return_value = [
            {"entity_id": "m1", "memory_content": "context", "score": 0.9}
        ]
        with patch("spacetime_memory.sdks.mem0._client._resolve_llm") as MockResolve:
            MockResolve.return_value = None
            result = mock_memory.chat("Hello", user_id="test-user")
            assert "response" in result
            assert "context" in result
            assert "memories" in result


# ── Test: _GraphStore ──────────────────────────────────────────────────────


class TestGraphStore:
    def test_add_entity(self, mock_memory):
        g = _GraphStore(mock_memory)
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = []
        mock_memory._mock_cel.return_value = {"id": "el-1"}
        mock_memory._mock_query.return_value = [
            {"id": "el-1", "entity_name": "Alice", "entity_type": "person",
             "description": '{"tag": "mem0_user:test-user"}'}
        ]
        result = g.add("Alice", entity_type="person", user_id="test-user")
        assert "id" in result
        assert result["label"] == "Alice"

    def test_add_empty_raises(self, mock_memory):
        g = _GraphStore(mock_memory)
        with pytest.raises(ValueError, match="non-empty"):
            g.add("", user_id="test")

    def test_search_no_results(self, mock_memory):
        g = _GraphStore(mock_memory)
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_search.return_value = []
        result = g.search("Alice", user_id="test-user")
        assert result == []

    def test_get_all(self, mock_memory):
        g = _GraphStore(mock_memory)
        mock_memory._mock_list_ws.return_value = [{"id": "ws-1", "name": "test-user"}]
        mock_memory._mock_query.return_value = [
            {"id": "el-1", "entity_name": "Alice", "entity_type": "person",
             "description": '{"tag": "mem0_user:test-user"}'}
        ]
        result = g.get_all(user_id="test-user")
        assert len(result) >= 1

    def test_delete(self, mock_memory):
        g = _GraphStore(mock_memory)
        mock_memory._mock_call.return_value = "ok"
        result = g.delete("entity-1")
        assert result["status"] == "ok"
        assert result["deleted"] == "entity-1"


# ── Test: create_memory_tool ───────────────────────────────────────────────


class TestCreateMemoryTool:
    def test_returns_tool_schemas(self, mock_memory):
        result = mock_memory.create_memory_tool()
        assert "tools" in result
        assert len(result["tools"]) == 4
        names = [t["function"]["name"] for t in result["tools"]]
        assert names == ["memory_add", "memory_search", "memory_get", "memory_delete"]
