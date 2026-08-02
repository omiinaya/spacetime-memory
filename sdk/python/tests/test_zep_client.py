"""Unit tests for the Zep adapter sync client (_client.py).

Tests ZepClient, UserClient, _MemoryProxy, _UserProxy,
_GraphClient, _GraphNodeNamespace, _GraphEdgeNamespace,
_GraphEpisodeNamespace, Zep, and helper functions.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spacetime_memory.sdks.zep._client import (
    UserClient,
    Zep,
    ZepClient,
    _GraphClient,
    _GraphEdgeNamespace,
    _GraphEpisodeNamespace,
    _GraphNodeNamespace,
    _json_dumps,
    _json_loads_or,
    _MemoryProxy,
    _now_micros,
    _UserProxy,
)
from spacetime_memory.sdks.zep._models import (
    BadRequestError,
    Fact,
    MemoryMessage,
    MemorySearchResult,
    NotFoundError,
)

pytestmark = pytest.mark.unit


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def mock_zep():
    """ZepClient with fully mocked _client."""
    z = Zep(host="127.0.0.1", port=3001)
    with patch.object(z._client, "_call") as mock_call:
        with patch.object(z._client, "_query") as mock_query:
            with patch.object(z._client, "_sql_param") as mock_sql_param:
                with patch.object(z._client, "store") as mock_store:
                    with patch.object(z._client, "list_memories") as mock_list_mems:
                        with patch.object(z._client, "list_workspaces") as mock_list_ws:
                            with patch.object(z._client, "create_workspace") as mock_create_ws:
                                with patch.object(z._client, "search") as mock_search:
                                    with patch.object(z._client, "delete_memory") as mock_del_mem:
                                        with patch.object(z._client, "update_memory") as mock_upd_mem:
                                            with patch.object(z._client, "create_edge") as mock_create_edge:
                                                with patch.object(z._client, "search_sessions_semantic") as mock_sss:
                                                    with patch.object(z._client, "_call") as mock_inner_call:
                                                        # Defaults
                                                        mock_call.return_value = "ok"
                                                        mock_query.return_value = []
                                                        mock_sql_param.return_value = []
                                                        mock_store.return_value = {"id": "stored"}
                                                        mock_list_mems.return_value = []
                                                        mock_list_ws.return_value = []
                                                        mock_create_ws.return_value = {"id": "ws-1"}
                                                        mock_search.return_value = []
                                                        mock_del_mem.return_value = {"status": "ok"}
                                                        mock_upd_mem.return_value = {"status": "ok"}
                                                        mock_create_edge.return_value = {"id": "edge-1"}
                                                        mock_sss.return_value = []
                                                        mock_inner_call.return_value = "ok"

                                                        z._mock_call = mock_call
                                                        z._mock_query = mock_query
                                                        z._mock_sql_param = mock_sql_param
                                                        z._mock_store = mock_store
                                                        z._mock_list_mems = mock_list_mems
                                                        z._mock_list_ws = mock_list_ws
                                                        z._mock_create_ws = mock_create_ws
                                                        z._mock_search = mock_search
                                                        z._mock_del_mem = mock_del_mem
                                                        z._mock_upd_mem = mock_upd_mem
                                                        z._mock_create_edge = mock_create_edge
                                                        z._mock_sss = mock_sss
                                                        z._mock_inner_call = mock_inner_call
                                                        yield z


# ── Test: Helper functions ─────────────────────────────────────────────────


class TestHelpers:
    def test_json_loads_or_valid(self):
        assert _json_loads_or('{"a": 1}', {}) == {"a": 1}

    def test_json_loads_or_invalid(self):
        assert _json_loads_or("{{{corrupt", {"fallback": True}) == {"fallback": True}

    def test_json_loads_or_empty(self):
        assert _json_loads_or("", "default") == "default"

    def test_json_dumps(self):
        result = _json_dumps({"key": "value"})
        assert isinstance(result, str)

    def test_now_micros(self):
        result = _now_micros()
        assert isinstance(result, int)
        assert result > 1_700_000_000_000_000  # reasonable micros timestamp


# ── Test: ZepClient (via Zep) ──────────────────────────────────────────────


class TestZepClient:
    def test_ensure_workspace_creates(self, mock_zep):
        mock_zep._mock_list_ws.return_value = []
        mock_zep._mock_create_ws.return_value = {"id": "new-id", "name": "s1"}
        # After create, re-list returns the workspace
        mock_zep._mock_list_ws.side_effect = [[], [{"id": "new-id", "name": "s1"}]]
        ws_id = mock_zep._ensure_workspace("s1")
        assert ws_id == "new-id"
        mock_zep._mock_create_ws.assert_called_once_with("s1", "Zep session: s1")

    def test_ensure_workspace_uses_cache(self, mock_zep):
        mock_zep._session_to_ws["cached-session"] = "cached-ws"
        ws_id = mock_zep._ensure_workspace("cached-session")
        assert ws_id == "cached-ws"
        mock_zep._mock_list_ws.assert_not_called()

    def test_ensure_workspace_finds_existing(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [{"id": "existing-ws", "name": "s1"}]
        ws_id = mock_zep._ensure_workspace("s1")
        assert ws_id == "existing-ws"
        mock_zep._mock_create_ws.assert_not_called()

    def test_resolve_session(self, mock_zep):
        mock_zep._session_to_ws["known"] = "ws-known"
        assert mock_zep._resolve_session("known") == "ws-known"

    def test_resolve_session_nonexistent(self, mock_zep):
        mock_zep._mock_list_ws.return_value = []
        assert mock_zep._resolve_session("unknown") is None

    def test_add_memory(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [{"id": "ws-1", "name": "s1"}]
        result = mock_zep.add_memory("s1", [{"role": "user", "content": "Hello"}])
        assert result["status"] == "ok"
        mock_zep._mock_store.assert_called()

    def test_add_memory_with_memory_message_objects(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [{"id": "ws-1", "name": "s1"}]
        mock_zep._mock_list_mems.return_value = []
        msg = MemoryMessage(role="user", content="Hi")
        result = mock_zep.add_memory("s1", [msg])
        assert result["status"] == "ok"

    def test_get_memory(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_list_mems.return_value = [
            {"id": "m1", "content": "Hello", "peer_id": "user",
             "created_at": "2024-01-01", "strength": 0.9},
        ]
        result = mock_zep.get_memory("s1")
        assert "messages" in result
        assert len(result["messages"]) > 0

    def test_get_memory_no_session(self, mock_zep):
        result = mock_zep.get_memory("nonexistent")
        assert result is None

    def test_delete_memory(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_list_mems.return_value = [
            {"id": "m1", "entity_id": "m1"},
        ]
        result = mock_zep.delete_memory("s1")
        assert result["status"] == "ok"
        assert result["deleted"] > 0

    def test_delete_memory_no_session(self, mock_zep):
        result = mock_zep.delete_memory("nonexistent")
        assert result["deleted"] == 0

    def test_search_memory(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_search.return_value = [
            {"score": 0.9, "memory_content": "Hello", "peer_id": "user",
             "content": "Hello"},
        ]
        results = mock_zep.search_memory("s1", "Hello")
        assert len(results) >= 1
        assert isinstance(results[0], MemorySearchResult)

    def test_search_memory_no_session(self, mock_zep):
        results = mock_zep.search_memory("nonexistent", "q")
        assert results == []

    def test_search_memory_with_threshold(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_search.return_value = [
            {"score": 0.3, "memory_content": "low", "peer_id": "user"},
        ]
        results = mock_zep.search_memory("s1", "q", score_threshold=0.5)
        assert len(results) == 0

    def test_add_fact(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [{"id": "ws-1", "name": "s1"}]
        result = mock_zep.add_fact("s1", "test fact")
        assert result["status"] == "ok"
        mock_zep._mock_store.assert_called()

    def test_list_facts(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_list_mems.return_value = [
            {"id": "f1", "content": "fact1", "created_at": "now",
             "entity_id": "f1"},
        ]
        facts = mock_zep.list_facts("s1")
        assert len(facts) >= 1
        assert isinstance(facts[0], Fact)

    def test_list_facts_no_session(self, mock_zep):
        facts = mock_zep.list_facts("nonexistent")
        assert facts == []

    def test_delete_fact(self, mock_zep):
        result = mock_zep.delete_fact("fact-uuid")
        assert result["deleted"] == 1

    def test_delete_fact_with_kwargs(self, mock_zep):
        result = mock_zep.delete_fact("", fact_id="fact-uuid")
        assert result["deleted"] == 1

    def test_get_fact(self, mock_zep):
        mock_zep._mock_query.return_value = [
            {"id": "f1", "content": "fact content", "created_at": "now",
             "entity_id": "f1"},
        ]
        fact = mock_zep.get_fact("f1")
        assert isinstance(fact, Fact)
        assert fact.fact == "fact content"

    def test_get_fact_not_found(self, mock_zep):
        mock_zep._mock_query.return_value = []
        with pytest.raises(NotFoundError):
            mock_zep.get_fact("missing")

    def test_update_memory(self, mock_zep):
        result = mock_zep.update_memory("s1", "m1", [{"role": "user", "content": "Updated"}])
        assert result["status"] == "ok"

    def test_get_session_messages(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_list_mems.return_value = []
        result = mock_zep.get_session_messages("s1")
        assert "messages" in result

    def test_get_session_messages_no_session(self, mock_zep):
        result = mock_zep.get_session_messages("nonexistent")
        assert result == {"messages": [], "cursor": None}

    def test_get_session_message(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_query.return_value = [
            {"id": "msg1", "content": "Hello", "peer_id": "user", "created_at": "now",
             "metadata": {}}
        ]
        result = mock_zep.get_session_message("s1", "msg1")
        assert result["content"] == "Hello"

    def test_get_session_message_not_found(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_query.return_value = []
        with pytest.raises(NotFoundError):
            mock_zep.get_session_message("s1", "missing")

    def test_update_message_metadata(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_query.return_value = [
            {"id": "msg1", "content": "test", "peer_id": "user", "created_at": "now",
             "metadata": {}, "summary": ""}
        ]
        result = mock_zep.update_message_metadata("s1", "msg1", {"pinned": True})
        assert "metadata" in result

    def test_update_message_metadata_no_session(self, mock_zep):
        with pytest.raises(NotFoundError):
            mock_zep.update_message_metadata("nonexistent", "msg1", {})

    def test_list_sessions(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [
            {"name": "s1", "id": "ws-1", "created_at": "now"},
            {"name": "s2", "id": "ws-2", "created_at": "now"},
        ]
        sessions = mock_zep.list_sessions()
        assert len(sessions) == 2

    def test_get_session(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [
            {"name": "s1", "id": "ws-1", "created_at": "now"},
        ]
        session = mock_zep.get_session("s1")
        assert session is not None
        assert session.session_id == "s1"

    def test_get_session_not_found(self, mock_zep):
        mock_zep._mock_list_ws.return_value = []
        with pytest.raises(NotFoundError):
            mock_zep.get_session("missing")

    def test_add_session(self, mock_zep):
        mock_zep._mock_list_ws.return_value = [{"id": "ws-1", "name": "s1"}]
        session = mock_zep.add_session("new-session")
        assert session.session_id == "new-session"

    def test_update_session(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        session = mock_zep.update_session("s1", metadata={"k": "v"})
        assert session is not None

    def test_update_session_not_found(self, mock_zep):
        with pytest.raises(NotFoundError):
            mock_zep.update_session("missing")

    def test_search_sessions_semantic(self, mock_zep):
        mock_zep._mock_sss.return_value = [
            {"workspace_id": "ws-1", "session_name": "s1", "score": 0.9,
             "top_memory_content": "hi", "memory_count": 5},
        ]
        sessions = mock_zep.search_sessions("query")
        assert len(sessions) >= 1

    def test_search_sessions_fallback(self, mock_zep):
        mock_zep._mock_sss.return_value = []
        mock_zep._mock_list_ws.return_value = [
            {"name": "test-session", "id": "ws-1", "created_at": "now"},
            {"name": "other", "id": "ws-2", "created_at": "now"},
        ]
        sessions = mock_zep.search_sessions("test")
        assert len(sessions) >= 1

    def test_close(self, mock_zep):
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep.close()
        assert mock_zep._session_to_ws == {}

    def test_now_iso(self, mock_zep):
        result = mock_zep._now_iso()
        assert "T" in result


# ── Test: _MemoryProxy ─────────────────────────────────────────────────────


class TestMemoryProxy:
    def test_add(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        with patch.object(proxy._c, "add_memory") as mock_am:
            mock_am.return_value = {"status": "ok"}
            r = proxy.add("s1", [{"role": "user", "content": "Hi"}])
            assert r == {"status": "ok"}

    def test_get(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        # Set up get_memory to return a result
        mock_zep._session_to_ws["s1"] = "ws-1"
        mock_zep._mock_list_mems.return_value = [
            {"id": "m1", "content": "Hello", "peer_id": "user",
             "created_at": "2024-01-01", "strength": 0.9},
        ]
        r = proxy.get("s1")
        assert r is not None
        assert "messages" in r

    def test_delete(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        r = proxy.delete("s1")
        assert r["status"] == "ok"

    def test_search(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        r = proxy.search("s1", "q")
        assert r == []

    def test_add_fact(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        r = proxy.add_fact("s1", "fact")
        assert r["status"] == "ok"

    def test_get_fact(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        with patch.object(proxy._c, "get_fact") as mock_gf:
            mock_gf.return_value = Fact(uuid="f1", fact="test")
            r = proxy.get_fact("f1")
            assert r.uuid == "f1"

    def test_add_session(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        r = proxy.add_session("s1")
        assert r is not None

    def test_list_sessions(self, mock_zep):
        proxy = _MemoryProxy(mock_zep)
        r = proxy.list_sessions()
        assert r == []


# ── Test: _UserProxy ───────────────────────────────────────────────────────


class TestUserProxy:
    def test_add(self, mock_zep):
        proxy = _UserProxy(mock_zep._client)
        with patch.object(proxy._inner, "add") as mock_add:
            mock_add.return_value = {"user_id": "u1"}
            r = proxy.add(user_id="u1")
            assert r["user_id"] == "u1"

    def test_get(self, mock_zep):
        proxy = _UserProxy(mock_zep._client)
        with patch.object(proxy._inner, "get") as mock_get:
            mock_get.return_value = {"user_id": "u1"}
            r = proxy.get("u1")
            assert r["user_id"] == "u1"

    def test_delete(self, mock_zep):
        proxy = _UserProxy(mock_zep._client)
        with patch.object(proxy._inner, "delete") as mock_del:
            mock_del.return_value = {"status": "ok"}
            r = proxy.delete("u1")
            assert r["status"] == "ok"


# ── Test: UserClient ───────────────────────────────────────────────────────


class TestUserClient:
    def test_add(self, mock_zep):
        uc = UserClient(mock_zep._client)
        mock_zep._mock_call.return_value = "ok"
        mock_zep._mock_sql_param.return_value = [
            {"user_id": "u1", "email": "a@b.com", "first_name": "A",
             "last_name": "B", "metadata_json": "{}", "created_at": 0, "updated_at": 0}
        ]
        r = uc.add(user_id="u1", email="a@b.com")
        assert r["user_id"] == "u1"

    def test_get(self, mock_zep):
        uc = UserClient(mock_zep._client)
        mock_zep._mock_call.return_value = "ok"
        mock_zep._mock_sql_param.return_value = [
            {"user_id": "u1", "email": "a@b.com", "first_name": "A",
             "last_name": "B", "metadata_json": "{}", "created_at": 0, "updated_at": 0}
        ]
        r = uc.get("u1")
        assert r["user_id"] == "u1"

    def test_get_not_found(self, mock_zep):
        uc = UserClient(mock_zep._client)
        mock_zep._mock_call.return_value = "ok"
        mock_zep._mock_sql_param.return_value = []
        with pytest.raises(NotFoundError):
            uc.get("missing")

    def test_update(self, mock_zep):
        uc = UserClient(mock_zep._client)
        mock_zep._mock_call.return_value = "ok"
        mock_zep._mock_sql_param.return_value = [
            {"user_id": "u1", "email": "a@b.com", "first_name": "A",
             "last_name": "B", "metadata_json": "{}", "created_at": 0, "updated_at": 0}
        ]
        r = uc.update("u1", email="new@b.com")
        assert r["user_id"] == "u1"

    def test_delete(self, mock_zep):
        uc = UserClient(mock_zep._client)
        mock_zep._mock_call.return_value = "ok"
        r = uc.delete("u1")
        assert r["status"] == "ok"

    def test_row_to_user(self, mock_zep):
        row = {
            "user_id": "u1", "email": "a@b.com", "first_name": "A",
            "last_name": "B", "metadata_json": '{"pref": "dark"}',
            "created_at": 0, "updated_at": 0,
        }
        r = UserClient._row_to_user(row)
        assert r["user_id"] == "u1"
        assert r["metadata"] == {"pref": "dark"}


# ── Test: _GraphClient ─────────────────────────────────────────────────────


class TestGraphClient:
    def test_add(self, mock_zep):
        g = _GraphClient(mock_zep)
        mock_zep._mock_list_ws.return_value = [{"id": "ws-g", "name": "zep-graph-default"}]
        mock_zep._mock_store.return_value = {"id": "ep-1"}
        r = g.add("test content")
        assert r["uuid"] is not None
        assert r["source"] == "text"

    def test_add_invalid_type(self, mock_zep):
        g = _GraphClient(mock_zep)
        with pytest.raises(BadRequestError):
            g.add("data", type="invalid")

    def test_search_nodes(self, mock_zep):
        g = _GraphClient(mock_zep)
        mock_zep._mock_list_ws.return_value = [{"id": "ws-g", "name": "zep-graph-default"}]
        mock_zep._mock_query.return_value = [
            {"id": "n1", "label": "Alice", "workspace_id": "ws-g",
             "node_type": "entity", "summary": "",
             "created_at": 0, "metadata_json": "{}"}
        ]
        r = g.search("Alice", scope="nodes")
        assert "nodes" in r

    def test_search_episodes(self, mock_zep):
        g = _GraphClient(mock_zep)
        mock_zep._mock_list_ws.return_value = [{"id": "ws-g", "name": "zep-graph-default"}]
        mock_zep._mock_search.return_value = [{"id": "ep1", "content": "test", "score": 0.9}]
        r = g.search("test", scope="episodes")
        assert "episodes" in r

    def test_search_edges_default(self, mock_zep):
        g = _GraphClient(mock_zep)
        mock_zep._mock_list_ws.return_value = [{"id": "ws-g", "name": "zep-graph-default"}]
        mock_zep._mock_query.return_value = []
        r = g.search("query")
        assert "edges" in r

    def test_add_triplet(self, mock_zep):
        g = _GraphClient(mock_zep)
        mock_zep._mock_list_ws.return_value = [{"id": "ws-g", "name": "zep-graph-default"}]
        mock_zep._mock_query.return_value = [
            {"id": "e1", "relation": "likes", "source_node_id": "src",
             "target_node_id": "tgt", "workspace_id": "ws-g",
             "weight": 1.0, "valid_at": 0, "invalid_at": 0,
             "created_at": 0, "metadata_json": "{}",
             "source_memory_id": "mem-1"}
        ]
        r = g.add_triplet("src", "tgt", "likes")
        assert "uuid" in r

    def test_graph_namespaces(self, mock_zep):
        g = _GraphClient(mock_zep)
        assert isinstance(g.node, _GraphNodeNamespace)
        assert isinstance(g.edge, _GraphEdgeNamespace)
        assert isinstance(g.episode, _GraphEpisodeNamespace)


# ── Test: Zep ──────────────────────────────────────────────────────────────


class TestZepClass:
    def test_has_sub_clients(self, mock_zep):
        """Zep should have .memory, .user, .graph sub-clients."""
        assert hasattr(mock_zep, "memory")
        assert hasattr(mock_zep, "user")
        assert hasattr(mock_zep, "graph")

    def test_zepclient_alias(self):
        """ZepClient should be an alias for Zep."""
        assert ZepClient is Zep
