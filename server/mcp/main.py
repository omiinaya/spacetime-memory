"""
MCP (Model Context Protocol) server for spacetime-memory.

Uses the spacetime-memory Python SDK client. No raw SQL.

Configuration via environment variables:
  SPACETIMEDB_HOST (default: localhost)
  SPACETIMEDB_PORT (default: 3001)
  SPACETIMEDB_DB (default: spacetime-memory)
  EMBEDDER_URL (default: http://localhost:9090)
  MCP_API_KEY (optional) — if set, tools require this key for HTTP/SSE transport.
    Stdio transport (local agent) does not use token auth; rely on filesystem
    permissions instead.  For HTTP/SSE access, it is recommended to pair this
    with a reverse proxy (nginx / Caddy) that enforces the API key at the
    transport layer.
"""

from __future__ import annotations

import functools
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

# Load reranker credentials from Hermes .env (same pattern as eval_harness.py)
_hermes_env = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_hermes_env):
    with open(_hermes_env) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("LITELLM_MASTER_KEY="):
                _, _key = _line.split("=", 1)
                os.environ.setdefault("LLM_RERANK_API_KEY", _key.strip().strip('"').strip("'"))
                break
os.environ.setdefault("LLM_RERANK_ENDPOINT", "http://192.168.1.111:4000/v1")
os.environ.setdefault("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

if MCP_API_KEY:
    print(
        "  [mcp] MCP API key authentication is enabled. "
        "Tools will require a valid key for HTTP/SSE transport."
    )


def require_api_key(func):
    """Decorator that enforces MCP_API_KEY on non-stdio transports.

    For HTTP/SSE transport, the FastMCP tool receives request context via
    the ``ctx`` argument.  If ``MCP_API_KEY`` is set, we extract the
    ``Authorization`` header from the request metadata and compare it
    against the configured key.

    For stdio transport (local agent), there are no HTTP headers, so auth
    does not apply — rely on filesystem permissions instead.

    .. note::

        FastMCP passes context as the first positional arg when the tool
        signature includes ``ctx``.  This decorator introspects the
        available context to determine the transport type.
    """

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        # If no key is configured, allow all
        if not MCP_API_KEY:
            return await func(*args, **kwargs)

        # Try to extract the Authorization header from the request context.
        # FastMCP passes the request context in a variety of ways depending
        # on transport.  We do a best-effort check.
        request_meta = None

        # Check if first arg is the FastMCP context object
        for arg in args:
            if hasattr(arg, "request"):
                request_meta = getattr(arg, "request", None)
                break
        if not request_meta:
            # Check kwargs for common context names
            for key in ("ctx", "context", "request"):
                val = kwargs.get(key)
                if val is not None and hasattr(val, "request"):
                    request_meta = getattr(val, "request", None)
                    break

        if request_meta is not None:
            # We have request metadata — check the Authorization header
            headers = getattr(request_meta, "headers", {}) or getattr(
                request_meta, "scope", {}
            )
            # FastMCP / Starlette-style: headers is a dict-like object
            auth_header = ""
            if isinstance(headers, dict):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )
            elif hasattr(headers, "get"):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )

            expected = f"Bearer {MCP_API_KEY}"
            if auth_header != expected:
                raise PermissionError("Unauthorized: invalid or missing API key")

        # If no request context (stdio), auth doesn't apply
        return await func(*args, **kwargs)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        # If no key is configured, allow all
        if not MCP_API_KEY:
            return func(*args, **kwargs)

        # Try to extract the Authorization header from the request context.
        request_meta = None
        for arg in args:
            if hasattr(arg, "request"):
                request_meta = getattr(arg, "request", None)
                break
        if not request_meta:
            for key in ("ctx", "context", "request"):
                val = kwargs.get(key)
                if val is not None and hasattr(val, "request"):
                    request_meta = getattr(val, "request", None)
                    break

        if request_meta is not None:
            headers = getattr(request_meta, "headers", {}) or getattr(
                request_meta, "scope", {}
            )
            auth_header = ""
            if isinstance(headers, dict):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )
            elif hasattr(headers, "get"):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )

            expected = f"Bearer {MCP_API_KEY}"
            if auth_header != expected:
                raise PermissionError("Unauthorized: invalid or missing API key")

        return func(*args, **kwargs)

    # Return the appropriate wrapper depending on whether the function is async
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


# ---------------------------------------------------------------------------
# MCP server + SDK Client
# ---------------------------------------------------------------------------

mcp = FastMCP("spacetime-memory", log_level="WARNING")

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(
            host=HOST,
            port=PORT,
            database=DB,
            embedder_url=EMBEDDER_URL,
        )
    return _client


# Embedder helpers (also available via Client, re-exported for convenience)


def _embed(text: str) -> list[float]:
    return get_client()._embed(text)


def _embed_batch(texts: list[str]) -> list[list[float]]:
    return get_client()._embed_batch(texts)


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def store_memory(
    workspace_id: str,
    peer_id: str,
    observer_id: str = "",
    memory_type: str = "experience",
    content: str = "",
    summary: str = "",
    entities_json: str = "[]",
    confidence: float = 0.8,
    source_session_id: str = "",
    source_message_id: str = "",
    tier: str = "",
) -> dict[str, Any]:
    """Store a new memory with optional tier override."""
    return get_client().store(
        workspace_id=workspace_id,
        content=content,
        summary=summary,
        memory_type=memory_type,
        peer_id=peer_id,
        observer_id=observer_id,
        entities_json=entities_json,
        confidence=confidence,
        source_session_id=source_session_id,
        source_message_id=source_message_id,
        tier=tier,
    )


