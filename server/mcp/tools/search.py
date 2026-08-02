"""MCP tools — Search / Recommend tools."""

from __future__ import annotations

from typing import Any

import json

from server.mcp.tools.app import get_client, mcp, require_api_key
# Recommendation tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def recommend_memories(
    workspace_id: str,
    limit: int = 20,
    min_urgency: float = 0.3,
) -> str:
    """Recommend memories that need attention (review, reinforce, discard).

    Returns memories sorted by urgency — low-trust, decaying, or
    consistently-poor memories that need human attention.

    Args:
        workspace_id: Target workspace.
        limit: Max recommendations (default 20).
        min_urgency: Minimum urgency threshold 0.0–1.0 (default 0.3).

    Returns:
        JSON string with recommended memories or empty list.
    """
    result = get_client().recommend_memories(
        workspace_id=workspace_id,
        limit=limit,
        min_urgency=min_urgency,
    )
    if not result:
        return json.dumps({
            "workspace_id": workspace_id,
            "recommendations": [],
            "message": "No recommendations found",
        })
    return json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def search_sessions_semantic(query: str, limit: int = 10) -> str:
    """Semantically search across all sessions/workspaces.

    Embes the query and returns session results sorted by relevance score.

    Args:
        query: Natural language query string.
        limit: Max results (default 10).

    Returns:
        JSON string with matching sessions sorted by score, or empty
        list if no embedder is available.
    """
    result = get_client().search_sessions_semantic(query=query, limit=limit)
    if not result:
        return json.dumps({"query": query, "sessions": [], "message": "No sessions found"})
    return json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def get_user_memories(user_scope: str, workspace_id: str) -> str:
    """Get all memories scoped to a specific user within a workspace.

    Calls the ``get_user_memories`` reducer which populates the
    ``user_memory_result`` table, then reads from it.

    Args:
        user_scope: The user identity hash to filter by.
        workspace_id: The workspace to search in.

    Returns:
        JSON string with memory records scoped to the given user.
    """
    result = get_client().get_user_memories(
        user_scope=user_scope,
        workspace_id=workspace_id,
    )
    if not result:
        return json.dumps({
            "user_scope": user_scope,
            "workspace_id": workspace_id,
            "memories": [],
            "message": "No user memories found",
        })
    return json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def search_profiles(workspace_id: str, query: str, limit: int = 20) -> str:
    """Search profiles by static_facts or dynamic_context (client-side filter).

    Lists all profiles in a workspace and filters by matching text
    in static_facts_json or dynamic_context_json fields.

    Args:
        workspace_id: Target workspace.
        query: Search query string (case-insensitive substring match).
        limit: Max results (default 20).

    Returns:
        JSON string with matching profiles or empty list.
    """
    result = get_client().search_profiles(
        workspace_id=workspace_id,
        query=query,
        limit=limit,
    )
    if not result:
        return json.dumps({
            "workspace_id": workspace_id,
            "query": query,
            "profiles": [],
            "message": "No profiles found",
        })
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
