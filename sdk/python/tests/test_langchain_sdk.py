"""Unit tests for the LangChain/LangGraph SDK adapter (sdks/langchain.py).

Mocks the underlying Client to test StmemMemoryStore, StmemStore,
StmemChatMessageHistory, and helper functions without a real SpacetimeDB.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spacetime_memory.sdks.langchain import (
    StmemChatMessageHistory,
    StmemMemoryStore,
    StmemStore,
    _apply_filter,
    _caller_tag,
    _esc,
    _hash_hex,
    _json_parse,
    _memory_to_dict,
    _to_dt,
)


# =====================================================================
# Helper functions
# =====================================================================
class TestHelpers:
    def test_esc(self):
        assert _esc("hello") == "hello"
        assert _esc("it's") == "it''s"
        assert _esc("") == ""

    def test_hash_hex(self):
        h = _hash_hex("test")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_to_dt_zero(self):
        # langgraph's SearchItem calls datetime.fromisoformat(created_at),
        # so an absent timestamp must be a parseable epoch, not "".
        assert _to_dt(0) == "1970-01-01T00:00:00+00:00"

    def test_to_dt_normal(self):
        result = _to_dt(1719000000000000)
        assert isinstance(result, str)
        assert "T" in result or result == ""

    def test_json_parse_dict(self):
        d = {"a": 1}
        assert _json_parse(d) is d

    def test_json_parse_string(self):
        assert _json_parse('{"a": 1}') == {"a": 1}

    def test_json_parse_empty(self):
        assert _json_parse("") == {}
        assert _json_parse("{}") == {}

    def test_json_parse_invalid(self):
        assert _json_parse("{bad") == {}

    def test_json_parse_int(self):
        assert _json_parse(42) == {}

    def test_memory_to_dict(self):
        row = {
            "content": "test content",
            "summary": "test summary",
            "memory_type": "memory",
            "entities_json": '{"source": "test"}',
        }
        d = _memory_to_dict(row)
        # put() persists the FULL original value in entities_json → get()
        # round-trips it verbatim (LangGraph BaseStore semantics).
        assert d == {"source": "test"}

    def test_memory_to_dict_legacy_row(self):
        # Rows written before put() stored the full value (empty entities_json)
        # fall back to the content/summary/memory_type envelope.
        row = {
            "content": "test content",
            "summary": "test summary",
            "memory_type": "memory",
            "entities_json": "{}",
        }
        d = _memory_to_dict(row)
        assert d["content"] == "test content"
        assert d["summary"] == "test summary"
        assert d["memory_type"] == "memory"

    def test_apply_filter_empty(self):
        rows = [{"content": "test", "entities_json": "{}"}]
        result = _apply_filter(rows, {})
        assert result == rows

    def test_apply_filter_match(self):
        rows = [{"entities_json": '{"role": "admin"}'}, {"entities_json": '{"role": "user"}'}]
        result = _apply_filter(rows, {"role": "admin"})
        assert len(result) == 1

    def test_apply_filter_no_match(self):
        rows = [{"entities_json": '{"role": "user"}'}]
        result = _apply_filter(rows, {"role": "admin"})
        assert result == []

    def test_caller_tag_no_token(self):
        mc = MagicMock()
        mc.token = ""
        tag = _caller_tag(mc)
        assert tag == "anon"

    def test_caller_tag_with_token(self):
        mc = MagicMock()
        mc.token = "test-token"
        tag = _caller_tag(mc)
        assert isinstance(tag, str)
        assert len(tag) > 0


# =====================================================================
# StmemMemoryStore
# =====================================================================
class TestStmemMemoryStore:
    def setup_method(self):
        self.store = StmemMemoryStore(config={"workspace_id": "test-ws"})
        self.store._client = MagicMock()

    def test_mget(self):
        self.store._client._query.return_value = [{
            "id": "m1",
            "content": "hello",
            "summary": "",
            "memory_type": "memory",
            "entities_json": "{}",
            "created_at": 1000,
            "updated_at": 1001,
        }]
        results = self.store.mget(["key1"])
        assert len(results) == 1
        assert results[0]["content"] == "hello"

    def test_mget_missing(self):
        self.store._client._query.return_value = []
        results = self.store.mget(["nonexistent"])
        assert results == [None]

    def test_mget_multiple(self):
        self.store._client._query.side_effect = [
            [{"id": "m1", "content": "alpha", "summary": "", "memory_type": "memory",
              "entities_json": "{}", "created_at": 0, "updated_at": 0}],
            [{"id": "m2", "content": "bravo", "summary": "", "memory_type": "memory",
              "entities_json": "{}", "created_at": 0, "updated_at": 0}],
            [],
        ]
        results = self.store.mget(["k1", "k2", "k3"])
        assert results[0]["content"] == "alpha"
        assert results[1]["content"] == "bravo"
        assert results[2] is None

    def test_mset(self):
        self.store._client.store.return_value = None
        self.store.mset([("k1", {"content": "hello"})])
        self.store._client.store.assert_called_once()

    def test_mset_non_dict_value(self):
        self.store._client.store.return_value = None
        self.store.mset([("k1", "plain string")])
        self.store._client.store.assert_called_once()

    def test_mdelete(self):
        self.store._client.delete_memory.return_value = {"status": "ok"}
        self.store.mdelete(["k1"])
        self.store._client.delete_memory.assert_called_once_with("k1")

    def test_yield_keys(self):
        self.store._client._query.return_value = [
            {"id": "m1", "content": "hello"},
            {"id": "m2", "content": "world"},
        ]
        keys = list(self.store.yield_keys())
        assert keys == ["m1", "m2"]

    def test_yield_keys_with_prefix(self):
        self.store._client._query.return_value = [
            {"id": "m1", "content": "hello world"},
            {"id": "m2", "content": "goodbye"},
        ]
        keys = list(self.store.yield_keys(prefix="hello"))
        assert keys == ["m1"]

    def test_yield_keys_query_error(self):
        self.store._client._query.side_effect = RuntimeError("fail")
        keys = list(self.store.yield_keys())
        assert keys == []

    def test_mset_with_metadata(self):
        self.store._client.store.return_value = None
        self.store.mset([("k1", {"content": "test", "metadata": {"source": "test"}})])

    def test_mget_query_error(self):
        self.store._client._query.side_effect = RuntimeError("fail")
        results = self.store.mget(["k1"])
        assert results == [None]


# =====================================================================
# StmemStore (LangGraph BaseStore)
# =====================================================================
class TestStmemStore:
    def setup_method(self):
        self.store = StmemStore(config={"workspace_id": "test-ws"})
        self.store._client = MagicMock()
        self.store._client.token = ""

    def test_get(self):
        self.store._client._query.return_value = [{
            "id": "m1",
            "content": "test content",
            "summary": "",
            "memory_type": "memory",
            "entities_json": "{}",
            "created_at": 1000,
            "updated_at": 1001,
        }]
        item = self.store.get(("ns", "user1"), "prefs")
        assert item is not None
        assert item.key == "prefs"
        assert item.value is not None

    def test_get_nonexistent(self):
        self.store._client._query.return_value = []
        item = self.store.get(("ns",), "no-key")
        assert item is None

    def test_put(self):
        self.store._client.store.return_value = None
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store.put(("testns",), "k1", {"content": "hello"})
        self.store._client.store.assert_called_once()

    def test_put_with_index(self):
        self.store._client.store.return_value = None
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store.put(("testns",), "k1", {"content": "hello"}, index=True)

    def test_put_with_text_key(self):
        self.store._client.store.return_value = None
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store.put(("testns",), "k1", {"text": "hello", "role": "user"})

    def test_delete(self):
        self.store._client._query.return_value = [{"id": "m1"}]
        self.store._client.delete_memory.return_value = {"status": "ok"}
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store.delete(("testns",), "k1")

    def test_search(self):
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store._client.search.return_value = [
            {"entity_id": "m1", "score": 0.9}
        ]
        self.store._client._query.return_value = [{"id": "m1", "content": "result"}]
        results = self.store.search(("testns",), query="test")
        assert isinstance(results, list)

    def test_search_no_query(self):
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store._client._query.return_value = [
            {"id": "m1", "content": "hello", "summary": "", "memory_type": "memory",
             "entities_json": "{}", "created_at": 0, "updated_at": 0}
        ]
        results = self.store.search(("testns",))
        assert isinstance(results, list)

    def test_search_with_filter(self):
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store._client._query.return_value = [
            {"id": "m1", "content": "admin", "summary": "", "memory_type": "memory",
             "entities_json": '{"role": "admin"}', "created_at": 0, "updated_at": 0}
        ]
        results = self.store.search(("testns",), filter={"role": "admin"})
        assert isinstance(results, list)

    def test_search_semantic_error_fallback(self):
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store._client.search.side_effect = RuntimeError("fail")
        self.store._client._query.return_value = [
            {"id": "m1", "content": "fallback", "summary": "", "memory_type": "memory",
             "entities_json": "{}", "created_at": 0, "updated_at": 0}
        ]
        results = self.store.search(("testns",), query="test")
        assert isinstance(results, list)

    def test_list_namespaces(self):
        self.store._client.list_workspaces.return_value = [
            {"id": "ws-1", "name": "users/alice"},
            {"id": "ws-2", "name": "users/bob"},
        ]
        namespaces = self.store.list_namespaces()
        assert len(namespaces) >= 2

    def test_list_namespaces_with_prefix(self):
        self.store._client.list_workspaces.return_value = [
            {"id": "ws-1", "name": "users/alice"},
            {"id": "ws-2", "name": "settings"},
        ]
        namespaces = self.store.list_namespaces(prefix=("users",))
        assert any(ns[0] == "users" for ns in namespaces)

    def test_list_namespaces_empty(self):
        self.store._client.list_workspaces.return_value = []
        namespaces = self.store.list_namespaces()
        assert namespaces == []

    def test_batch_get(self):
        self.store._client._query.return_value = [{"id": "m1", "content": "test"}]
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        from collections import namedtuple
        Op = namedtuple("Op", ["type", "namespace", "key"])
        results = self.store.batch([Op(type="get", namespace=("testns",), key="k1")])
        assert len(results) == 1

    def test_batch_put(self):
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        from collections import namedtuple
        Op = namedtuple("Op", ["type", "namespace", "key", "value"])
        results = self.store.batch([
            Op(type="put", namespace=("testns",), key="k1", value={"content": "hello"})
        ])
        assert len(results) == 1

    def test_batch_search(self):
        self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
        self.store._client._query.return_value = [
            {"id": "m1", "content": "result", "summary": "", "memory_type": "memory",
             "entities_json": "{}", "created_at": 0, "updated_at": 0}
        ]
        from collections import namedtuple
        Op = namedtuple("Op", ["type", "namespace_prefix", "query", "limit"])
        results = self.store.batch([
            Op(type="search", namespace_prefix=("testns",), query="test", limit=5)
        ])
        assert len(results) == 1

    def test_batch_langgraph_ops(self):
        try:
            from langgraph.store.base import GetOp, PutOp, SearchOp
            self.store._client.list_workspaces.return_value = [{"id": "ws-1", "name": "testns"}]
            self.store._client._query.return_value = []
            results = self.store.batch([
                GetOp(namespace=("testns",), key="k1"),
                PutOp(namespace=("testns",), key="k2", value={"content": "hello"}, index=None),
                SearchOp(namespace_prefix=("testns",), query="test", filter=None, limit=10, offset=0),
            ])
            assert len(results) == 3
        except ImportError:
            pytest.skip("langgraph not installed")

    def test_ns_to_ws(self):
        ws = self.store._ns_to_ws(("users", "alice"))
        assert ws == "users/alice"

    def test_ns_to_ws_empty(self):
        ws = self.store._ns_to_ws(())
        assert ws.startswith("langgraph-")


# =====================================================================
# StmemChatMessageHistory
# =====================================================================
class TestStmemChatMessageHistory:
    def setup_method(self):
        self.history = StmemChatMessageHistory(
            session_id="test-session",
            config={},
        )
        self.history._client = MagicMock()

    def test_add_messages(self):
        pytest.importorskip("langchain_core", reason="langchain_core not installed")
        self.history._client.list_workspaces.return_value = [{"id": "ws-1", "name": "chat_history"}]
        from langchain_core.messages import AIMessage, HumanMessage
        self.history.add_messages([
            HumanMessage(content="Hello!"),
            AIMessage(content="Hi there!"),
        ])
        assert True

    def test_messages(self):
        pytest.importorskip("langchain_core", reason="langchain_core not installed")
        self.history._client.list_workspaces.return_value = [{"id": "ws-1", "name": "chat_history"}]
        self.history._client._query.return_value = []
        msgs = self.history.messages
        assert isinstance(msgs, list)

    def test_clear(self):
        self.history._client.list_workspaces.return_value = [{"id": "ws-1", "name": "chat_history"}]
        self.history._client._query.return_value = []
        self.history.clear()
        assert True

    def test_workspace_resolution(self):
        self.history._client.list_workspaces.return_value = [{"id": "ws-1", "name": "chat_history"}]
        ws_id = self.history._resolve_workspace()
        assert ws_id == "ws-1"

    def test_workspace_creates_if_needed(self):
        self.history._client.list_workspaces.side_effect = [
            [],
            [{"id": "ws-new", "name": "chat_history"}],
        ]
        ws_id = self.history._resolve_workspace()
        assert ws_id == "ws-new"
