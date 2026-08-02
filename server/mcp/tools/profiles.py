"""MCP tools — Profile tools."""

from __future__ import annotations

import json
from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Profile tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def get_profile(peer_id: str) -> list[dict[str, Any]]:
    """Retrieve a peer's profile."""
    return get_client().get_profile(peer_id)


@mcp.tool()
@require_api_key
def upsert_profile(
    peer_id: str,
    static_facts_json: str = "[]",
    dynamic_context_json: str = "[]",
    preferences_json: str = "{}",
    tags_json: str = "[]",
) -> dict[str, Any]:
    """Create or update a peer profile."""
    return get_client().upsert_profile(
        peer_id, static_facts_json, dynamic_context_json,
        preferences_json, tags_json,
    )


@mcp.tool()
@require_api_key
def list_profiles(workspace_id: str) -> list[dict[str, Any]]:
    """List all profiles in a workspace.

    Complements search_profiles by returning all profiles without filtering.
    Useful for admin browsing and workspace member discovery.

    Args:
        workspace_id: Target workspace ID.

    Returns:
        List of profile records with metadata, static facts, and dynamic context.
    """
    return get_client().list_profiles(workspace_id)


@mcp.tool()
@require_api_key
def add_dynamic_context(peer_id: str, context: str) -> str:
    """Add dynamic context to a peer's profile mid-session.

    Appends context to the peer's dynamic_context_json array without
    replacing the whole profile. Useful for agents to update their
    running context during a session.

    Args:
        peer_id: The peer ID whose profile to update.
        context: Context text to append (e.g. status, state, or
            current activity).

    Returns:
        Confirmation message.
    """
    get_client().add_dynamic_context(peer_id, context)
    return f"Dynamic context added for peer {peer_id[:16]}..."


@mcp.tool()
@require_api_key
def add_profile_fact(peer_id: str, fact: str) -> str:
    """Add a fact to a peer's profile (appended to static_facts_json).

    Complements the ``add_fact`` MCP tool — ``add_profile_fact`` stores
    the fact directly on the peer's profile record rather than in the
    separate facts table.

    Args:
        peer_id: The peer ID whose profile to update.
        fact: Fact text to append to the profile's static facts.

    Returns:
        Confirmation message.
    """
    get_client().add_profile_fact(peer_id, fact)
    return f"Profile fact added for peer {peer_id[:16]}..."


@mcp.tool()
@require_api_key
def get_profile_context(peer_id: str) -> list[dict[str, Any]]:
    """Get computed profile context for a peer.

    Calls the get_profile_context reducer and returns the result.
    Unlike ``get_profile`` which returns the raw profile record,
    this returns the computed context data.

    Args:
        peer_id: The peer ID to get context for.

    Returns:
        List of profile context result rows, or empty list if none.
    """
    rows = get_client().get_profile_context(peer_id)
    if rows:
        return [rows]
    return []


@mcp.tool()
@require_api_key
def get_peer_reputation(peer_id: str) -> dict[str, Any] | None:
    """Get reputation stats for a peer.

    Calls the get_peer_reputation reducer and returns the result
    from the peer_reputation_result table. Returns None if the peer
    has no feedback history. Useful for monitoring peer trustworthiness
    in multi-agent systems.

    Args:
        peer_id: Peer identifier.

    Returns:
        Reputation stats dict with id (UUID), peer_id, helpful_count,
        unhelpful_count, total_feedback, reputation_score, last_feedback_at;
        or None.
    """
    return get_client().get_peer_reputation(peer_id)


@mcp.tool()
@require_api_key
def run_maintenance() -> dict[str, Any]:
    """Trigger periodic maintenance routines.

    Runs expire (stale memory cleanup), decay (confidence decay),
    and dedup (duplicate detection). Useful for scheduled system
    upkeep and health management.

    Returns:
        Status report with expired, decayed, and deduped counts.
    """
    return get_client().run_maintenance()


@mcp.tool()
@require_api_key
def expire_memories() -> dict[str, Any]:
    """Manually expire all overdue memories.

    Iterates all memories and deactivates any whose expires_at
    timestamp is in the past. Requires database admin privileges.

    Returns:
        Reducer status.
    """
    return get_client().expire_memories()


@mcp.tool()
@require_api_key
def check_embedder_health() -> dict[str, Any]:
    """Check if the embedder sidecar is running.

    Standalone embedder health check. Returns reachability status,
    model name, dimension, uptime, and any error messages.

    Returns:
        Embedder health status dict with status, reachable, model,
        dimension, uptime_seconds.
    """
    return get_client().check_embedder_health()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def add_fact(
    workspace_id: str,
    peer_id: str,
    content: str,
    fact_type: str = "dynamic",
    category: str = "custom",
    confidence: float = 0.8,
    source: str = "manual",
    tier: str = "L1",
) -> str:
    """Add a fact about a peer. Returns the fact ID."""
    get_client().add_fact(workspace_id, peer_id, content, fact_type, category, confidence, source, tier)
    return f"Fact added for peer {peer_id[:16]}... in workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def list_facts(
    workspace_id: str,
    peer_id: str = "",
    fact_type: str = "",
    tier: str = "",
    category: str = "",
) -> list[dict[str, Any]]:
    """List facts for a workspace with optional filters (peer_id, fact_type, tier, category)."""
    client = get_client()
    rows = client.list_facts(workspace_id, peer_id, fact_type, tier, category)
    if rows:
        try:
            return json.loads(rows[0].get("json_data", "[]"))
        except (json.JSONDecodeError, IndexError):
            pass
    return []


@mcp.tool()
@require_api_key
def delete_fact(fact_id: str) -> str:
    """Deactivate a fact (soft delete)."""
    get_client().delete_fact(fact_id)
    return f"Fact {fact_id[:16]}... deactivated."


@mcp.tool()
@require_api_key
def update_fact(
    fact_id: str,
    content: str = "",
    confidence: float = 0.0,
    category: str = "",
    tier: str = "",
) -> str:
    """Update a fact's content, confidence, category, and/or tier.

    Empty string parameters leave the corresponding field unchanged.
    A confidence of 0.0 leaves confidence unchanged.
    """
    get_client().update_fact(fact_id, content, confidence, category, tier)
    return f"Fact {fact_id[:16]}... updated."


@mcp.tool()
@require_api_key
def search_facts(
    workspace_id: str,
    query: str,
    tier: str = "",
) -> list[dict[str, Any]]:
    """Search facts by content text (substring / case-insensitive match)."""
    client = get_client()
    rows = client.search_facts(workspace_id, query, tier)
    if rows:
        try:
            return json.loads(rows[0].get("json_data", "[]"))
        except (json.JSONDecodeError, IndexError):
            pass
    return []


# ---------------------------------------------------------------------------
