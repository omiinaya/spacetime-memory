"""MCP tools — Memory tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
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
    images_json: str = "",
    images: str | list[str] | None = None,
) -> dict[str, Any]:
    """Store a new memory with optional tier override and image attachments.

    Args:
        images: Convenience alternative to ``images_json``. Accepts a URL
            string, file path, or list of URLs/file paths. File paths are
            read and converted to data: URIs automatically. Overrides
            ``images_json`` when both are provided.
    """
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
        images=images,
        images_json=images_json,
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
    return_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Search memories via keyword with optional filters.

    Set rerank=True to enable LLM reranking for improved precision.

    Args:
        entity_types: Optional list of entity_type values to filter by
            (e.g. ["memory", "note"], or ["node"] for KG nodes only).
        before: Optional Unix timestamp — only return results created before this time.
        after: Optional Unix timestamp — only return results created after this time.
        return_schema: "llm" for compact LLM-friendly dicts, or None for raw dicts.
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
        return_schema=return_schema,
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
    return_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Multi-strategy hybrid search across memories, KG nodes, and temporal data.

    Uses LLM reranking by default for improved precision (P@5=29% vs 23% baseline).

    Args:
        entity_types: Optional list of entity_type values to filter by
            (e.g. ["memory", "note"], or ["node"] for KG nodes only).
        before: Optional Unix timestamp — only return results created before this time.
        after: Optional Unix timestamp — only return results created after this time.
        return_schema: "llm" for compact LLM-friendly dicts, or None for raw dicts.
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
        return_schema=return_schema,
    )


@mcp.tool()
@require_api_key
def search_with_filters(
    workspace_id: str,
    query: str = "",
    memory_type: str = "",
    tier: str = "",
    metadata_filter: str = "",
    location_filter: str = "",
    limit: int = 20,
    return_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Search memories with metadata and location filters.

    Provides structured metadata and location-based filtering that the
    general ``search_memories`` and ``hybrid_search`` tools do not
    expose.

    Args:
        workspace_id: Target workspace.
        query: Optional text query (keyword search).
        memory_type: Optional memory type filter (e.g. "memory", "note").
        tier: Optional tier filter (e.g. "L0", "L1", "L2").
        metadata_filter: JSON string of metadata key/value pairs to match
            (e.g. ``'{"source": "wiki", "priority": "high"}'``).
        location_filter: JSON string of location coordinates or named
            location (e.g. ``'{"lat": 37.77, "lng": -122.42}'``).
        limit: Max results (default: 20).
        return_schema: "llm" for compact LLM-friendly dicts, or None for raw dicts.

    Returns:
        List of matching memory dicts.
    """
    return get_client().search_with_filters(
        workspace_id=workspace_id,
        query=query,
        memory_type=memory_type,
        tier=tier,
        metadata_filter=metadata_filter,
        location_filter=location_filter,
        limit=limit,
        return_schema=return_schema,
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
    expires_at: int = -1,
) -> dict[str, Any]:
    """Update a memory's content, summary, and/or confidence.

    Only fields with non-empty/non-zero values are updated. Pass
    empty strings for fields you want to leave unchanged.

    Creates a revision snapshot before updating (version history).

    Parameters
    ----------
    expires_at:
        Expiration timestamp in microseconds (epoch).
        ``-1`` (default): preserve the current expiration.
        ``0``: clear expiration (memory never expires).
        ``>0``: set to the given absolute timestamp.
    """
    return get_client().update_memory(memory_id, content, summary, confidence, expires_at)


@mcp.tool()
@require_api_key
def delete_memory(memory_id: str) -> dict[str, Any]:
    """Delete (hard-delete) a memory by its ID."""
    return get_client().delete_memory(memory_id)


@mcp.tool()
@require_api_key
def update_memory_tier(memory_id: str, tier: str) -> dict[str, Any]:
    """Change a memory's compression tier.

    L0 = highest importance / shortest retention window (fits in primary context).
    L1 = warm cache (moderate importance, compressed periodically).
    L2 = cold storage (low importance, long-term archival).

    Args:
        memory_id: The ID of the memory to update.
        tier: New tier. Must be ``"L0"``, ``"L1"``, or ``"L2"``.

    Returns:
        The updated memory object.
    """
    return get_client().update_memory_tier(memory_id, tier)


