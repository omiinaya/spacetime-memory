"""MCP tools — Peer tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Peer tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def list_peers(workspace_id: str | None = None) -> list[dict[str, Any]]:
    """List all peers, optionally filtered by workspace.

    Returns peer IDs, workspace membership, and profile metadata for
    peer discovery and multi-agent coordination.

    Args:
        workspace_id: Optional workspace ID to filter peers by.

    Returns:
        List of peer records with ID, profile, and metadata.
    """
    return get_client().list_peers(workspace_id)


# ---------------------------------------------------------------------------
# Session tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def get_peer_sessions(peer_id: str) -> list[dict[str, Any]]:
    """List all sessions a peer has participated in."""
    return get_client().get_peer_sessions(peer_id)


@mcp.tool()
@require_api_key
def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Retrieve all messages for a session."""
    return get_client().get_session_messages(session_id)


# ---------------------------------------------------------------------------
