# flake8: noqa: F811
"""Admin, maintenance, and configuration mixin."""
from __future__ import annotations

import json
from typing import Any

from ._base import ClientBase, logger, _TRACER, _tracing_span, EmbedderUnavailableError, SpacetimeDBError, NotFoundError, ApiError
from ._utils import _esc, _parse_sql_response



class AdminMixin:
    """Spacetime-Memory admin mixin.

    Provides Client methods related to admin management.
    Inherits from ClientBase for connection infrastructure.
    """
    pass
    def run_maintenance(self) -> dict[str, Any]:
        """Trigger periodic maintenance (expire, decay, dedup)."""
        return self._call("manual_maintenance", [])

    def expire_memories(self) -> dict[str, Any]:
        """Manually expire all overdue memories.

        Iterates all memories and deactivates any whose ``expires_at``
        timestamp is in the past (greater than 0 and less than current
        time). Requires admin privileges on the database.

        Returns:
            Reducer status.
        """
        return self._call("expire_memories", [])

    def dedup(self, workspace_id: str) -> dict[str, Any]:
        """Run dedup within a workspace."""
        return self._call("dedup_memories", [workspace_id])

    def dedup_memories(self, workspace_id: str) -> dict[str, Any]:
        """Deduplicate near-duplicate memories in a workspace.

        Wraps the ``dedup_memories`` reducer (consolidation.rs:478).
        Near-duplicate detection uses cosine >= 0.85 + edit distance <= 30%.

        Args:
            workspace_id: The workspace to deduplicate.

        Returns:
            Reducer status dict.
        """
        return self.dedup(workspace_id)

    def consolidate_memories(
        self,
        workspace_id: str,
        source_ids: list[str],
        target_content: str,
        target_summary: str,
    ) -> dict[str, Any]:
        """Merge several source memories into a single new consolidated memory.

        Source memories are deactivated and a ``ConsolidationLog`` entry is
        created linking them to the new memory. The caller must be a workspace
        admin.

        Args:
            workspace_id: The workspace containing the source memories.
            source_ids: List of memory IDs to consolidate.
            target_content: Content for the new consolidated memory.
            target_summary: Summary for the new consolidated memory.

        Returns:
            Reducer status.
        """
        return self._call(
            "consolidate_memories",
            [workspace_id, json.dumps(source_ids), target_content, target_summary],
        )

    def suggest_merges(self, workspace_id: str, threshold: float = 0.8) -> dict[str, Any]:
        """Scan active memories and record merge suggestions.

        Args:
            workspace_id: The workspace to scan.
            threshold: Minimum cosine similarity threshold (default: 0.8).

        Returns:
            Reducer status.
        """
        return self._call("suggest_merges", [workspace_id, threshold])

    def approve_merge(self, suggestion_id: str) -> dict[str, Any]:
        """Approve a pending merge suggestion.

        Deactivates the source memory into the target (survivor) memory.

        Args:
            suggestion_id: The ID of the MergeSuggestion row.

        Returns:
            Reducer status.
        """
        return self._call("approve_merge", [suggestion_id])

    def reject_merge(self, suggestion_id: str) -> dict[str, Any]:
        """Reject a pending merge suggestion without merging.

        Args:
            suggestion_id: The ID of the MergeSuggestion row.

        Returns:
            Reducer status.
        """
        return self._call("reject_merge", [suggestion_id])

    # -----------------------------------------------------------------------
    # Session
    # -----------------------------------------------------------------------

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

        # Index the note into search_index so hybrid search finds it
        if result.get("status") == "ok" and content.strip():
            note_id = ""
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

    def get_note_by_title(self, title: str) -> list[dict[str, Any]]:
        """Find a note by exact title."""
        return self._query("note", filter_dict={"title": title, "is_active": "true"})

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

    # -------------------------------------------------------------------
    # KG Graph Traversal
    # -------------------------------------------------------------------

    def create_tour(self, workspace_id: str, title: str, description: str = "") -> None:
        """Create a new guided tour."""
        self._call("create_tour", [workspace_id, title, description])

    def add_tour_stop(
        self, tour_id: str, node_id: str, heading: str, description: str = ""
    ) -> None:
        """Add a stop to a tour."""
        self._call("add_tour_stop", [tour_id, node_id, heading, description])

    def delete_tour(self, tour_id: str) -> None:
        """Delete a tour and all its stops."""
        self._call("delete_tour", [tour_id])

    def delete_tour_stop(self, stop_id: str) -> None:
        """Remove a single stop from a tour.

        Args:
            stop_id: The ID of the tour stop to remove.
        """
        self._call("remove_tour_stop", [stop_id])

    # -------------------------------------------------------------------
    # Tag Management
    # -------------------------------------------------------------------

    def register_connector(
        self,
        name: str,
        connector_type: str,
        config_json: str,
        workspace_id: str,
        schedule_secs: int,
    ) -> None:
        """Register a new connector configuration."""
        self._call(
            "register_connector",
            [name, connector_type, config_json, workspace_id, schedule_secs],
        )

    def update_connector(
        self,
        id: str,
        name: str,
        connector_type: str,
        config_json: str,
        workspace_id: str,
        schedule_secs: int,
        is_active: bool,
    ) -> None:
        """Update an existing connector configuration."""
        self._call(
            "update_connector",
            [id, name, connector_type, config_json, workspace_id, schedule_secs, is_active],
        )

    def delete_connector(self, id: str) -> None:
        """Delete a connector configuration."""
        self._call("delete_connector", [id])

    # -------------------------------------------------------------------
    # Entity Extraction
    # -------------------------------------------------------------------

    def extract_entities(self, workspace_id: str, content: str) -> None:
        """Extract entities from text content and create KG nodes."""
        self._call("extract_entities", [workspace_id, content])

    # -------------------------------------------------------------------
    # Harmonic Beliefs
    # -------------------------------------------------------------------

    def store_harmonic_beliefs(
        self,
        workspace_id: str,
        peer_id: str,
        beliefs_json: str,
        cluster_id: str,
    ) -> None:
        """Store harmonized beliefs from one resonance round."""
        self._call(
            "store_harmonic_beliefs",
            [workspace_id, peer_id, beliefs_json, cluster_id],
        )

    def clear_harmonic_beliefs(self, workspace_id: str, min_confidence: float) -> None:
        """Clear stale beliefs for a workspace."""
        self._call("clear_harmonic_beliefs", [workspace_id, min_confidence])

    def log_resonance_session(
        self,
        workspace_id: str,
        peer_id: str,
        cluster_count: int,
        beliefs_generated: int,
        contradictions_resolved: int,
        harmony_score_avg: float,
        duration_ms: int,
    ) -> None:
        """Log a resonance session summary."""
        self._call(
            "log_resonance_session",
            [
                workspace_id,
                peer_id,
                cluster_count,
                beliefs_generated,
                contradictions_resolved,
                harmony_score_avg,
                duration_ms,
            ],
        )

    # -------------------------------------------------------------------
    # Entity Linking
    # -------------------------------------------------------------------

    def create_entity_link(
        self,
        workspace_id: str,
        canonical_name: str,
        entity_type: str,
        description: str = "",
    ) -> None:
        """Create a canonical entity link for Mem0-style entity resolution."""
        self._call(
            "create_entity_link",
            [
                workspace_id,
                canonical_name,
                "[]",
                entity_type,
                description,
            ],
        )

    def add_alias(self, entity_link_id: str, alias: str) -> None:
        """Add an alias to an existing entity link."""
        self._call("add_alias", [entity_link_id, alias])

    def resolve_entity(self, workspace_id: str, name: str) -> None:
        """Resolve an entity name within a workspace."""
        self._call("resolve_entity", [workspace_id, name])

    # -------------------------------------------------------------------
    # Backup & Restore
    # -------------------------------------------------------------------

    _BACKUP_TABLES = [
        "workspace",
        "space_permission",
        "memory",
        "memory_version",
        "kg_node",
        "kg_edge",
        "kg_community",
        "session",
        "session_participant",
        "message",
        "profile",
        "note",
        "fact",
        "peer",
        "context_pack",
        "context_entry",
        "directory",
        "directory_link",
        "backlink",
        "merge_suggestion",
        "connector_config",
        "entity_link",
    ]

    # -------------------------------------------------------------------
    # Memory Encryption at Rest
    # -------------------------------------------------------------------

    def init_workspace_encryption(self, workspace_id: str) -> dict[str, str]:
        """Initialise AES-256-GCM encryption for a workspace.

        Generates a new encryption key and enables encryption. Memories
        stored after this call will be encrypted before being written to
        SpacetimeDB. Existing plaintext memories are NOT automatically
        encrypted — call ``encrypt_existing_memories()`` after init.

        Idempotent: returns an error if encryption is already initialised.

        Args:
            workspace_id: The workspace to encrypt.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("init_workspace_encryption", [workspace_id])

    def set_workspace_encryption_enabled(
        self, workspace_id: str, enabled: bool
    ) -> dict[str, str]:
        """Enable or disable memory encryption for a workspace.

        When disabled, new memories are stored in plaintext. Existing
        encrypted memories are not automatically decrypted — they remain
        in their encrypted form in the database.

        Args:
            workspace_id: The workspace to modify.
            enabled: True to enable encryption, False to disable.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call(
            "set_workspace_encryption_enabled", [workspace_id, enabled]
        )

    def rotate_workspace_encryption_key(self, workspace_id: str) -> dict[str, str]:
        """Rotate the encryption key for a workspace.

        New memories will use the new key. Call ``encrypt_existing_memories()``
        after rotation to re-encrypt existing memories with the new key.

        Args:
            workspace_id: The workspace whose key should be rotated.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("rotate_workspace_encryption_key", [workspace_id])

    def encrypt_existing_memories(self, workspace_id: str) -> dict[str, str]:
        """Re-encrypt all unencrypted memories in a workspace.

        Useful after initial encryption setup or key rotation. Encrypts
        any memories whose content is still in plaintext using the current
        workspace encryption key.

        Requires encryption to be enabled for the workspace.

        Args:
            workspace_id: The workspace whose memories should be encrypted.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("encrypt_existing_memories", [workspace_id])

    def get_decrypted_memory(self, memory_id: str) -> dict[str, str]:
        """Fetch a memory with its content and summary decrypted.

        Calls the ``get_decrypted_memory`` reducer which decrypts the
        stored ciphertext using the workspace key. Results are written
        to the ``decrypted_memory_result`` table for the calling identity.

        Args:
            memory_id: The ID of the memory to decrypt and return.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("get_decrypted_memory", [memory_id])

    def backup(self, output_path: str | None = None) -> dict[str, Any]:
        """Export all user data tables to a JSON file.

        Args:
            output_path: Path to write the backup file. If None, generates
                a filename like ``spacetime-memory-backup-YYYY-MM-DD.json``.

        Returns:
            Dict with backup metadata: tables backed up, row counts, file path.
        """
        import datetime

        manifest: dict[str, list[dict[str, Any]]] = {}
        total_rows = 0
        backed_up = []

        for table in self._BACKUP_TABLES:
            try:
                rows = self._query(table)
            except RuntimeError:
                logger.debug("backup: table '%s' does not exist or is not queryable, skipping", table)
                continue  # table doesn't exist or isn't queryable
            if rows:
                manifest[table] = rows
                total_rows += len(rows)
                backed_up.append(table)
            else:
                manifest[table] = []

        if output_path is None:
            date = datetime.date.today().isoformat()
            output_path = f"spacetime-memory-backup-{date}.json"

        payload = {
            "version": "0.3.0",
            "created_at": datetime.datetime.utcnow().isoformat(),
            "tables": manifest,
            "stats": {
                "table_count": len(backed_up),
                "total_rows": total_rows,
            },
        }

        # ── Plugin dispatch: on_export ──
        if self.plugin_manager is not None:
            # Convert manifest to flat list for plugin filtering
            all_rows: list[dict[str, Any]] = []
            for rows in manifest.values():
                all_rows.extend(rows)
            self.plugin_manager.dispatch_export(all_rows)

        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        return {
            "status": "ok",
            "path": output_path,
            "tables": backed_up,
            "total_rows": total_rows,
        }

    def restore(self, input_path: str) -> dict[str, Any]:
        """Import a backup file into the current database.

        Args:
            input_path: Path to the backup JSON file.

        Returns:
            Dict with restore metadata: tables restored, row counts.
        """
        with open(input_path, "r") as f:
            payload = json.load(f)

        manifest = payload.get("tables", {})
        total_restored = 0
        restored = []

        # ── Plugin dispatch: on_import ──
        if self.plugin_manager is not None:
            all_rows: list[dict[str, Any]] = []
            for rows in manifest.values():
                all_rows.extend(rows)
            self.plugin_manager.dispatch_import(all_rows)

        for table, rows in manifest.items():
            if not rows:
                continue
            if not rows[0]:
                continue
            try:
                col_names = list(rows[0].keys())
                placeholders = ", ".join(col_names)
                for row in rows:
                    values = []
                    for col in col_names:
                        val = row.get(col)
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, bool):
                            values.append("true" if val else "false")
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        else:
                            values.append(f"'{_esc(str(val))}'")
                    sql = f"INSERT INTO {table} ({placeholders}) VALUES ({', '.join(values)})"
                    try:
                        self._sql(sql)
                    except RuntimeError:
                        logger.warning("restore: INSERT failed for table '%s' row, may be duplicate or schema mismatch", table)
                restored.append(table)
                total_restored += len(rows)
            except Exception:
                logger.error("restore: failed to restore table '%s', skipping", table)
                continue

        return {
            "status": "ok",
            "input_path": input_path,
            "tables": restored,
            "total_rows": total_restored,
        }