@mcp.tool()
@require_api_key
def create_tag(workspace_id: str, name: str, color: str = "#808080") -> dict[str, Any]:
    """Create a new tag for organizing memories.

    Tags can be attached to memories to group them by topic, project,
    or any custom category.

    Args:
        workspace_id: Target workspace.
        name: Tag display name.
        color: Hex color string (default: ``"#808080"``).

    Returns:
        Confirmation dict with tag details.
    """
    return get_client().create_tag(workspace_id, name, color)


@mcp.tool()
@require_api_key
def tag_memory(memory_id: str, tag_id: str) -> dict[str, Any]:
    """Attach a tag to a memory.

    Args:
        memory_id: The memory to tag.
        tag_id: The tag ID to attach.

    Returns:
        Confirmation dict.
    """
    return get_client().tag_memory(memory_id, tag_id)


@mcp.tool()
@require_api_key
def untag_memory(memory_id: str, tag_id: str) -> dict[str, Any]:
    """Remove a tag from a memory.

    Args:
        memory_id: The tagged memory.
        tag_id: The tag ID to detach.

    Returns:
        Confirmation dict.
    """
    return get_client().untag_memory(memory_id, tag_id)


@mcp.tool()
@require_api_key
def list_tags(workspace_id: str) -> list[dict[str, Any]]:
    """List all tags in a workspace.

    Args:
        workspace_id: Target workspace.

    Returns:
        List of tag dicts with id, workspace_id, name, color, created_at.
    """
    return get_client().list_tags(workspace_id)


@mcp.tool()
@require_api_key
def delete_tag(tag_id: str) -> dict[str, Any]:
    """Delete a tag and all its memory associations.

    Args:
        tag_id: The tag ID to delete.

    Returns:
        Confirmation dict.
    """
    get_client().delete_tag(tag_id)
    return {"status": "ok", "deleted_tag_id": tag_id}


@mcp.tool()
@require_api_key
def batch_tag_memories(tag_id: str, memory_ids_json: str) -> dict[str, Any]:
    """Batch-attach a tag to multiple memories in a single reducer call.

    Eliminates O(n) network round-trips for bulk tagging. Already-tagged
    memories are silently skipped (idempotent).

    Args:
        tag_id: The tag ID to attach.
        memory_ids_json: JSON array of memory ID strings to tag.

    Returns:
        Status dict.
    """
    import json
    return get_client().batch_tag_memories(tag_id, json.loads(memory_ids_json))


@mcp.tool()
@require_api_key
def batch_untag_memories(tag_id: str, memory_ids_json: str) -> dict[str, Any]:
    """Batch-remove a tag from multiple memories in a single reducer call.

    Eliminates O(n) network round-trips for bulk untagging. Missing
    associations are silently skipped (idempotent).

    Args:
        tag_id: The tag ID to detach.
        memory_ids_json: JSON array of memory ID strings to untag.

    Returns:
        Status dict.
    """
    import json
    return get_client().batch_untag_memories(tag_id, json.loads(memory_ids_json))


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
            - ``images_json`` (str, optional) — JSON string of image
              attachments to associate with this memory (e.g., URLs or
              base64 data URIs).  Stored in the memory's ``context``
              field.  Pass ``""`` (default) for no images.
            - ``images`` (str or list[str], optional) — convenience
              alternative to ``images_json``. Accepts a URL string, file
              path, or list of URLs/file paths. File paths are read and
              converted to data: URIs automatically. Overrides
              ``images_json`` when both are provided.
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


# ---------------------------------------------------------------------------
# Batch operations tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def batch_update_memories(
    workspace_id: str,
    memory_ids_json: str,
    updates_json: str,
) -> str:
    """Batch update multiple memories with the same field changes.

    Performs client-side batching: loops over each memory_id and calls
    ``update_memory`` for each, preserving fields not in *updates_json*.

    Args:
        workspace_id: The workspace containing the memories.
        memory_ids_json: JSON array of memory IDs to update,
            e.g. ``'[\"mem-001\", \"mem-002\"]'``.
        updates_json: JSON object with fields to update,
            e.g. ``'{\"summary\": \"Updated\", \"confidence\": 0.95}'``.
            Supported fields: content, summary, confidence, tier, is_active.

    Returns:
        Confirmation message with update count and any errors.
    """
    import json as _json

    try:
        memory_ids = _json.loads(memory_ids_json)
    except (_json.JSONDecodeError, TypeError):
        return (
            "Error: memory_ids_json must be a valid JSON array of strings, "
            "e.g. '[\"mem-001\", \"mem-002\"]'"
        )
    if not isinstance(memory_ids, list):
        return "Error: memory_ids_json must be a JSON array."

    try:
        updates = _json.loads(updates_json)
    except (_json.JSONDecodeError, TypeError):
        return (
            "Error: updates_json must be a valid JSON object, "
            "e.g. '{\"summary\": \"...\", \"confidence\": 0.95}'"
        )
    if not isinstance(updates, dict):
        return "Error: updates_json must be a JSON object."

    result = get_client().batch_update_memories(
        workspace_id=workspace_id,
        memory_ids=memory_ids,
        updates=updates,
    )
    status = result.get("status", "ok")
    updated = result.get("updated", 0)
    errors = result.get("errors", [])
    msg = (
        f"Batch update complete (status: {status}).\n"
        f"  Memories updated: {updated}/{len(memory_ids)}\n"
    )
    if errors:
        msg += f"  Errors ({len(errors)}):\n"
        for err in errors:
            msg += f"    - {err}\n"
    return msg


