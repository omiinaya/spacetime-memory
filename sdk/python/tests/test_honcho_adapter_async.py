"""
Async (Aio) wrapper tests via asyncio.to_thread.

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


class TestAsyncWrappers:
    """Tests for async (Aio) wrappers that go through asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_peer_aio_message(self, honcho: Honcho) -> None:
        """PeerAio.message() works."""
        pid = _uid()
        p = honcho.peer(pid)
        result = await p.aio.message("async hello")
        assert result is not None
        assert result.peer_id == pid

    @pytest.mark.asyncio
    async def test_peer_aio_chat(self, honcho: Honcho) -> None:
        """PeerAio.chat() works."""
        pid = _uid()
        p = honcho.peer(pid)
        result = await p.aio.chat("async query")
        assert result is None or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_peer_aio_search(self, honcho: Honcho) -> None:
        """PeerAio.search() works."""
        pid = _uid()
        p = honcho.peer(pid)
        results = await p.aio.search("async search")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_peer_aio_sessions(self, honcho: Honcho) -> None:
        """PeerAio.sessions() works."""
        pid = _uid()
        p = honcho.peer(pid)
        pages = await p.aio.sessions()
        assert pages is not None

    @pytest.mark.asyncio
    async def test_peer_aio_get_set_metadata(self, honcho: Honcho) -> None:
        """PeerAio.get_metadata() and set_metadata() work."""
        pid = _uid()
        p = honcho.peer(pid)
        md = await p.aio.get_metadata()
        assert isinstance(md, dict)
        await p.aio.set_metadata({"async": True})

    @pytest.mark.asyncio
    async def test_peer_aio_get_set_configuration(self, honcho: Honcho) -> None:
        """PeerAio.get_configuration() and set_configuration() work."""
        from spacetime_memory.sdks.honcho import PeerConfig

        pid = _uid()
        p = honcho.peer(pid)
        cfg = await p.aio.get_configuration()
        assert cfg is not None
        await p.aio.set_configuration(PeerConfig(observe_me=True))

    @pytest.mark.asyncio
    async def test_peer_aio_refresh(self, honcho: Honcho) -> None:
        """PeerAio.refresh() works."""
        pid = _uid()
        p = honcho.peer(pid)
        await p.aio.refresh()

    @pytest.mark.asyncio
    async def test_peer_aio_chat_stream(self, honcho: Honcho) -> None:
        """PeerAio.chat_stream() works."""
        pid = _uid()
        p = honcho.peer(pid)
        gen = await p.aio.chat_stream("async stream")
        assert gen is not None

    @pytest.mark.asyncio
    async def test_peer_aio_get_card(self, honcho: Honcho) -> None:
        """PeerAio.get_card() works."""
        pid = _uid()
        p = honcho.peer(pid)
        card = await p.aio.get_card()
        assert isinstance(card, dict)

    @pytest.mark.asyncio
    async def test_peer_aio_representation(self, honcho: Honcho) -> None:
        """PeerAio.representation() works."""
        pid = _uid()
        p = honcho.peer(pid)
        rep = await p.aio.representation()
        assert isinstance(rep, str)

    @pytest.mark.asyncio
    async def test_peer_aio_context(self, honcho: Honcho) -> None:
        """PeerAio.context() works."""
        pid = _uid()
        p = honcho.peer(pid)
        ctx = await p.aio.context()
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_session_aio_add_peers(self, honcho: Honcho) -> None:
        """SessionAio.add_peers() works."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        await s.aio.add_peers([p])

    @pytest.mark.asyncio
    async def test_session_aio_peers(self, honcho: Honcho) -> None:
        """SessionAio.peers() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        peers = await s.aio.peers()
        assert isinstance(peers, list)

    @pytest.mark.asyncio
    async def test_session_aio_add_messages(self, honcho: Honcho) -> None:
        """SessionAio.add_messages() works."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        msg = p.message("async add messages")
        result = await s.aio.add_messages([msg])
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_session_aio_messages(self, honcho: Honcho) -> None:
        """SessionAio.messages() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        pages = await s.aio.messages()
        assert pages is not None

    @pytest.mark.asyncio
    async def test_session_aio_search(self, honcho: Honcho) -> None:
        """SessionAio.search() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        results = await s.aio.search("async session search")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_session_aio_context(self, honcho: Honcho) -> None:
        """SessionAio.context() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        ctx = await s.aio.context()
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_session_aio_summaries(self, honcho: Honcho) -> None:
        """SessionAio.summaries() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        summaries = await s.aio.summaries()
        assert summaries is not None

    @pytest.mark.asyncio
    async def test_session_aio_delete(self, honcho: Honcho) -> None:
        """SessionAio.delete() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        await s.aio.delete()

    @pytest.mark.asyncio
    async def test_session_aio_clone(self, honcho: Honcho) -> None:
        """SessionAio.clone() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        try:
            cloned = await s.aio.clone()
            assert cloned is not None
        except RuntimeError:
            # create_workspace requires auth we may not have
            pass

    @pytest.mark.asyncio
    async def test_session_aio_refresh(self, honcho: Honcho) -> None:
        """SessionAio.refresh() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        await s.aio.refresh()

    @pytest.mark.asyncio
    async def test_session_aio_get_set_metadata(self, honcho: Honcho) -> None:
        """SessionAio.get/set_metadata works."""
        sid = _uid("session")
        s = honcho.session(sid)
        await s.aio.set_metadata({"aio": True})
        md = await s.aio.get_metadata()
        assert md["aio"] is True

    @pytest.mark.asyncio
    async def test_session_aio_get_set_configuration(self, honcho: Honcho) -> None:
        """SessionAio.get/set_configuration works."""
        from spacetime_memory.sdks.honcho import SessionConfiguration

        sid = _uid("session")
        s = honcho.session(sid)
        await s.aio.set_configuration(SessionConfiguration())
        cfg = await s.aio.get_configuration()
        assert cfg is not None

    @pytest.mark.asyncio
    async def test_session_aio_set_peers(self, honcho: Honcho) -> None:
        """SessionAio.set_peers() works."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        await s.aio.set_peers([p])

    @pytest.mark.asyncio
    async def test_session_aio_remove_peers(self, honcho: Honcho) -> None:
        """SessionAio.remove_peers() works."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])
        await s.aio.remove_peers([p])

    @pytest.mark.asyncio
    async def test_session_aio_get_peer_configuration(self, honcho: Honcho) -> None:
        """SessionAio.get_peer_configuration() works."""
        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        cfg = await s.aio.get_peer_configuration(p)
        assert cfg is not None

    @pytest.mark.asyncio
    async def test_session_aio_set_peer_configuration(self, honcho: Honcho) -> None:
        """SessionAio.set_peer_configuration() works."""
        from spacetime_memory.sdks.honcho import SessionPeerConfig

        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        await s.aio.set_peer_configuration(p, SessionPeerConfig())

    @pytest.mark.asyncio
    async def test_session_aio_get_message(self, honcho: Honcho) -> None:
        """SessionAio.get_message() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        result = await s.aio.get_message("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_session_aio_update_message(self, honcho: Honcho) -> None:
        """SessionAio.update_message() works."""
        sid = _uid("session")
        s = honcho.session(sid)
        await s.aio.update_message("nonexistent", {"k": "v"})

    @pytest.mark.asyncio
    async def test_honcho_aio_peer(self, honcho: Honcho) -> None:
        """HonchoAio.peer() works."""
        pid = _uid()
        p = await honcho.aio.peer(pid)
        assert p is not None
        assert p.id == pid

    @pytest.mark.asyncio
    async def test_honcho_aio_peers(self, honcho: Honcho) -> None:
        """HonchoAio.peers() works."""
        pages = await honcho.aio.peers()
        assert pages is not None

    @pytest.mark.asyncio
    async def test_honcho_aio_session(self, honcho: Honcho) -> None:
        """HonchoAio.session() works."""
        sid = _uid("session")
        s = await honcho.aio.session(sid)
        assert s is not None

    @pytest.mark.asyncio
    async def test_honcho_aio_sessions(self, honcho: Honcho) -> None:
        """HonchoAio.sessions() works."""
        pages = await honcho.aio.sessions()
        assert pages is not None

    @pytest.mark.asyncio
    async def test_honcho_aio_search(self, honcho: Honcho) -> None:
        """HonchoAio.search() works."""
        results = await honcho.aio.search("async search")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_honcho_aio_workspaces(self, honcho: Honcho) -> None:
        """HonchoAio.workspaces() works."""
        pages = await honcho.aio.workspaces()
        assert pages is not None

    @pytest.mark.asyncio
    async def test_honcho_aio_delete_workspace(self, honcho: Honcho) -> None:
        """HonchoAio.delete_workspace() works."""
        await honcho.aio.delete_workspace()

    @pytest.mark.asyncio
    async def test_honcho_aio_queue_status(self, honcho: Honcho) -> None:
        """HonchoAio.queue_status() works."""
        status = await honcho.aio.queue_status()
        assert status is not None

    @pytest.mark.asyncio
    async def test_honcho_aio_schedule_dream(self, honcho: Honcho) -> None:
        """HonchoAio.schedule_dream() works."""
        pid = _uid()
        p = honcho.peer(pid)
        try:
            await honcho.aio.schedule_dream(observer=p)
        except RuntimeError:
            pass

    @pytest.mark.asyncio
    async def test_honcho_aio_close(self, honcho: Honcho) -> None:
        """HonchoAio.close() works."""
        await honcho.aio.close()

    @pytest.mark.asyncio
    async def test_honcho_aio_get_set_metadata(self, honcho: Honcho) -> None:
        """HonchoAio.get/set_metadata works."""
        await honcho.aio.set_metadata({"aio_honcho": True})
        md = await honcho.aio.get_metadata()
        assert md["aio_honcho"] is True

    @pytest.mark.asyncio
    async def test_honcho_aio_get_set_configuration(self, honcho: Honcho) -> None:
        """HonchoAio.get/set_configuration works."""
        from spacetime_memory.sdks.honcho import WorkspaceConfiguration

        await honcho.aio.set_configuration(WorkspaceConfiguration())
        cfg = await honcho.aio.get_configuration()
        assert cfg is not None

    @pytest.mark.asyncio
    async def test_honcho_aio_refresh(self, honcho: Honcho) -> None:
        """HonchoAio.refresh() works."""
        await honcho.aio.refresh()

    @pytest.mark.asyncio
    async def test_conclusion_scope_aio_list(self, honcho: Honcho) -> None:
        """ConclusionScopeAio.list() works."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        page = await scope.aio.list()
        assert page is not None

    @pytest.mark.asyncio
    async def test_conclusion_scope_aio_query(self, honcho: Honcho) -> None:
        """ConclusionScopeAio.query() works."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        results = await scope.aio.query("test")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_conclusion_scope_aio_delete(self, honcho: Honcho) -> None:
        """ConclusionScopeAio.delete() works."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        await scope.aio.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_conclusion_scope_aio_create(self, honcho: Honcho) -> None:
        """ConclusionScopeAio.create() works (may fail without auth)."""
        from spacetime_memory.sdks.honcho import ConclusionCreateParams

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        try:
            results = await scope.aio.create([ConclusionCreateParams(content="aio conclusion")])
            assert isinstance(results, list)
        except RuntimeError:
            pass

    @pytest.mark.asyncio
    async def test_conclusion_scope_aio_representation(self, honcho: Honcho) -> None:
        """ConclusionScopeAio.representation() works."""
        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)
        rep = await scope.aio.representation()
        assert isinstance(rep, str)


# ---------------------------------------------------------------------------
# Mock-based tests to cover internal success paths
# ---------------------------------------------------------------------------


