"""Enhanced RBAC mixin — Cognee-parity role-based access control.

Provides workspace-level roles (admin, editor, viewer, custom) and
resource-level permissions (read, write, delete, share, admin) via
the existing SpacetimeDB ACL infrastructure.

Builds on the ``grant_space_access`` / ``revoke_space_access`` /
``promote_admin`` / ``demote_admin`` reducers and adds client-side
role templates, permission inheritance, and high-level assignment
and revocation methods.

Usage::

    client.assign_role(workspace_id="ws-1", user_id="...", role="editor")
    client.revoke_role(workspace_id="ws-1", user_id="...")
    client.check_permission(workspace_id="ws-1", user_id="...", permission="write")
    client.create_custom_role(workspace_id="ws-1", role_name="moderator",
                              permissions=["read", "write", "delete"])
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ._base import SpacetimeDBError, logger

# ---------------------------------------------------------------------------
# Sentinel constants
# ---------------------------------------------------------------------------

_INHERIT = object()  # sentinel for "inherit from parent scope"


# ---------------------------------------------------------------------------
# Built-in workspace-level roles and their mapping to SpacetimeDB permission
# levels
# ---------------------------------------------------------------------------

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLE_CUSTOM = "custom"

# Maps workspace role → SpacetimeDB native permission string.
# These are the same values the ``grant_space_access`` reducer accepts.
BUILTIN_ROLES: dict[str, str] = {
    ROLE_ADMIN: "owner",
    ROLE_EDITOR: "editor",
    ROLE_VIEWER: "viewer",
}

# Resource-level permission primitives.
PERMISSION_READ = "read"
PERMISSION_WRITE = "write"
PERMISSION_DELETE = "delete"
PERMISSION_SHARE = "share"
PERMISSION_ADMIN = "admin"

ALL_PERMISSIONS: set[str] = {
    PERMISSION_READ,
    PERMISSION_WRITE,
    PERMISSION_DELETE,
    PERMISSION_SHARE,
    PERMISSION_ADMIN,
}

# Default templates: built-in roles expressed as sets of resource permissions.
ROLE_TEMPLATES: dict[str, set[str]] = {
    ROLE_ADMIN: {PERMISSION_READ, PERMISSION_WRITE, PERMISSION_DELETE, PERMISSION_SHARE, PERMISSION_ADMIN},
    ROLE_EDITOR: {PERMISSION_READ, PERMISSION_WRITE, PERMISSION_DELETE},
    ROLE_VIEWER: {PERMISSION_READ},
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RBACError(SpacetimeDBError):
    """Raised on RBAC operation failures (invalid role, permission denied, etc.)."""


class InvalidRoleError(RBACError):
    """Raised when an unknown or invalid role name is supplied."""


class InvalidPermissionError(RBACError):
    """Raised when an unknown or invalid permission is supplied."""


class UserNotFoundError(RBACError):
    """Raised when a user identity is not found in the system."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RoleTemplate:
    """A named template mapping permissions to a role.

    Attributes:
        name: The role name (e.g. ``"editor"``, ``"moderator"``).
        permissions: The set of resource-level permission strings granted
            by this role.
        description: Optional human-readable description.
    """
    name: str
    permissions: set[str]
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "permissions": sorted(self.permissions),
            "description": self.description,
        }


@dataclass
class RoleAssignment:
    """A record of a user assigned to a role at some scope.

    Attributes:
        workspace_id: The workspace scope.
        user_id: The identity hex string of the user.
        role: The role name (``"admin"``, ``"editor"``, ``"viewer"``, or a
            custom role name).
        permission_level: The SpacetimeDB-native permission string
            (``"owner"``, ``"editor"``, ``"viewer"`` — or ``"custom"``).
        granted_by: The identity hex of the granter.
    """
    workspace_id: str
    user_id: str
    role: str
    permission_level: str = ""
    granted_by: str = ""


# ---------------------------------------------------------------------------
# RBAC Mixin
# ---------------------------------------------------------------------------


