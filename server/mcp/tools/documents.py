"""MCP tools — Document tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key

import json as _json

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
    return get_client().rate_memory(memory_id, rating, peer_id)


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
    get_client().dedup(workspace_id)
    return f"Dedup complete for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def consolidate_memories(
    workspace_id: str,
    source_ids_json: str,
    target_content: str,
    target_summary: str,
) -> str:
    """Merge several source memories into a single new consolidated memory.

    Source memories are deactivated and a ConsolidationLog entry is created.
    The caller must be a workspace admin.

    Args:
        workspace_id: The workspace containing the source memories.
        source_ids_json: JSON array of memory IDs to consolidate,
            e.g. '["id1","id2","id3"]'.
        target_content: Content for the new consolidated memory.
        target_summary: Summary for the new consolidated memory.

    Returns:
        Confirmation message.
    """
    get_client().consolidate_memories(
        workspace_id, _json.loads(source_ids_json), target_content, target_summary
    )
    return (
        f"Consolidation complete for workspace {workspace_id[:16]}... "
        f"{len(_json.loads(source_ids_json))} source memories merged."
    )


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
    get_client().set_memory_scope(memory_id, user_scope)
    return f"Memory {memory_id[:16]}... scoped to '{user_scope or 'shared'}'."


# ---------------------------------------------------------------------------
