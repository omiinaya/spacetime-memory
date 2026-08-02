"""Memory batch update and history mixin."""
from __future__ import annotations

from typing import Any


class HistoryMixin:
    """Spacetime-Memory batch update and history mixin.

    Provides Client methods related to batch memory updates and
    revision history for memories and notes.
    Inherits from ClientBase for connection infrastructure.
    """

    def batch_update_memories(
        self, workspace_id: str, memory_ids: list[str], updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Batch update multiple memories. Mem0 parity.
        updates can contain: content, summary, confidence, tier, is_active,
        expires_at

        Performs client-side batching: loops over each memory_id and
        calls the existing ``update_memory`` reducer individually.
        """
        updated = 0
        errors: list[str] = []
        for mem_id in memory_ids:
            try:
                # Fetch current memory to preserve unchanged fields
                current_rows = self._query(
                    "memory",
                    filter_dict={"id": mem_id},
                )
                if not current_rows:
                    errors.append(f"Memory '{mem_id}' not found")
                    continue
                current = current_rows[0]
                mem_ws = current.get("workspace_id", "")
                if workspace_id and mem_ws and mem_ws != workspace_id:
                    errors.append(f"Memory '{mem_id}' not in workspace '{workspace_id}'")
                    continue
                content = updates.get("content", current.get("content", ""))
                summary = updates.get("summary", current.get("summary", ""))
                confidence = updates.get("confidence", current.get("confidence", 0.8))
                expires_at = updates.get("expires_at", 0)
                self.update_memory(mem_id, content, summary, confidence, expires_at)
                updated += 1
            except Exception as e:
                errors.append(f"Memory '{mem_id}': {e}")

        if errors:
            return {"status": "partial", "updated": updated, "errors": errors}
        return {"status": "ok", "updated": updated}

    def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory. Mem0 parity.

        Returns revision history from the ``memory_revision`` table,
        ordered by version ascending.  Each entry shows what changed
        in that revision (previous vs new content/summary/confidence).

        The current (latest) state is appended as the final entry
        with no ``previous_*`` fields.
        """
        # Fetch revision history from the memory_revision table
        revisions = self._query(
            "memory_revision",
            filter_dict={"memory_id": memory_id},
        )
        # Sort by version ascending
        revisions.sort(key=lambda r: r.get("version", 0))

        result: list[dict[str, Any]] = []
        for rev in revisions:
            result.append(
                {
                    "version": rev.get("version", 0),
                    "previous_content": rev.get("previous_content", ""),
                    "previous_summary": rev.get("previous_summary", ""),
                    "previous_confidence": rev.get("previous_confidence", 1.0),
                    "content": rev.get("new_content", ""),
                    "summary": rev.get("new_summary", ""),
                    "confidence": rev.get("new_confidence", 1.0),
                    "changed_at": rev.get("changed_at", 0),
                    "changed_by": rev.get("changed_by", ""),
                }
            )

        # Append the current state as the latest version
        rows = self._query(
            "memory",
            filter_dict={"id": memory_id},
            columns=["content", "summary", "version", "updated_at", "confidence"],
        )
        if rows:
            r = rows[0]
            current_version = r.get("version", 1)
            # Only append if we don't already have this version
            if not result or result[-1].get("version") != current_version:
                result.append(
                    {
                        "version": current_version,
                        "previous_content": "",
                        "previous_summary": "",
                        "previous_confidence": 0.0,
                        "content": r.get("content", ""),
                        "summary": r.get("summary", ""),
                        "confidence": r.get("confidence", 1.0),
                        "changed_at": r.get("updated_at", 0),
                        "changed_by": "",
                    }
                )

        return result

    def get_note_history(self, note_id: str) -> list[dict[str, Any]]:
        """Get version history for a note.

        Returns revision history from the ``note_revision`` table,
        ordered by version ascending.  Each entry shows what changed
        in that revision (previous vs new title/content).

        The current (latest) state is appended as the final entry
        with no ``previous_*`` fields.
        """
        # Fetch revision history from the note_revision table
        revisions = self._query(
            "note_revision",
            filter_dict={"note_id": note_id},
        )
        # Sort by version ascending
        revisions.sort(key=lambda r: r.get("version", 0))

        result: list[dict[str, Any]] = []
        for rev in revisions:
            result.append(
                {
                    "version": rev.get("version", 0),
                    "previous_title": rev.get("previous_title", ""),
                    "previous_content": rev.get("previous_content", ""),
                    "title": rev.get("new_title", ""),
                    "content": rev.get("new_content", ""),
                    "changed_at": rev.get("changed_at", 0),
                    "changed_by": rev.get("changed_by", ""),
                }
            )

        # Append the current state as the latest version
        rows = self._query(
            "note",
            filter_dict={"id": note_id},
            columns=["title", "content", "version", "updated_at"],
        )
        if rows:
            r = rows[0]
            current_version = r.get("version", 1)
            # Only append if we don't already have this version
            if not result or result[-1].get("version") != current_version:
                result.append(
                    {
                        "version": current_version,
                        "previous_title": "",
                        "previous_content": "",
                        "title": r.get("title", ""),
                        "content": r.get("content", ""),
                        "changed_at": r.get("updated_at", 0),
                        "changed_by": "",
                    }
                )

        return result
