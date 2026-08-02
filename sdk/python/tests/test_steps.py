"""Tests for spacetime_memory.agent_orchestrator._steps — StepRecordingMixin.

All tests use mocked client — no live SpacetimeDB required.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestAddStep:
    """Recording chain-of-thought reasoning steps."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.agent_orchestrator._session import AgentSessionState
        from spacetime_memory.agent_orchestrator._steps import StepRecordingMixin

        m = StepRecordingMixin()
        m._client = MagicMock()
        m._workspace_id = "ws-1"
        m._sessions = {}
        # Create a session state
        state = AgentSessionState(session_id="session-1", agent_name="test-agent", user_id="user-1", workspace_id="ws-1")
        m._sessions["session-1"] = state
        return m

    def test_add_step_with_thought(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "step-1"}]
        step_id = mixin.add_step(session_id="session-1", thought="I think therefore I am")
        assert step_id == "step-1"
        mixin._client._call.assert_called_once()
        args = mixin._client._call.call_args[0]
        assert args[0] == "add_agent_step"
        assert args[1][2] == "thought"
        assert "## Thought" in args[1][3]

    def test_add_step_with_action(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "step-2"}]
        step_id = mixin.add_step(session_id="session-1", action="search memory")
        assert step_id == "step-2"
        args = mixin._client._call.call_args[0]
        assert args[1][2] == "action"

    def test_add_step_with_observation(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "step-3"}]
        step_id = mixin.add_step(session_id="session-1", observation="saw result X")
        assert step_id == "step-3"
        args = mixin._client._call.call_args[0]
        assert args[1][2] == "observation"

    def test_add_step_all_fields(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "step-4"}]
        step_id = mixin.add_step(
            session_id="session-1",
            thought="I need to search",
            action="calling search",
            observation="got results",
        )
        assert step_id == "step-4"
        args = mixin._client._call.call_args[0]
        # When both thought and action present, step_type is action (action > thought)
        assert args[1][2] == "action"
        assert "## Thought" in args[1][3]
        assert "## Action" in args[1][3]
        assert "## Observation" in args[1][3]

    def test_add_step_no_content_raises(self, mixin):
        with pytest.raises(ValueError, match="At least one"):
            mixin.add_step(session_id="session-1")

    def test_add_step_links_to_parent(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "step-5"}]
        # First step
        mixin.add_step(session_id="session-1", thought="first")
        # Second step should link to first as parent
        mixin._client._query.return_value = [{"id": "step-6"}]
        step_id = mixin.add_step(session_id="session-1", thought="second")
        assert step_id == "step-6"
        # Check that parent_step_id was set (second call has parent from last_step_id)
        calls = mixin._client._call.call_args_list
        assert len(calls) == 2
        # First call: parent_step_id = "" (index 5 in the params list)
        assert calls[0][0][1][5] == ""
        # Second call: parent_step_id = "step-5"
        assert calls[1][0][1][5] == "step-5"

    def test_add_step_increments_step_count(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "step-n"}]
        mixin.add_step(session_id="session-1", thought="first")
        assert mixin._sessions["session-1"].step_count == 1
        mixin.add_step(session_id="session-1", thought="second")
        assert mixin._sessions["session-1"].step_count == 2


