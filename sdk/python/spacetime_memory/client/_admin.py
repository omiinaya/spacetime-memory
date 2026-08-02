"""Admin, maintenance, and configuration mixin."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ._base import SpacetimeDBError, logger
from ._utils import _esc


class AdminMixin:
    """Spacetime-Memory admin mixin.

    Provides Client methods related to admin management.
    Inherits from ClientBase for connection infrastructure.
    """
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
            Dict with the decrypted memory fields (content, summary, etc.)
            or an empty dict if not found.
        """
        self._call("get_decrypted_memory", [memory_id])
        rows = self._query("decrypted_memory_result", workspace_id="")
        return rows[0] if rows else {}

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
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
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
                    if not isinstance(row, dict):
                        logger.warning("restore: skipping malformed row (not a dict) in table '%s'", table)
                        continue
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
            except (SpacetimeDBError, httpx.HTTPError):
                logger.error("restore: failed to restore table '%s', skipping", table)
                continue

        return {
            "status": "ok",
            "input_path": input_path,
            "tables": restored,
            "total_rows": total_restored,
        }



    def remove_tour_stop(self, tour_stop_id: str) -> dict[str, Any]:
        """Remove a stop from a tour.

        Args:
            tour_stop_id: Tour stop ID to remove.

        Returns:
            The reducer status dict.
        """
        return self._call("remove_tour_stop", [tour_stop_id])

    def store_context_pack(
        self,
        workspace_id: str,
        name: str,
        memory_ids: list[str],
        context_text: str = "",
    ) -> dict[str, Any]:
        """Store a context pack (named collection of memories).

        Args:
            workspace_id: The workspace ID.
            name: Context pack name.
            memory_ids: List of memory IDs to include.
            context_text: Optional context description text.

        Returns:
            The reducer status dict.
        """
        return self._call(
            "store_context_pack",
            [workspace_id, name, json.dumps(memory_ids), context_text],
        )

    def decay_weak_memories(self, workspace_id: str, decay_rate: float = 0.5, threshold: float = 0.1) -> dict[str, Any]:
        """Decay weak memories in a workspace.

        Args:
            workspace_id: The workspace to decay memories in.
            decay_rate: Rate of decay (default: 0.5).
            threshold: Minimum relevance threshold (default: 0.1).

        Returns:
            Reducer status dict.
        """
        return self._call("decay_weak_memories", [workspace_id, decay_rate, threshold])

    def admin_deactivate_account(self, target_identity: str) -> dict[str, Any]:
        """Deactivate a user account.

        Args:
            target_identity: The identity string to deactivate.

        Returns:
            Reducer status dict.
        """
        return self._call("admin_deactivate_account", [target_identity])

    def delete_api_key(self, api_key_id: str) -> dict[str, Any]:
        """Delete an API key.

        Args:
            api_key_id: The API key ID to delete.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_api_key", [api_key_id])

    def manual_decay(self, workspace_id: str, memory_ids_json: str) -> dict[str, Any]:
        """Manually decay specific memories.

        Args:
            workspace_id: The workspace containing the memories.
            memory_ids_json: JSON-encoded list of memory IDs to decay.

        Returns:
            Reducer status dict.
        """
        return self._call("manual_decay", [workspace_id, memory_ids_json])
