"""MCP tools — Directory tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key

import json as _json

# Directory tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_directory(workspace_id: str, name: str, path: str, parent_id: str = "", description: str = "") -> str:
    """Create a directory in the context directory tree."""
    get_client().create_directory(workspace_id, name, path, parent_id, description)
    return f"Directory '{name}' created."


@mcp.tool()
@require_api_key
def traverse_directory(workspace_id: str, root_directory_id: str) -> str:
    """Recursively traverse directory tree showing all children."""
    rows = get_client().traverse_directory(workspace_id, root_directory_id)
    return _json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def list_directory(directory_id: str) -> str:
    """List children of a directory."""
    rows = get_client().list_directory(directory_id)
    return _json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def get_directory(workspace_id: str, path_or_id: str) -> str:
    """Get a directory by ID or path.

    Resolves a directory within a workspace using either its unique ID or
    its path in the context directory tree.

    Args:
        workspace_id: The workspace ID to search in.
        path_or_id: Directory ID or path string to look up.

    Returns:
        JSON array of matching directory entries.
    """
    rows = get_client().get_directory(workspace_id, path_or_id)
    return _json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def link_memory_to_directory(directory_id: str, memory_id: str, workspace_id: str) -> str:
    """Link a memory to a directory.

    Associates a memory with a directory in the context directory tree so
    the memory can be discovered via directory traversal.

    Args:
        directory_id: The directory ID to link into.
        memory_id: The memory ID to link.
        workspace_id: The workspace containing both the directory and memory.

    Returns:
        Confirmation message.
    """
    get_client().link_memory_to_directory(directory_id, memory_id, workspace_id)
    return f"Memory {memory_id[:16]}... linked to directory {directory_id[:16]}..."


@mcp.tool()
@require_api_key
def unlink_memory_from_directory(directory_id: str, memory_id: str) -> str:
    """Unlink a memory from a directory.

    Removes the association between a memory and a directory. The memory
    itself is not deleted.

    Args:
        directory_id: The directory ID to unlink from.
        memory_id: The memory ID to unlink.

    Returns:
        Confirmation message.
    """
    get_client().unlink_memory_from_directory(directory_id, memory_id)
    return f"Memory {memory_id[:16]}... unlinked from directory {directory_id[:16]}..."


@mcp.tool()
@require_api_key
def search_directory_contents(workspace_id: str, directory_path: str) -> str:
    """Recursively search directory contents.

    Finds a directory by path, recursively collects all subdirectories
    and memory entries within the tree, and returns the complete listing.
    Useful for discovering all memories organized under a directory branch.

    Args:
        workspace_id: Target workspace.
        directory_path: Path of the root directory to search (e.g. "/projects/ai").

    Returns:
        JSON string with the DirectoryContentResult containing:
        directory_id, subdirectory_ids_json, memory_ids_json, directory_path,
        workspace_id, id, created_at.
    """
    rows = get_client().search_directory_contents(workspace_id, directory_path)
    return _json.dumps(rows, default=str)


# ---------------------------------------------------------------------------
