"""Unit tests for the Honcho adapter client (_client.py).

Tests Peer, Session, Honcho, ConclusionScope, and related classes
using mocked HTTP — no real SpacetimeDB calls.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spacetime_memory.sdks.honcho._client import (
    ConclusionScope,
    ConclusionScopeAio,
    Honcho,
    HonchoAio,
    Peer,
    PeerAio,
    Session,
    SessionAio,
)
from spacetime_memory.sdks.honcho._models import (
    ConclusionCreateParams,
    Message,
    MessageCreateParams,
    PeerConfig,
    SyncPage,
)

pytestmark = pytest.mark.unit


# ── Fixture ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_honcho():
    """Honcho with fully mocked _client."""
    h = Honcho(
        workspace_id="test-ws",
        stdb_host="127.0.0.1",
        stdb_port=3001,
    )
    with patch.object(h._client, "search") as mock_search:
        with patch.object(h._client, "store") as mock_store:
            with patch.object(h._client, "_query") as mock_query:
                with patch.object(h._client, "_call") as mock_call:
                    with patch.object(h._client, "get_memory") as mock_get_mem:
                        with patch.object(h._client, "update_memory") as mock_upd_mem:
                            with patch.object(h._client, "list_memories") as mock_list_mems:
                                mock_search.return_value = []
                                mock_store.return_value = {"id": "stored"}
                                mock_query.return_value = []
                                mock_call.return_value = "ok"
                                mock_get_mem.return_value = []
                                mock_upd_mem.return_value = {"status": "ok"}
                                mock_list_mems.return_value = []
                                h._mock_search = mock_search
                                h._mock_store = mock_store
                                h._mock_query = mock_query
                                h._mock_call = mock_call
                                h._mock_get_mem = mock_get_mem
                                h._mock_upd_mem = mock_upd_mem
                                h._mock_list_mems = mock_list_mems
                                yield h


# ── Test: Peer ─────────────────────────────────────────────────────────────


class TestPeer:
    def test_peer_construction(self, mock_honcho):
        p = Peer(peer_id="alice", honcho=mock_honcho)
        assert p.id == "alice"
        assert p.metadata == {}
        assert isinstance(p.configuration, PeerConfig)

    def test_peer_message_creates_params(self, mock_honcho):
        p = Peer(peer_id="alice", honcho=mock_honcho)
        msg = p.message("Hello")
        assert isinstance(msg, MessageCreateParams)
        assert msg.content == "Hello"
        assert msg.peer_id == "alice"

    def test_peer_chat_with_memories(self, mock_honcho):
        mock_honcho._mock_search.return_value = [
            {"memory_content": "Alice likes pizza"},
        ]
        p = Peer(peer_id="alice", honcho=mock_honcho)
        result = p.chat("What do you like?")
        assert result is not None
        assert "pizza" in result

    def test_peer_chat_without_memories(self, mock_honcho):
        mock_honcho._mock_search.return_value = []
        p = Peer(peer_id="bob", honcho=mock_honcho)
        result = p.chat("Hello")
        assert result is None

    def test_peer_chat_search_error_returns_none(self, mock_honcho):
        mock_honcho._mock_search.side_effect = RuntimeError("fail")
        p = Peer(peer_id="alice", honcho=mock_honcho)
        result = p.chat("Hi")
        assert result is None

    def test_peer_chat_stream(self, mock_honcho):
        mock_honcho._mock_search.return_value = [
            {"memory_content": "Context data"},
        ]
        p = Peer(peer_id="alice", honcho=mock_honcho)
        gen = p.chat_stream("Tell me")
        chunks = list(gen)
        assert len(chunks) >= 1

    def test_peer_get_card_llm_unavailable(self, mock_honcho):
        with patch("spacetime_memory.sdks.honcho._conclusion.LLMClient") as MockLLM:
            MockLLM.return_value.available = False
            p = Peer(peer_id="alice", honcho=mock_honcho)
            card = p.get_card()
            assert card == {"summary": "", "traits": []}

    def test_peer_search(self, mock_honcho):
        mock_honcho._mock_search.return_value = [
            {"id": "m1", "memory_content": "Hello", "metadata": {}}
        ]
        p = Peer(peer_id="alice", honcho=mock_honcho)
        results = p.search("Hello")
        assert len(results) == 1
        assert isinstance(results[0], Message)

    def test_peer_sessions(self, mock_honcho):
        p = Peer(peer_id="alice", honcho=mock_honcho)
        # Create a session and add peer to it
        s = Session(session_id="s1", honcho=mock_honcho)
        s.add_peers(p)
        mock_honcho._session_cache["s1"] = s
        page = p.sessions()
        assert isinstance(page, SyncPage)
        assert len(page.items) >= 1

    def test_peer_context(self, mock_honcho):
        mock_honcho._mock_search.return_value = []
        p = Peer(peer_id="alice", honcho=mock_honcho)
        ctx = p.context()
        assert ctx.peer_id == "alice"
        assert ctx.target_id == ""

    def test_peer_aio(self, mock_honcho):
        p = Peer(peer_id="alice", honcho=mock_honcho)
        aio = p.aio
        assert isinstance(aio, PeerAio)

    def test_peer_conclusions(self, mock_honcho):
        p1 = Peer(peer_id="alice", honcho=mock_honcho)
        p2 = Peer(peer_id="bob", honcho=mock_honcho)
        scope = p1.conclusions(observer=p2)
        assert isinstance(scope, ConclusionScope)
        assert scope.observer is p2
        assert scope.observed is p1

    def test_peer_conclusions_of(self, mock_honcho):
        p1 = Peer(peer_id="alice", honcho=mock_honcho)
        p2 = Peer(peer_id="bob", honcho=mock_honcho)
        scope = p1.conclusions_of(p2)
        assert isinstance(scope, ConclusionScope)


# ── Test: Session ──────────────────────────────────────────────────────────


class TestSession:
    def test_session_construction(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        assert s.id == "s1"
        assert s.is_active is True
        assert s._peers == []

    def test_add_peers(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        p = Peer(peer_id="alice", honcho=mock_honcho)
        s.add_peers(p)
        assert len(s._peers) == 1
        assert s._peers[0] is p

    def test_add_peers_by_string(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        s.add_peers("bob")
        assert len(s._peers) == 1
        assert s._peers[0].id == "bob"

    def test_peers_list(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        p = Peer(peer_id="alice", honcho=mock_honcho)
        s.add_peers(p)
        assert p in s.peers()

    def test_add_messages(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        msg = MessageCreateParams(content="Hello", peer_id="alice")
        result = s.add_messages(msg)
        assert len(result) == 1
        assert result[0].content == "Hello"
        mock_honcho._mock_store.assert_called()

    def test_messages_returns_page(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        page = s.messages()
        assert isinstance(page, SyncPage)

    def test_search(self, mock_honcho):
        mock_honcho._mock_search.return_value = [
            {"id": "m1", "memory_content": "test", "metadata": {"peer_id": "alice"}}
        ]
        s = Session(session_id="s1", honcho=mock_honcho)
        results = s.search("test")
        assert len(results) == 1

    def test_context(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        ctx = s.context()
        assert ctx.session_id == "s1"

    def test_summaries(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        summaries = s.summaries()
        assert summaries.id == "s1"

    def test_metadata_get_set(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        assert s.get_metadata() == {}
        s.set_metadata({"key": "val"})
        assert s.get_metadata() == {"key": "val"}

    def test_peers_config(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        p = Peer(peer_id="alice", honcho=mock_honcho)
        cfg = s.get_peer_configuration(p)
        assert cfg is not None
        s.set_peer_configuration(p, cfg)

    def test_delete(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        s.delete()
        assert s.is_active is False

    def test_clone(self, mock_honcho):
        mock_honcho._mock_call.side_effect = None
        with patch.object(mock_honcho._client, "create_workspace") as mock_cw:
            mock_cw.return_value = {"id": "new-ws"}
            s = Session(session_id="s1", honcho=mock_honcho)
            cloned = s.clone()
            assert cloned.id != s.id

    def test_upload_file(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        p = Peer(peer_id="alice", honcho=mock_honcho)
        msgs = s.upload_file("/tmp/test.txt", p)
        assert len(msgs) == 1
        assert "[File:" in msgs[0].content

    def test_session_aio(self, mock_honcho):
        s = Session(session_id="s1", honcho=mock_honcho)
        aio = s.aio
        assert isinstance(aio, SessionAio)


# ── Test: ConclusionScope ──────────────────────────────────────────────────


class TestConclusionScope:
    def test_list_returns_page(self, mock_honcho):
        p1 = Peer(peer_id="obs", honcho=mock_honcho)
        p2 = Peer(peer_id="obd", honcho=mock_honcho)
        scope = ConclusionScope(mock_honcho, p1, p2)
        page = scope.list()
        assert isinstance(page, SyncPage)

    def test_create_stores_conclusions(self, mock_honcho):
        p1 = Peer(peer_id="obs", honcho=mock_honcho)
        p2 = Peer(peer_id="obd", honcho=mock_honcho)
        scope = ConclusionScope(mock_honcho, p1, p2)
        result = scope.create([ConclusionCreateParams(content="test conclusion")])
        assert len(result) == 1
        mock_honcho._mock_store.assert_called()

    def test_query_returns_list(self, mock_honcho):
        p1 = Peer(peer_id="obs", honcho=mock_honcho)
        p2 = Peer(peer_id="obd", honcho=mock_honcho)
        scope = ConclusionScope(mock_honcho, p1, p2)
        results = scope.query("test")
        assert results == []

    def test_delete(self, mock_honcho):
        p1 = Peer(peer_id="obs", honcho=mock_honcho)
        p2 = Peer(peer_id="obd", honcho=mock_honcho)
        scope = ConclusionScope(mock_honcho, p1, p2)
        scope.delete("conclusion-1")  # should not raise

    def test_representation_no_llm(self, mock_honcho):
        p1 = Peer(peer_id="obs", honcho=mock_honcho)
        p2 = Peer(peer_id="obd", honcho=mock_honcho)
        scope = ConclusionScope(mock_honcho, p1, p2)
        with patch("spacetime_memory.sdks.honcho._conclusion.LLMClient") as MockLLM:
            MockLLM.return_value.available = False
            rep = scope.representation()
            assert "No conclusions" in rep

    def test_aio_property(self, mock_honcho):
        p1 = Peer(peer_id="obs", honcho=mock_honcho)
        p2 = Peer(peer_id="obd", honcho=mock_honcho)
        scope = ConclusionScope(mock_honcho, p1, p2)
        assert isinstance(scope.aio, ConclusionScopeAio)


# ── Test: Honcho ───────────────────────────────────────────────────────────


class TestHoncho:
    def test_peer_get_or_create(self, mock_honcho):
        p = mock_honcho.peer("alice")
        assert p.id == "alice"
        # same ID returns cached
        p2 = mock_honcho.peer("alice")
        assert p2 is p

    def test_peers_list(self, mock_honcho):
        mock_honcho.peer("alice")
        mock_honcho.peer("bob")
        page = mock_honcho.peers()
        assert len(page.items) == 2

    def test_session_get_or_create(self, mock_honcho):
        s = mock_honcho.session("s1")
        assert s.id == "s1"
        s2 = mock_honcho.session("s1")
        assert s2 is s

    def test_session_with_peers(self, mock_honcho):
        s = mock_honcho.session("s1", peers=["alice"])
        assert len(s._peers) == 1

    def test_sessions_list(self, mock_honcho):
        mock_honcho.session("s1")
        mock_honcho.session("s2")
        page = mock_honcho.sessions()
        assert len(page.items) == 2

    def test_search(self, mock_honcho):
        mock_honcho._mock_search.return_value = [
            {"id": "m1", "memory_content": "test", "metadata": {}}
        ]
        results = mock_honcho.search("test")
        assert len(results) == 1

    def test_workspaces(self, mock_honcho):
        wp = mock_honcho.workspaces()
        assert len(wp.items) == 1
        assert wp.items[0] == "test-ws"

    def test_metadata(self, mock_honcho):
        assert mock_honcho.get_metadata() == {}
        mock_honcho.set_metadata({"custom": "data"})
        assert mock_honcho.get_metadata() == {"custom": "data"}

    def test_configuration(self, mock_honcho):
        cfg = mock_honcho.get_configuration()
        assert cfg is not None
        from spacetime_memory.sdks.honcho._models import WorkspaceConfiguration

        mock_honcho.set_configuration(WorkspaceConfiguration())
        assert mock_honcho.get_configuration() is not None

    def test_queue_status(self, mock_honcho):
        qs = mock_honcho.queue_status()
        assert qs.total_work_units == 0

    def test_schedule_dream(self, mock_honcho):
        mock_honcho._mock_list_mems.return_value = []
        mock_honcho.schedule_dream("observer")  # should not raise

    def test_delete_workspace(self, mock_honcho):
        mock_honcho.delete_workspace()
        assert mock_honcho._session_cache == {}
        assert mock_honcho._peer_cache == {}

    def test_close(self, mock_honcho):
        mock_honcho.close()
        assert mock_honcho._closed is True

    def test_honcho_aio(self, mock_honcho):
        aio = mock_honcho.aio
        assert isinstance(aio, HonchoAio)
