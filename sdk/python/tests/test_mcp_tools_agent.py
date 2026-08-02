"""Tests for server/mcp/tools/agent.py — Agent Step tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_get_client():
    """Patch get_client at the module level where agent.py imports it."""
    with patch("server.mcp.tools.agent.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# add_agent_step
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddAgentStep:
    """Tests for the add_agent_step MCP tool."""

    def test_adds_step(self, _patch_get_client: MagicMock):
        from server.mcp.tools.agent import add_agent_step

        result = add_agent_step(
            session_id="sess_abc",
            workspace_id="ws1",
            step_type="thought",
            content="I need to search the web.",
            summary="",
        )
        assert "recorded" in result
        assert "sess_abc" in result
        _patch_get_client.add_agent_step.assert_called_once_with(
            session_id="sess_abc",
            workspace_id="ws1",
            step_type="thought",
            content="I need to search the web.",
            summary="",
        )

    def test_with_summary(self, _patch_get_client: MagicMock):
        from server.mcp.tools.agent import add_agent_step

        add_agent_step(
            session_id="sess_xyz",
            workspace_id="ws1",
            step_type="tool_call",
            content='{"tool": "search"}',
            summary="Searched for AI news",
        )
        _patch_get_client.add_agent_step.assert_called_once_with(
            session_id="sess_xyz",
            workspace_id="ws1",
            step_type="tool_call",
            content='{"tool": "search"}',
            summary="Searched for AI news",
        )

    def test_all_step_types(self, _patch_get_client: MagicMock):
        """Verify all valid step_type values pass through correctly."""
        from server.mcp.tools.agent import add_agent_step

        for step_type in ("thought", "action", "observation", "tool_call", "tool_result"):
            _patch_get_client.reset_mock()
            result = add_agent_step(
                session_id="sess_t",
                workspace_id="ws1",
                step_type=step_type,
                content="test",
            )
            assert "recorded" in result
            _patch_get_client.add_agent_step.assert_called_once_with(
                session_id="sess_t",
                workspace_id="ws1",
                step_type=step_type,
                content="test",
                summary="",
            )

    def test_empty_content(self, _patch_get_client: MagicMock):
        """add_agent_step handles empty content string."""
        from server.mcp.tools.agent import add_agent_step

        result = add_agent_step(
            session_id="sess_e",
            workspace_id="ws1",
            step_type="thought",
            content="",
        )
        assert "recorded" in result
        _patch_get_client.add_agent_step.assert_called_once()

    def test_propagates_exception(self, _patch_get_client: MagicMock):
        """Errors from the client propagate to the caller."""
        from server.mcp.tools.agent import add_agent_step

        _patch_get_client.add_agent_step.side_effect = RuntimeError("API failure")
        with pytest.raises(RuntimeError, match="API failure"):
            add_agent_step(
                session_id="sess_err",
                workspace_id="ws1",
                step_type="thought",
                content="oops",
            )


# ---------------------------------------------------------------------------
# get_session_steps
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSessionSteps:
    """Tests for the get_session_steps MCP tool."""

    def test_gets_steps(self, _patch_get_client: MagicMock):
        from server.mcp.tools.agent import get_session_steps

        expected = [
            {"step_type": "thought", "content": "Step 1"},
            {"step_type": "action", "content": "Step 2"},
        ]
        _patch_get_client.get_session_steps.return_value = expected

        result = get_session_steps(session_id="sess_abc")
        assert result == expected
        _patch_get_client.get_session_steps.assert_called_once_with("sess_abc")

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.agent import get_session_steps

        _patch_get_client.get_session_steps.return_value = []
        result = get_session_steps(session_id="sess_empty")
        assert result == []

    def test_single_step(self, _patch_get_client: MagicMock):
        """get_session_steps returns a single-element list correctly."""
        from server.mcp.tools.agent import get_session_steps

        _patch_get_client.get_session_steps.return_value = [
            {"step_type": "action", "content": "Only step"}
        ]
        result = get_session_steps(session_id="sess_single")
        assert len(result) == 1
        assert result[0]["step_type"] == "action"

    def test_propagates_exception(self, _patch_get_client: MagicMock):
        """Errors from the client propagate through get_session_steps."""
        from server.mcp.tools.agent import get_session_steps

        _patch_get_client.get_session_steps.side_effect = ConnectionError("db down")
        with pytest.raises(ConnectionError, match="db down"):
            get_session_steps(session_id="sess_err")


# ---------------------------------------------------------------------------
# get_agent_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAgentContext:
    """Tests for the get_agent_context MCP tool."""

    def test_gets_context(self, _patch_get_client: MagicMock):
        from server.mcp.tools.agent import get_agent_context

        expected = {"context": [{"memory": "relevant fact"}], "entries": 1}

        with patch(
            "spacetime_memory.agent_orchestrator.AgentOrchestrator"
        ) as mock_orch_cls:
            mock_orch_instance = MagicMock()
            mock_orch_cls.return_value = mock_orch_instance
            mock_orch_instance.get_context.return_value = expected

            result_str = get_agent_context(
                workspace_id="ws1",
                query="What is RLHF?",
                session_id="sess_abc",
                top_k=5,
            )
            result = json.loads(result_str)
            assert result == expected

            mock_orch_cls.assert_called_once_with(
                _patch_get_client, workspace_id="ws1"
            )
            mock_orch_instance.get_context.assert_called_once_with(
                query="What is RLHF?", top_k=5, session_id="sess_abc"
            )

    def test_default_params(self, _patch_get_client: MagicMock):
        from server.mcp.tools.agent import get_agent_context

        with patch(
            "spacetime_memory.agent_orchestrator.AgentOrchestrator"
        ) as mock_orch_cls:
            mock_orch_instance = MagicMock()
            mock_orch_cls.return_value = mock_orch_instance
            mock_orch_instance.get_context.return_value = {}

            get_agent_context(workspace_id="ws1")
            mock_orch_instance.get_context.assert_called_once_with(
                query="", top_k=10, session_id=""
            )

    def test_with_query_only(self, _patch_get_client: MagicMock):
        """get_agent_context with query but no session_id uses defaults."""
        from server.mcp.tools.agent import get_agent_context

        with patch(
            "spacetime_memory.agent_orchestrator.AgentOrchestrator"
        ) as mock_orch_cls:
            mock_orch_instance = MagicMock()
            mock_orch_cls.return_value = mock_orch_instance
            mock_orch_instance.get_context.return_value = {"entries": []}

            result_str = get_agent_context(
                workspace_id="ws1", query="test query"
            )
            result = json.loads(result_str)
            assert result == {"entries": []}
            mock_orch_instance.get_context.assert_called_once_with(
                query="test query", top_k=10, session_id=""
            )

    def test_empty_context_response(self, _patch_get_client: MagicMock):
        """get_agent_context handles empty context dict from orchestrator."""
        from server.mcp.tools.agent import get_agent_context

        with patch(
            "spacetime_memory.agent_orchestrator.AgentOrchestrator"
        ) as mock_orch_cls:
            mock_orch_instance = MagicMock()
            mock_orch_cls.return_value = mock_orch_instance
            mock_orch_instance.get_context.return_value = {}

            result_str = get_agent_context(
                workspace_id="ws_empty", query="nothing"
            )
            result = json.loads(result_str)
            assert result == {}

    def test_propagates_orchestrator_exception(self, _patch_get_client: MagicMock):
        """Errors from AgentOrchestrator propagate to the caller."""
        from server.mcp.tools.agent import get_agent_context

        with patch(
            "spacetime_memory.agent_orchestrator.AgentOrchestrator"
        ) as mock_orch_cls:
            mock_orch_instance = MagicMock()
            mock_orch_cls.return_value = mock_orch_instance
            mock_orch_instance.get_context.side_effect = ValueError("bad query")

            with pytest.raises(ValueError, match="bad query"):
                get_agent_context(workspace_id="ws1", query="bad")
