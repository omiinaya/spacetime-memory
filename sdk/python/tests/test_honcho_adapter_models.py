"""
Model tests - Pydantic models and response types.

Integration tests for the Honcho adapter - split from the original
test_honcho_adapter.py.  These tests require a running SpacetimeDB instance
on localhost:3001 (handled by the ``stdb_session`` fixture in conftest.py).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
]


def _uid(prefix: str = "honcho-test") -> str:
    """Generate a unique ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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
            DreamConfiguration,
            MessageConfiguration,
            MessageCreateParams,
            PeerCardConfiguration,
            PeerConfig,
            ReasoningConfiguration,
            SessionPeerConfig,
            SummaryConfiguration,
            WorkspaceConfiguration,
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
            ConclusionCreateParams,
            ConclusionResponse,
            DialecticResponse,
            MessageResponse,
            PeerContextResponse,
            PeerResponse,
            QueueStatusResponse,
            SessionContext,
            SessionQueueStatus,
            SessionResponse,
            SessionSummaries,
            Summary,
            WorkspaceResponse,
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


