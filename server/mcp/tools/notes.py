"""MCP tools — Note tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Note CRUD tools (LLM Wiki page management)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_note(
    workspace_id: str = "default",
    title: str = "",
    content: str = "",
    note_date: str = "",
    embed: bool = True,
) -> dict[str, Any]:
    """Create a wiki note (LLM Wiki page). Auto-embeds if *embed* is True.

    Args:
        workspace_id: Target workspace (default: "default").
        title: Note title (concise, human-readable).
        content: Markdown body content. Supports [[wiki-links]].
        note_date: Optional ISO-8601 date string.
        embed: Whether to auto-embed content for semantic search (default: True).

    Returns:
        Dictionary with creation status and note details.
    """
    return get_client().create_note(
        workspace_id=workspace_id,
        title=title,
        content=content,
        note_date=note_date,
        embed=embed,
    )


@mcp.tool()
@require_api_key
def get_note(note_id: str) -> list[dict[str, Any]]:
    """Get a note by its ID.

    Args:
        note_id: The note's unique identifier.

    Returns:
        List of note records matching the ID (should be one).
    """
    return get_client().get_note(note_id)


@mcp.tool()
@require_api_key
def update_note(
    note_id: str,
    title: str = "",
    content: str = "",
    embed: bool = True,
) -> dict[str, Any]:
    """Update a wiki note. Re-embeds if content changes and *embed* is True.

    Args:
        note_id: The note's unique identifier.
        title: New title (empty string leaves unchanged).
        content: New markdown body (empty string leaves unchanged).
        embed: Whether to re-embed content (default: True).

    Returns:
        Dictionary with update status.
    """
    return get_client().update_note(
        note_id=note_id,
        title=title,
        content=content,
        embed=embed,
    )


@mcp.tool()
@require_api_key
def delete_note(note_id: str) -> dict[str, Any]:
    """Delete a note by its ID.

    Args:
        note_id: The note's unique identifier.

    Returns:
        Dictionary with deletion status.
    """
    return get_client().delete_note(note_id)


@mcp.tool()
@require_api_key
def list_notes(workspace_id: str = "default") -> list[dict[str, Any]]:
    """List all notes in a workspace.

    Args:
        workspace_id: Target workspace (default: "default").

    Returns:
        List of note records in the workspace.
    """
    return get_client().list_notes(workspace_id)


@mcp.tool()
@require_api_key
def get_note_by_title(title: str) -> list[dict[str, Any]]:
    """Find a note by its title.

    Args:
        title: The note title to search for.

    Returns:
        List of note records matching the title (usually one).
    """
    return get_client().get_note_by_title(title)


@mcp.tool()
@require_api_key
def get_note_by_date(note_date: str) -> list[dict[str, Any]]:
    """Find notes by ISO-8601 date string (YYYY-MM-DD).

    Args:
        note_date: The date string to search for (e.g. "2026-06-26").

    Returns:
        List of note records matching the date.
    """
    return get_client().get_note_by_date(note_date)


@mcp.tool()
@require_api_key
def get_note_history(note_id: str) -> list[dict[str, Any]]:
    """Get revision history for a note.

    Args:
        note_id: The note's unique identifier.

    Returns:
        List of revision records ordered by version ascending.
    """
    return get_client().get_note_history(note_id)


@mcp.tool()
@require_api_key
def get_backlinks(note_id: str) -> list[dict[str, Any]]:
    """Get all backlinks pointing to a note ([[wiki-links]] from other notes).

    Args:
        note_id: The note's unique identifier.

    Returns:
        List of backlink records showing which notes reference this one.
    """
    return get_client().get_backlinks(note_id)


@mcp.tool()
@require_api_key
def get_outgoing_links(note_id: str) -> list[dict[str, Any]]:
    """Get all outgoing [[wiki-links]] from a note.

    Args:
        note_id: The note's unique identifier.

    Returns:
        List of outgoing link records.
    """
    return get_client().get_outgoing_links(note_id)


# ---------------------------------------------------------------------------
