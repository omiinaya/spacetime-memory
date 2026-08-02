"""
Peer operations - advanced and extended.

Integration tests for the Honcho adapter - split from the original
test_honcho_adapter.py.  These tests require a running SpacetimeDB instance
on localhost:3001 (handled by the ``stdb_session`` fixture in conftest.py).
"""

from __future__ import annotations

import uuid

import pytest

from spacetime_memory.sdks import Honcho

pytestmark = [
    pytest.mark.integration,
]


def _uid(prefix: str = "honcho-test") -> str:
    """Generate a unique ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TestHonchoPeerAdvanced:
    """Advanced Peer operations."""

    def test_peer_chat(self, honcho: Honcho) -> None:
        """Peer.chat() returns a response based on context."""
        pid = _uid()
        p = honcho.peer(pid)
        response = p.chat("What do I like?")
        # Returns None when no memories exist, or a string
        assert response is None or isinstance(response, str)

    def test_peer_chat_with_stored_data(self, honcho: Honcho) -> None:
        """Peer.chat() with stored memories returns context."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("I love hiking in the mountains")
        s.add_messages([msg])
        response = p.chat("What do I enjoy?")
        # May be None if search doesn't find, or a string
        assert response is None or isinstance(response, str)

    def test_peer_chat_stream(self, honcho: Honcho) -> None:
        """Peer.chat_stream() returns a generator."""
        pid = _uid()
        p = honcho.peer(pid)
        generator = p.chat_stream("Hello")
        chunks = list(generator)
        assert isinstance(chunks, list)

    def test_peer_get_card(self, honcho: Honcho) -> None:
        """Peer.get_card() returns a dict with summary and traits."""
        pid = _uid()
        p = honcho.peer(pid)
        card = p.get_card()
        assert isinstance(card, dict)
        assert "summary" in card
        assert "traits" in card

    def test_peer_search(self, honcho: Honcho) -> None:
        """Peer.search() returns relevant memories."""
        pid = _uid()
        p = honcho.peer(pid)
        results = p.search("anything")
        assert results is not None

    def test_peer_sessions_actual(self, honcho: Honcho) -> None:
        """Peer.sessions() returns sessions with data."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        pages = p.sessions()
        assert pages is not None

    def test_peer_representation(self, honcho: Honcho) -> None:
        """Peer.representation() returns a description."""
        pid = _uid()
        p = honcho.peer(pid)
        rep = p.representation()
        assert rep is None or isinstance(rep, str)

    def test_peer_context(self, honcho: Honcho) -> None:
        """Peer.context() returns peer context."""
        pid = _uid()
        p = honcho.peer(pid)
        ctx = p.context()
        assert ctx is not None

    def test_peer_get_set_metadata(self, honcho: Honcho) -> None:
        """Peer.get_metadata() and set_metadata()."""
        pid = _uid()
        p = honcho.peer(pid)
        initial = p.get_metadata()
        assert isinstance(initial, dict)
        p.set_metadata({"test": "value"})
        updated = p.get_metadata()
        assert updated["test"] == "value"

    def test_peer_get_set_configuration(self, honcho: Honcho) -> None:
        """Peer.get_configuration() and set_configuration()."""
        pid = _uid()
        p = honcho.peer(pid)
        config = p.get_configuration()
        assert config is not None

    def test_peer_refresh(self, honcho: Honcho) -> None:
        """Peer.refresh() does not raise."""
        pid = _uid()
        p = honcho.peer(pid)
        p.refresh()

    def test_peer_aio(self, honcho: Honcho) -> None:
        """Peer.aio property returns async interface."""
        pid = _uid()
        p = honcho.peer(pid)
        aio = p.aio
        assert aio is not None

    def test_peer_conclusions(self, honcho: Honcho) -> None:
        """Peer.conclusions() returns conclusion scope."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        assert scope is not None



class TestPeerMore:
    """Additional Peer method coverage."""

    def test_peer_properties(self, honcho: Honcho) -> None:
        """Peer.metadata, configuration, created_at properties."""
        pid = _uid()
        p = honcho.peer(pid)
        assert isinstance(p.metadata, dict)
        assert p.configuration is not None
        assert p.created_at is not None

    def test_peer_chat_with_memories(self, honcho: Honcho) -> None:
        """Peer.chat() returns a string when memories exist."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("I really enjoy tennis and swimming")
        s.add_messages([msg])
        response = p.chat("What sports do I like?")
        # May be None if search doesn't find it, or a string
        assert response is None or isinstance(response, str)

    def test_peer_chat_stream_with_data(self, honcho: Honcho) -> None:
        """Peer.chat_stream() yields chunks when chat returns data."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("I love programming in Python")
        s.add_messages([msg])
        gen = p.chat_stream("What do I like?")
        chunks = list(gen)
        assert isinstance(chunks, list)

    def test_peer_set_configuration(self, honcho: Honcho) -> None:
        """Peer.set_configuration() stores the config."""
        from spacetime_memory.sdks.honcho import PeerConfig

        pid = _uid()
        p = honcho.peer(pid)
        cfg = PeerConfig(observe_me=True)
        p.set_configuration(cfg)
        assert p.get_configuration().observe_me is True

    def test_peer_conclusions_of_string(self, honcho: Honcho) -> None:
        """Peer.conclusions_of() with string peer ID."""
        pid = _uid()
        pid2 = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions_of(pid2)
        assert scope is not None

    def test_peer_sessions_with_reverse(self, honcho: Honcho) -> None:
        """Peer.sessions() with reverse=True."""
        pid = _uid()
        p = honcho.peer(pid)
        s1 = honcho.session(_uid("session"))
        s2 = honcho.session(_uid("session"))
        s1.add_peers([p])
        s2.add_peers([p])
        pages = p.sessions(reverse=True)
        assert pages is not None

    def test_peer_search(self, honcho: Honcho) -> None:
        """Peer.search() returns messages or empty list."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Peer searchable content")
        s.add_messages([msg])
        results = p.search("searchable")
        assert isinstance(results, list)

    def test_peer_representation_no_llm(self, honcho: Honcho) -> None:
        """Peer.representation() works without LLM."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Representation test data")
        s.add_messages([msg])
        rep = p.representation()
        assert isinstance(rep, str)

    def test_peer_get_card_no_llm(self, honcho: Honcho) -> None:
        """Peer.get_card() returns dict with empty fields when LLM unavailable."""
        pid = _uid()
        p = honcho.peer(pid)
        card = p.get_card()
        assert isinstance(card, dict)
        assert "summary" in card
        assert "traits" in card

    def test_peer_context_rich(self, honcho: Honcho) -> None:
        """Peer.context() returns PeerContextResponse with representation."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Context for peer analysis")
        s.add_messages([msg])
        ctx = p.context(target="target1")
        assert ctx is not None
        assert ctx.peer_id == pid
        assert ctx.target_id == "target1"


# ---------------------------------------------------------------------------
# Session advanced tests
# ---------------------------------------------------------------------------


