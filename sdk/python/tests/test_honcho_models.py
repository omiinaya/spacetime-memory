"""Unit tests for the Honcho adapter models (_models.py).

Tests Pydantic models and plain classes: configuration models,
response models, SyncPage, Conclusion, Message, and helpers.
"""

from __future__ import annotations

import datetime

import pytest

from spacetime_memory.sdks.honcho._models import (
    Conclusion,
    ConclusionCreateParams,
    ConclusionResponse,
    DialecticResponse,
    DreamConfiguration,
    Message,
    MessageConfiguration,
    MessageCreateParams,
    MessageResponse,
    PeerCardConfiguration,
    PeerConfig,
    PeerContextResponse,
    PeerResponse,
    QueueStatusResponse,
    ReasoningConfiguration,
    SessionConfiguration,
    SessionConfigurationResponse,
    SessionContext,
    SessionPeerConfig,
    SessionQueueStatus,
    SessionResponse,
    SessionSummaries,
    Summary,
    SummaryConfiguration,
    SyncPage,
    WorkspaceConfiguration,
    WorkspaceConfigurationResponse,
    WorkspaceResponse,
)

pytestmark = pytest.mark.unit


# ── Configuration models ───────────────────────────────────────────────────


class TestConfigModels:
    def test_reasoning_config_defaults(self):
        rc = ReasoningConfiguration()
        assert rc.enabled is None
        assert rc.custom_instructions is None

    def test_reasoning_config_with_values(self):
        rc = ReasoningConfiguration(enabled=True, custom_instructions="Be logical")
        assert rc.enabled is True
        assert rc.custom_instructions == "Be logical"

    def test_peer_card_config_defaults(self):
        pcc = PeerCardConfiguration()
        assert pcc.use is None
        assert pcc.create is None

    def test_summary_config_defaults(self):
        sc = SummaryConfiguration()
        assert sc.enabled is None
        assert sc.messages_per_short_summary is None

    def test_dream_config_defaults(self):
        dc = DreamConfiguration()
        assert dc.enabled is None

    def test_workspace_config_has_sub_configs(self):
        wc = WorkspaceConfiguration()
        assert wc.reasoning is None
        assert wc.peer_card is None
        assert wc.summary is None
        assert wc.dream is None

    def test_workspace_config_with_all(self):
        wc = WorkspaceConfiguration(
            reasoning=ReasoningConfiguration(enabled=True),
            peer_card=PeerCardConfiguration(use=True),
            summary=SummaryConfiguration(enabled=True),
            dream=DreamConfiguration(enabled=True),
        )
        assert wc.reasoning.enabled is True
        assert wc.peer_card.use is True
        assert wc.summary.enabled is True
        assert wc.dream.enabled is True

    def test_workspace_config_response_alias(self):
        assert WorkspaceConfigurationResponse is WorkspaceConfiguration

    def test_session_config_alias(self):
        assert SessionConfiguration is WorkspaceConfiguration

    def test_session_config_response_alias(self):
        assert SessionConfigurationResponse is WorkspaceConfiguration

    def test_peer_config_defaults(self):
        pc = PeerConfig()
        assert pc.observe_me is None

    def test_peer_config_with_value(self):
        pc = PeerConfig(observe_me=True)
        assert pc.observe_me is True

    def test_session_peer_config_defaults(self):
        spc = SessionPeerConfig()
        assert spc.observe_others is None
        assert spc.observe_me is None

    def test_message_config_defaults(self):
        mc = MessageConfiguration()
        assert mc.reasoning is None


# ── Response models ────────────────────────────────────────────────────────


