"""MCP tools — Space tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Space tools (Supermemory shareable workspace permissions)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def grant_space_access(workspace_id: str, peer_id: str, permission: str) -> str:
    """Grant a peer access to a workspace with a specific permission level.

    Only an existing owner can grant access. Permission levels: owner, editor, viewer.

    Args:
        workspace_id: The workspace (space) ID.
        peer_id: The peer ID to grant access to.
        permission: One of 'owner', 'editor', 'viewer'.

    Returns:
        Confirmation message.
    """
    get_client().grant_space_access(workspace_id, peer_id, permission)
    return f"Granted '{permission}' access to peer '{peer_id[:16]}...' for workspace '{workspace_id[:16]}...'."


@mcp.tool()
@require_api_key
def revoke_space_access(workspace_id: str, peer_id: str) -> str:
    """Revoke a peer's access to a workspace.

    Only an existing owner can revoke access.

    Args:
        workspace_id: The workspace (space) ID.
        peer_id: The peer ID to revoke access from.

    Returns:
        Confirmation message.
    """
    get_client().revoke_space_access(workspace_id, peer_id)
    return f"Revoked access for peer '{peer_id[:16]}...' from workspace '{workspace_id[:16]}...'."


@mcp.tool()
@require_api_key
def list_space_members(workspace_id: str) -> list[dict[str, str]]:
    """List all members with their permissions for a workspace.

    Calls the list_space_members reducer and reads results from
    the space_member_result table.

    Args:
        workspace_id: The workspace (space) ID.

    Returns:
        A list of dicts, each with keys: peer_id, permission, granted_by, created_at.
    """
    client = get_client()
    return client.list_space_members(workspace_id)


# ---------------------------------------------------------------------------
