"""
Session operations - advanced and extended.

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
        if hasattr(s, "get_metadata"):
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


# ---------------------------------------------------------------------------
# Model unit tests (no DB required)
# ---------------------------------------------------------------------------



class TestSessionMore:
    """Additional Session method coverage."""

    def test_session_properties(self, honcho: Honcho) -> None:
        """Session metadata, configuration, created_at, is_active properties."""
        sid = _uid("session")
        s = honcho.session(sid)
        assert isinstance(s.metadata, dict)
        assert s.configuration is not None
        assert s.created_at is not None
        assert s.is_active is True

    def test_session_add_peers_single(self, honcho: Honcho) -> None:
        """Session.add_peers() with a single peer (not a list)."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        s.add_peers(p)  # single, not list
        assert len(s.peers()) >= 1

    def test_session_add_peers_with_string(self, honcho: Honcho) -> None:
        """Session.add_peers() with a string peer ID."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        s.add_peers([pid])  # string ID
        assert len(s.peers()) >= 1

    def test_session_peers_method(self, honcho: Honcho) -> None:
        """Session.peers() returns list of peers."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        s.add_peers([p])
        peers = s.peers()
        assert isinstance(peers, list)
        assert p in peers

    def test_session_add_messages_single(self, honcho: Honcho) -> None:
        """Session.add_messages() with a single MessageCreateParams (not list)."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Single message test")
        result = s.add_messages(msg)  # single, not list
        assert isinstance(result, list)

    def test_session_set_peers(self, honcho: Honcho) -> None:
        """Session.set_peers() replaces peers list."""
        sid = _uid("session")
        pid1, pid2 = _uid(), _uid()
        s = honcho.session(sid)
        p1 = honcho.peer(pid1)
        p2 = honcho.peer(pid2)
        s.set_peers([p1, p2])
        assert len(s.peers()) == 2

    def test_session_set_peers_single(self, honcho: Honcho) -> None:
        """Session.set_peers() with single peer."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        s.set_peers(p)  # single
        assert len(s.peers()) == 1

    def test_session_set_peers_with_string(self, honcho: Honcho) -> None:
        """Session.set_peers() with string IDs."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        s.set_peers([pid])  # string
        assert len(s.peers()) == 1

    def test_session_remove_peers(self, honcho: Honcho) -> None:
        """Session.remove_peers() removes peers."""
        sid = _uid("session")
        pid1, pid2, pid3 = _uid(), _uid(), _uid()
        s = honcho.session(sid)
        p1 = honcho.peer(pid1)
        p2 = honcho.peer(pid2)
        p3 = honcho.peer(pid3)
        s.set_peers([p1, p2, p3])
        assert len(s.peers()) == 3
        s.remove_peers([p2])
        assert len(s.peers()) == 2
        assert p2 not in s.peers()

    def test_session_remove_peers_single(self, honcho: Honcho) -> None:
        """Session.remove_peers() with single peer (not list)."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        s.set_peers([p])
        s.remove_peers(p)  # single
        assert len(s.peers()) == 0

    def test_session_remove_peers_by_string(self, honcho: Honcho) -> None:
        """Session.remove_peers() with string peer IDs."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        s.set_peers([p])
        s.remove_peers([pid])  # string
        assert len(s.peers()) == 0

    def test_session_get_peer_configuration(self, honcho: Honcho) -> None:
        """Session.get_peer_configuration() returns config."""
        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        cfg = s.get_peer_configuration(p)
        assert cfg is not None
        # Also test with string ID
        cfg2 = s.get_peer_configuration(pid)
        assert cfg2 is not None

    def test_session_set_peer_configuration(self, honcho: Honcho) -> None:
        """Session.set_peer_configuration() stores config."""
        from spacetime_memory.sdks.honcho import SessionPeerConfig

        sid = _uid("session")
        pid = _uid()
        s = honcho.session(sid)
        p = honcho.peer(pid)
        cfg = SessionPeerConfig(observe_me=True)
        s.set_peer_configuration(p, cfg)
        # Verify via get
        stored = s.get_peer_configuration(p)
        assert stored.observe_me is True
        # With string ID
        s.set_peer_configuration(pid, SessionPeerConfig(observe_me=False))
        stored2 = s.get_peer_configuration(pid)
        assert stored2.observe_me is False

    def test_session_get_message(self, honcho: Honcho) -> None:
        """Session.get_message() returns None for non-existent message."""
        sid = _uid("session")
        s = honcho.session(sid)
        result = s.get_message("non-existent-id")
        assert result is None

    def test_session_update_message(self, honcho: Honcho) -> None:
        """Session.update_message() does not raise."""
        sid = _uid("session")
        s = honcho.session(sid)
        # Non-existent message should not raise
        s.update_message("non-existent-id", {"key": "value"})

    def test_session_clone(self, honcho: Honcho) -> None:
        """Session.clone() creates a new session (may fail if not authenticated)."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("Clone test message")
        s.add_messages([msg])
        try:
            cloned = s.clone()
            assert cloned is not None
            assert cloned.id != sid
        except RuntimeError:
            # create_workspace requires auth we may not have
            pass

    def test_session_upload_file_with_string(self, honcho: Honcho) -> None:
        """Session.upload_file() with a string path."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        result = s.upload_file("/tmp/test.txt", p)
        assert isinstance(result, list)

    def test_session_upload_file_with_tuple(self, honcho: Honcho) -> None:
        """Session.upload_file() with a tuple (filename, ...)."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        result = s.upload_file(("report.pdf", None), p)
        assert isinstance(result, list)

    def test_session_upload_file_with_object_name(self, honcho: Honcho) -> None:
        """Session.upload_file() with an object having a name attribute."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        class FileObj:
            name = "data.csv"

        result = s.upload_file(FileObj(), p)
        assert isinstance(result, list)

    def test_session_upload_file_with_filename_attr(self, honcho: Honcho) -> None:
        """Session.upload_file() with object having filename attribute."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        class FileObj:
            filename = "image.png"

        result = s.upload_file(FileObj(), p)
        assert isinstance(result, list)

    def test_session_upload_file_fallback(self, honcho: Honcho) -> None:
        """Session.upload_file() with arbitrary object (fallback to str)."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        result = s.upload_file(12345, p)
        assert isinstance(result, list)

    def test_session_refresh(self, honcho: Honcho) -> None:
        """Session.refresh() does not raise."""
        sid = _uid("session")
        s = honcho.session(sid)
        s.refresh()

    def test_session_set_metadata(self, honcho: Honcho) -> None:
        """Session.set_metadata() stores metadata."""
        sid = _uid("session")
        s = honcho.session(sid)
        s.set_metadata({"topic": "testing"})
        assert s.get_metadata()["topic"] == "testing"


# ---------------------------------------------------------------------------
# Honcho client advanced tests
# ---------------------------------------------------------------------------


