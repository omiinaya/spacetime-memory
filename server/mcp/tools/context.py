"""MCP tools — Context tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Context tools  (QMD-style context chains)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def set_workspace_context(workspace_id: str, context: str) -> dict[str, Any]:
    """Attach a context string to a workspace for QMD-style context trees.

    Args:
        workspace_id: The workspace to set context on.
        context: The context string to attach.

    Returns:
        Dict with reducer response status.
    """
    return get_client().set_workspace_context(workspace_id, context)


@mcp.tool()
@require_api_key
def set_memory_context(memory_id: str, context: str) -> dict[str, Any]:
    """Attach a context string to a memory for QMD-style context trees.

    Args:
        memory_id: The memory to set context on.
        context: The context string to attach.

    Returns:
        Dict with reducer response status.
    """
    return get_client().set_memory_context(memory_id, context)


@mcp.tool()
@require_api_key
def get_context_chain(memory_id: str) -> dict[str, Any]:
    """Return the context chain for a memory: workspace context + memory context.

    Args:
        memory_id: The memory ID to retrieve context chain for.

    Returns:
        Dict with ``workspace_context`` and ``memory_context`` keys.
    """
    return get_client().get_context_chain(memory_id)


@mcp.tool()
@require_api_key
def list_context_packs(workspace_id: str) -> list[dict[str, Any]]:
    """List all context packs in a workspace.

    Context packs group related context entries together for QMD-style
    context management. Each pack represents a "state snapshot" of a
    conversation or agent session.

    Args:
        workspace_id: The workspace to list packs for.

    Returns:
        List of context pack records.
    """
    return get_client().list_context_packs(workspace_id)


@mcp.tool()
@require_api_key
def list_context_entries(pack_id: str) -> list[dict[str, Any]]:
    """List all entries in a context pack.

    Each entry is a piece of contextual data within the pack, such as
    agent state, conversation history, or metadata.

    Args:
        pack_id: The context pack ID to list entries for.

    Returns:
        List of context entry records.
    """
    return get_client().list_context_entries(pack_id)


@mcp.tool()
@require_api_key
def list_context_deltas(previous_pack_id: str) -> list[dict[str, Any]]:
    """List delta entries between two context packs.

    Deltas show what changed between consecutive context pack snapshots.
    Useful for diffing agent state across sessions.

    Args:
        previous_pack_id: The ID of the earlier context pack to compare.

    Returns:
        List of context delta records showing changes.
    """
    return get_client().list_context_deltas(previous_pack_id)


@mcp.tool()
@require_api_key
def fuzzy_get(
    workspace_id: str,
    name: str,
    field: str = "content",
    threshold: float = 0.5,
    limit: int = 50,
) -> str:
    """Find the closest-matching memory by string similarity (difflib).

    Fetches up to *limit* memories from the workspace and uses
    ``difflib.SequenceMatcher`` to find the one whose *field* value is
    most similar to *name*.

    Args:
        workspace_id: The workspace to search.
        name: The target name to fuzzy-match against.
        field: Which memory field to compare (default "content").
        threshold: Minimum similarity ratio 0.0-1.0 (default 0.5).
        limit: Max memories to scan (default 50).

    Returns:
        JSON string with the best match if found and similarity >= threshold,
        or a message indicating no match found.
    """
    import json as _json

    result = get_client().fuzzy_get(
        workspace_id=workspace_id,
        name=name,
        field=field,
        threshold=threshold,
        limit=limit,
    )
    if result is None:
        return f"No memory found matching '{name}' with similarity >= {threshold} (field: {field})."
    return _json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def glob_get(
    workspace_id: str,
    pattern: str,
    field: str = "id",
    limit: int = 200,
) -> str:
    """Find memories matching a glob pattern (fnmatch-style).

    Fetches up to *limit* memories and returns those whose *field*
    matches the glob *pattern* (``*``, ``?``, ``[...]`` wildcards).

    Args:
        workspace_id: The workspace to search.
        pattern: Glob pattern (e.g. ``"auth-*"``, ``"*agent*"``).
        field: Which memory field to match against (default "id").
        limit: Max memories to scan (default 200).

    Returns:
        JSON string with matching memories, or a message if none found.
    """
    import json as _json

    result = get_client().glob_get(
        workspace_id=workspace_id,
        pattern=pattern,
        field=field,
        limit=limit,
    )
    if not result:
        return f"No memories matching pattern '{pattern}' (field: {field})."
    return _json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def detect_patterns(
    workspace_id: str,
    limit: int = 200,
    include_clusters: bool = True,
    include_terms: bool = True,
    include_co_occur: bool = True,
) -> str:
    """Run pattern detection on a workspace's memories.

    Performs temporal clustering, frequent term extraction, and
    co-occurrence detection to surface patterns across memories.

    Args:
        workspace_id: The workspace to analyze.
        limit: Max memories to fetch for analysis (default 200).
        include_clusters: Run temporal clustering (default True).
        include_terms: Run frequent term extraction (default True).
        include_co_occur: Run co-occurrence detection (default True).

    Returns:
        JSON string with temporal_clusters, frequent_terms,
        co_occurrences, total_memories, and summary.
    """
    import json as _json

    result = get_client().detect_patterns(
        workspace_id=workspace_id,
        limit=limit,
        include_clusters=include_clusters,
        include_terms=include_terms,
        include_co_occur=include_co_occur,
    )
    return _json.dumps(result, default=str)


# ---------------------------------------------------------------------------