class TestAddToolCall:
    """Recording tool calls as reasoning steps."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.agent_orchestrator._session import AgentSessionState
        from spacetime_memory.agent_orchestrator._steps import StepRecordingMixin

        m = StepRecordingMixin()
        m._client = MagicMock()
        m._workspace_id = "ws-1"
        state = AgentSessionState(session_id="session-1", agent_name="test-agent", user_id="user-1", workspace_id="ws-1")
        m._sessions = {"session-1": state}
        return m

    def test_add_tool_call_no_result(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "tc-1"}]
        step_id = mixin.add_tool_call(session_id="session-1", tool="search", args={"q": "test"})
        assert step_id == "tc-1"
        mixin._client._call.assert_called_once()
        args = mixin._client._call.call_args[0]
        assert args[1][2] == "tool_call"

    def test_add_tool_call_with_result(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        # First _call for tool_call, second _call for tool_result
        # First two _query calls return tool_call step, last returns []
        query_results = iter([
            [{"id": "tc-1"}],  # tool_call step discovery
            [],  # unused
        ])
        mixin._client._query = MagicMock(side_effect=lambda *a, **kw: next(query_results))

        step_id = mixin.add_tool_call(
            session_id="session-1",
            tool="search",
            args={"q": "hello"},
            result="found 5 results",
        )
        assert step_id == "tc-1"
        # Should have called _call twice
        assert mixin._client._call.call_count == 2
        calls = mixin._client._call.call_args_list
        assert calls[0][0][1][2] == "tool_call"
        assert calls[1][0][1][2] == "tool_result"

    def test_add_tool_call_args_string(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "tc-2"}]
        step_id = mixin.add_tool_call(
            session_id="session-1",
            tool="search",
            args='{"q": "test"}',
        )
        assert step_id == "tc-2"
        # args are passed as str directly
        # The content is double-JSON-encoded: json.dumps({"name": tool, "args": args_str})
        # where args_str is already a JSON string, so its quotes are escaped
        args = mixin._client._call.call_args[0]
        assert '"name"' in args[1][3]
        assert '"args"' in args[1][3]
        assert args[1][3] == '{"name": "search", "args": "{\\"q\\": \\"test\\"}"}'

    def test_tool_call_updates_last_step_id(self, mixin):
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [{"id": "tc-3"}]
        mixin.add_tool_call(session_id="session-1", tool="read")
        assert mixin._sessions["session-1"].last_step_id == "tc-3"

    def test_add_tool_call_with_result_json_serializable(self, mixin):
        """Result dicts are JSON-serialized."""
        mixin._client._call.return_value = {"status": "ok"}
        query_results = iter([
            [{"id": "tc-4"}],
            [],
        ])
        mixin._client._query = MagicMock(side_effect=lambda *a, **kw: next(query_results))

        step_id = mixin.add_tool_call(
            session_id="session-1",
            tool="search",
            args={"q": "test"},
            result=[{"id": "mem-1"}],
        )
        assert step_id == "tc-4"
        calls = mixin._client._call.call_args_list
        assert len(calls) == 2
        # Result should be JSON string in the content (double-JSON-encoded)
        # The result is json.dumps(result) then json.dumps({"name": tool, "result": result_str})
        # so the inner JSON has escaped quotes: \"
        assert '"result"' in calls[1][0][1][3]
        assert '\\"mem-1\\"' in calls[1][0][1][3]


class TestGetContext:
    """Context assembly from memory search and session steps."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.agent_orchestrator._session import AgentSessionState
        from spacetime_memory.agent_orchestrator._steps import StepRecordingMixin

        m = StepRecordingMixin()
        m._client = MagicMock()
        m._workspace_id = "ws-1"
        state = AgentSessionState(session_id="session-1", agent_name="test-agent", user_id="user-1", workspace_id="ws-1")
        m._sessions = {"session-1": state}
        return m

    def test_empty_query_and_no_session(self, mixin):
        result = mixin.get_context(query="", session_id=None)
        assert result == []

    def test_with_query_searches_memories(self, mixin):
        mixin._client.search.return_value = [
            {"id": "m1", "memory_content": "content1", "score": 0.9},
            {"id": "m2", "content": "content2", "score": 0.7},
        ]
        result = mixin.get_context(query="test", top_k=10)
        assert len(result) == 2
        assert result[0]["type"] == "memory"
        assert result[0]["source"] == "memory_search"
        assert result[0]["score"] == 0.9

    def test_with_session_includes_steps(self, mixin):
        mixin._client.search.return_value = []
        mixin._client._call.return_value = {"status": "ok"}
        mixin._client._query.return_value = [
            {"id": "s1", "step_type": "thought", "content": "step 1", "summary": "s1",
             "created_at": "2024-01-01"},
            {"id": "s2", "step_type": "action", "content": "step 2", "summary": "s2",
             "created_at": "2024-01-02"},
        ]
        result = mixin.get_context(query="test", top_k=10, session_id="session-1")
        assert len(result) == 2
        assert result[0]["type"] == "step"
        assert result[0]["source"] == "session_steps"

    def test_results_sorted_by_score_desc(self, mixin):
        mixin._client.search.return_value = [
            {"id": "m1", "content": "low", "score": 0.3},
            {"id": "m2", "content": "high", "score": 0.9},
        ]
        result = mixin.get_context(query="test", top_k=10)
        assert result[0]["score"] == 0.9
        assert result[1]["score"] == 0.3

    def test_top_k_limit(self, mixin):
        mixin._client.search.return_value = [
            {"id": f"m{i}", "content": f"c{i}", "score": 1.0 - i * 0.1}
            for i in range(20)
        ]
        result = mixin.get_context(query="test", top_k=5)
        assert len(result) == 5

    def test_session_steps_error_graceful(self, mixin):
        mixin._client.search.return_value = []
        mixin._client._call.side_effect = RuntimeError("no session")
        result = mixin.get_context(query="test", session_id="session-1")
        # Should not raise — error is caught
        assert result == []
