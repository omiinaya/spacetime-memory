"""Tag management mixin."""
from __future__ import annotations

import json
from typing import Any

from ._utils import _query_hash


class TagMixin:
    """Spacetime-Memory tag management mixin.

    Provides Client methods related to memory tagging and organization.
    Inherits from ClientBase for connection infrastructure.
    """

    # -----------------------------------------------------------------------
    # Profiles / Tags
    # -----------------------------------------------------------------------

    def create_tag(self, workspace_id: str, name: str, color: str = "#808080") -> None:
        """Create a new tag for organizing memories.

        Args:
            workspace_id: Target workspace.
            name: Tag display name.
            color: Hex color string (default: ``"#808080"``).
        """
        self._call("create_tag", [workspace_id, name, color])

    def tag_memory(self, memory_id: str, tag_id: str) -> None:
        """Attach a tag to a memory.

        Args:
            memory_id: The memory to tag.
            tag_id: The tag to attach.
        """
        self._call("tag_memory", [memory_id, tag_id])

    def untag_memory(self, memory_id: str, tag_id: str) -> None:
        """Remove a tag from a memory.

        Args:
            memory_id: The tagged memory.
            tag_id: The tag to detach.
        """
        self._call("untag_memory", [memory_id, tag_id])

    def batch_tag_memories(self, tag_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-attach a tag to multiple memories in a single reducer call.

        Eliminates O(n) network round-trips for bulk tagging by sending all
        memory IDs in one call to the ``batch_tag_memories`` reducer.

        Args:
            tag_id: The tag to attach.
            memory_ids: List of memory ID strings to tag. Already-tagged
                memories are silently skipped (idempotent).

        Returns:
            Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no memory IDs provided"}
        return self._call("batch_tag_memories", [tag_id, json.dumps(memory_ids)])

    def batch_untag_memories(self, tag_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-remove a tag from multiple memories in a single reducer call.

        Eliminates O(n) network round-trips for bulk untagging by sending all
        memory IDs in one call to the ``batch_untag_memories`` reducer.

        Args:
            tag_id: The tag to detach.
            memory_ids: List of memory ID strings to untag. Missing
                associations are silently skipped (idempotent).

        Returns:
            Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no memory IDs provided"}
        return self._call("batch_untag_memories", [tag_id, json.dumps(memory_ids)])

    def list_tags(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all tags in a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of tag dicts with id, workspace_id, name, color, created_at.
        """
        # Note: the list_tags reducer was changed to return () for STDB v2.6 compat.
        # We now query the tag table directly via _query.
        self._call("list_tags", [workspace_id])  # auth gate
        return self._query("tag", workspace_id=workspace_id, columns=["id", "workspace_id", "name", "color", "created_at"])

    def delete_tag(self, tag_id: str) -> None:
        """Delete a tag and all its memory associations.

        Args:
            tag_id: The tag ID to delete.
        """
        self._call("delete_tag", [tag_id])

    def list_tags_by_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """List all tags attached to a specific memory.

        Calls the ``list_tags_by_memory`` reducer which writes to the
        ``memory_tag_result`` table, then queries that table.

        Args:
            memory_id: The memory to look up tags for.

        Returns:
            A list of dicts with keys: id, memory_id, tag_id, tag_name, tag_color.
        """
        self._call("list_tags_by_memory", [memory_id])
        return self._query(
            "memory_tag_result",
            filter_dict={"memory_id": memory_id},
            columns=["id", "memory_id", "tag_id", "tag_name", "tag_color"],
        )

    def update_tag(self, tag_id: str, name: str = "", color: str = "#808080") -> None:
        """Update a tag's name and/or color.

        Args:
            tag_id: The tag ID to update.
            name: New display name (empty string leaves unchanged).
            color: New hex color string.
        """
        self._call("update_tag", [tag_id, name, color])

    def search_by_tags(
        self,
        workspace_id: str,
        tag_ids: list[str],
        query: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories by tag filter, optionally with semantic ranking.

        Only memories that have ALL specified tags are returned (intersection).

        Args:
            workspace_id: Target workspace.
            tag_ids: List of tag IDs to filter by (AND intersection).
            query: Optional query string for semantic ranking. Pass empty
                string to skip semantic similarity (results ordered by recency).
            limit: Maximum number of results.

        Returns:
            List of hybrid_result rows matching all tags, sorted by
            relevance (if query provided) or recency.
        """
        # Get embedding if query provided
        emb_json = "[]"
        if query:
            query_text = (
                f"Represent this sentence for searching relevant passages: {query}"
            )
            emb = self._embed(query_text)
            emb_json = json.dumps(emb) if emb else "[]"

        tag_ids_json = json.dumps(tag_ids)
        self._call(
            "search_by_tags",
            [
                workspace_id,
                tag_ids_json,
                emb_json,
                limit,
            ],
        )
        qhash = _query_hash(f"tagged:{tag_ids_json}")
        rows = self._query(
            "hybrid_result",
            workspace_id=workspace_id,
            filter_dict={"query_hash": qhash},
        )
        if rows:
            rows.sort(key=lambda r: r.get("score", 0) or 0, reverse=True)
        return rows
