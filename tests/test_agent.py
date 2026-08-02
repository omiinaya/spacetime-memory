"""Tests for server/mcp/tools/agent.py - Agent MCP tools."""
import pytest
from server.mcp.tools.agent import get_agent_context, add_agent_step, get_session_steps


class TestAgentModule:
    """Test suite for agent.py - verify all expected exports exist."""

    def test_get_agent_context_exists(self):
        assert callable(get_agent_context)

    def test_add_agent_step_exists(self):
        assert callable(add_agent_step)

    def test_get_session_steps_exists(self):
        assert callable(get_session_steps)
