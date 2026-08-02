"""Note CRUD and backlink management mixin."""
from __future__ import annotations

import json
from typing import Any

from ._base import logger


class NotesMixin:
    """Spacetime-Memory notes mixin.

    Provides Client methods related to note management, backlinks,
    and wiki-style cross-referencing.
    Inherits from ClientBase for connection infrastructure.
    """

    # ------------------------------------------------------------------
    # Notes (wiki-style)
    # ------------------------------------------------------------------

    def create_note(
        self,
        workspace_id: str = "default",
        title: str = "",
        content: str = "",
        note_date: str = "",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Create a note. If *embed* is True, auto-embeds via the sidecar."""
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        result = self._call(
            "create_note",
            [
                workspace_id,
                title,
                content,
                note_date,
                embedding_json,
            ],
        )
        if not isinstance(result, dict):
            result = {"status": "ok" if result is None else str(result)}

        # Resolve the created note ID so callers can immediately reference it
        # (same convention as create_workspace / store). The reducer only
        # returns status, so look it up by content match.
        if result.get("status") == "ok" and content.strip():
            try:
                notes = self._query(
                    "note",
                    workspace_id=workspace_id,
                    filter_dict={},
                    columns=["id", "content", "title"],
                )
                for n in reversed(notes):
                    if n.get("content", "") == content:
                        result["id"] = n["id"]
                        result["title"] = n.get("title", title)
                        result["content"] = n.get("content", content)
                        result["created_at"] = n.get("created_at")
                        break
            except RuntimeError:
                pass

        # Index the note into search_index so hybrid search finds it
        if result.get("status") == "ok" and content.strip():
            note_id = result.get("id", "")
            if not note_id:
                try:
                    # Resolve the note ID by content match (same pattern as store_memory)
                    notes = self._query(
                        "note",
                        workspace_id=workspace_id,
                        filter_dict={},
                        columns=["id", "content", "title"],
                    )
                    for n in reversed(notes):
                        if n.get("content", "") == content:
                            note_id = n["id"]
                            break
                except RuntimeError:
                    logger.warning("add_note: note ID resolution failed, skipping Tantivy/BM25 indexing")
                    return result
            if note_id:
                try:
                    index_emb = embedding_json if embedding_json != "[]" else "[]"
                    self._call(
                        "index_entity",
                        [
                            workspace_id,
                            "note",
                            note_id,
                            content,
                            index_emb,
                        ],
                    )
                    # Populate BM25 inverted index
                    self._call(
                        "index_terms",
                        [
                            workspace_id,
                            "note",
                            note_id,
                            content,
                        ],
                    )
                    # Index into Tantivy BM25 sidecar
                    self._tantivy_index(workspace_id, note_id, content, "note")
                except RuntimeError:
                    logger.warning("add_note: Tantivy/BM25 indexing failed for note %s, skipping", note_id)
        return result

    def update_note(
        self,
        note_id: str,
        title: str = "",
        content: str = "",
        embed: bool = True,
        expected_version: int = 0,
    ) -> dict[str, Any]:
        """Update a note. Re-embeds if content changes and *embed* is True.

        Pass *expected_version* to enable optimistic concurrency control.
        If the note has been modified since you last read it, the reducer
        returns an error and you should re-read, re-apply, and retry.
        """
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        result = self._call("update_note", [note_id, title, content, embedding_json, expected_version])

        # Re-index the note in search_index (best-effort)
        if result.get("status") == "ok" and content.strip():
            try:
                # Resolve workspace_id from the note record
                note_records = self._query(
                    "note",
                    filter_dict={"id": note_id},
                    columns=["id", "workspace_id", "content"],
                )
                wid = note_records[0]["workspace_id"] if note_records else "default"
                # Remove old index entries first
                self._call("remove_from_index", ["note", note_id])
                # Re-index with new content
                index_emb = embedding_json if embedding_json != "[]" else "[]"
                self._call("index_entity", [wid, "note", note_id, content, index_emb])
                self._call("index_terms", [wid, "note", note_id, content])
                self._tantivy_index(wid, note_id, content, "note")
            except RuntimeError:
                logger.warning("update_note: Tantivy re-indexing failed for note %s, skipping", note_id)
        return result

    def delete_note(self, note_id: str) -> dict[str, Any]:
        """Delete a note and its backlinks, and remove from search index."""
        result = self._call("delete_note", [note_id])
        # Clean up search index entries
        if result.get("status") == "ok":
            try:
                self._call("remove_from_index", ["note", note_id])
            except RuntimeError:
                logger.warning("delete_note: remove_from_index failed for note %s, skipping", note_id)
        return result

    def list_notes(
        self, workspace_id: str = "default", include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        """List notes in a workspace."""
        filt = {"workspace_id": workspace_id}
        if not include_inactive:
            filt["is_active"] = "true"
        rows = self._query("note", workspace_id=workspace_id, filter_dict=filt)
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        return rows

    def get_note(self, note_id: str) -> list[dict[str, Any]]:
        """Get a note by ID."""
        return self._query("note", filter_dict={"id": note_id})

    def get_note_by_date(self, note_date: str) -> list[dict[str, Any]]:
        """Get a note by its date string (YYYY-MM-DD)."""
        return self._query("note", filter_dict={"note_date": note_date, "is_active": "true"})

    def get_note_by_title(self, title: str, workspace_id: str = "") -> list[dict[str, Any]]:
        """Find a note by exact title.

        Args:
            title: The exact title to search for.
            workspace_id: Optional workspace to scope the search to.
                Pass an empty string (default) to search without workspace
                scoping.
        """
        return self._query("note", workspace_id=workspace_id, filter_dict={"title": title, "is_active": "true"})

    def get_backlinks(self, note_id: str) -> list[dict[str, Any]]:
        """Get all notes that link *to* the given note."""
        rows = self._query("note_backlink", filter_dict={"target_note_id": note_id})
        for r in rows:
            src = self._query("note", filter_dict={"id": r.get("source_note_id", "")})
            r["source_title"] = src[0].get("title", "") if src else ""
        return rows

    def get_outgoing_links(self, note_id: str) -> list[dict[str, Any]]:
        """Get all notes that the given note links *to*."""
        rows = self._query("note_backlink", filter_dict={"source_note_id": note_id})
        for r in rows:
            tgt = self._query("note", filter_dict={"id": r.get("target_note_id", "")})
            r["target_title"] = tgt[0].get("title", "") if tgt else ""
        return rows

    def update_note_block(self, block_id: str, content: str = "", block_type: str = "") -> dict[str, Any]:
        """Update a single note block.

        Args:
            block_id: The block ID to update.
            content: New content for the block.
            block_type: New block type.

        Returns:
            Reducer status dict.
        """
        return self._call("update_note_block", [block_id, content, block_type])

    def parse_note_blocks(self, note_id: str) -> dict[str, Any]:
        """Parse a note into blocks.

        Args:
            note_id: The note ID to parse.

        Returns:
            Reducer status dict.
        """
        return self._call("parse_note_blocks", [note_id])
