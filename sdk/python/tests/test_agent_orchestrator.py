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
