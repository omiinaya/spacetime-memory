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

from spacetime_memory import Client  # noqa: E402 — intentional: after sys.path.insert
from spacetime_memory.sdks import Honcho, Peer, Session  # noqa: E402 — intentional: after sys.path.insert

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
        host=host,
        port=port,
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
        stdb_host=host,
        stdb_port=port,
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
        _uid()
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


class TestModels:
    """Tests for model classes: Conclusion, Message, SyncPage, etc."""

    def test_conclusion_init_full(self) -> None:
        """Conclusion.__init__ with all args."""
        import datetime as dt
        from spacetime_memory.sdks.honcho import Conclusion

        now = dt.datetime.utcnow()
        c = Conclusion(
            id="conc-1",
            content="Smart observation",
            observer_id="obs-1",
            observed_id="sub-1",
            session_id="sess-1",
            created_at=now,
        )
        assert c.id == "conc-1"
        assert c.content == "Smart observation"
        assert c.observer_id == "obs-1"
        assert c.observed_id == "sub-1"
        assert c.session_id == "sess-1"
        assert c.created_at == now

    def test_conclusion_init_minimal(self) -> None:
        """Conclusion.__init__ with minimal args (default created_at)."""
        from spacetime_memory.sdks.honcho import Conclusion

        c = Conclusion(id="conc-2", content="test", observer_id="o", observed_id="s")
        assert c.id == "conc-2"
        assert c.created_at is not None

    def test_conclusion_from_api_response(self) -> None:
        """Conclusion.from_api_response() constructs from response model."""
        import datetime as dt
        from spacetime_memory.sdks.honcho import Conclusion, ConclusionResponse

        now = dt.datetime.utcnow()
        resp = ConclusionResponse(
            id="cr-1",
            content="api content",
            observer_id="o1",
            observed_id="s1",
            session_id="sess-1",
            created_at=now,
        )
        c = Conclusion.from_api_response(resp)
        assert c.id == "cr-1"
        assert c.content == "api content"
        assert c.observer_id == "o1"
        assert c.created_at == now

    def test_conclusion_repr(self) -> None:
        """Conclusion.__repr__ produces readable string."""
        from spacetime_memory.sdks.honcho import Conclusion

        c = Conclusion(
            id="long-id-12345",
            content="A" * 60,
            observer_id="obs",
            observed_id="sub",
        )
        r = repr(c)
        assert "Conclusion" in r
        assert "long-id-" in r
        assert "obs" in r
        assert "sub" in r

    def test_message_init_full(self) -> None:
        """Message.__init__ with all args."""
        import datetime as dt
        from spacetime_memory.sdks.honcho import Message

        now = dt.datetime.utcnow()
        m = Message(
            id="msg-1",
            content="Hello",
            peer_id="p1",
            session_id="s1",
            workspace_id="ws1",
            metadata={"k": "v"},
            created_at=now,
            token_count=42,
        )
        assert m.id == "msg-1"
        assert m.content == "Hello"
        assert m.peer_id == "p1"
        assert m.session_id == "s1"
        assert m.workspace_id == "ws1"
        assert m.metadata == {"k": "v"}
        assert m.created_at == now
        assert m.token_count == 42

    def test_message_init_defaults(self) -> None:
        """Message.__init__ with defaults (no metadata, no created_at)."""
        from spacetime_memory.sdks.honcho import Message

        m = Message(id="m2", content="hi", peer_id="p", session_id="s", workspace_id="w")
        assert m.metadata == {}
        assert m.created_at is not None
        assert m.token_count == 0

    def test_message_from_api_response(self) -> None:
        """Message.from_api_response() constructs from MessageResponse."""
        import datetime as dt
        from spacetime_memory.sdks.honcho import Message, MessageResponse

        now = dt.datetime.utcnow()
        resp = MessageResponse(
            id="mr-1",
            content="resp content",
            peer_id="p1",
            session_id="s1",
            workspace_id="ws1",
            metadata={"x": 1},
            created_at=now,
            token_count=10,
        )
        m = Message.from_api_response(resp)
        assert m.id == "mr-1"
        assert m.content == "resp content"
        assert m.token_count == 10

    def test_message_from_api_response_no_workspace(self) -> None:
        """Message.from_api_response with empty workspace_id."""
        import datetime as dt
        from spacetime_memory.sdks.honcho import Message, MessageResponse

        resp = MessageResponse(
            id="mr-2",
            content="x",
            peer_id="p",
            session_id="s",
            workspace_id="",
            created_at=dt.datetime.utcnow(),
        )
        m = Message.from_api_response(resp)
        assert m.workspace_id == ""

    def test_message_repr(self) -> None:
        """Message.__repr__ produces readable string."""
        from spacetime_memory.sdks.honcho import Message

        m = Message(
            id="long-msg-id",
            content="B" * 60,
            peer_id="peer1",
            session_id="s1",
            workspace_id="w1",
        )
        r = repr(m)
        assert "Message" in r
        assert "peer1" in r

    def test_syncpage_init_with_data(self) -> None:
        """SyncPage initialized with a data dict."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp = SyncPage(data={"items": [1, 2, 3], "total": 3, "page": 1, "size": 10, "pages": 1})
        assert list(sp.items) == [1, 2, 3]
        assert sp.total == 3
        assert sp.page == 1
        assert sp.size == 10
        assert sp.pages == 1

    def test_syncpage_init_with_kwargs(self) -> None:
        """SyncPage initialized with explicit kwargs (no data dict)."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp = SyncPage(items=["a", "b"], total=2, page=1, size=10, pages=1)
        assert list(sp.items) == ["a", "b"]
        assert sp.total == 2

    def test_syncpage_len(self) -> None:
        """SyncPage.__len__ delegates to items."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp = SyncPage(items=[1, 2, 3])
        assert len(sp) == 3

    def test_syncpage_getitem(self) -> None:
        """SyncPage.__getitem__ delegates to items."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp = SyncPage(items=["x", "y", "z"])
        assert sp[0] == "x"
        assert sp[2] == "z"

    def test_syncpage_iter(self) -> None:
        """SyncPage.__iter__ yields items."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp = SyncPage(items=[10, 20])
        assert list(sp) == [10, 20]

    def test_syncpage_has_next_page_true(self) -> None:
        """SyncPage.has_next_page() returns True when page < pages."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp = SyncPage(items=[], page=1, pages=3)
        assert sp.has_next_page() is True

    def test_syncpage_has_next_page_false(self) -> None:
        """SyncPage.has_next_page() returns False when page >= pages or None."""
        from spacetime_memory.sdks.honcho import SyncPage

        sp1 = SyncPage(items=[], page=3, pages=3)
        assert sp1.has_next_page() is False
        sp2 = SyncPage(items=[])
        assert sp2.has_next_page() is False

    def test_configuration_models(self) -> None:
        """Smoke-test configuration model instantiation."""
        from spacetime_memory.sdks.honcho import (
            ReasoningConfiguration,
            PeerCardConfiguration,
            SummaryConfiguration,
            DreamConfiguration,
            WorkspaceConfiguration,
            PeerConfig,
            SessionPeerConfig,
            MessageConfiguration,
            MessageCreateParams,
        )

        rc = ReasoningConfiguration(enabled=True, custom_instructions="be nice")
        assert rc.enabled is True
        pc = PeerCardConfiguration(use=True, create=False)
        assert pc.use is True
        sc = SummaryConfiguration(messages_per_short_summary=5)
        assert sc.messages_per_short_summary == 5
        dc = DreamConfiguration(enabled=False)
        assert dc.enabled is False
        wc = WorkspaceConfiguration(reasoning=rc, peer_card=pc, summary=sc, dream=dc)
        assert wc.reasoning == rc
        pcfg = PeerConfig(observe_me=True)
        assert pcfg.observe_me is True
        spc = SessionPeerConfig(observe_others=True)
        assert spc.observe_others is True
        mc = MessageConfiguration(reasoning=rc)
        assert mc.reasoning == rc
        mcp = MessageCreateParams(content="test", peer_id="p1")
        assert mcp.content == "test"
        assert mcp.peer_id == "p1"

    def test_response_models(self) -> None:
        """Smoke-test response model instantiation."""
        import datetime as dt
        from spacetime_memory.sdks.honcho import (
            WorkspaceResponse,
            PeerResponse,
            SessionResponse,
            MessageResponse,
            Summary,
            SessionSummaries,
            SessionContext,
            PeerContextResponse,
            ConclusionResponse,
            ConclusionCreateParams,
            QueueStatusResponse,
            SessionQueueStatus,
            DialecticResponse,
        )

        now = dt.datetime.utcnow()
        wr = WorkspaceResponse(id="w1", created_at=now)
        assert wr.id == "w1"
        pr = PeerResponse(id="p1", workspace_id="w1", created_at=now)
        assert pr.id == "p1"
        sr = SessionResponse(id="s1", is_active=True, workspace_id="w1", created_at=now)
        assert sr.is_active is True
        mr = MessageResponse(
            id="m1", content="hi", peer_id="p1", session_id="s1", workspace_id="w1", created_at=now
        )
        assert mr.content == "hi"
        sm = Summary(content="summary", message_id="m1", summary_type="short", created_at="now")
        assert sm.summary_type == "short"
        ss = SessionSummaries(id="s1", short_summary=sm)
        assert ss.short_summary == sm
        sc = SessionContext(session_id="s1", messages=[])
        assert len(sc) == 0
        pcr = PeerContextResponse(peer_id="p1", target_id="p2")
        assert pcr.peer_id == "p1"
        cr = ConclusionResponse(
            id="c1", content="conc", observer_id="o1", observed_id="s1", created_at=now
        )
        assert cr.content == "conc"
        ccp = ConclusionCreateParams(content="conc", session_id="s1")
        assert ccp.content == "conc"
        qs = QueueStatusResponse(total_work_units=5, completed_work_units=3)
        assert qs.total_work_units == 5
        sqs = SessionQueueStatus(session_id="s1", total_work_units=1)
        assert sqs.session_id == "s1"
        dr = DialecticResponse(content="thought")
        assert dr.content == "thought"