# ---------------------------------------------------------------------------
# Veracity (Bayesian Confidence Scoring)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def update_memory_veracity(
    workspace_id: str,
    memory_id: str,
    outcome: bool = True,
    weight: float = 0.25,
) -> dict[str, Any]:
    """Update Bayesian veracity for a single memory with an observation.

    Each observation updates the Beta(alpha, beta) posterior:
    - Positive outcome (True): alpha += weight (confirmatory evidence)
    - Negative outcome (False): beta += weight (contradictory evidence)

    The memory's confidence and tier fields are automatically synced.

    Args:
        workspace_id: Target workspace.
        memory_id: The memory to update.
        outcome: ``True`` = confirmatory, ``False`` = contradictory.
        weight: Evidence weight (0.25 for explicit feedback, 0.05 for passive).

    Returns:
        Reducer status dict.
    """
    return get_client().update_memory_veracity(
        workspace_id=workspace_id,
        memory_id=memory_id,
        outcome=outcome,
        weight=weight,
    )


@mcp.tool()
@require_api_key
def batch_update_veracity(
    workspace_id: str,
    items_json: str,
) -> dict[str, Any]:
    """Batch update veracity for multiple memories.

    Args:
        workspace_id: Target workspace.
        items_json: JSON array of items, each with ``memory_id``,
            ``outcome`` (optional, default True), and ``weight``
            (optional, default 0.05).

    Example:
        ``'[{"memory_id": "abc", "outcome": true, "weight": 0.1}]'``

    Returns:
        Reducer status dict.
    """
    import json as _json

    try:
        items = _json.loads(items_json)
    except (_json.JSONDecodeError, TypeError):
        items = []
    return get_client().batch_update_veracity(
        workspace_id=workspace_id,
        items=items,
    )


@mcp.tool()
@require_api_key
def get_memory_veracity(
    workspace_id: str,
    memory_id: str,
) -> dict[str, Any] | None:
    """Get Bayesian veracity evidence for a memory.

    Returns the Beta(alpha, beta) posterior parameters, derived
    confidence score, veracity tier, and evidence counts.

    Args:
        workspace_id: Target workspace.
        memory_id: The memory to look up.

    Returns:
        Dict with keys: memory_id, alpha, beta, confidence, tier,
        evidence_count, confirmatory_count, contradictory_count.
    """
    return get_client().get_memory_veracity(
        workspace_id=workspace_id,
        memory_id=memory_id,
    )


@mcp.tool()
@require_api_key
def list_workspace_veracity(
    workspace_id: str,
) -> list[dict[str, Any]]:
    """List all veracity evidence entries for a workspace.

    Args:
        workspace_id: Target workspace.

    Returns:
        List of veracity summaries with memory_id, confidence, tier,
        evidence_count, and total_evidence.
    """
    return get_client().list_workspace_veracity(workspace_id=workspace_id)


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def detect_anomalies(
    workspace_id: str,
) -> list[dict[str, Any]]:
    """Detect statistical anomalies among memories in a workspace.

    Identifies memories whose confidence, content length, or entity
    count deviate from the workspace mean by more than 3 standard
    deviations (z-score > 3.0).

    Args:
        workspace_id: Target workspace.

    Returns:
        List of anomaly records with memory_id, anomaly_type
        (confidence_outlier|length_outlier|entity_outlier),
        metric_value, z_score, and description.
    """
    return get_client().detect_anomalies(workspace_id=workspace_id)
