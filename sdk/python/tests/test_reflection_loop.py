"""Tests for the ReflectionLoopMixin — autonomous reflection loop lifecycle.

Unit tests use the mock_http_client fixture (no SpacetimeDB required)
and monkeypatch to control _call / _query return values.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

# ============================================================================
# Helpers
# ============================================================================


def _reducer_resp() -> Mock:
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _make_session(
    session_id: str = "rs_001",
    workspace_id: str = "ws_001",
    peer_id: str = "agent-1",
    status: str = "running",
    cycle_count: int = 0,
) -> dict:
    """Build a reflection session dict for testing."""
    return {
        "id": session_id,
        "session_id": session_id,
        "workspace_id": workspace_id,
        "peer_id": peer_id,
        "status": status,
        "cycle_count": cycle_count,
        "max_cycles": 100,
        "config_json": json.dumps({
            "interval_minutes": 60,
            "focus_areas": [],
            "min_confidence": 0.3,
            "llm_model": "default",
        }),
        "started_at": 1_000_000,
        "updated_at": 1_000_000,
        "created_at": 1_000_000,
    }


def _make_insight(
    insight_id: str = "ins_001",
    session_id: str = "rs_001",
    workspace_id: str = "ws_001",
    content: str = "Test insight",
    confidence: float = 0.8,
    insight_type: str = "pattern",
) -> dict:
    """Build a reflection insight dict for testing."""
    return {
        "id": insight_id,
        "session_id": session_id,
        "workspace_id": workspace_id,
        "content": content,
        "confidence": confidence,
        "insight_type": insight_type,
        "source_memory_ids_json": json.dumps([]),
        "source_note_ids_json": json.dumps([]),
        "created_at": 1_000_000,
    }


# ============================================================================
# ReflectionLoopMixin tests
# ============================================================================


class TestReflectionLoopMixin:
    """ReflectionLoopMixin — create, start, store, complete, get, delete."""

    # ── create_reflection_session ─────────────────────────────────────────

    def test_create_reflection_session(self, mock_http_client):
        """create_reflection_session calls the reducer and returns status."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_reflection_session(
            workspace_id="ws_001",
            peer_id="agent-1",
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/create_reflection_session" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "agent-1", "{}"]

    def test_create_session_with_custom_config(self, mock_http_client):
        """create_reflection_session accepts custom config options."""
        mock_http_client._http.post.return_value = _reducer_resp()

        config = {
            "interval_minutes": 30,
            "max_cycles": 50,
            "focus_areas": ["user_preferences", "domain_knowledge"],
            "min_confidence": 0.5,
            "llm_model": "gpt-4o",
        }
        result = mock_http_client.create_reflection_session(
            workspace_id="ws_001",
            peer_id="agent-1",
            config=config,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        # Extract the config JSON from the args and verify
        assert body[0] == "ws_001"
        assert body[1] == "agent-1"
        sent_config = json.loads(body[2])
        assert sent_config["interval_minutes"] == 30
        assert sent_config["max_cycles"] == 50
        assert sent_config["focus_areas"] == ["user_preferences", "domain_knowledge"]
        assert sent_config["min_confidence"] == 0.5
        assert sent_config["llm_model"] == "gpt-4o"

    # ── start_reflection_cycle ───────────────────────────────────────────

    def test_start_reflection_cycle(self, mock_http_client):
        """start_reflection_cycle calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.start_reflection_cycle(
            workspace_id="ws_001",
            session_id="rs_001",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/start_reflection_cycle" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "rs_001"]

    # ── store_reflection_insight ─────────────────────────────────────────

    def test_store_and_get_insights(self, mock_http_client, monkeypatch):
        """Store insights via reducer then retrieve them via get_reflection_insights."""
        # Mock the store call
        mock_http_client._http.post.side_effect = None
        mock_http_client._http.post.return_value = _reducer_resp()

        # Store first insight
        result = mock_http_client.store_reflection_insight(
            workspace_id="ws_001",
            session_id="rs_001",
            content="User prefers async communication",
            confidence=0.85,
            insight_type="pattern",
            source_memory_ids=["mem-1"],
            source_note_ids=[],
        )
        assert result["status"] == "ok"

        # Store second insight
        result = mock_http_client.store_reflection_insight(
            workspace_id="ws_001",
            session_id="rs_001",
            content="Knowledge of Python 3.12 is current",
            confidence=0.9,
            insight_type="observation",
            source_memory_ids=["mem-2"],
            source_note_ids=[],
        )
        assert result["status"] == "ok"

        # Mock get_reflection_insights via monkeypatch on _call
        insights_data = [
            _make_insight("ins_001", "rs_001", "ws_001",
                          content="User prefers async communication",
                          confidence=0.85, insight_type="pattern"),
            _make_insight("ins_002", "rs_001", "ws_001",
                          content="Knowledge of Python 3.12 is current",
                          confidence=0.9, insight_type="observation"),
        ]
        monkeypatch.setattr(
            mock_http_client,
            "_call",
            lambda reducer, args: (
                {"data": json.dumps(insights_data)}
                if reducer == "get_reflection_insights"
                else {"status": "ok"}
            ),
        )

        insights = mock_http_client.get_reflection_insights("ws_001", "rs_001")
        assert len(insights) == 2
        assert insights[0]["content"] == "User prefers async communication"
        assert insights[0]["insight_type"] == "pattern"
        assert insights[1]["content"] == "Knowledge of Python 3.12 is current"
        assert insights[1]["insight_type"] == "observation"

    # ── complete_reflection_session ──────────────────────────────────────

    def test_complete_reflection_session(self, mock_http_client):
        """complete_reflection_session calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.complete_reflection_session(
            workspace_id="ws_001",
            session_id="rs_001",
            status="completed",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/complete_reflection_session" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "rs_001", "completed"]

    def test_complete_reflection_session_failed(self, mock_http_client):
        """complete_reflection_session accepts 'failed' status."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.complete_reflection_session(
            workspace_id="ws_001",
            session_id="rs_001",
            status="failed",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body[2] == "failed"

    # ── get_reflection_state ─────────────────────────────────────────────

    def test_get_reflection_state(self, mock_http_client, monkeypatch):
        """get_reflection_state returns combined session + insights snapshot."""
        sessions_data = [
            _make_session("rs_001", "ws_001", peer_id="agent-1",
                          status="running", cycle_count=3),
        ]
        insights_data = [
            _make_insight("ins_001", "rs_001", "ws_001",
                          content="Pattern A", confidence=0.8, insight_type="pattern"),
            _make_insight("ins_002", "rs_001", "ws_001",
                          content="Contradiction B", confidence=0.6, insight_type="contradiction"),
            _make_insight("ins_003", "rs_001", "ws_001",
                          content="Gap C", confidence=0.4, insight_type="gap"),
        ]

        def mock_call(reducer, args):
            if reducer == "get_reflection_sessions":
                return {"data": json.dumps(sessions_data)}
            if reducer == "get_reflection_insights":
                return {"data": json.dumps(insights_data)}
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        state = mock_http_client.get_reflection_state("ws_001", "rs_001")

        assert "session" in state
        assert state["session"]["id"] == "rs_001"
        assert state["insights_count"] == 3
        assert "type_breakdown" in state
        assert state["type_breakdown"].get("pattern") == 1
        assert state["type_breakdown"].get("contradiction") == 1
        assert state["type_breakdown"].get("gap") == 1
        assert "age_hours" in state
        assert isinstance(state["age_hours"], float)
        assert "recent_insights" in state
        assert len(state["recent_insights"]) == 3

    def test_get_reflection_state_session_not_found(self, mock_http_client, monkeypatch):
        """get_reflection_state returns error dict when session not found."""
        monkeypatch.setattr(
            mock_http_client,
            "_call",
            lambda reducer, args: {"data": json.dumps([])},
        )

        state = mock_http_client.get_reflection_state("ws_001", "rs_notfound")

        assert "error" in state
        assert "not found" in state["error"]

    # ── delete_reflection_session ────────────────────────────────────────

    def test_delete_session(self, mock_http_client, monkeypatch):
        """delete_reflection_session removes session;
        verify insights are gone afterward."""
        # Track calls
        delete_called = False

        def mock_call(reducer, args):
            nonlocal delete_called
            if reducer == "delete_reflection_session":
                delete_called = True
                return {"status": "ok"}
            if reducer == "get_reflection_sessions":
                return {"data": json.dumps([])}  # empty after delete
            if reducer == "get_reflection_insights":
                return {"data": json.dumps([])}  # empty after delete
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        # Delete the session
        result = mock_http_client.delete_reflection_session("ws_001", "rs_001")
        assert result["status"] == "ok"
        assert delete_called

        # Verify no sessions remain
        sessions = mock_http_client.get_reflection_sessions("ws_001")
        assert sessions == []

        # Verify no insights remain
        insights = mock_http_client.get_reflection_insights("ws_001", "rs_001")
        assert insights == []

    # ── insight_type_validation ───────────────────────────────────────────

    def test_insight_type_validation(self, mock_http_client):
        """All 6 insight types are accepted by the reducer."""
        insights_types = [
            "pattern",
            "contradiction",
            "gap",
            "observation",
            "connection",
            "synthesis",
        ]
        mock_http_client._http.post.return_value = _reducer_resp()

        for itype in insights_types:
            result = mock_http_client.store_reflection_insight(
                workspace_id="ws_001",
                session_id="rs_001",
                content=f"Test {itype}",
                confidence=0.7,
                insight_type=itype,
            )
            assert result["status"] == "ok", f"Failed for insight_type={itype}"

    # ── source_ids_serialization ──────────────────────────────────────────

    def test_source_ids_serialization(self, mock_http_client):
        """source_memory_ids and source_note_ids are serialized as JSON arrays."""
        mock_http_client._http.post.return_value = _reducer_resp()

        mem_ids = ["mem-1", "mem-2", "mem-3"]
        note_ids = ["note-a", "note-b"]

        result = mock_http_client.store_reflection_insight(
            workspace_id="ws_001",
            session_id="rs_001",
            content="Test with sources",
            confidence=0.75,
            insight_type="connection",
            source_memory_ids=mem_ids,
            source_note_ids=note_ids,
        )
        assert result["status"] == "ok"

        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        # Args index 5 = source_memory_ids (JSON string), 6 = source_note_ids (JSON string)
        assert json.loads(body[5]) == mem_ids
        assert json.loads(body[6]) == note_ids

    def test_source_ids_default_empty(self, mock_http_client):
        """source_memory_ids and source_note_ids default to empty lists."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.store_reflection_insight(
            workspace_id="ws_001",
            session_id="rs_001",
            content="Test with no sources",
            confidence=0.7,
            insight_type="observation",
        )
        assert result["status"] == "ok"

        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert json.loads(body[5]) == []
        assert json.loads(body[6]) == []

    # ── confidence_bounds ─────────────────────────────────────────────────

    def test_confidence_bounds(self, mock_http_client):
        """Confidence 0.0 and 1.0 are accepted."""
        mock_http_client._http.post.return_value = _reducer_resp()

        for conf in [0.0, 1.0]:
            result = mock_http_client.store_reflection_insight(
                workspace_id="ws_001",
                session_id="rs_001",
                content=f"Confidence {conf}",
                confidence=conf,
                insight_type="observation",
            )
            assert result["status"] == "ok"

            args, kwargs = mock_http_client._http.post.call_args
            body = json.loads(kwargs["content"])
            assert body[3] == conf

    # ── state_summary ─────────────────────────────────────────────────────

    def test_state_summary(self, mock_http_client, monkeypatch):
        """get_reflection_state provides type_breakdown and recent_insights."""
        sessions_data = [
            _make_session("rs_001", "ws_001", status="completed", cycle_count=5),
        ]
        insights_data = [
            _make_insight(f"ins_{i:03d}", "rs_001", "ws_001",
                          content=f"Insight {i}", confidence=0.5 + i * 0.1,
                          insight_type="pattern" if i % 2 == 0 else "observation")
            for i in range(8)  # 8 insights, recent should be last 5
        ]

        def mock_call(reducer, args):
            if reducer == "get_reflection_sessions":
                return {"data": json.dumps(sessions_data)}
            if reducer == "get_reflection_insights":
                return {"data": json.dumps(insights_data)}
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        state = mock_http_client.get_reflection_state("ws_001", "rs_001")

        # Type breakdown
        assert state["type_breakdown"]["pattern"] == 4
        assert state["type_breakdown"]["observation"] == 4

        # Recent insights (last 5)
        assert len(state["recent_insights"]) == 5
        assert state["recent_insights"][0]["id"] == "ins_003"
        assert state["recent_insights"][-1]["id"] == "ins_007"

        # Age hours is a positive float
        assert isinstance(state["age_hours"], float)
        assert state["age_hours"] > 0

    # ── sessions_isolated_by_workspace ────────────────────────────────────

    def test_sessions_isolated_by_workspace(self, mock_http_client, monkeypatch):
        """Sessions in different workspaces are isolated."""
        ws1_sessions = [
            _make_session("rs_001", "ws_001", peer_id="agent-1"),
            _make_session("rs_002", "ws_001", peer_id="agent-1"),
        ]
        ws2_sessions = [
            _make_session("rs_003", "ws_002", peer_id="agent-2"),
        ]

        def mock_call(reducer, args):
            if reducer == "get_reflection_sessions":
                workspace_id = args[0]
                if workspace_id == "ws_001":
                    return {"data": json.dumps(ws1_sessions)}
                elif workspace_id == "ws_002":
                    return {"data": json.dumps(ws2_sessions)}
                return {"data": json.dumps([])}
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        sessions_ws1 = mock_http_client.get_reflection_sessions("ws_001")
        sessions_ws2 = mock_http_client.get_reflection_sessions("ws_002")

        assert len(sessions_ws1) == 2
        assert len(sessions_ws2) == 1

        # No cross-contamination
        ws1_ids = {s["id"] for s in sessions_ws1}
        ws2_ids = {s["id"] for s in sessions_ws2}
        assert ws1_ids == {"rs_001", "rs_002"}
        assert ws2_ids == {"rs_003"}
        assert ws1_ids.isdisjoint(ws2_ids)

    # ── Error handling ────────────────────────────────────────────────────

    def test_create_session_reducer_error(self, mock_http_client):
        """create_reflection_session raises when reducer returns error."""
        mock_http_client._http.post.return_value = Mock(
            status_code=400,
            text="Reflection session limit reached",
            json=lambda: {"error": "Reflection session limit reached"},
        )

        with pytest.raises(Exception):
            mock_http_client.create_reflection_session(
                workspace_id="ws_001",
                peer_id="agent-1",
            )

    def test_get_reflection_sessions_after_delete(self, mock_http_client, monkeypatch):
        """get_reflection_sessions returns empty list after all sessions deleted."""
        # Start with sessions
        sessions_data = [
            _make_session("rs_001", "ws_001"),
        ]

        def mock_call(reducer, args):
            nonlocal sessions_data
            if reducer == "delete_reflection_session":
                # Simulate deletion
                sessions_data = []
                return {"status": "ok"}
            if reducer == "get_reflection_sessions":
                return {"data": json.dumps(sessions_data)}
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        # Before delete
        assert len(mock_http_client.get_reflection_sessions("ws_001")) == 1

        # Delete
        mock_http_client.delete_reflection_session("ws_001", "rs_001")

        # After delete
        assert mock_http_client.get_reflection_sessions("ws_001") == []

    def test_insights_isolated_by_session(self, mock_http_client, monkeypatch):
        """Insights from different sessions don't mix."""
        insight_data_rs1 = [
            _make_insight("ins_001", "rs_001", "ws_001", content="Session 1 insight"),
        ]
        insight_data_rs2 = [
            _make_insight("ins_010", "rs_002", "ws_001", content="Session 2 insight"),
        ]

        def mock_call(reducer, args):
            if reducer == "get_reflection_insights":
                session_id = args[1]
                if session_id == "rs_001":
                    return {"data": json.dumps(insight_data_rs1)}
                elif session_id == "rs_002":
                    return {"data": json.dumps(insight_data_rs2)}
                return {"data": json.dumps([])}
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        ins1 = mock_http_client.get_reflection_insights("ws_001", "rs_001")
        ins2 = mock_http_client.get_reflection_insights("ws_001", "rs_002")

        assert len(ins1) == 1
        assert len(ins2) == 1
        assert ins1[0]["session_id"] == "rs_001"
        assert ins2[0]["session_id"] == "rs_002"
        assert ins1[0]["id"] != ins2[0]["id"]

    def test_get_reflection_sessions_empty_result(self, mock_http_client, monkeypatch):
        """get_reflection_sessions returns empty list when no sessions exist."""
        monkeypatch.setattr(
            mock_http_client,
            "_call",
            lambda reducer, args: {"data": json.dumps([])},
        )

        sessions = mock_http_client.get_reflection_sessions("ws_empty")
        assert sessions == []

    def test_get_reflection_insights_empty_result(self, mock_http_client, monkeypatch):
        """get_reflection_insights returns empty list when no insights exist."""
        monkeypatch.setattr(
            mock_http_client,
            "_call",
            lambda reducer, args: {"data": json.dumps([])},
        )

        insights = mock_http_client.get_reflection_insights("ws_001", "rs_nonexistent")
        assert insights == []

    def test_get_reflection_state_with_no_insights(self, mock_http_client, monkeypatch):
        """get_reflection_state handles sessions with zero insights."""
        sessions_data = [
            _make_session("rs_001", "ws_001", status="completed", cycle_count=2),
        ]

        def mock_call(reducer, args):
            if reducer == "get_reflection_sessions":
                return {"data": json.dumps(sessions_data)}
            if reducer == "get_reflection_insights":
                return {"data": json.dumps([])}
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)

        state = mock_http_client.get_reflection_state("ws_001", "rs_001")

        assert state["session"]["id"] == "rs_001"
        assert state["insights_count"] == 0
        assert state["type_breakdown"] == {}
        assert state["recent_insights"] == []

    def test_create_reflection_session_invalid_json_config(self, mock_http_client):
        """create_reflection_session handles config with non-serializable values."""
        mock_http_client._http.post.return_value = _reducer_resp()

        class CustomObj:
            pass

        config = {
            "interval_minutes": 60,
            "custom": CustomObj(),  # This will cause json.dumps to fail
        }

        with pytest.raises(TypeError):
            mock_http_client.create_reflection_session(
                workspace_id="ws_001",
                peer_id="agent-1",
                config=config,
            )
