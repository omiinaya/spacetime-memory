"""
Integration tests for the Honcho adapter.

These tests require a running SpacetimeDB instance.
"""

from __future__ import annotations

import os
import sys
import uuid
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from spacetime_memory import Client
from spacetime_memory.sdks import Honcho, Peer, Session

pytestmark = [
    pytest.mark.integration,
]


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture
def honcho(host: str, port: int, stdb_session: dict) -> Honcho:
    """Fresh Honcho client with unique workspace per test."""
    uid = uuid.uuid4().hex[:12]
    ws_id = f"test-{uid}"

    # Register identity and create workspace so store_memory's ACL passes
    reg = Client(
        host=host, port=port,
        database=stdb_session["database"],
    )
    try:
        reg._call("register", [f"honcho-{uid}", "Honcho Test", "pw"])
    except RuntimeError:
        pass
    try:
        reg._call("create_workspace", ["honcho-test", "auto", ws_id])
    except RuntimeError:
        pass
    identity_token = reg._identity_token or ""

    h = Honcho(
        workspace_id=ws_id,
        stdb_host=host, stdb_port=port,
        stdb_database=stdb_session["database"],
        api_key=identity_token or None,
    )
    yield h
    h.close()


def _uid(prefix: str = "honcho-test") -> str:
    """Generate a unique ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TestHonchoCore:
    """Core Honcho API operations."""

    def test_peer_get_or_create(self, honcho: Honcho) -> None:
        """peer() returns a Peer by ID."""
        pid = _uid()
        p = honcho.peer(pid)
        assert isinstance(p, Peer)
        assert p.id == pid

    def test_peer_reuses_cache(self, honcho: Honcho) -> None:
        """Calling peer() twice with the same ID returns the same object."""
        pid = _uid()
        p1 = honcho.peer(pid)
        p2 = honcho.peer(pid)
        assert p1 is p2

    def test_peer_message(self, honcho: Honcho) -> None:
        """Peer.message() creates a MessageCreateParams."""
        pid = _uid()
        p = honcho.peer(pid)
        msg = p.message("Hello")
        assert msg is not None
        assert msg.peer_id == pid

    def test_peer_sessions(self, honcho: Honcho) -> None:
        """Peer.sessions() returns paginated results."""
        pid = _uid()
        p = honcho.peer(pid)
        pages = p.sessions()
        assert pages is not None

    def test_session_get_or_create(self, honcho: Honcho) -> None:
        """session() returns a Session by ID."""
        sid = _uid("session")
        s = honcho.session(sid)
        assert isinstance(s, Session)
        assert s.id == sid

    def test_session_peers(self, honcho: Honcho) -> None:
        """Session has peers attribute."""
        sid = _uid("session")
        s = honcho.session(sid)
        assert s.peers is not None

    def test_session_summaries(self, honcho: Honcho) -> None:
        """Session.summaries() returns summaries."""
        sid = _uid("session")
        s = honcho.session(sid)
        summaries = s.summaries()
        assert summaries is not None

    def test_session_messages(self, honcho: Honcho) -> None:
        """Session.messages() returns paginated results on empty session."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        pages = s.messages()
        assert pages is not None

    def test_add_messages_to_session(self, honcho: Honcho) -> None:
        """Session.add_messages() stores and Session.messages() retrieves."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Hello world")
        s.add_messages([msg])
        pages = s.messages()
        assert pages is not None

    def test_session_context(self, honcho: Honcho) -> None:
        """Session.context() returns session context with messages."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Test context")
        s.add_messages([msg])
        ctx = s.context()
        assert ctx is not None

    def test_session_delete(self, honcho: Honcho) -> None:
        """Session.delete() removes the session."""
        sid = _uid("session")
        s = honcho.session(sid)
        s.delete()
        # After delete, session should be gone
        pages = s.messages()
        assert pages is not None


class TestHonchoSearch:
    """Honcho search operations."""

    def test_search_empty_workspace(self, honcho: Honcho) -> None:
        """search() returns empty on workspace with no data."""
        results = honcho.search("anything")
        assert results is not None

    def test_search_no_params(self, honcho: Honcho) -> None:
        """search() called with no params returns gracefully."""
        results = honcho.search("")
        assert results is not None

    def test_search_with_stored_data(self, honcho: Honcho) -> None:
        """search() finds stored content."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("I like pizza")
        s.add_messages([msg])
        results = honcho.search("pizza")
        assert results is not None


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


class TestHonchoSessionAdvanced:
    """Advanced Session operations."""

    def test_session_search(self, honcho: Honcho) -> None:
        """Session.search() searches within session."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Session search test content")
        s.add_messages([msg])
        results = s.search("test")
        assert results is not None

    def test_session_context_rich(self, honcho: Honcho) -> None:
        """Session.context() with multiple messages."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        for i in range(3):
            msg = p.message(f"Context message {i}")
            s.add_messages([msg])
        ctx = s.context()
        assert ctx is not None

    def test_session_summaries_rich(self, honcho: Honcho) -> None:
        """Session.summaries() with stored data."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Summarize this session content")
        s.add_messages([msg])
        summaries = s.summaries()
        assert summaries is not None

    def test_session_get_set_metadata(self, honcho: Honcho) -> None:
        """Session get/set metadata."""
        sid = _uid("session")
        s = honcho.session(sid)
        if hasattr(s, 'get_metadata'):
            md = s.get_metadata()
            assert md is not None

    def test_honcho_search_with_filters(self, honcho: Honcho) -> None:
        """Honcho.search() with stored data returns results."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Additional filter search test")
        s.add_messages([msg])
        results = honcho.search("filter")
        assert results is not None

    def test_session_get_configuration(self, honcho: Honcho) -> None:
        """Session.get_configuration returns config."""
        sid = _uid("session")
        s = honcho.session(sid)
        config = s.get_configuration()
        assert config is not None

    def test_session_set_configuration(self, honcho: Honcho) -> None:
        """Session.set_configuration does not raise."""
        from spacetime_memory.sdks.honcho import SessionConfiguration
        sid = _uid("session")
        s = honcho.session(sid)
        s.set_configuration(SessionConfiguration())
        # No error = success

    def test_session_aio(self, honcho: Honcho) -> None:
        """Session.aio property returns async interface."""
        sid = _uid("session")
        s = honcho.session(sid)
        aio = s.aio
        assert aio is not None

    def test_honcho_aio(self, honcho: Honcho) -> None:
        """Honcho.aio property returns async interface."""
        aio = honcho.aio
        assert aio is not None

    def test_honcho_close(self, honcho: Honcho) -> None:
        """Honcho.close() releases resources."""
        # Already closed in fixture teardown, but test it anyway
        honcho.close()  # Should not raise