class TestResponseModels:
    def test_workspace_response(self):
        now = datetime.datetime.utcnow()
        wr = WorkspaceResponse(id="ws-1", created_at=now)
        assert wr.id == "ws-1"
        assert wr.metadata == {}
        assert wr.configuration is not None

    def test_peer_response(self):
        now = datetime.datetime.utcnow()
        pr = PeerResponse(id="alice", workspace_id="ws-1", created_at=now)
        assert pr.id == "alice"
        assert pr.workspace_id == "ws-1"
        assert isinstance(pr.configuration, PeerConfig)

    def test_session_response(self):
        now = datetime.datetime.utcnow()
        sr = SessionResponse(id="s1", is_active=True, workspace_id="ws-1", created_at=now)
        assert sr.id == "s1"
        assert sr.is_active is True

    def test_message_response(self):
        now = datetime.datetime.utcnow()
        mr = MessageResponse(
            id="m1", content="Hello", peer_id="alice",
            session_id="s1", created_at=now, workspace_id="ws-1",
        )
        assert mr.content == "Hello"
        assert mr.token_count == 0

    def test_message_create_params(self):
        mcp = MessageCreateParams(content="Hi", peer_id="bob")
        assert mcp.content == "Hi"
        assert mcp.peer_id == "bob"
        assert mcp.metadata is None
        assert mcp.created_at is None

    def test_message_create_params_with_all(self):
        now = datetime.datetime.utcnow()
        mcp = MessageCreateParams(
            content="Hi",
            peer_id="bob",
            metadata={"foo": "bar"},
            configuration=MessageConfiguration(),
            created_at=now,
        )
        assert mcp.metadata == {"foo": "bar"}
        assert mcp.created_at == now

    def test_summary_model(self):
        s = Summary(content="summary", message_id="m1", summary_type="short", created_at="now")
        assert s.content == "summary"
        assert s.token_count == 0

    def test_session_summaries(self):
        ss = SessionSummaries(id="s1")
        assert ss.id == "s1"
        assert ss.short_summary is None

    def test_session_context(self):
        sc = SessionContext(session_id="s1")
        assert sc.session_id == "s1"
        assert len(sc) == 0

    def test_session_context_with_messages(self):
        sc = SessionContext(session_id="s1", messages=["msg1"])
        assert len(sc) == 1

    def test_peer_context_response(self):
        pcr = PeerContextResponse(peer_id="alice", target_id="bob")
        assert pcr.peer_id == "alice"
        assert pcr.target_id == "bob"
        assert pcr.representation is None

    def test_conclusion_response(self):
        now = datetime.datetime.utcnow()
        cr = ConclusionResponse(
            id="c1", content="test", observer_id="obs",
            observed_id="obd", created_at=now,
        )
        assert cr.content == "test"

    def test_conclusion_create_params(self):
        ccp = ConclusionCreateParams(content="test")
        assert ccp.content == "test"
        assert ccp.session_id is None

    def test_session_queue_status_defaults(self):
        sqs = SessionQueueStatus()
        assert sqs.total_work_units == 0
        assert sqs.session_id is None

    def test_queue_status_response_defaults(self):
        qsr = QueueStatusResponse()
        assert qsr.total_work_units == 0
        assert qsr.sessions is None

    def test_queue_status_response_with_sessions(self):
        qsr = QueueStatusResponse(sessions={"s1": SessionQueueStatus()})
        assert "s1" in qsr.sessions

    def test_dialectic_response(self):
        dr = DialecticResponse(content="reply")
        assert dr.content == "reply"


# ── SyncPage ───────────────────────────────────────────────────────────────


class TestSyncPage:
    def test_empty_construction(self):
        sp = SyncPage()
        assert sp.items == []
        assert sp.total is None

    def test_from_data_dict(self):
        sp = SyncPage(data={"items": ["a", "b"], "total": 2, "page": 1, "size": 10, "pages": 1})
        assert len(sp.items) == 2
        assert sp.total == 2
        assert sp.page == 1

    def test_iteration(self):
        sp = SyncPage(data={"items": ["x", "y"]})
        assert list(sp) == ["x", "y"]

    def test_getitem(self):
        sp = SyncPage(data={"items": ["a", "b", "c"]})
        assert sp[1] == "b"

    def test_len(self):
        sp = SyncPage(data={"items": [1, 2, 3]})
        assert len(sp) == 3

    def test_has_next_page_true(self):
        sp = SyncPage(data={"items": ["a"], "page": 1, "pages": 2})
        assert sp.has_next_page() is True

    def test_has_next_page_false(self):
        sp = SyncPage(data={"items": ["a"], "page": 2, "pages": 2})
        assert sp.has_next_page() is False

    def test_has_next_page_none(self):
        sp = SyncPage()
        assert sp.has_next_page() is False


# ── Conclusion ─────────────────────────────────────────────────────────────


class TestConclusionModel:
    def test_minimal_construction(self):
        c = Conclusion(id="c1", content="test", observer_id="obs", observed_id="obd")
        assert c.id == "c1"
        assert c.content == "test"
        assert c.session_id is None

    def test_with_session_id(self):
        c = Conclusion(
            id="c1", content="test", observer_id="obs",
            observed_id="obd", session_id="s1",
        )
        assert c.session_id == "s1"

    def test_from_api_response(self):
        now = datetime.datetime.utcnow()
        cr = ConclusionResponse(
            id="c1", content="api content", observer_id="obs",
            observed_id="obd", created_at=now,
        )
        c = Conclusion.from_api_response(cr)
        assert c.content == "api content"
        assert c.id == "c1"

    def test_repr(self):
        c = Conclusion(id="abc12345", content="some content here", observer_id="obs", observed_id="obd")
        r = repr(c)
        assert "abc12345" in r
        assert "some content here" in r


# ── Message ────────────────────────────────────────────────────────────────


class TestMessageModel:
    def test_minimal_construction(self):
        m = Message(id="m1", content="Hi", peer_id="alice", session_id="s1", workspace_id="ws-1")
        assert m.content == "Hi"
        assert m.metadata == {}
        assert m.token_count == 0

    def test_with_all_fields(self):
        m = Message(
            id="m1", content="Hi", peer_id="alice",
            session_id="s1", workspace_id="ws-1",
            metadata={"key": "val"}, token_count=42,
        )
        assert m.metadata == {"key": "val"}
        assert m.token_count == 42

    def test_from_api_response(self):
        now = datetime.datetime.utcnow()
        mr = MessageResponse(
            id="m1", content="Hello", peer_id="alice",
            session_id="s1", workspace_id="ws-1",
            created_at=now, token_count=7,
        )
        m = Message.from_api_response(mr)
        assert m.content == "Hello"
        assert m.token_count == 7
        assert m.workspace_id == "ws-1"

    def test_repr(self):
        m = Message(id="12345678", content="Hello there", peer_id="alice",
                     session_id="s1", workspace_id="ws-1")
        r = repr(m)
        assert "12345678" in r
        assert "Hello there" in r
