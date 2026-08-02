"""MCP tools — Agent Step tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key

import json as _json

# Agent Step tools (P3g agent orchestration hooks)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def add_agent_step(
    session_id: str,
    workspace_id: str,
    step_type: str,
    content: str,
    summary: str = "",
) -> str:
    """Record an agent reasoning step (thought, action, tool_call, etc.).

    Args:
        session_id: The session to attach the step to.
        workspace_id: The workspace containing the session.
        step_type: One of "thought", "action", "observation", "tool_call", "tool_result".
        content: The step content (text or JSON).
        summary: Optional short summary of the step.

    Returns:
        Confirmation message with step ID.
    """
    get_client().add_agent_step(
        session_id=session_id,
        workspace_id=workspace_id,
        step_type=step_type,
        content=content,
        summary=summary,
    )
    return f"Agent step recorded for session {session_id[:16]}..."


@mcp.tool()
@require_api_key
def get_session_steps(session_id: str) -> list[dict[str, Any]]:
    """Retrieve all reasoning steps for a session.

    Args:
        session_id: The session to get steps for.

    Returns:
        A list of step dicts ordered by creation time.
    """
    client = get_client()
    return client.get_session_steps(session_id)


@mcp.tool()
@require_api_key
def get_agent_context(
    workspace_id: str,
    query: str = "",
    session_id: str = "",
    top_k: int = 10,
) -> str:
    """Retrieve relevant context for an agent prompt from memories + session steps.

    Args:
        workspace_id: The workspace to search in.
        query: Natural language query for relevant memories.
        session_id: Optional session to include recent steps from.
        top_k: Maximum context entries (default: 10).

    Returns:
        JSON string with context entries.
    """
    from spacetime_memory.agent_orchestrator import AgentOrchestrator

    orch = AgentOrchestrator(get_client(), workspace_id=workspace_id)
    context = orch.get_context(query=query, top_k=top_k, session_id=session_id)
    return _json.dumps(context, default=str)


# ---------------------------------------------------------------------------
