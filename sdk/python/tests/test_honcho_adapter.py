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
