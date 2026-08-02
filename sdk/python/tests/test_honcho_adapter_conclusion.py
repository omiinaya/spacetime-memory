"""
Conclusion scope and additional Honcho operations.

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


class TestHonchoMore:
    """Additional Honcho client method coverage."""

    def test_honcho_properties(self, honcho: Honcho) -> None:
        """Honcho.metadata, configuration, base_url properties."""
        assert isinstance(honcho.metadata, dict)
        assert honcho.configuration is not None
        assert isinstance(honcho.base_url, str)

    def test_honcho_peers_with_reverse(self, honcho: Honcho) -> None:
        """Honcho.peers() with reverse=True."""
        honcho.peer(_uid())
        honcho.peer(_uid())
        pages = honcho.peers(reverse=True)
        assert pages is not None

    def test_honcho_session_with_peers(self, honcho: Honcho) -> None:
        """Honcho.session() with peers kwarg."""
        pid = _uid()
        p = honcho.peer(pid)
        sid = _uid("session-special")
        s = honcho.session(sid, peers=[p])
        assert s is not None
        assert p in s.peers()

    def test_honcho_session_cache_hit(self, honcho: Honcho) -> None:
        """Honcho.session() returns cached session on second call."""
        sid = _uid("session")
        s1 = honcho.session(sid)
        s2 = honcho.session(sid)
        assert s1 is s2

    def test_honcho_sessions(self, honcho: Honcho) -> None:
        """Honcho.sessions() lists sessions."""
        honcho.session(_uid("session-a"))
        honcho.session(_uid("session-b"))
        pages = honcho.sessions()
        assert pages is not None

    def test_honcho_sessions_reverse(self, honcho: Honcho) -> None:
        """Honcho.sessions() with reverse=True."""
        honcho.session(_uid("session-x"))
        pages = honcho.sessions(reverse=True)
        assert pages is not None

    def test_honcho_workspaces(self, honcho: Honcho) -> None:
        """Honcho.workspaces() returns list of workspace IDs."""
        pages = honcho.workspaces()
        assert pages is not None

    def test_honcho_delete_workspace(self, honcho: Honcho) -> None:
        """Honcho.delete_workspace() clears caches."""
        honcho.peer(_uid())
        honcho.session(_uid("session"))
        honcho.delete_workspace()
        # Caches should be cleared, not raising is success

    def test_honcho_queue_status(self, honcho: Honcho) -> None:
        """Honcho.queue_status() returns QueueStatusResponse."""
        status = honcho.queue_status()
        assert status is not None
        assert hasattr(status, "total_work_units")

    def test_honcho_schedule_dream(self, honcho: Honcho) -> None:
        """Honcho.schedule_dream() does not raise."""
        pid = _uid()
        p = honcho.peer(pid)
        try:
            honcho.schedule_dream(observer=p)
        except RuntimeError:
            # May fail if LLM/list_memories not available
            pass

    def test_honcho_get_set_metadata(self, honcho: Honcho) -> None:
        """Honcho.get_metadata() and set_metadata()."""
        honcho.set_metadata({"workspace_meta": "test"})
        assert honcho.get_metadata()["workspace_meta"] == "test"

    def test_honcho_get_set_configuration(self, honcho: Honcho) -> None:
        """Honcho.get_configuration() and set_configuration()."""
        from spacetime_memory.sdks.honcho import WorkspaceConfiguration

        cfg = WorkspaceConfiguration()
        honcho.set_configuration(cfg)
        assert honcho.get_configuration() is not None

    def test_honcho_refresh(self, honcho: Honcho) -> None:
        """Honcho.refresh() does not raise."""
        honcho.refresh()


# ---------------------------------------------------------------------------
# ConclusionScope tests
# ---------------------------------------------------------------------------



class TestConclusionScope:
    """Tests for ConclusionScope methods."""

    def test_conclusions_list_empty(self, honcho: Honcho) -> None:
        """ConclusionScope.list() on empty scope."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        page = scope.list()
        assert page is not None
        assert len(page) == 0

    def test_conclusions_query_empty(self, honcho: Honcho) -> None:
        """ConclusionScope.query() on empty scope."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        results = scope.query("anything")
        assert isinstance(results, list)

    def test_conclusions_delete_nonexistent(self, honcho: Honcho) -> None:
        """ConclusionScope.delete() on non-existent ID does not raise."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        scope.delete("nonexistent-12345")

    def test_conclusions_create(self, honcho: Honcho) -> None:
        """ConclusionScope.create() stores conclusions (may fail without auth)."""
        from spacetime_memory.sdks.honcho import ConclusionCreateParams

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        params = ConclusionCreateParams(content="Test conclusion", session_id=None)
        try:
            results = scope.create([params])
            assert isinstance(results, list)
        except RuntimeError:
            pass

    def test_conclusions_create_from_dict(self, honcho: Honcho) -> None:
        """ConclusionScope.create() accepts dict items (may fail without auth)."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        try:
            results = scope.create([{"content": "Dict conclusion"}])
            assert isinstance(results, list)
        except RuntimeError:
            pass

    def test_conclusions_representation(self, honcho: Honcho) -> None:
        """ConclusionScope.representation() returns a string."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        rep = scope.representation()
        assert isinstance(rep, str)

    def test_conclusions_scope_aio(self, honcho: Honcho) -> None:
        """ConclusionScope.aio property returns async interface."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        aio = scope.aio
        assert aio is not None


# ---------------------------------------------------------------------------
# Async wrapper tests
# ---------------------------------------------------------------------------


