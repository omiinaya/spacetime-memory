"""Workspace and user management mixin."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from typing import Any

from ._base import NotFoundError
from ._utils import _esc

logger = logging.getLogger(__name__)



class WorkspaceMixin:
    """Spacetime-Memory workspace mixin.

    Provides Client methods related to workspace management.
    Inherits from ClientBase for connection infrastructure.
    """
    def create_workspace(
        self, name: str, description: str = "", id: str | None = None
    ) -> dict[str, Any]:
        """Create a new workspace. Returns reducer status plus the workspace id.
        If *id* is omitted, generates a UUID client-side matching the reducer's
        UUID v4 format so callers can discover it immediately via list_workspaces.
        """
        import uuid

        ws_id = id if id else uuid.uuid4().hex[:32]
        self._call("create_workspace", [name, description, ws_id])

        # Plugin on_session_start hook (Hermes lifecycle parity) — plugins
        # can attach extra metadata to a freshly-created workspace.
        if self.plugin_manager is not None:
            try:
                extra = self.plugin_manager.dispatch_session_start(
                    ws_id, ws_id, {"name": name, "description": description}
                )
                if extra:
                    self.update_workspace(ws_id, name, description)
            except Exception:
                logger.debug("on_session_start plugin dispatch skipped", exc_info=True)

        return {"status": "ok", "id": ws_id}

    def list_workspaces(self) -> list[dict[str, Any]]:
        """List all workspaces."""
        return self._query("workspace")

    def delete_workspace(self, workspace_id: str) -> dict[str, Any]:
        """Delete a workspace and all its data."""
        return self._call("delete_workspace", [workspace_id])

    def update_workspace(self, id: str, name: str, description: str) -> dict[str, Any]:
        """Update a workspace's name and description. Requires owner access.

        Args:
            id: The workspace ID.
            name: New name for the workspace.
            description: New description for the workspace.

        Returns:
            Dict with reducer response status.
        """
        return self._call("update_workspace", [id, name, description])

    def set_workspace_visibility(self, workspace_id: str, is_public: bool) -> dict[str, Any]:
        """Toggle whether a workspace is public or private. Requires owner access.

        Args:
            workspace_id: The workspace to update.
            is_public: True to make public, False to make private.

        Returns:
            Dict with reducer response status.
        """
        return self._call("set_workspace_visibility", [workspace_id, is_public])

    def get_workspace_context(self, workspace_id: str) -> dict[str, Any]:
        """Get the context string attached to a workspace.

        Calls the ``get_workspace_context`` reducer which writes to the
        ``workspace_context_result`` table, then queries that table.

        Args:
            workspace_id: The workspace to retrieve context for.

        Returns:
            Dict with workspace_id, context, and queried_at fields.
        """
        self._call("get_workspace_context", [workspace_id])
        rows = self._query("workspace_context_result")
        if rows:
            return rows[0]
        return {"workspace_id": workspace_id, "context": "", "queried_at": 0}

    def list_space_members(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all members with their permissions for a workspace.

        Calls the ``list_space_members`` reducer which writes to the
        ``space_member_result`` table, then queries that table.

        Args:
            workspace_id: The workspace (space) ID.

        Returns:
            A list of dicts with keys: id, workspace_id, peer_id, permission,
            granted_by, created_at, queried_at.
        """
        self._call("list_space_members", [workspace_id])
        rows = self._query("space_member_result")
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def grant_space_access(
        self, workspace_id: str, peer_id: str, permission: str
    ) -> dict[str, Any]:
        """Grant a peer access to a workspace with a specific permission level.

        Only an existing owner or admin can grant access.

        Args:
            workspace_id: The workspace (space) ID.
            peer_id: The peer ID to grant access to.
            permission: One of ``'owner'``, ``'editor'``, or ``'viewer'``.

        Returns:
            Reducer status.
        """
        return self._call("grant_space_access", [workspace_id, peer_id, permission])

    def revoke_space_access(self, workspace_id: str, peer_id: str) -> dict[str, Any]:
        """Revoke a peer's access to a workspace.

        Only an existing owner or admin can revoke access. Owners cannot
        revoke their own access (use a separate escalation process).

        Args:
            workspace_id: The workspace (space) ID.
            peer_id: The peer ID to revoke access from.

        Returns:
            Reducer status.
        """
        return self._call("revoke_space_access", [workspace_id, peer_id])

    # -----------------------------------------------------------------------
    # Auth / Account
    # -----------------------------------------------------------------------

    def register(
        self, username: str, display_name: str = "", password: str = ""
    ) -> dict[str, Any]:
        """Register a new account. First user becomes admin.

        Args:
            username: Unique username for the account.
            display_name: Optional display name (defaults to username).
            password: Password (minimum 6 characters). If empty, generates
                a warning — the Rust reducer enforces >=6 chars.

        Returns:
            Reducer status dict.
        """
        return self._call("register", [username, display_name, password])

    def login(self, username: str, password: str) -> dict[str, Any]:
        """Login with username + password. Links this identity to the account.

        After a successful login, the caller's identity is associated with
        this account. A new identity token is captured from the response
        headers automatically by :meth:`_call`.

        Args:
            username: Account username.
            password: Account password.

        Returns:
            Reducer status dict.
        """
        return self._call("login", [username, password])

    def logout(self) -> dict[str, Any]:
        """Logout — detach the current identity from its account.

        After logout, the caller must re-login to access gated features.

        Returns:
            Reducer status dict.
        """
        return self._call("logout", [])

    def update_account(
        self,
        display_name: str = "",
        current_password: str = "",
        new_password: str = "",
    ) -> dict[str, Any]:
        """Update account display name and/or password.

        Args:
            display_name: New display name (empty = no change).
            current_password: Current password (required for verification).
            new_password: New password (empty = no change, min 6 chars).

        Returns:
            Reducer status dict.
        """
        return self._call("update_account", [display_name, current_password, new_password])

    def deactivate_account(self, password: str) -> dict[str, Any]:
        """Deactivate (soft-delete) this account.

        The account remains in the database with ``is_active = false``,
        preventing future logins. Cannot be reversed through the API.

        Args:
            password: Account password (required for verification).

        Returns:
            Reducer status dict.
        """
        return self._call("deactivate_account", [password])

    def promote_admin(self, target_identity: str) -> dict[str, Any]:
        """Promote a user to admin. Caller must be an existing admin.

        Args:
            target_identity: The identity hex string of the user to promote.

        Returns:
            Reducer status dict.
        """
        return self._call("promote_admin", [target_identity])

    def demote_admin(self, target_identity: str) -> dict[str, Any]:
        """Demote an admin to regular user. Caller must be an existing admin.

        Cannot demote yourself. At least one admin must always remain.

        Args:
            target_identity: The identity hex string of the admin to demote.

        Returns:
            Reducer status dict.
        """
        return self._call("demote_admin", [target_identity])

    def list_admins(self) -> list[dict[str, Any]]:
        """List all admin accounts.

        Results are read from the admin_result public table after calling
        the reducer.

        Returns:
            List of admin account records.
        """
        self._call("list_admins", [])
        return self._query("admin_result")

    # -----------------------------------------------------------------------
    # Memory
    # -----------------------------------------------------------------------

    def create_api_key(
        self,
        workspace_id: str,
        name: str,
        permissions: str = '["read"]',
        scope: str = "*",
    ) -> dict[str, Any]:
        """Create a new API key with optional scope limits.

        Generates a secure random key secret, hashes it, and stores the
        hash in the SpacetimeDB ``ApiKey`` table.  The unhashed secret is
        returned **only once** — save it.

        Args:
            workspace_id: The workspace to associate the key with.
            name: A human-readable label for this key.
            permissions: JSON array of permission strings
                (default: ``["read"]``).
            scope: JSON scope defining workspace access limits.
                ``"*"`` (default) = system-wide / admin-level access.
                ``'["ws-1", "ws-2"]'`` = scoped to specific workspace IDs.

        Returns:
            Dict with ``status``, ``api_key`` (the secret), ``id`` (the
            key's database ID), ``scope``, and a warning note.
        """
        raw = secrets.token_bytes(32)
        api_key = "sk-" + raw.hex()
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        request_id = secrets.token_hex(16)

        self._call(
            "create_api_key",
            [
                workspace_id,
                name,
                permissions,
                key_hash,
                request_id,
                scope,
            ],
        )

        # Fetch the just-created key from the result table
        rows = self._query(
            "api_key_result",
            workspace_id="",
            filter_dict={"request_id": request_id, "operation": "create"},
            columns=["api_key_id", "name", "permissions", "scope"],
        )
        key_id = rows[0]["api_key_id"] if rows else ""

        return {
            "status": "ok",
            "api_key": api_key,
            "id": key_id,
            "scope": scope,
            "note": "Save this key — it will not be shown again.",
        }

    def verify_api_key(
        self,
        raw_key: str,
    ) -> dict[str, Any]:
        """Verify an API key by its raw secret (sk-...).

        Hashes the key and looks it up against stored key hashes in the
        ``ApiKey`` table.  Returns the key's scope, permissions, and
        metadata if valid.

        Args:
            raw_key: The full ``sk-...`` API key secret.

        Returns:
            Dict with verification result including ``valid``, ``api_key_id``,
            ``workspace_id``, ``scope``, ``permissions``, ``name``, and
            ``verified_at``. If the key is invalid, ``valid`` is ``False``.
        """
        try:
            self._call("verify_api_key", [raw_key])
        except Exception as e:
            return {"valid": False, "error": str(e)}

        rows = self._query(
            "api_key_verification_result",
            workspace_id="",
            columns=[
                "api_key_id", "workspace_id", "name", "permissions", "scope",
                "is_active", "created_at", "last_used_at", "verified_at",
            ],
        )
        # Sort by most recent verification
        rows.sort(key=lambda r: r.get("verified_at", 0), reverse=True)
        if not rows:
            return {"valid": False, "error": "Key not found or deactivated"}

        row = rows[0]
        return {
            "valid": True,
            "api_key_id": row["api_key_id"],
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "permissions": row["permissions"],
            "scope": row["scope"],
            "is_active": row["is_active"],
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
            "verified_at": row["verified_at"],
        }

    def update_api_key(
        self,
        key_id: str,
        name: str = "",
        permissions: str = "",
        scope: str = "",
        is_active: bool = True,
    ) -> dict[str, Any]:
        """Update an API key's name, permissions, scope, or active status.

        Args:
            key_id: The primary-key ``id`` of the ``ApiKey`` row.
            name: New label (empty = leave unchanged).
            permissions: New JSON permission array (empty = leave unchanged).
            scope: New scope string (empty = leave unchanged).
                ``"*"`` for all workspaces, or ``'["ws-1"]'`` for scoped access.
            is_active: Active status (default: True).

        Returns:
            Reducer status dict.
        """
        return self._call(
            "update_api_key",
            [key_id, name, permissions, scope, is_active],
        )

    def deactivate_api_key(self, key_id: str) -> dict[str, Any]:
        """Deactivate (revoke) an API key so it can no longer be used.

        Args:
            key_id: The primary-key ``id`` of the ``ApiKey`` row.

        Returns:
            Reducer status dict.
        """
        return self._call("deactivate_api_key", [key_id])

    def list_api_keys(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all API keys for a workspace.

        Calls the ``list_api_keys`` reducer which populates the public
        ``api_key_result`` table with metadata (key_hash excluded).

        Args:
            workspace_id: The workspace to query.

        Returns:
            List of API key metadata dicts.  The ``key_hash`` is never
            exposed — only safe metadata is returned.
        """
        self._call("list_api_keys", [workspace_id])
        return self._query(
            "api_key_result",
            workspace_id=workspace_id,
            filter_dict={"operation": "list"},
            columns=["api_key_id", "name", "permissions", "scope", "is_active", "created_at", "last_used_at"],
        )

    # -----------------------------------------------------------------------
    # User management
    # -----------------------------------------------------------------------

    def add_user(
        self,
        user_id: str,
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        metadata_json: str = "",
    ) -> dict[str, Any]:
        """Add a new user.

        The user table is public (readable via SQL) but mutations go through
        this reducer for auth enforcement.

        Args:
            user_id: Unique identifier for the user.
            email: Optional email address.
            first_name: Optional first name.
            last_name: Optional last name.
            metadata_json: Optional JSON blob for custom metadata.

        Returns:
            Reducer status dict.
        """
        return self._call("add_user", [user_id, email, first_name, last_name, metadata_json])

    def get_user(self, user_id: str) -> dict[str, Any]:
        """Verify a user exists and return their data.

        Calls the ``get_user`` reducer which populates the public
        ``user_get_result`` table, then reads from it.

        Args:
            user_id: The user to look up.

        Returns:
            The user row, or raises :class:`NotFoundError` if absent.
        """
        self._call("get_user", [user_id])
        rows = self._query("user_get_result", filter_dict={"id": f"get_user:{user_id}"})
        if not rows:
            raise NotFoundError(f"User '{user_id}' not found")
        return rows[0]

    def update_user(
        self,
        user_id: str,
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        metadata_json: str = "",
    ) -> dict[str, Any]:
        """Update an existing user. Empty strings are treated as "don't update"
        (the Rust reducer preserves the existing value).

        Args:
            user_id: The user to update.
            email: New email (empty = unchanged).
            first_name: New first name (empty = unchanged).
            last_name: New last name (empty = unchanged).
            metadata_json: New metadata JSON (empty = unchanged).

        Returns:
            Reducer status dict.
        """
        return self._call("update_user", [user_id, email, first_name, last_name, metadata_json])

    def delete_user(self, user_id: str) -> dict[str, Any]:
        """Delete a user by user_id.

        Args:
            user_id: The user to delete.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_user", [user_id])

    def list_users(self) -> list[dict[str, Any]]:
        """List all users.

        Calls the ``list_users`` reducer which populates the public
        ``user_get_result`` table, then reads from it.

        Returns:
            List of user rows.
        """
        self._call("list_users", [])
        rows = self._query("user_get_result")
        return [r for r in rows if r.get("id", "").startswith("list_users:")]

    def get_user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all sessions for a user.

        Calls the ``get_user_sessions`` reducer which populates the public
        ``user_session_result`` table with session metadata.

        Args:
            user_id: The user to look up sessions for.

        Returns:
            List of session records (query_id, user_id, session_id,
            session_name, workspace_id, created_at).
        """
        query_id = f"user_sessions:{user_id}"
        self._call("get_user_sessions", [user_id])
        return self._query("user_session_result", filter_dict={"query_id": query_id})

    # -----------------------------------------------------------------------
    # Peer queries
    # -----------------------------------------------------------------------

    def list_peers(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """List peers, optionally filtered by workspace."""
        return self._query("peer", workspace_id=workspace_id or "")

    # -----------------------------------------------------------------------
    # Context pack queries
    # -----------------------------------------------------------------------

    def list_context_packs(self, workspace_id: str) -> list[dict[str, Any]]:
        """List context packs for a workspace."""
        return self._query("context_pack", filter_dict={"workspace_id": workspace_id})

    def list_context_entries(self, pack_id: str) -> list[dict[str, Any]]:
        """List entries in a context pack."""
        return self._query("context_entry", filter_dict={"pack_id": pack_id})

    def list_context_deltas(self, previous_pack_id: str) -> list[dict[str, Any]]:
        """List delta entries for a pack."""
        return self._query("context_delta", filter_dict={"previous_pack_id": previous_pack_id})

    # -----------------------------------------------------------------------
    # Notes (markdown documents with wikilink backlinking)
    # -----------------------------------------------------------------------


    # -----------------------------------------------------------------------
    # Workspace overview & export
    # -----------------------------------------------------------------------

    def generate_overview(self, workspace_id: str) -> dict[str, Any]:
        """Generate a workspace overview with counts of memories, KG nodes, edges, and notes.

        Args:
            workspace_id: The workspace ID.

        Returns:
            A dict with counts: memories, nodes, edges, notes, sessions, etc.
        """
        # Count memories
        memories = self._sql(
            f"SELECT COUNT(*) as cnt FROM memory WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        memory_count = memories[0]["cnt"] if memories else 0

        # Count KG nodes
        nodes = self._sql(
            f"SELECT COUNT(*) as cnt FROM kg_node WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        node_count = nodes[0]["cnt"] if nodes else 0

        # Count KG edges
        edges = self._sql(
            f"SELECT COUNT(*) as cnt FROM kg_edge WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        edge_count = edges[0]["cnt"] if edges else 0

        # Count notes
        notes = self._sql(
            f"SELECT COUNT(*) as cnt FROM note WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        note_count = notes[0]["cnt"] if notes else 0

        # Count sessions
        sessions = self._sql(
            f"SELECT COUNT(*) as cnt FROM session WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        session_count = sessions[0]["cnt"] if sessions else 0

        return {
            "workspace_id": workspace_id,
            "memories": memory_count,
            "nodes": node_count,
            "edges": edge_count,
            "notes": note_count,
            "sessions": session_count,
        }

    def export_workspace(self, workspace_id: str) -> str:
        """Export workspace notes as a single markdown string.

        Each note becomes an H1 title followed by its content, separated by ``---``.

        Args:
            workspace_id: The workspace ID.

        Returns:
            A concatenated markdown string of all notes.
        """
        notes = self._sql(
            f"SELECT title, content FROM note WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        parts = []
        for note in notes:
            title = note.get("title", "")
            content = note.get("content", "") or ""
            parts.append(f"# {title}\n\n{content}")
        return "\n\n---\n\n".join(parts)

    def export_workspace_json(
        self,
        workspace_id: str,
        include_system_notes: bool = False,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Export all workspace data as structured JSON.

        Includes notes, KG nodes/edges, memories, profiles, facts, sessions,
        tours, directories, and more.

        Args:
            workspace_id: The workspace ID to export.
            include_system_notes: Whether to include notes starting with '_'.
            output_path: Optional file path to write JSON (local filesystem).

        Returns:
            A dict with ``status``, ``workspace_id``, ``tables``, ``total_rows``,
            and ``json`` fields.
        """
        import datetime

        manifests: dict[str, list[dict[str, Any]]] = {}
        backed_up: list[str] = []
        total_rows = 0

        # Tables scoped by workspace_id
        ws_scoped_tables = [
            "memory", "memory_version", "kg_node", "kg_edge", "kg_community",
            "note", "session", "session_participant", "message", "profile",
            "fact", "tour", "tour_stop", "directory", "directory_link",
            "backlink", "merge_suggestion", "context_pack", "context_entry",
            "context_delta", "document", "document_chunk",
        ]

        for table in ws_scoped_tables:
            rows = self._query(table, workspace_id=workspace_id)
            if not include_system_notes and table == "note":
                rows = [r for r in rows if not r.get("title", "").startswith("_")]
            manifests[table] = rows or []
            total_rows += len(manifests[table])
            backed_up.append(table)

        # Include workspace metadata itself
        ws_data = self._sql(
            f"SELECT * FROM workspace WHERE id = '{_esc(workspace_id)}' LIMIT 1"
        )
        if ws_data:
            manifests["workspace"] = [ws_data[0]]
            backed_up.append("workspace")
            total_rows += 1
        else:
            manifests["workspace"] = []

        payload = {
            "version": "0.3.0",
            "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "workspace_id": workspace_id,
            "tables": manifests,
            "stats": {
                "table_count": len(backed_up),
                "total_rows": total_rows,
            },
        }

        json_str = json.dumps(payload, indent=2, default=str)

        if output_path:
            with open(output_path, "w") as f:
                f.write(json_str)

        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "tables": backed_up,
            "total_rows": total_rows,
            "json": json_str,
        }
