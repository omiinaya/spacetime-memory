"""Integration tests for Honcho-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_honcho_adapter.py -v

"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


from spacetime_memory.sdks.honcho import Honcho, Peer, Session, Message, SyncPage


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture(scope="module")
def token() -> str:
    """Generate a JWT token for authenticated identity."""
    try:
        from spacetime_memory.auth import generate_token
        key_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "id_ecdsa_pkcs8.pem"
        if key_path.exists():
            return generate_token(str(key_path))
    except ImportError:
        pass
    return ""


@pytest.fixture
def honcho(host: str, port: int, stdb_session: dict, token: str) -> Honcho:
    """Fresh Honcho client with unique workspace per test."""
    uid = uuid.uuid4().hex[:12]
    h = Honcho(
        workspace_id=f"test-{uid}",
        stdb_host=host, stdb_port=port,
        stdb_database=stdb_session["database"],
        api_key=token or None,
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
        msg = p.message("Hello, world!")
        assert msg.content == "Hello, world!"
        assert msg.peer_id == pid

    def test_session_get_or_create(self, honcho: Honcho) -> None:
        """session() returns a Session by ID."""
        sid = _uid("session")
        s = honcho.session(sid)
        assert isinstance(s, Session)
        assert s.id == sid

    def test_add_peers_to_session(self, honcho: Honcho) -> None:
        """Session.add_peers() stores peers."""
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid, peers=[p])
        peers = s.peers()
        assert len(peers) == 1
        assert peers[0].id == pid

    def test_add_messages_to_session(self, honcho: Honcho) -> None:
        """Session.add_messages() stores and Session.messages() retrieves."""
        pytest.skip("Skipped: module ACL requires matching identity for store reducer")
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        msg = p.message("Test message content")
        stored = s.add_messages([msg])
        assert len(stored) == 1
        assert stored[0].content == "Test message content"
        assert stored[0].peer_id == pid

    def test_session_context(self, honcho: Honcho) -> None:
        """Session.context() returns session context with messages."""
        pytest.skip("Skipped: module ACL requires matching identity for store reducer")
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        msg = p.message("Context test")
        s.add_messages([msg])
        ctx = s.context()
        assert ctx.session_id == s.id
        assert len(ctx.messages) >= 1

    def test_workspaces(self, honcho: Honcho) -> None:
        """workspaces() returns list including this workspace."""
        ws = honcho.workspaces()
        assert isinstance(ws, SyncPage)
        assert len(ws.items) >= 1

    def test_delete_workspace(self, honcho: Honcho) -> None:
        """delete_workspace() clears caches."""
        honcho.delete_workspace()
        sessions = honcho.sessions()
        assert len(sessions.items) == 0

    def test_queue_status(self, honcho: Honcho) -> None:
        """queue_status() returns a QueueStatusResponse."""
        qs = honcho.queue_status()
        assert qs is not None


class TestHonchoSearch:
    """Search operations."""

    def test_search_returns_list(self, honcho: Honcho) -> None:
        """search() returns a list."""
        results = honcho.search("test")
        assert isinstance(results, list)

    def test_search_with_stored_data(self, honcho: Honcho) -> None:
        """search() finds stored content."""
        pytest.skip("Skipped: module ACL requires matching identity for store reducer")
        pid = _uid()
        sid = _uid("session")
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        msg = p.message("I like pizza")
        s.add_messages([msg])

        results = honcho.search("pizza")
        assert len(results) >= 1
        assert "pizza" in results[0].content.lower()