@mcp.tool()
@require_api_key
def search_memories(
    workspace_id: str,
    query_text: str = "",
    memory_type: str = "",
    tier: str = "",
    limit: int = 50,
    rerank: bool = False,
    entity_types: list[str] | None = None,
    before: float | None = None,
    after: float | None = None,
) -> list[dict[str, Any]]:
    """Search memories via keyword with optional filters.

    Set rerank=True to enable LLM reranking for improved precision.

    Args:
        entity_types: Optional list of entity_type values to filter by
            (e.g. ["memory", "note"], or ["node"] for KG nodes only).
        before: Optional Unix timestamp — only return results created before this time.
        after: Optional Unix timestamp — only return results created after this time.
    """
    return get_client().search(
        workspace_id=workspace_id,
        query=query_text,
        memory_type=memory_type,
        tier=tier,
        limit=limit,
        semantic=True,
        rerank=rerank,
        entity_types=entity_types,
        before=before,
        after=after,
    )


@mcp.tool()
@require_api_key
def hybrid_search(
    workspace_id: str,
    query_text: str,
    memory_type: str = "",
    tier: str = "",
    limit: int = 20,
    strategies: str = "semantic,keyword,graph,temporal",
    rerank: bool = True,
    entity_types: list[str] | None = None,
    before: float | None = None,
    after: float | None = None,
) -> list[dict[str, Any]]:
    """Multi-strategy hybrid search across memories, KG nodes, and temporal data.

    Uses LLM reranking by default for improved precision (P@5=29% vs 23% baseline).

    Args:
        entity_types: Optional list of entity_type values to filter by
            (e.g. ["memory", "note"], or ["node"] for KG nodes only).
        before: Optional Unix timestamp — only return results created before this time.
        after: Optional Unix timestamp — only return results created after this time.
    """
    return get_client().search(
        workspace_id=workspace_id,
        query=query_text,
        memory_type=memory_type,
        tier=tier,
        limit=limit,
        semantic=True,
        rerank=rerank,
        entity_types=entity_types,
        before=before,
        after=after,
    )


@mcp.tool()
@require_api_key
def get_memory(id: str) -> list[dict[str, Any]]:
    """Retrieve a single memory by its ID. Auto-reinforces on read."""
    return get_client().get_memory(id)


@mcp.tool()
@require_api_key
def get_memory_history(memory_id: str) -> list[dict[str, Any]]:
    """Get version history for a memory (mem0 parity).

    Returns revision history from the memory_revision table,
    ordered by version ascending. Each entry shows what changed
    in that revision (previous vs new content/summary/confidence).

    The current (latest) state is appended as the final entry.
    """
    return get_client().get_memory_history(memory_id)


