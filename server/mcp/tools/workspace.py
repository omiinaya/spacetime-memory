"""MCP tools — Workspace tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Workspace tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_workspace(name: str, description: str = "") -> dict[str, Any]:
    """Create a new workspace."""
    return get_client().create_workspace(name, description)


@mcp.tool()
@require_api_key
def list_workspaces() -> list[dict[str, Any]]:
    """List all workspaces."""
    return get_client().list_workspaces()


@mcp.tool()
@require_api_key
def delete_workspace(workspace_id: str) -> dict[str, Any]:
    """Delete a workspace and all its data.

    Args:
        workspace_id: The ID of the workspace to delete.

    Returns:
        Dict with status and workspace ID.
    """
    return get_client().delete_workspace(workspace_id)


@mcp.tool()
@require_api_key
def update_workspace(id: str, name: str, description: str) -> dict[str, Any]:
    """Update a workspace's name and description. Requires owner access.

    Args:
        id: The workspace ID.
        name: New name for the workspace.
        description: New description for the workspace.

    Returns:
        Dict with reducer response status.
    """
    return get_client().update_workspace(id, name, description)


@mcp.tool()
@require_api_key
def set_workspace_visibility(workspace_id: str, is_public: bool) -> dict[str, Any]:
    """Toggle whether a workspace is public or private. Requires owner access.

    Args:
        workspace_id: The workspace to update.
        is_public: True to make public, False to make private.

    Returns:
        Dict with reducer response status.
    """
    return get_client().set_workspace_visibility(workspace_id, is_public)


@mcp.tool()
@require_api_key
def get_workspace_context(workspace_id: str) -> dict[str, Any]:
    """Get the context string attached to a workspace.

    Args:
        workspace_id: The workspace to retrieve context for.

    Returns:
        Dict with workspace_id, context, and queried_at fields.
    """
    return get_client().get_workspace_context(workspace_id)


# ---------------------------------------------------------------------------
