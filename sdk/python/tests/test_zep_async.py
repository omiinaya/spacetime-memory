"""Unit tests for the Zep adapter async client (_async.py).

Tests AsyncZepClient, _AsyncMemoryProxy, _AsyncUserProxy,
_AsyncGraphClient, AsyncZep, and async wrappers.
Uses mocked HTTP — no real network calls.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spacetime_memory.sdks.zep._async import (
    AsyncZep,
    _AsyncGraphClient,
    _AsyncGraphEdgeNamespace,
    _AsyncGraphEpisodeNamespace,
    _AsyncGraphNodeNamespace,
    _AsyncMemoryProxy,
    _AsyncUserProxy,
)
from spacetime_memory.sdks.zep._models import Fact, MemoryMessage, Session

pytestmark = pytest.mark.unit


# ── Fixture ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_async_zep():
    """AsyncZepClient with fully mocked sync client."""
    az = AsyncZep(host="127.0.0.1", port=3001)
    # Patch the underlying sync client completely
    with patch.object(az._sync, "add_memory") as mock_add_memory:
        with patch.object(az._sync, "get_memory") as mock_get_memory:
            with patch.object(az._sync, "delete_memory") as mock_delete_memory:
                with patch.object(az._sync, "search_memory") as mock_search_memory:
                    with patch.object(az._sync, "add_fact") as mock_add_fact:
                        with patch.object(az._sync, "list_facts") as mock_list_facts:
                            with patch.object(az._sync, "delete_fact") as mock_delete_fact:
                                with patch.object(az._sync, "get_fact") as mock_get_fact:
                                    with patch.object(az._sync, "update_memory") as mock_update_memory:
                                        with patch.object(az._sync, "get_session_messages") as mock_gsm:
                                            with patch.object(az._sync, "get_session_message") as mock_gsm_single:
                                                with patch.object(az._sync, "update_message_metadata") as mock_umm:
                                                    with patch.object(az._sync, "list_sessions") as mock_list_sessions:
                                                        with patch.object(az._sync, "get_session") as mock_get_session:
                                                            with patch.object(az._sync, "add_session") as mock_add_session:
                                                                with patch.object(az._sync, "update_session") as mock_update_session:
                                                                    with patch.object(az._sync, "search_sessions") as mock_search_sessions:
                                                                        with patch.object(az._sync, "close") as mock_close:
                                                                            with patch.object(az._sync, "summarize_memory") as mock_summarize:
                                                                                # Defaults
                                                                                mock_add_memory.return_value = {"status": "ok"}
                                                                                mock_get_memory.return_value = {"messages": []}
                                                                                mock_delete_memory.return_value = {"status": "ok"}
                                                                                mock_search_memory.return_value = []
                                                                                mock_add_fact.return_value = {"status": "ok"}
                                                                                mock_list_facts.return_value = []
                                                                                mock_delete_fact.return_value = {"status": "ok"}
                                                                                mock_get_fact.return_value = Fact(uuid="f1", fact="test")
                                                                                mock_update_memory.return_value = {"status": "ok"}
                                                                                mock_gsm.return_value = {"messages": []}
                                                                                mock_gsm_single.return_value = {"content": "test"}
                                                                                mock_umm.return_value = {"content": "test"}
                                                                                mock_list_sessions.return_value = []
                                                                                mock_get_session.return_value = None
                                                                                mock_add_session.return_value = Session(session_id="s1")
                                                                                mock_update_session.return_value = Session(session_id="s1")
                                                                                mock_search_sessions.return_value = []
                                                                                mock_close.return_value = None
                                                                                mock_summarize.return_value = None

                                                                                az._mock_add_memory = mock_add_memory
                                                                                az._mock_get_memory = mock_get_memory
                                                                                az._mock_delete_memory = mock_delete_memory
                                                                                az._mock_search_memory = mock_search_memory
                                                                                az._mock_add_fact = mock_add_fact
                                                                                az._mock_list_facts = mock_list_facts
                                                                                az._mock_delete_fact = mock_delete_fact
                                                                                az._mock_get_fact = mock_get_fact
                                                                                az._mock_update_memory = mock_update_memory
                                                                                az._mock_gsm = mock_gsm
                                                                                az._mock_gsm_single = mock_gsm_single
                                                                                az._mock_umm = mock_umm
                                                                                az._mock_list_sessions = mock_list_sessions
                                                                                az._mock_get_session = mock_get_session
                                                                                az._mock_add_session = mock_add_session
                                                                                az._mock_update_session = mock_update_session
                                                                                az._mock_search_sessions = mock_search_sessions
                                                                                az._mock_close = mock_close
                                                                                az._mock_summarize = mock_summarize
                                                                                yield az


# ── Test: AsyncZepClient ───────────────────────────────────────────────────


class TestAsyncZepClient:
    async def test_add_memory(self, mock_async_zep):
        result = await mock_async_zep.add_memory("s1", [MemoryMessage(role="user", content="Hi")])
        assert result == {"status": "ok"}

    async def test_get_memory(self, mock_async_zep):
        result = await mock_async_zep.get_memory("s1")
        assert result == {"messages": []}

    async def test_get_memory_with_limit(self, mock_async_zep):
        await mock_async_zep.get_memory("s1", limit=5, min_rating=0.5)
        mock_async_zep._mock_get_memory.assert_called_once_with("s1", limit=5, min_rating=0.5)

    async def test_delete_memory(self, mock_async_zep):
        result = await mock_async_zep.delete_memory("s1")
        assert result == {"status": "ok"}

    async def test_search_memory(self, mock_async_zep):
        result = await mock_async_zep.search_memory("s1", "test")
        assert result == []

    async def test_search_memory_with_params(self, mock_async_zep):
        await mock_async_zep.search_memory("s1", "query", limit=5, score_threshold=0.5,
                                            search_type="mmr")
        mock_async_zep._mock_search_memory.assert_called_once_with(
            "s1", "query", limit=5, score_threshold=0.5,
            min_score=None, search_type="mmr",
        )

    async def test_add_fact(self, mock_async_zep):
        result = await mock_async_zep.add_fact("s1", "Some fact")
        assert result == {"status": "ok"}

    async def test_list_facts(self, mock_async_zep):
        result = await mock_async_zep.list_facts("s1")
        assert result == []

    async def test_delete_fact(self, mock_async_zep):
        result = await mock_async_zep.delete_fact("f1")
        assert result == {"status": "ok"}

    async def test_get_fact(self, mock_async_zep):
        result = await mock_async_zep.get_fact("f1")
        assert isinstance(result, Fact)
        assert result.uuid == "f1"

    async def test_update_memory(self, mock_async_zep):
        result = await mock_async_zep.update_memory("s1", "m1",
                                                      [{"role": "user", "content": "Updated"}])
        assert result == {"status": "ok"}

    async def test_get_session_messages(self, mock_async_zep):
        result = await mock_async_zep.get_session_messages("s1")
        assert result == {"messages": []}

    async def test_get_session_message(self, mock_async_zep):
        result = await mock_async_zep.get_session_message("s1", "msg1")
        assert result == {"content": "test"}

    async def test_update_message_metadata(self, mock_async_zep):
        result = await mock_async_zep.update_message_metadata("s1", "msg1", {"key": "val"})
        assert result == {"content": "test"}

    async def test_list_sessions(self, mock_async_zep):
        result = await mock_async_zep.list_sessions()
        assert result == []

    async def test_get_session(self, mock_async_zep):
        result = await mock_async_zep.get_session("s1")
        assert result is None

    async def test_add_session(self, mock_async_zep):
        result = await mock_async_zep.add_session("s1")
        assert result.session_id == "s1"

    async def test_update_session(self, mock_async_zep):
        result = await mock_async_zep.update_session("s1", metadata={"k": "v"})
        assert result.session_id == "s1"

    async def test_search_sessions(self, mock_async_zep):
        result = await mock_async_zep.search_sessions("query")
        assert result == []

    async def test_summarize_memory(self, mock_async_zep):
        result = await mock_async_zep.summarize_memory("s1")
        assert result is None

    async def test_close(self, mock_async_zep):
        await mock_async_zep.close()
        mock_async_zep._mock_close.assert_called_once()

    async def test_context_manager(self, mock_async_zep):
        async with mock_async_zep as cm:
            assert cm is mock_async_zep


# ── Test: _AsyncMemoryProxy ────────────────────────────────────────────────


class TestAsyncMemoryProxy:
    async def test_add(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.add("s1", [MemoryMessage(role="user", content="Hi")])
        assert result == {"status": "ok"}

    async def test_get(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.get("s1")
        assert result == {"messages": []}

    async def test_delete(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.delete("s1")
        assert result == {"status": "ok"}

    async def test_search(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.search("s1", "test")
        assert result == []

    async def test_add_fact(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.add_fact("s1", "fact")
        assert result == {"status": "ok"}

    async def test_get_fact(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.get_fact("f1")
        assert isinstance(result, Fact)

    async def test_delete_fact(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.delete_fact("f1")
        assert result == {"status": "ok"}

    async def test_add_session(self, mock_async_zep):
        proxy = _AsyncMemoryProxy(mock_async_zep)
        result = await proxy.add_session("s1")
        assert result.session_id == "s1"


# ── Test: _AsyncUserProxy ──────────────────────────────────────────────────


class TestAsyncUserProxy:
    async def test_add(self, mock_async_zep):
        proxy = _AsyncUserProxy(mock_async_zep)
        with patch.object(proxy._inner, "add") as mock_add:
            mock_add.return_value = {"user_id": "u1"}
            result = await proxy.add(user_id="u1")
            assert result["user_id"] == "u1"

    async def test_get(self, mock_async_zep):
        proxy = _AsyncUserProxy(mock_async_zep)
        with patch.object(proxy._inner, "get") as mock_get:
            mock_get.return_value = {"user_id": "u1"}
            result = await proxy.get("u1")
            assert result["user_id"] == "u1"

    async def test_update(self, mock_async_zep):
        proxy = _AsyncUserProxy(mock_async_zep)
        with patch.object(proxy._inner, "update") as mock_upd:
            mock_upd.return_value = {"user_id": "u1", "email": "a@b.com"}
            result = await proxy.update("u1", email="a@b.com")
            assert result["email"] == "a@b.com"

    async def test_delete(self, mock_async_zep):
        proxy = _AsyncUserProxy(mock_async_zep)
        with patch.object(proxy._inner, "delete") as mock_del:
            mock_del.return_value = {"status": "ok"}
            result = await proxy.delete("u1")
            assert result["status"] == "ok"


# ── Test: _AsyncGraphClient ────────────────────────────────────────────────


class TestAsyncGraphClient:
    async def test_add(self, mock_async_zep):
        g = _AsyncGraphClient(mock_async_zep)
        with patch.object(g._sync_graph, "add") as mock_add:
            mock_add.return_value = {"uuid": "ep1"}
            result = await g.add("some data")
            assert result["uuid"] == "ep1"

    async def test_search(self, mock_async_zep):
        g = _AsyncGraphClient(mock_async_zep)
        with patch.object(g._sync_graph, "search") as mock_search:
            mock_search.return_value = {"edges": []}
            result = await g.search("query")
            assert result["edges"] == []

    async def test_add_triplet(self, mock_async_zep):
        g = _AsyncGraphClient(mock_async_zep)
        with patch.object(g._sync_graph, "add_triplet") as mock_trip:
            mock_trip.return_value = {"uuid": "edge-1"}
            result = await g.add_triplet("src", "tgt", "rel")
            assert result["uuid"] == "edge-1"

    async def test_graph_namespaces(self, mock_async_zep):
        g = _AsyncGraphClient(mock_async_zep)
        assert isinstance(g.node, _AsyncGraphNodeNamespace)
        assert isinstance(g.edge, _AsyncGraphEdgeNamespace)
        assert isinstance(g.episode, _AsyncGraphEpisodeNamespace)


# ── Test: AsyncZep ─────────────────────────────────────────────────────────


class TestAsyncZep:
    async def test_has_sub_clients(self, mock_async_zep):
        """AsyncZep should have .memory, .user, .graph sub-clients."""
        assert hasattr(mock_async_zep, "memory")
        assert hasattr(mock_async_zep, "user")
        assert hasattr(mock_async_zep, "graph")