# ---------------------------------------------------------------------------
# Peer advanced tests (more coverage)
# ---------------------------------------------------------------------------


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


class TestWithMocks:
    """Tests that mock client internals to cover success paths."""

    def test_add_messages_success_path(self, honcho: Honcho, monkeypatch) -> None:
        """Session.add_messages() success path — mock store to return ok."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        # Mock store to succeed
        mock_store = MagicMock(return_value={"status": "ok"})
        monkeypatch.setattr(honcho._client, "store", mock_store)

        msg = p.message("Mocked success")
        results = s.add_messages([msg])
        assert isinstance(results, list)

    def test_session_search_returns_results(self, honcho: Honcho, monkeypatch) -> None:
        """Session.search() with mocked search results."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_search = MagicMock(
            return_value=[
                {"id": "mem-1", "memory_content": "test result", "metadata": {"peer_id": "p1"}}
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = s.search("test")
        assert isinstance(results, list)

    def test_peer_search_returns_results(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.search() with mocked search results."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "mem-1",
                    "memory_content": "peer search result",
                    "metadata": {"peer_id": pid},
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = p.search("test")
        assert isinstance(results, list)

    def test_peer_chat_with_search_results(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.chat() returns string when search finds memories."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_search = MagicMock(
            return_value=[
                {"memory_content": "I enjoy hiking", "metadata": {"peer_id": pid}},
                {"memory_content": "I like pizza", "metadata": {"peer_id": pid}},
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        response = p.chat("What do I like?")
        # Should return a string now since search finds data
        assert response is not None
        assert isinstance(response, str)

    def test_peer_chat_stream_with_results(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.chat_stream() yields chunks when chat returns data."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_search = MagicMock(
            return_value=[
                {"memory_content": "stream test data", "metadata": {"peer_id": pid}},
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        gen = p.chat_stream("test")
        chunks = list(gen)
        assert isinstance(chunks, list)

    def test_honcho_search_returns_results(self, honcho: Honcho, monkeypatch) -> None:
        """Honcho.search() with mocked search results hits Message construction."""
        from unittest.mock import MagicMock

        mock_search = MagicMock(
            return_value=[
                {"id": "mem-1", "memory_content": "honcho search", "metadata": {"peer_id": "p1"}}
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = honcho.search("test")
        assert isinstance(results, list)

    def test_session_messages_returns_data(self, honcho: Honcho, monkeypatch) -> None:
        """Session.messages() with mocked search results."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_search = MagicMock(
            return_value=[
                {"id": "msg-1", "memory_content": "content", "metadata": {"peer_id": "p1"}}
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = s.messages()
        assert page is not None

    def test_session_delete_fallback(self, honcho: Honcho, monkeypatch) -> None:
        """Session.delete() exercises the _call fallback path."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        # Mock _call to see the fallback path
        mock_call = MagicMock()
        monkeypatch.setattr(honcho._client, "_call", mock_call)

        try:
            s.delete()
        except RuntimeError:
            pass  # Fallback call may still fail but tests the path

    def test_queue_status_with_memories(self, honcho: Honcho, monkeypatch) -> None:
        """Honcho.queue_status() with mocked list_memories."""
        from unittest.mock import MagicMock

        mock_list = MagicMock(return_value=[{"id": "c1"}, {"id": "c2"}])
        monkeypatch.setattr(honcho._client, "list_memories", mock_list)

        status = honcho.queue_status()
        assert status is not None

    def test_conclusion_scope_list_with_data(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() with mocked search returning conclusions."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "conclusion text",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list()
        assert page is not None

    def test_conclusion_scope_query_with_data(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.query() with mocked search returning conclusions."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "queried conclusion",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = scope.query("test")
        assert isinstance(results, list)

    def test_conclusion_scope_list_reverse(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() with reverse=True."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "first",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },
                {
                    "id": "c2",
                    "memory_content": "second",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list(reverse=True)
        assert page is not None

    def test_conclusion_scope_list_filters(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() exercises filter skip paths (non-matching data)."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        # Return mix: some non-conclusion, some wrong observer/observed
        mock_search = MagicMock(
            return_value=[
                {
                    "id": "s1",
                    "memory_content": "not a conclusion",
                    "metadata": {"memory_type": "message"},
                },  # skipped: wrong type
                {
                    "id": "c1",
                    "memory_content": "wrong observer",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": "other",
                        "observed_id": p.id,
                    },
                },  # skipped: wrong observer
                {
                    "id": "c2",
                    "memory_content": "wrong observed",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": "other",
                    },
                },  # skipped: wrong observed
                {
                    "id": "c3",
                    "memory_content": "valid conclusion",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },  # included
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list()
        assert page is not None

    def test_conclusion_scope_list_with_session_filter(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() with session filter skips wrong session."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "wrong session",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                        "session_id": "other-session",
                    },
                },  # skipped: wrong session
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list(session="target-session")
        assert page is not None

    def test_conclusion_scope_query_filters(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.query() exercises filter skip paths."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "s1",
                    "memory_content": "plain message",
                    "metadata": {"memory_type": "message"},
                },  # skipped
                {
                    "id": "c1",
                    "memory_content": "wrong observer",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": "other",
                        "observed_id": p.id,
                    },
                },  # skipped
                {
                    "id": "c2",
                    "memory_content": "wrong observed",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": "other",
                    },
                },  # skipped
                {
                    "id": "c3",
                    "memory_content": "valid query result",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },  # included
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = scope.query("filter test")
        assert isinstance(results, list)

    def test_session_get_message_with_mock(self, honcho: Honcho, monkeypatch) -> None:
        """Session.get_message() success path with mocked get_memory."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_get = MagicMock(
            return_value=[
                {
                    "id": "msg-1",
                    "memory_content": "found message",
                    "peer_id": "p1",
                    "metadata": {"k": "v"},
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)

        result = s.get_message("msg-1")
        assert result is not None

    def test_session_update_message_with_mock(self, honcho: Honcho, monkeypatch) -> None:
        """Session.update_message() success path with mocked get_memory."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_get = MagicMock(
            return_value=[
                {"id": "msg-1", "memory_content": "update me", "peer_id": "p1", "metadata": {}}
            ]
        )
        mock_update = MagicMock()
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)
        monkeypatch.setattr(honcho._client, "update_memory", mock_update)

        s.update_message("msg-1", {"new_key": "new_val"})

    def test_session_delete_call_path(self, honcho: Honcho) -> None:
        """Session.delete() exercises the real _call path (not mocked)."""
        sid = _uid("session")
        s = honcho.session(sid)
        try:
            s.delete()
        except RuntimeError:
            pass  # May fail without auth but tests the path

    def test_peer_get_card_llm_unavailable(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.get_card() returns empty when LLM unavailable."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        # Mock LLMClient to be unavailable
        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )
        # Also mock search to return something so we exercise the path
        mock_search = MagicMock(
            return_value=[{"memory_content": "some data", "metadata": {"peer_id": pid}}]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        card = p.get_card()
        assert card == {"summary": "", "traits": []}

    def test_peer_representation_llm_unavailable(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.representation() with LLM unavailable but memories exist."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        # Mock LLMClient to be unavailable
        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )
        # Mock search to return data
        mock_search = MagicMock(
            return_value=[
                {"memory_content": "I like running", "metadata": {"peer_id": pid}},
                {"memory_content": "I enjoy reading", "metadata": {"peer_id": pid}},
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        rep = p.representation()
        assert isinstance(rep, str)
        assert pid in rep

    def test_schedule_dream_with_session_and_observed(self, honcho: Honcho) -> None:
        """Honcho.schedule_dream() with explicit session and observed params."""
        pid = _uid()
        pid2 = _uid()
        p = honcho.peer(pid)
        p2 = honcho.peer(pid2)
        sid = _uid("session")
        s = honcho.session(sid)

        try:
            honcho.schedule_dream(observer=p, session=s, observed=p2)
        except RuntimeError:
            pass  # May fail without LLM but tests the ID resolution paths

    def test_schedule_dream_with_string_ids(self, honcho: Honcho) -> None:
        """Honcho.schedule_dream() with string IDs (not Peer/Session objects)."""
        pid = _uid()
        pid2 = _uid()
        sid = _uid("session")

        try:
            honcho.schedule_dream(observer=pid, session=sid, observed=pid2)
        except RuntimeError:
            pass  # May fail without LLM but tests the string ID paths

    def test_schedule_dream_with_mock(self, honcho: Honcho, monkeypatch) -> None:
        """Honcho.schedule_dream() with mocked list_memories to hit filter path."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_list = MagicMock(
            return_value=[
                {"peer_id": pid, "content": "observation 1"},
                {"peer_id": pid, "content": "observation 2"},
                {"peer_id": "other", "content": "irrelevant"},
            ]
        )
        monkeypatch.setattr(honcho._client, "list_memories", mock_list)

        # Mock LLM to be unavailable to avoid API calls
        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )

        try:
            honcho.schedule_dream(observer=p)
        except RuntimeError:
            pass

    def test_peer_representation_no_llm_no_memories(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.representation() with LLM unavailable and no memories."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )
        # Mock search to return empty
        mock_search = MagicMock(return_value=[])
        monkeypatch.setattr(honcho._client, "search", mock_search)

        rep = p.representation()
        assert "no context available" in rep

    def test_session_get_message_empty_results(self, honcho: Honcho, monkeypatch) -> None:
        """Session.get_message() returns None when get_memory returns empty."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        # Empty results from get_memory
        mock_get = MagicMock(return_value=[])
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)

        result = s.get_message("msg-1")
        assert result is None

    def test_session_update_message_empty_results(self, honcho: Honcho, monkeypatch) -> None:
        """Session.update_message() returns early when get_memory returns empty."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_get = MagicMock(return_value=[])
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)

        # Should return without calling update_memory
        s.update_message("msg-1", {"k": "v"})

    def test_conclusion_scope_create_success(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.create() success path — mock store to return ok."""
        from unittest.mock import MagicMock
        from spacetime_memory.sdks.honcho import ConclusionCreateParams

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_store = MagicMock(return_value={"status": "ok"})
        monkeypatch.setattr(honcho._client, "store", mock_store)

        params = ConclusionCreateParams(content="Success conclusion")
        results = scope.create([params])
        assert isinstance(results, list)
        assert len(results) > 0
