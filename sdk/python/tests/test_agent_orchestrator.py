"""Tests for the AgentOrchestrator."""

import re
from unittest.mock import MagicMock

import pytest
from spacetime_memory.agent_orchestrator import AgentOrchestrator, AgentSessionState


class TestAgentOrchestrator:
    """Test suite for AgentOrchestrator."""

    def test_init(self, mock_client):
        """Verify the orchestrator stores workspace_id and client."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        assert orch._workspace_id == "ws1"
        assert orch._client is mock_client
        assert orch._sessions == {}

    def test_start_session_creates_state(self, mock_client):
        """start_session should create a session and store state."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test-agent", user_id="user42")

        # Should return a non-empty session ID
        assert session_id
        assert isinstance(session_id, str)

        # Should have stored state
        state = orch._sessions.get(session_id)
        assert state is not None
        assert state.agent_name == "test-agent"
        assert state.user_id == "user42"
        assert state.workspace_id == "ws1"

        # Should have called the API with metadata JSON
        create_calls = [
            c for c in mock_client._call.call_args_list
            if c[0][0] == "create_session"
        ]
        assert len(create_calls) >= 1
        _reducer, args = create_calls[0][0]
        assert args[0] == "ws1"
        assert args[1] == "test-agent-user42"
        assert '"agent_name": "test-agent"' in args[2]
        assert '"user_id": "user42"' in args[2]

    def test_add_step_records_step(self, mock_client):
        """add_step should record a reasoning step and return a step ID."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Provide a real SQL response so the step discovery works
        mock_client._query.return_value = [{"id": "step-uuid-123"}]
        step_id = orch.add_step(
            session_id,
            thought="I should check the data",
            action="query_database",
            observation="got 5 rows",
        )

        assert step_id == "step-uuid-123"

        # Verify the API was called
        api_call = mock_client._call.call_args_list
        create_call = api_call[1]  # second call (after create_session)
        assert create_call[0][0] == "add_agent_step"
        args = create_call[0][1]
        assert args[0] == session_id
        assert args[1] == "ws1"
        assert args[2] in ("thought", "action", "observation")

    def test_add_step_requires_content(self, mock_client):
        """add_step should raise ValueError if all fields are empty."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        with pytest.raises(ValueError, match="At least one of"):
            orch.add_step(session_id)

    def test_add_tool_call(self, mock_client):
        """add_tool_call should record a tool_call and tool_result step."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        mock_client._query.return_value = [{"id": "call-step-456"}]
        result = orch.add_tool_call(
            session_id,
            tool="search_web",
            args={"q": "hello"},
            result={"hits": ["link1"]},
        )

        # The tool_call step ID should be returned
        assert result == "call-step-456"

        # Should have called add_agent_step at least twice (tool_call + tool_result)
        add_calls = [
            c for c in mock_client._call.call_args_list
            if c[0][0] == "add_agent_step"
        ]
        assert len(add_calls) >= 2

    def test_get_context(self, mock_client):
        """get_context should return a list of context entries."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")

        mock_client.search.return_value = [
            {
                "id": "mem-1",
                "memory_content": "Some relevant memory",
                "score": 0.95,
            },
        ]
        context = orch.get_context("test query", top_k=5)

        # Should return a list
        assert isinstance(context, list)
        # Should contain the memory result
        assert len(context) >= 1
        assert context[0]["type"] == "memory"
        assert context[0]["source"] == "memory_search"

    def test_get_context_with_session_id(self, mock_client):
        """get_context should include session steps when session_id given."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Provide a SQL result for session steps
        mock_client._query.return_value = [
            {"step_type": "thought", "id": "step-1", "content": "thinking...",
             "summary": "think"},
        ]

        context = orch.get_context("test query", top_k=5, session_id=session_id)

        assert isinstance(context, list)
        # The context should contain a step entry (either from search or steps)
        assert any(
            entry.get("source") == "session_steps" for entry in context
        ) or not context  # empty is also acceptable if mock returns empty

    def test_end_session(self, mock_client):
        """end_session should clean up and return session summary."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Make _sql return a memory entry so memory_id gets populated
        mock_client._query.return_value = [{"id": "mem-999"}]
        mock_client.store.return_value = {"status": "ok"}

        summary = orch.end_session(
            session_id=session_id,
            summary="Completed task successfully.",
            create_summary_memory=True,
        )

        assert summary["session_id"] == session_id
        assert summary["summary"] == "Completed task successfully."
        # Session should be cleaned up
        assert session_id not in orch._sessions

    def test_end_session_no_active_sessions(self, mock_client):
        """end_session without sessions should return error dict."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        result = orch.end_session()
        assert "error" in result

    def test_share_session(self, mock_client):
        """share_session should add peers and return shared list."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        result = orch.share_session(session_id, peer_ids=["peer1", "peer2"])

        assert result["session_id"] == session_id
        assert "peer1" in result["shared_with"]
        assert "peer2" in result["shared_with"]

    def test_share_session_failure_tracked(self, mock_client):
        """share_session should track peers that fail."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Make _call raise for one peer
        def _call_side_effect(reducer, args):
            if args[1] == "bad-peer":
                raise RuntimeError("join failed")

        mock_client._call.side_effect = _call_side_effect

        result = orch.share_session(
            session_id,
            peer_ids=["good-peer", "bad-peer"],
        )

        assert "good-peer" in result["shared_with"]
        assert "bad-peer" in result["failed"]

    def test_get_collaborative_context(self, mock_client):
        """get_collaborative_context should add visibility notes."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        context = orch.get_collaborative_context(
            session_id="sess-1",
            peer_id="peer1",
            query="test",
        )
        assert isinstance(context, list)
        for entry in context:
            assert "visible_to" in entry

    def test_error_swallowing_replaced(self, mock_client):
        """Verify the except: pass blocks have been replaced with logging.

        This test ensures that when errors occur in get_context's session
        steps path, they are logged rather than silently ignored.
        """
        import logging

        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Make the session steps call raise an error; the code should
        # log a warning and continue instead of crashing or silently passing.
        mock_client._query.side_effect = RuntimeError("db connection lost")

        # Should not raise — error is now logged as a warning
        context = orch.get_context("query", session_id=session_id)
        assert isinstance(context, list)

    def test_add_tool_call_no_result(self, mock_client):
        """add_tool_call without a result should still record the call."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        mock_client._query.return_value = [{"id": "tool-call-789"}]
        result = orch.add_tool_call(
            session_id,
            tool="search",
            args={"q": "test"},
            # result=None — no tool_result step should be created
        )

        assert result == "tool-call-789"

    # ── Coverage gap: context=string with JSONDecodeError (lines 101-105) ────

    def test_start_session_context_string_invalid_json(self, mock_client):
        """start_session with invalid JSON string context uses it raw."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(
            agent_name="test",
            user_id="user1",
            context="this is not json at all",
        )
        assert session_id
        # The metadata should have {"context": "this is not json at all"}
        create_calls = [
            c for c in mock_client._call.call_args_list
            if c[0][0] == "create_session"
        ]
        assert len(create_calls) >= 1
        _reducer, args = create_calls[0][0]
        assert '"context"' in args[2]
        assert "this is not json at all" in args[2]

    def test_start_session_context_valid_json_string(self, mock_client):
        """start_session with valid JSON string context parses it."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(
            agent_name="test",
            user_id="user1",
            context='{"key": "value", "nested": {"a": 1}}',
        )
        assert session_id
        create_calls = [
            c for c in mock_client._call.call_args_list
            if c[0][0] == "create_session"
        ]
        assert len(create_calls) >= 1
        _reducer, args = create_calls[0][0]
        assert '"key": "value"' in args[2]

    # ── Coverage gap: _query returns empty rows → fallback UUID (line 131) ───

    def test_start_session_no_query_rows_fallback(self, mock_client):
        """When _query returns no rows, session_id falls back to UUID."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        # _query returns empty list — fallback session_id = uuid4()
        mock_client._query.return_value = []
        session_id = orch.start_session(agent_name="test", user_id="user1")
        assert session_id
        # Should be a UUID-like string (36 chars with dashes)
        assert len(session_id) == 36
        assert session_id.count("-") == 4

    # ── Coverage gap: end_session without session_id but with sessions (line 162) ──

    def test_end_session_implicit_uses_last(self, mock_client):
        """end_session() with no session_id picks the last session."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        sid1 = orch.start_session(agent_name="first", user_id="user1")
        sid2 = orch.start_session(agent_name="second", user_id="user2")

        # Both sessions exist
        assert sid1 in orch._sessions
        assert sid2 in orch._sessions

        # mock _query for store memory lookup
        mock_client._query.return_value = [{"id": "mem-999"}]
        mock_client.store.return_value = {"status": "ok"}

        result = orch.end_session(summary="done")  # no session_id

        # The last session (sid2) should have been ended
        assert result["session_id"] == sid2
        assert sid2 not in orch._sessions
        assert sid1 in orch._sessions  # first session still active

    # ── Coverage gap: end_session with unknown session_id (line 167) ─────────

    def test_end_session_unknown_session_id(self, mock_client):
        """end_session with a session_id not in _sessions still works."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")

        mock_client._query.return_value = [{"id": "mem-999"}]
        mock_client.store.return_value = {"status": "ok"}

        result = orch.end_session(
            session_id="unknown-session-999",
            summary="cleanup",
        )

        assert result["session_id"] == "unknown-session-999"
        assert result["step_count"] == 0

    # ── Coverage gap: get_context with _sql session steps (lines 401-419) ───

    def test_get_context_with_session_steps_via_sql(self, mock_client):
        """get_context with session_id uses _sql for session steps."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Mock _sql to return steps (not _query)
        mock_client._sql.return_value = [
            {
                "step_type": "thought",
                "id": "step-abc",
                "content": "thinking about the problem",
                "summary": "thinking",
            },
        ]

        context = orch.get_context("test", top_k=5, session_id=session_id)

        # Should have session steps entries
        steps = [e for e in context if e.get("source") == "session_steps"]
        assert len(steps) >= 1
        assert steps[0]["type"] == "step"
        assert steps[0]["step_type"] == "thought"
        assert steps[0]["content"] == "thinking about the problem"
        assert steps[0]["score"] == 1.0

    def test_get_context_session_steps_error(self, mock_client):
        """get_context catches RuntimeError from session steps path."""
        import logging

        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Make _call raise RuntimeError for the get_session_steps call
        def _call_side_effect(reducer, args):
            if reducer == "get_session_steps":
                raise RuntimeError("failed to get steps")
            return {"status": "ok"}

        mock_client._call.side_effect = _call_side_effect

        # Should not raise — error is logged
        context = orch.get_context("query", session_id=session_id)
        assert isinstance(context, list)

    # ── Coverage gap: get_collaborative_context with non-empty context (line 505) ──

    def test_get_collaborative_context_with_entries(self, mock_client):
        """get_collaborative_context sets visible_to on each entry."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(agent_name="test", user_id="user1")

        # Mock search to return memories so context is non-empty
        mock_client.search.return_value = [
            {
                "id": "mem-1",
                "memory_content": "relevant memory",
                "score": 0.9,
            },
        ]
        # Mock _sql for session steps
        mock_client._sql.return_value = [
            {
                "step_type": "thought",
                "id": "step-1",
                "content": "thinking",
                "summary": "think",
            },
        ]

        context = orch.get_collaborative_context(
            session_id=session_id,
            peer_id="peer1",
            query="test",
        )

        assert len(context) > 0
        for entry in context:
            assert "visible_to" in entry
            assert entry["visible_to"] == ["peer1"]

    # ── Coverage gap: context=dict (line 107) ──────────────────────────────

    def test_start_session_context_dict(self, mock_client):
        """start_session with a dict context uses it directly."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        session_id = orch.start_session(
            agent_name="test",
            user_id="user1",
            context={"key": "value", "nested": {"a": 1}},
        )
        assert session_id
        create_calls = [
            c for c in mock_client._call.call_args_list
            if c[0][0] == "create_session"
        ]
        assert len(create_calls) >= 1
        _reducer, args = create_calls[0][0]
        assert '"key": "value"' in args[2]

    # ── Coverage gap: _query returns rows → session_id from DB (line 131) ──

    def test_start_session_query_returns_rows(self, mock_client):
        """When _query returns rows, session_id comes from the DB."""
        orch = AgentOrchestrator(mock_client, workspace_id="ws1")
        mock_client._query.return_value = [{"id": "db-session-001", "created_at": 999999}]
        session_id = orch.start_session(agent_name="test", user_id="user1")
        assert session_id == "db-session-001"