@mcp.tool()
@require_api_key
def list_memories(
    workspace_id: str,
    memory_type: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List active memories in a workspace, newest first.

    Args:
        workspace_id: Target workspace.
        memory_type: Optional memory type filter (e.g. ``"experience"``, ``"observation"``).
        limit: Max memories to return (default 50).

    Returns:
        List of memory records sorted by creation time, newest first.
    """
    return get_client().list_memories(workspace_id, memory_type, limit)


@mcp.tool()
@require_api_key
def update_memory(
    memory_id: str,
    content: str = "",
    summary: str = "",
    confidence: float = 0.0,
) -> dict[str, Any]:
    """Update a memory's content, summary, and/or confidence.

    Only fields with non-empty/non-zero values are updated. Pass
    empty strings for fields you want to leave unchanged.

    Creates a revision snapshot before updating (version history).
    """
    return get_client().update_memory(memory_id, content, summary, confidence)


@mcp.tool()
@require_api_key
def delete_memory(memory_id: str) -> dict[str, Any]:
    """Delete (hard-delete) a memory by its ID."""
    return get_client().delete_memory(memory_id)


@mcp.tool()
@require_api_key
def store_batch(
    items_json: str,
    workspace_id: str = "default",
) -> str:
    """Store multiple memories in a single batch call.

    Much faster than N sequential store() calls when the embedder is the
    bottleneck.  Embeds all items in one batch, then sends a single reducer.

    Args:
        items_json: JSON string of a list of item dicts, each with:
            - ``content`` (str, required)
            - ``summary`` (str, optional)
            - ``memory_type`` (str, default ``"experience"``)
            - ``peer_id`` (str, optional)
            - ``observer_id`` (str, optional)
            - ``entities_json`` (str, optional)
            - ``confidence`` (float, default 0.8)
            - ``source_session_id`` (str, optional)
            - ``source_message_id`` (str, optional)
            Example: '[{"content": "Hello world", "memory_type": "observation"}]'
        workspace_id: Target workspace (default: "default").

    Returns:
        Summary string with count of stored items.
    """
    import json as _json

    try:
        items = _json.loads(items_json)
    except _json.JSONDecodeError as e:
        return f"Error: invalid JSON in items_json — {e}"

    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return "Error: items_json must be a JSON list of dicts, e.g. '[{\"content\": \"...\"}]'"

    results = get_client().store_batch(workspace_id=workspace_id, items=items)
    return f"Stored {len(results)} memories in batch (workspace: {workspace_id})"


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
# Document tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_document(
    workspace_id: str = "default",
    title: str = "",
    content: str = "",
    content_type: str = "text",
    file_path: str = "",
    source_url: str = "",
    metadata_json: str = "",
) -> dict[str, Any]:
    """Create a document with auto-chunking.

    Documents with content ≥ 100 chars are automatically split into
    overlapping ~500-char chunks (sentence-boundary-aware).

    Args:
        workspace_id: Target workspace (default: "default").
        title: Document title.
        content: Document body text. Auto-chunked if ≥ 100 chars.
        content_type: ``"text"``, ``"pdf"``, ``"image"``, ``"video"``, ``"code"``, or ``"url"``.
        file_path: Optional file path reference.
        source_url: Optional source URL.
        metadata_json: Optional JSON string of metadata.

    Returns:
        Dictionary with creation status and document details.
    """
    import json as _json

    metadata = _json.loads(metadata_json) if metadata_json else None
    return get_client().create_document(
        workspace_id=workspace_id,
        title=title,
        content=content,
        content_type=content_type,
        file_path=file_path,
        source_url=source_url,
        metadata=metadata,
    )


@mcp.tool()
@require_api_key
def get_document(doc_id: str) -> dict[str, Any] | None:
    """Get a document by its ID.

    Args:
        doc_id: The document's unique identifier.

    Returns:
        Document record if found, None otherwise.
    """
    return get_client().get_document(doc_id)


@mcp.tool()
@require_api_key
def list_documents(workspace_id: str = "default") -> list[dict[str, Any]]:
    """List all documents in a workspace.

    Args:
        workspace_id: Target workspace (default: "default").

    Returns:
        List of document records in the workspace.
    """
    return get_client().list_documents(workspace_id)


@mcp.tool()
@require_api_key
def get_document_chunks(doc_id: str) -> list[dict[str, Any]]:
    """Get all chunks for a document, ordered by chunk_index.

    Args:
        doc_id: The document's unique identifier.

    Returns:
        List of chunk records ordered by chunk index.
    """
    return get_client().get_document_chunks(doc_id)


@mcp.tool()
@require_api_key
def delete_document(doc_id: str) -> dict[str, Any]:
    """Delete a document and all its chunks (cascading).

    Args:
        doc_id: The document's unique identifier.

    Returns:
        Dictionary with deletion status.
    """
    return get_client().delete_document(doc_id)


@mcp.tool()
@require_api_key
def reinforce_memory(memory_id: str) -> dict[str, Any]:
    """Reinforce a memory: increment access_count and bump strength."""
    return get_client().reinforce(memory_id)


@mcp.tool()
@require_api_key
def rate_memory(memory_id: str, rating: str, peer_id: str) -> dict[str, Any]:
    """Rate a memory on a 1-5 scale to adjust its trust score.

    Accepts:
      - "helpful" (score 5) or "unhelpful" (score 1) for binary ratings.
      - "1", "2", "3", "4", or "5" for graded numeric feedback.

    Trust score is recomputed as the average of all feedback scores / 5.
    """
    return get_client()._call("rate_memory", [memory_id, rating, peer_id])


@mcp.tool()
@require_api_key
def escalate_memories(workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20) -> str:
    """Batch-escalate memory tiers: L2->L1 at l2_to_l1 accesses, L1->L0 at l1_to_l0."""
    get_client().escalate_memories(workspace_id, l2_to_l1, l1_to_l0)
    return f"Tier escalation triggered for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def dedup_memories(workspace_id: str) -> str:
    """Deduplicate near-duplicate memories in a workspace (cosine >= 0.85 + edit dist <= 30%)."""
    get_client()._call("dedup_memories", [workspace_id])
    return f"Dedup complete for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def suggest_merges(workspace_id: str, threshold: float = 0.8) -> str:
    """Find candidate merge pairs in a workspace and record them as MergeSuggestion rows.

    Args:
        workspace_id: The workspace to scan.
        threshold: Minimum cosine similarity threshold (default: 0.8).

    Returns:
        Confirmation message.
    """
    get_client().suggest_merges(workspace_id, threshold)
    return (f"Merge suggestion scan complete for workspace {workspace_id[:16]}... "
            f"Check the merge_suggestion table for results.")


@mcp.tool()
@require_api_key
def approve_merge(suggestion_id: str) -> str:
    """Approve a pending merge suggestion — deactivates the source into the target.

    Args:
        suggestion_id: The ID of the MergeSuggestion row to approve.

    Returns:
        Confirmation message.
    """
    get_client().approve_merge(suggestion_id)
    return f"Merge suggestion {suggestion_id[:16]}... approved."


@mcp.tool()
@require_api_key
def reject_merge(suggestion_id: str) -> str:
    """Reject a pending merge suggestion without merging.

    Args:
        suggestion_id: The ID of the MergeSuggestion row to reject.

    Returns:
        Confirmation message.
    """
    get_client().reject_merge(suggestion_id)
    return f"Merge suggestion {suggestion_id[:16]}... rejected."


@mcp.tool()
@require_api_key
def set_memory_scope(memory_id: str, user_scope: str) -> str:
    """Set the user scope on an existing memory for user-level isolation.

    Args:
        memory_id: The UUID of the memory to scope.
        user_scope: The user identity hash to scope the memory to.
            Use an empty string ("") to make the memory shared (visible to all).

    Returns:
        A confirmation message.

    Example::

        set_memory_scope("abc-123", "alice")   # Scope to alice only
        set_memory_scope("abc-123", "")         # Make shared
    """
    get_client()._call("set_memory_scope", [memory_id, user_scope])
    return f"Memory {memory_id[:16]}... scoped to '{user_scope or 'shared'}'."


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Knowledge Graph tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_node(
    workspace_id: str,
    label: str,
    node_type: str,
    summary: str = "",
    metadata_json: str = "{}",
) -> dict[str, Any]:
    """Create a knowledge graph node and index it for semantic search."""
    return get_client().create_node(workspace_id, label, node_type, summary, metadata_json)


@mcp.tool()
@require_api_key
def update_node(
    node_id: str,
    label: str,
    node_type: str = "concept",
    summary: str = "",
    metadata_json: str = "{}",
    source_memory_id: str = "",
) -> dict[str, Any]:
    """Update an existing knowledge graph node's mutable fields.

    Args:
        node_id: The ID of the node to update.
        label: New label (display name).
        node_type: Type category (default: ``"concept"``).
        summary: Updated summary text.
        metadata_json: Updated JSON metadata string.
        source_memory_id: Optional source memory ID.
    """
    return get_client().update_node(
        node_id, label, node_type, summary, metadata_json,
        source_memory_id,
    )


@mcp.tool()
@require_api_key
def create_edge(
    workspace_id: str,
    source_node_id: str,
    target_node_id: str,
    relation: str,
    weight: float = 1.0,
    confidence: str = "EXTRACTED",
    metadata_json: str = "{}",
    source_memory_id: str = "",
) -> dict[str, Any]:
    """Create a directed, typed edge between two knowledge graph nodes.

    Args:
        workspace_id: Target workspace.
        source_node_id: Source node ID.
        target_node_id: Target node ID.
        relation: Relationship type label (e.g. "informed_by", "related_to", "part_of").
        weight: Edge weight (default: 1.0).
        confidence: Confidence level (default: "EXTRACTED").
        metadata_json: Optional JSON metadata string.
        source_memory_id: Optional memory record ID that supports this edge.
    """
    return get_client().create_edge(
        workspace_id, source_node_id, target_node_id,
        relation, weight, confidence, metadata_json,
        source_memory_id,
    )


@mcp.tool()
@require_api_key
def query_graph(workspace_id: str, query: str = "") -> list[dict[str, Any]]:
    """Search knowledge graph nodes by label within a workspace."""
    return get_client().query_graph(workspace_id, query)


@mcp.tool()
@require_api_key
def get_node(id: str) -> list[dict[str, Any]]:
    """Retrieve a knowledge graph node by its ID."""
    return get_client().get_node(id)


@mcp.tool()
@require_api_key
def get_neighbors(node_id: str) -> list[dict[str, Any]]:
    """Get all edges (neighbors) connected to a node."""
    return get_client().get_neighbors(node_id)


@mcp.tool()
@require_api_key
def get_community(community_id: int) -> dict[str, Any]:
    """Get community details and list all nodes in that community."""
    return get_client().get_community(community_id)


@mcp.tool()
@require_api_key
def compute_pagerank(workspace_id: str, damping: float = 0.85, max_iterations: int = 100) -> str:
    """Compute PageRank centrality for all nodes in a workspace.
    
    Args:
        workspace_id: The workspace to compute PageRank for.
        damping: PageRank damping factor (default: 0.85).
        max_iterations: Maximum iterations (default: 100).
    
    Returns:
        Summary string with the number of nodes ranked.
    """
    get_client().compute_pagerank(workspace_id, damping, max_iterations)
    # Read back the results
    rows = get_client()._sql(
        "SELECT * FROM pagerank_result WHERE "
        f"workspace_id = '{workspace_id}' "
        "ORDER BY rank DESC"
    )
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def compute_community_hierarchy(workspace_id: str) -> str:
    """Build hierarchical community dendrogram using agglomerative clustering.
    
    Args:
        workspace_id: The workspace to build hierarchy for.
    
    Returns:
        JSON string with hierarchy edges and clusters.
    """
    get_client().compute_community_hierarchy(workspace_id)
    # Read back the hierarchy
    edges = get_client()._sql(
        "SELECT * FROM community_hierarchy WHERE "
        f"workspace_id = '{workspace_id}' "
        "ORDER BY depth ASC"
    )
    clusters = get_client()._sql(
        "SELECT * FROM hierarchy_cluster WHERE "
        f"workspace_id = '{workspace_id}' "
        "ORDER BY depth ASC"
    )
    return json.dumps({"edges": edges, "clusters": clusters}, default=str)


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
# KG Graph Traversal tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def graph_bfs(workspace_id: str, start_node_id: str, max_depth: int = 3) -> str:
    """BFS traverse the knowledge graph from a node. Results in graph_traversal_result table."""
    get_client().graph_bfs(workspace_id, start_node_id, max_depth)
    return f"BFS from {start_node_id} up to depth {max_depth} completed. Read via SQL on graph_traversal_result."


@mcp.tool()
@require_api_key
def shortest_path(workspace_id: str, source_id: str, target_id: str, max_hops: int = 6) -> str:
    """Find shortest path between two KG nodes. Results in shortest_path_result table."""
    get_client().shortest_path(workspace_id, source_id, target_id, max_hops)
    return f"Shortest path computed. Read via SQL on shortest_path_result."


# ---------------------------------------------------------------------------
# Tour tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_tour(workspace_id: str, title: str, description: str = "") -> str:
    """Create a new guided tour through KG nodes."""
    get_client().create_tour(workspace_id, title, description)
    return f"Tour '{title}' created."


@mcp.tool()
@require_api_key
def add_tour_stop(tour_id: str, node_id: str, heading: str, description: str = "") -> str:
    """Add a stop to an existing tour."""
    get_client().add_tour_stop(tour_id, node_id, heading, description)
    return f"Stop '{heading}' added to tour."


# ---------------------------------------------------------------------------
# Mental Model tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def synthesize_mental_models(workspace_id: str, memory_ids_json: str) -> str:
    """Request synthesis of a mental model from a set of source memories.

    Creates a pending MentalModel record. Run mental_model_synthesis.py
    to generate actual LLM content.
    """
    client = get_client()
    client._call("synthesize_mental_models", [workspace_id, memory_ids_json])
    return f"Mental model synthesis requested for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def get_mental_model(id: str) -> str:
    """Get a single mental model by its ID."""
    client = get_client()
    rows = client._sql(f"SELECT * FROM mental_model WHERE id = '{id}'")
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def list_mental_models(workspace_id: str, status: str = "") -> str:
    """List mental models for a workspace, optionally filtered by status.

    Args:
        workspace_id: The workspace ID
        status: Optional filter: "pending", "completed", "failed", or empty for all
    """
    client = get_client()
    where = f"workspace_id = '{workspace_id}'"
    if status:
        where += f" AND status = '{status}'"
    rows = client._sql(f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at DESC")
    return json.dumps(rows, default=str)


# -------------------------------------------------------------------------
# Fact tools
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
    get_client()._call("add_fact", [workspace_id, peer_id, fact_type, category, content, confidence, source, tier])
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
    client._call("list_facts", [workspace_id, peer_id, fact_type, tier, category])
    query_hash = f"{workspace_id}:{peer_id}:{fact_type}:{tier}:{category}"
    rows = client._sql(
        f"SELECT * FROM fact_result WHERE query_hash = '{query_hash}' ORDER BY created_at DESC"
    )
    if rows:
        try:
            return json.loads(rows[0].get("json_data", "[]"))
        except (json.JSONDecodeError, IndexError):
            pass
    return []


# ---------------------------------------------------------------------------
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
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def list_directory(directory_id: str) -> str:
    """List children of a directory."""
    rows = get_client().list_directory(directory_id)
    return json.dumps(rows, default=str)


# ---------------------------------------------------------------------------
# Org-mode sync tool
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def org_sync(
    workspace_id: str,
    directory: str = "~/org",
    dry_run: bool = False,
) -> str:
    """One-shot sync of .org files in a directory to Spacetime Memory as notes and KG task nodes.

    Scans all .org files under DIRECTORY, parses headings with OrgModeParser,
    and stores each heading as a memory. TODO items are additionally created
    as knowledge graph nodes (type="task").

    Args:
        workspace_id: The target workspace to sync into.
        directory: Path to directory containing .org files (default: ~/org).
        dry_run: If True, preview changes without writing any data.

    Returns:
        A summary string describing how many events were synced.
    """
    import os
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"),
    )
    from org_sync_daemon import OrgSyncDaemon

    daemon = OrgSyncDaemon(
        org_dir=directory,
        workspace_id=workspace_id,
        client=get_client(),
        dry_run=dry_run,
    )
    total = daemon.scan()
    if dry_run:
        return f"[dry-run] Org sync would produce {total} events from {daemon.get_status()['files_tracked']} file(s)."
    return f"Org sync complete — {total} events synced from {daemon.get_status()['files_tracked']} file(s)."


# ---------------------------------------------------------------------------
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
    get_client()._call("grant_space_access", [workspace_id, peer_id, permission])
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
    get_client()._call("revoke_space_access", [workspace_id, peer_id])
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
    client._call("list_space_members", [workspace_id])
    rows = client._sql(
        f"SELECT peer_id, permission, granted_by, created_at "
        f"FROM space_member_result WHERE "
        f"workspace_id = '{workspace_id}' "
        f"ORDER BY created_at ASC"
    )
    return rows


# ---------------------------------------------------------------------------
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
    get_client()._call(
        "add_agent_step",
        [session_id, workspace_id, step_type, content, summary, ""],
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
    client._call("get_session_steps", [session_id])
    query_hash = f"steps:{session_id}"
    steps = client._sql(
        "SELECT * FROM session_step_result WHERE "
        f"query_hash = '{query_hash}' "
        "ORDER BY created_at ASC"
    )
    return steps


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
    return json.dumps(context, default=str)


# ---------------------------------------------------------------------------
# Health & Monitoring tools
# ---------------------------------------------------------------------------


@mcp.tool()
def health_check() -> dict:
    """Check the health of all system components.

    Returns status of SpacetimeDB connection, embedder, and basic stats.
    """
    client = get_client()
    result: dict = {
        "status": "ok",
        "spacetimedb": "unknown",
        "embedder": "unknown",
        "memory_count": 0,
        "workspace_count": 0,
    }
    # Check SpacetimeDB
    try:
        ws = client.list_workspaces()
        result["spacetimedb"] = "ok"
        result["workspace_count"] = len(ws)
    except Exception as e:
        result["spacetimedb"] = f"error: {e}"
        result["status"] = "degraded"
    # Check embedder
    try:
        emb = client.check_embedder_health()
        result["embedder"] = emb.get("status", "unknown")
    except Exception as e:
        result["embedder"] = f"error: {e}"
        result["status"] = "degraded"
    # Get memory count
    try:
        mems = client._sql("SELECT COUNT(*) as cnt FROM memory WHERE is_active = TRUE")
        if mems:
            result["memory_count"] = mems[0].get("cnt", 0)
    except Exception:
        pass
    return result


@mcp.tool()
def get_metrics() -> dict:
    """Get operational metrics for monitoring.

    Returns counters and gauges for: memory operations, search operations,
    connector events, errors, and system health.
    """
    client = get_client()
    metrics: dict = {
        "memories": {
            "total": 0,
            "active": 0,
            "by_tier": {"L0": 0, "L1": 0, "L2": 0},
        },
        "workspaces": 0,
        "peers": 0,
        "kg_nodes": 0,
        "kg_edges": 0,
        "sessions": 0,
        "notes": 0,
        "facts": 0,
    }
    try:
        # Memory counts
        rows = client._sql("SELECT COUNT(*) as c FROM memory")
        if rows:
            metrics["memories"]["total"] = rows[0].get("c", 0)

        rows = client._sql(
            "SELECT COUNT(*) as c FROM memory WHERE is_active = TRUE"
        )
        if rows:
            metrics["memories"]["active"] = rows[0].get("c", 0)

        for tier in ["L0", "L1", "L2"]:
            rows = client._sql(
                f"SELECT COUNT(*) as c FROM memory "
                f"WHERE tier = '{tier}' AND is_active = TRUE"
            )
            if rows:
                metrics["memories"]["by_tier"][tier] = rows[0].get("c", 0)

        # Workspaces
        metrics["workspaces"] = len(client.list_workspaces())

        # Distinct peers from memory table
        rows = client._sql(
            "SELECT COUNT(DISTINCT peer_id) as c FROM memory"
        )
        if rows:
            metrics["peers"] = rows[0].get("c", 0)

        # KG nodes (if table exists)
        try:
            rows = client._sql("SELECT COUNT(*) as c FROM kg_node")
            if rows:
                metrics["kg_nodes"] = rows[0].get("c", 0)
        except Exception:
            metrics["kg_nodes"] = -1  # table not available

        # KG edges (if table exists)
        try:
            rows = client._sql("SELECT COUNT(*) as c FROM kg_edge")
            if rows:
                metrics["kg_edges"] = rows[0].get("c", 0)
        except Exception:
            metrics["kg_edges"] = -1

        # Sessions (if table exists)
        try:
            rows = client._sql("SELECT COUNT(*) as c FROM session")
            if rows:
                metrics["sessions"] = rows[0].get("c", 0)
        except Exception:
            metrics["sessions"] = -1

        # Notes (if table exists)
        try:
            rows = client._sql("SELECT COUNT(*) as c FROM note")
            if rows:
                metrics["notes"] = rows[0].get("c", 0)
        except Exception:
            metrics["notes"] = -1

        # Facts (if table exists)
        try:
            rows = client._sql("SELECT COUNT(*) as c FROM fact")
            if rows:
                metrics["facts"] = rows[0].get("c", 0)
        except Exception:
            metrics["facts"] = -1

    except Exception as e:
        metrics["error"] = str(e)

    return metrics


# ---------------------------------------------------------------------------
# Compounder tools — LLM Wiki workflow
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def ingest_source(
    source_text: str,
    source_title: str,
    workspace_id: str = "default",
    source_type: str = "article",
) -> str:
    """Ingest a source document into the wiki.

    Full LLM Wiki workflow: summarize, extract entities, create KG nodes,
    link, ripple-update entities, and check for contradictions.
    """
    from spacetime_memory.compounder import Compounder

    client = get_client()
    llm_available = bool(os.environ.get("OPENAI_API_KEY", False))
    cp = Compounder(client)
    result = cp.ingest_source(
        source_text=source_text,
        source_title=source_title,
        workspace_id=workspace_id,
        source_type=source_type,
    )
    n_entities = len(result.get("entities", []))
    n_links = len(result.get("links", []))
    n_contra = len(result.get("contradictions", []))
    return (
        f"Ingested '{source_title}' into workspace {workspace_id[:16]}...\n"
        f"  Entities: {n_entities}, Links: {n_links}, "
        f"Contradictions: {n_contra}"
    )


@mcp.tool()
@require_api_key
def create_entity_page(
    name: str,
    description: str,
    entity_type: str = "concept",
    workspace_id: str = "default",
) -> str:
    """Create a structured entity wiki page with KG node + YAML frontmatter.

    Entity types: person, org, concept, product, location, event, topic.
    Creates both a wiki note and a knowledge graph node.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.create_entity_page(
        name=name,
        description=description,
        entity_type=entity_type,
        workspace_id=workspace_id,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    return f"Entity page '{name}' created (note: {note_id}...)"


@mcp.tool()
@require_api_key
def update_entity_page(
    name: str,
    description: str | None = None,
    entity_type: str | None = None,
    workspace_id: str = "default",
) -> str:
    """Update an existing entity wiki page and its KG node.

    Finds the entity by name and updates the provided fields. Fields not
    provided are left unchanged.

    Args:
        name: Entity name (used to find the existing entity).
        description: New 2-3 sentence description (optional).
        entity_type: New entity type (e.g. person, org, concept).
        workspace_id: Target workspace.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.update_entity_page(
        name=name,
        description=description,
        entity_type=entity_type,
        workspace_id=workspace_id,
    )
    if not result:
        return f"Entity page '{name}' not found."
    return f"Entity page '{name}' updated."


@mcp.tool()
@require_api_key
def create_concept_page(
    concept: str,
    definition: str,
    workspace_id: str = "default",
    related_concepts: str = "",
) -> str:
    """Create a concept wiki page with definition and [[wiki-links]].

    Args:
        concept: The concept name.
        definition: Clear definition text.
        workspace_id: Target workspace.
        related_concepts: Comma-separated list of related concept names.
    """
    from spacetime_memory.compounder import Compounder

    rel_list = [c.strip() for c in related_concepts.split(",") if c.strip()]
    cp = Compounder(get_client())
    result = cp.create_concept_page(
        concept=concept,
        definition=definition,
        workspace_id=workspace_id,
        related_concepts=rel_list or None,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    return f"Concept page '{concept}' created (note: {note_id}...)"


@mcp.tool()
@require_api_key
def create_comparison_page(
    title: str,
    items: str,
    workspace_id: str = "default",
    criteria: str = "features,performance,ecosystem",
) -> str:
    """Create a comparison wiki page with markdown table.

    Creates a note with YAML frontmatter (type: comparison) and a
    markdown comparison table of the given items across specified
    criteria.

    Args:
        title: Page title (e.g. \"LangGraph vs CrewAI vs AutoGen\").
        items: Comma-separated list of items to compare.
        workspace_id: Target workspace.
        criteria: Comma-separated comparison criteria.
    """
    from spacetime_memory.compounder import Compounder

    item_list = [i.strip() for i in items.split(",") if i.strip()]
    crit_list = [c.strip() for c in criteria.split(",") if c.strip()]
    cp = Compounder(get_client())
    result = cp.create_comparison_page(
        title=title,
        items=item_list,
        workspace_id=workspace_id,
        criteria=crit_list,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    return f"Comparison page '{title}' created with {len(item_list)} items (note: {note_id}...)"


@mcp.tool()
@require_api_key
def lint_workspace(
    workspace_id: str = "default",
    check_contradictions: bool = False,
) -> str:
    """Health-check the workspace wiki.

    Scans for orphans (KG nodes with no edges) and missing
    cross-references.  Set check_contradictions=True (slower)
    to also detect contradictory claims using the LLM.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.lint_workspace(
        workspace_id=workspace_id,
        check_contradictions=check_contradictions,
    )
    summary = result.get("summary", {})
    return (
        f"Lint complete for workspace {workspace_id[:16]}...\n"
        f"  Orphans: {summary.get('orphan_count', 0)}\n"
        f"  Missing crossrefs: {summary.get('missing_crossref_count', 0)}\n"
        f"  Note orphans: {summary.get('note_orphan_count', 0)}\n"
        f"  Contradictions: {summary.get('contradiction_count', 0)}\n"
        f"  Total issues: {summary.get('total_issues', 0)}"
    )


@mcp.tool()
@require_api_key
def generate_overview(workspace_id: str = "default") -> str:
    """Generate a workspace overview/synthesis page (_overview).

    Creates a note with workspace stats, entity tables, recent activity,
    and (if LLM available) an AI-written synthesis.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.generate_overview_page(workspace_id=workspace_id)
    note = result.get("note", {})
    if note.get("id"):
        return f"Overview generated: `{note['id'][:16]}...`"
    return "Workspace is empty. Nothing to generate."


@mcp.tool()
@require_api_key
def search_entities(
    workspace_id: str = "default",
    label: str = "",
    node_type: str = "",
    semantic_query: str = "",
    limit: int = 20,
) -> str:
    """Search knowledge-graph entities with flexible filters.

    Supports label search, type filtering, and semantic search.
    Combine filters to narrow results.

    Args:
        workspace_id: Target workspace.
        label: Exact entity label to search for (optional).
        node_type: Entity type filter (person, org, concept, product,
            location, event, topic). Optional.
        semantic_query: Natural-language query for semantic entity
            search (optional).
        limit: Max results (default: 20).
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    results = cp.search_entities(
        workspace_id=workspace_id,
        label=label or None,
        node_type=node_type or None,
        semantic_query=semantic_query or None,
        limit=limit,
    )
    if not results:
        return "No entities found."
    lines = [f"Found {len(results)} entities:"]
    for n in results:
        nid = n.get("id", "")[:12]
        label_text = n.get("label", "?")
        ntype = n.get("node_type", "?")
        summary = (n.get("summary", "") or "")[:80]
        lines.append(f"- [{label_text}]({nid}) [{ntype}] {summary}")
    return "\n".join(lines)


@mcp.tool()
@require_api_key
def find_near_duplicates(
    content: str,
    workspace_id: str = "default",
    threshold: float = 0.92,
    limit: int = 5,
) -> str:
    """Find memories with semantically similar content to the given text.

    Uses the hybrid search pipeline to catch rephrasings of the same fact.
    Default threshold of 0.92 works well for BGE-M3 embeddings.

    Args:
        content: The text to check for near-duplicates.
        workspace_id: Target workspace (default: "default").
        threshold: Minimum similarity score (0.0-1.0, default: 0.92).
        limit: Max results to return (default: 5).

    Returns:
        Formatted string listing near-duplicate candidates with scores.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    results = cp.find_near_duplicates(
        content=content,
        workspace_id=workspace_id,
        threshold=threshold,
        limit=limit,
    )
    if not results:
        return "No near-duplicates found."
    lines = [f"Found {len(results)} near-duplicate candidate(s):"]
    for r in results[:limit]:
        eid = r.get("entity_id", "")[:16]
        etype = r.get("entity_type", "?")
        score = r.get("score", 0.0)
        snippet = (r.get("content", "") or "")[:120].replace("\n", " ")
        lines.append(f"  - [{etype}] {eid} (score: {score:.4f}) {snippet}")
    return "\n".join(lines)


@mcp.tool()
@require_api_key
def cross_link(workspace_id: str = "default") -> str:
    """Auto-link related but unconnected memories in a workspace.

    Finds memories that reference similar concepts or share entities
    but aren't directly linked, and creates edges between them.

    Args:
        workspace_id: Target workspace (default: "default").
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.cross_link(workspace_id=workspace_id)
    links_created = result.get("links_created", 0)
    pairs_checked = result.get("pairs_checked", 0)
    return (
        f"Cross-link complete for workspace {workspace_id[:16]}...\n"
        f"  Pairs checked: {pairs_checked}\n"
        f"  Links created: {links_created}"
    )


@mcp.tool()
@require_api_key
def suggest_connections(workspace_id: str = "default") -> str:
    """Find knowledge-graph node pairs that should be linked.

    Identifies node pairs that share neighbours but aren't directly
    connected, and returns ranked suggestions for new edges.

    Args:
        workspace_id: Target workspace (default: "default").
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    suggestions = cp.suggest_connections(workspace_id=workspace_id)
    if not suggestions:
        return "No connection suggestions found."
    lines = [
        f"Found {len(suggestions)} connection suggestion(s) "
        f"for workspace {workspace_id[:16]}...:"
    ]
    for s in suggestions[:20]:
        src = s.get("source_label", "?")
        tgt = s.get("target_label", "?")
        common = s.get("common_count", 0)
        lines.append(f"  - {src[:40]} → {tgt[:40]} ({common} common neighbour(s))")
    return "\n".join(lines)


@mcp.tool()
@require_api_key
def store_answer(
    query: str,
    answer: str,
    workspace_id: str = "default",
    source_memory_ids: str = "",
) -> str:
    """Persist an LLM-synthesized answer as a wiki page.

    Creates a note, extracts entities, creates KG nodes, links to
    source memories, ripple-updates entity summaries, and logs the
    activity.

    Args:
        query: The question that prompted the answer.
        answer: The synthesized answer text.
        workspace_id: Target workspace.
        source_memory_ids: Comma-separated list of source memory/node IDs.
    """
    from spacetime_memory.compounder import Compounder

    ids = [s.strip() for s in source_memory_ids.split(",") if s.strip()]
    cp = Compounder(get_client())
    result = cp.store_answer(
        query=query,
        answer=answer,
        workspace_id=workspace_id,
        source_memory_ids=ids or None,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    n_entities = len(result.get("entities", []))
    return (
        f"Answer stored (note: {note_id}...)\n"
        f"  Entities extracted: {n_entities}"
    )


@mcp.tool()
@require_api_key
def store_answers_batch(
    qa_pairs_json: str,
    workspace_id: str = "default",
    source_memory_ids: str = "",
) -> str:
    """Batch-persist multiple LLM-synthesized answers as wiki pages.

    More efficient than calling store_answer repeatedly — fetches the
    workspace index once and creates a single consolidated log entry.

    Args:
        qa_pairs_json: JSON string of [[query, answer], ...] pairs.
            Example: '[["What is RLHF?", "RLHF is..."], ["What is
            PPO?", "PPO is a..."]]'
        workspace_id: Target workspace (default: "default").
        source_memory_ids: Comma-separated list of source memory/node
            IDs that informed *all* answers in this batch (optional).

    Returns:
        Summary string with count of stored answers and extracted
        entities.
    """
    import json as _json

    from spacetime_memory.compounder import Compounder

    try:
        qa_pairs = _json.loads(qa_pairs_json)
    except _json.JSONDecodeError as e:
        return f"Error: invalid JSON in qa_pairs_json — {e}"

    if not isinstance(qa_pairs, list) or not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
        for p in qa_pairs
    ):
        return (
            "Error: qa_pairs_json must be a JSON list of [query, answer] "
            "string pairs, e.g. '[[\"Q1\", \"A1\"], [\"Q2\", \"A2\"]]'"
        )

    ids = (
        [s.strip() for s in source_memory_ids.split(",") if s.strip()]
        if source_memory_ids
        else None
    )
    cp = Compounder(get_client())
    results = cp.store_answers(
        qa_pairs=qa_pairs,
        workspace_id=workspace_id,
        source_memory_ids=ids,
    )

    n_stored = len(results)
    n_entities = sum(len(r.get("entities", [])) for r in results)
    return (
        f"Batch stored {n_stored} answers (note: {n_stored} notes)\n"
        f"  Total entities extracted: {n_entities}"
    )


@mcp.tool()
@require_api_key
def export_workspace(
    output_dir: str,
    workspace_id: str = "default",
    include_kg: bool = False,
    include_system_notes: bool = False,
) -> str:
    """Export all notes in a workspace as markdown files with YAML frontmatter.

    Generates one ``.md`` file per note, using the note title as the filename.
    Output is ready for Obsidian or git-based wiki browsing.

    Args:
        output_dir: Directory to write markdown files into.
        workspace_id: Target workspace (default: "default").
        include_kg: Also export KG node summaries as markdown.
        include_system_notes: Include ``_index`` and ``_log`` notes.

    Returns:
        Summary string with files written and output directory.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.export_workspace(
        output_dir=output_dir,
        workspace_id=workspace_id,
        include_kg=include_kg,
        include_system_notes=include_system_notes,
    )
    files_written = result.get("files_written", 0)
    out_dir = result.get("output_dir", output_dir)
    errors = result.get("errors", [])
    summary = f"Exported {files_written} file(s) to {out_dir}"
    if errors:
        summary += f"\n  Errors: {len(errors)}"
        for e in errors[:5]:
            summary += f"\n    - {e}"
    return summary


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="spacetime-memory MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transports (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8099,
        help="Port for HTTP transports (default: 8099)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport=args.transport)