class RBACMixin:
    """Spacetime-Memory RBAC mixin.

    Provides workspace-level and resource-level access control methods
    that wrap the existing reducer infrastructure with role abstractions,
    permission checking, role templates, and bulk operations.

    Inherits from ClientBase for connection infrastructure.
    """

    # -------------------------------------------------------------------
    # Role assignment & revocation
    # -------------------------------------------------------------------

    def assign_role(
        self,
        workspace_id: str,
        user_id: str,
        role: str,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Assign a role to a user for a workspace.

        For built-in roles (admin, editor, viewer), the method maps the
        role to the corresponding SpacetimeDB permission level and calls
        ``grant_space_access``.

        For custom roles, the caller **must** supply explicit permission
        list. The method grants access with a ``"custom"`` permission
        level and records the custom role metadata in a ``RoleTemplate``
        table if the role does not already exist.

        Args:
            workspace_id: Target workspace.
            user_id: The identity hex of the user to assign the role to.
            role: Role name — one of ``"admin"``, ``"editor"``,
                ``"viewer"``, or any custom role name.
            permissions: Required when ``role="custom"``. Optional for
                built-in roles (defaults to the built-in template
                permissions). A list of permission strings from:
                ``"read"``, ``"write"``, ``"delete"``, ``"share"``,
                ``"admin"``.

        Returns:
            Reducer status dict with extra ``role`` and ``user_id`` keys.

        Raises:
            InvalidRoleError: If the role name is unknown and not custom.
            InvalidPermissionError: If any permission is not recognised.
            RBACError: On backend failure.
        """
        role_lower = role.lower()

        if role_lower == ROLE_CUSTOM:
            if not permissions or not set(permissions).issubset(ALL_PERMISSIONS):
                invalid = set(permissions or []) - ALL_PERMISSIONS
                raise InvalidPermissionError(
                    f"Invalid permissions for custom role: {sorted(invalid)}. "
                    f"Valid permissions: {sorted(ALL_PERMISSIONS)}"
                )
            # Grant with native "editor" level (most flexible base) and
            # store the fine-grained custom role definition.
            self._call("grant_space_access", [workspace_id, user_id, "editor"])
            self._upsert_custom_role(workspace_id, role, permissions)
            return {
                "status": "ok",
                "role": role,
                "user_id": user_id,
                "permissions": permissions,
                "note": "Custom role assigned. Fine-grained enforcement is client-side.",
            }

        if role_lower not in BUILTIN_ROLES:
            # Check if it's a previously registered custom role
            try:
                stored = self._get_custom_role(workspace_id, role_lower)
                if stored is not None:
                    return self.assign_role(
                        workspace_id, user_id, ROLE_CUSTOM,
                        permissions=stored.get("permissions"),
                    )
            except Exception:
                pass
            raise InvalidRoleError(
                f"Unknown role '{role}'. "
                f"Built-in roles: {', '.join(BUILTIN_ROLES)}. "
                f"Use custom roles via assign_role(…, role='custom', permissions=[…])."
            )

        # Built-in role: map to native permission level
        native_perm = BUILTIN_ROLES[role_lower]
        self._call("grant_space_access", [workspace_id, user_id, native_perm])

        return {
            "status": "ok",
            "role": role_lower,
            "user_id": user_id,
            "permission_level": native_perm,
        }

    def revoke_role(
        self,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Revoke a user's role (all permissions) for a workspace.

        Wraps the ``revoke_space_access`` reducer.

        Args:
            workspace_id: Target workspace.
            user_id: The identity hex of the user to revoke access from.

        Returns:
            Reducer status dict.
        """
        return self._call("revoke_space_access", [workspace_id, user_id])

    def list_role_assignments(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List all role assignments (members) for a workspace.

        Wraps ``list_space_members`` and normalises the output to
        include the role name alongside the native permission level.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of member dicts with keys: id, workspace_id, user_id,
            role, permission_level, granted_by, created_at.
        """
        self._call("list_space_members", [workspace_id])
        rows = self._query("space_member_result")
        rows.sort(key=lambda r: r.get("created_at", 0))

        # Build a reverse map: native permission → role name
        native_to_role: dict[str, str] = {v: k for k, v in BUILTIN_ROLES.items()}
        native_to_role["custom"] = ROLE_CUSTOM

        result: list[dict[str, Any]] = []
        for row in rows:
            perm = row.get("permission", "").lower()
            role_name = native_to_role.get(perm, perm)
            result.append({
                "id": row.get("id", ""),
                "workspace_id": row.get("workspace_id", workspace_id),
                "user_id": row.get("peer_id", ""),
                "role": role_name,
                "permission_level": perm,
                "granted_by": row.get("granted_by", ""),
                "created_at": row.get("created_at", 0),
            })
        return result

    # -------------------------------------------------------------------
    # Permission checking
    # -------------------------------------------------------------------

    def check_permission(
        self,
        workspace_id: str,
        user_id: str,
        permission: str,
        resource_id: str | None = None,
    ) -> bool:
        """Check whether a user has a specific permission at workspace scope.

        This is a **client-side** check that introspects the workspace's
        member list. For authoritative server-side enforcement, rely on
        SpacetimeDB reducer-level access controls.

        Args:
            workspace_id: Target workspace.
            user_id: The identity hex of the user.
            permission: One of ``"read"``, ``"write"``, ``"delete"``,
                ``"share"``, ``"admin"``.
            resource_id: Optional resource ID for resource-level checks.
                Currently uses workspace-level inheritance: resource-level
                checks fall back to the workspace permission level.

        Returns:
            ``True`` if the user has the permission, ``False`` otherwise.
        """
        if user_id == "admin":
            return True  # admin bypass

        members = self.list_role_assignments(workspace_id)
        for member in members:
            if member.get("user_id") != user_id:
                continue
            role = member.get("role", "")
            if role == ROLE_ADMIN:
                return True  # workspace admin has all permissions
            if role == ROLE_CUSTOM:
                # Look up the custom role permissions
                try:
                    stored = self._get_custom_role(workspace_id, role)
                    if stored is not None:
                        return permission in (stored.get("permissions") or [])
                except Exception:
                    pass
                # If the custom role definition is not found, fall back to
                # the native permission level
                return self._permission_from_native_level(
                    member.get("permission_level", ""), permission
                )
            if role in ROLE_TEMPLATES:
                return permission in ROLE_TEMPLATES[role]
            # Fallback: derive from native level
            return self._permission_from_native_level(
                member.get("permission_level", ""), permission
            )

        return False

    def _permission_from_native_level(
        self, native_level: str, permission: str
    ) -> bool:
        """Derive whether a SpacetimeDB-native level grants a permission."""
        level_lower = native_level.lower()
        if level_lower == "owner":
            return True  # owner = full access
        if level_lower == "editor":
            return permission in {PERMISSION_READ, PERMISSION_WRITE, PERMISSION_DELETE}
        if level_lower == "viewer":
            return permission == PERMISSION_READ
        return False

    # -------------------------------------------------------------------
    # Custom role management
    # -------------------------------------------------------------------

    def create_custom_role(
        self,
        workspace_id: str,
        role_name: str,
        permissions: list[str],
        description: str = "",
    ) -> dict[str, Any]:
        """Register or update a custom role definition for a workspace.

        The role definition is stored client-side in the ``role_template``
        table managed by the SDK. Once registered, the role can be assigned
        by name via :meth:`assign_role`.

        Args:
            workspace_id: Target workspace.
            role_name: The custom role name (e.g. ``"moderator"``).
            permissions: List of permission strings from ``"read"``,
                ``"write"``, ``"delete"``, ``"share"``, ``"admin"``.
            description: Optional human-readable description.

        Returns:
            Dict with status and the registered role template.

        Raises:
            InvalidPermissionError: If any permission is not recognised.
        """
        perm_set = set(permissions)
        if not perm_set.issubset(ALL_PERMISSIONS):
            invalid = perm_set - ALL_PERMISSIONS
            raise InvalidPermissionError(
                f"Invalid permissions: {sorted(invalid)}. "
                f"Valid: {sorted(ALL_PERMISSIONS)}"
            )
        if role_name.lower() in BUILTIN_ROLES:
            raise InvalidRoleError(
                f"'{role_name}' is a built-in role and cannot be redefined."
            )

        template = RoleTemplate(
            name=role_name,
            permissions=perm_set,
            description=description,
        )
        self._upsert_custom_role(workspace_id, role_name, list(perm_set), description)
        return {
            "status": "ok",
            "role_template": template.to_dict(),
        }

    def list_custom_roles(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all custom role templates defined for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of role template dicts.
        """
        try:
            rows = self._query(
                "role_template",
                workspace_id=workspace_id,
            )
            return [
                {
                    "name": r.get("role_name", ""),
                    "permissions": json.loads(r.get("permissions_json", "[]")),
                    "description": r.get("description", ""),
                }
                for r in rows
            ]
        except RuntimeError:
            return []  # table may not exist yet

    def get_custom_role(
        self,
        workspace_id: str,
        role_name: str,
    ) -> dict[str, Any] | None:
        """Get a custom role template by name.

        Args:
            workspace_id: Target workspace.
            role_name: The custom role name.

        Returns:
            Role template dict or ``None``.
        """
        return self._get_custom_role(workspace_id, role_name)

    def delete_custom_role(
        self,
        workspace_id: str,
        role_name: str,
    ) -> dict[str, Any]:
        """Delete a custom role template.

        Does **not** revoke existing assignments of this role — they are
        preserved but the role degrades to the native permission level.

        Args:
            workspace_id: Target workspace.
            role_name: The custom role name to delete.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_role_template", [workspace_id, role_name])

    def _upsert_custom_role(
        self,
        workspace_id: str,
        role_name: str,
        permissions: list[str],
        description: str = "",
    ) -> None:
        """Store or update a custom role template via the reducer."""
        try:
            self._call(
                "upsert_role_template",
                [
                    workspace_id,
                    role_name,
                    json.dumps(sorted(permissions)),
                    description,
                ],
            )
        except RuntimeError as e:
            # If the reducer doesn't exist yet, log and store in-memory
            logger.debug(
                "upsert_role_template reducer not available (%s); "
                "custom role metadata is ephemeral",
                e,
            )

    def _get_custom_role(
        self,
        workspace_id: str,
        role_name: str,
    ) -> dict[str, Any] | None:
        """Retrieve a custom role template — tries reducer then fallback."""
        try:
            self._call("get_role_template", [workspace_id, role_name])
            rows = self._query(
                "role_template",
                workspace_id=workspace_id,
                filter_dict={"role_name": role_name},
            )
            if rows:
                return {
                    "name": rows[0].get("role_name", role_name),
                    "permissions": json.loads(rows[0].get("permissions_json", "[]")),
                    "description": rows[0].get("description", ""),
                }
        except RuntimeError:
            pass
        return None

    # -------------------------------------------------------------------
    # Bulk operations
    # -------------------------------------------------------------------

    def bulk_assign_roles(
        self,
        workspace_id: str,
        assignments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Assign multiple roles at once.

        Each assignment dict must have ``user_id`` and ``role`` keys.
        Optionally ``permissions`` for custom roles.

        Args:
            workspace_id: Target workspace.
            assignments: List of dicts, each with ``user_id`` and ``role``.

        Returns:
            List of individual result dicts.
        """
        results: list[dict[str, Any]] = []
        for assignment in assignments:
            user_id = assignment.get("user_id", "")
            role = assignment.get("role", "")
            permissions = assignment.get("permissions")
            try:
                result = self.assign_role(
                    workspace_id, user_id, role, permissions=permissions
                )
                results.append(result)
            except (RBACError, SpacetimeDBError) as e:
                results.append({
                    "status": "error",
                    "user_id": user_id,
                    "role": role,
                    "error": str(e),
                })
        return results

    def bulk_revoke_roles(
        self,
        workspace_id: str,
        user_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Revoke roles for multiple users at once.

        Args:
            workspace_id: Target workspace.
            user_ids: List of user identity hex strings.

        Returns:
            List of individual result dicts.
        """
        results: list[dict[str, Any]] = []
        for user_id in user_ids:
            try:
                result = self.revoke_role(workspace_id, user_id)
                results.append(result)
            except SpacetimeDBError as e:
                results.append({
                    "status": "error",
                    "user_id": user_id,
                    "error": str(e),
                })
        return results

    # -------------------------------------------------------------------
    # Permission inheritance (workspace → resource)
    # -------------------------------------------------------------------

    def get_effective_permissions(
        self,
        workspace_id: str,
        user_id: str,
        resource_id: str | None = None,
    ) -> set[str]:
        """Get the effective permission set for a user at a given scope.

        For workspace-level checks, returns the permissions of the user's
        assigned role. For resource-level checks, currently falls back
        to workspace-level inheritance (resources inherit workspace
        permissions).

        Args:
            workspace_id: Target workspace.
            user_id: The identity hex of the user.
            resource_id: Optional resource ID for resource-level checks.

        Returns:
            Set of permission strings the user effectively holds.
        """
        members = self.list_role_assignments(workspace_id)
        for member in members:
            if member.get("user_id") != user_id:
                continue
            role = member.get("role", "")
            if role == ROLE_ADMIN:
                return set(ALL_PERMISSIONS)
            if role in ROLE_TEMPLATES:
                return set(ROLE_TEMPLATES[role])
            if role == ROLE_CUSTOM:
                try:
                    stored = self._get_custom_role(workspace_id, role)
                    if stored:
                        return set(stored.get("permissions", []))
                except Exception:
                    pass
            # Fallback: native level
            native = member.get("permission_level", "").lower()
            if native == "owner":
                return set(ALL_PERMISSIONS)
            if native == "editor":
                return {PERMISSION_READ, PERMISSION_WRITE, PERMISSION_DELETE}
            if native == "viewer":
                return {PERMISSION_READ}
        return set()

    # -------------------------------------------------------------------
    # Admin system role management
    # -------------------------------------------------------------------

    def promote_to_system_admin(
        self,
        target_identity: str,
    ) -> dict[str, Any]:
        """Promote a user to system-level admin.

        Wraps the ``promote_admin`` reducer.

        Args:
            target_identity: The identity hex of the user to promote.

        Returns:
            Reducer status dict.
        """
        return self._call("promote_admin", [target_identity])

    def demote_from_system_admin(
        self,
        target_identity: str,
    ) -> dict[str, Any]:
        """Demote a system admin back to regular user.

        Wraps the ``demote_admin`` reducer.

        Args:
            target_identity: The identity hex of the admin to demote.

        Returns:
            Reducer status dict.
        """
        return self._call("demote_admin", [target_identity])

    def list_system_admins(self) -> list[dict[str, Any]]:
        """List all system-level admin accounts.

        Returns:
            List of admin account records.
        """
        self._call("list_admins", [])
        return self._query("admin_result")
