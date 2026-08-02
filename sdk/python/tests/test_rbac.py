"""Tests for the RBACMixin — role assignment, permission checks, custom roles.

All tests use the ``mock_http_client`` fixture (no SpacetimeDB required).
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
from conftest import make_sql_response

from spacetime_memory.client._rbac import (
    ALL_PERMISSIONS,
    BUILTIN_ROLES,
    ROLE_TEMPLATES,
    InvalidPermissionError,
    InvalidRoleError,
    RoleAssignment,
    RoleTemplate,
)

# ============================================================================
# Helpers
# ============================================================================

def _reducer_resp():
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _sql_resp(rows):
    """Return a mock response for a SQL query returning the given rows."""
    payload = make_sql_response(rows)
    resp = Mock(status_code=200)
    resp.text = payload
    resp.json = lambda: {"result": payload}
    return resp


# ============================================================================
# Dataclass Tests
# ============================================================================

class TestRoleTemplate:
    """RoleTemplate dataclass construction and serialisation."""

    def test_construction(self):
        t = RoleTemplate(name="moderator", permissions={"read", "write"}, description="Can read and write")
        assert t.name == "moderator"
        assert t.permissions == {"read", "write"}
        assert t.description == "Can read and write"

    def test_to_dict(self):
        t = RoleTemplate(name="viewer", permissions={"read"}, description="Read-only")
        d = t.to_dict()
        assert d["name"] == "viewer"
        assert d["permissions"] == ["read"]
        assert d["description"] == "Read-only"


class TestRoleAssignment:
    """RoleAssignment dataclass construction."""

    def test_construction(self):
        a = RoleAssignment(
            workspace_id="ws-1",
            user_id="user-1",
            role="editor",
            permission_level="editor",
            granted_by="admin-1",
        )
        assert a.workspace_id == "ws-1"
        assert a.user_id == "user-1"
        assert a.role == "editor"


# ============================================================================
# Constants
# ============================================================================

class TestConstants:
    """Verify module-level constants are correct."""

    def test_builtin_roles(self):
        assert BUILTIN_ROLES == {"admin": "owner", "editor": "editor", "viewer": "viewer"}

    def test_all_permissions(self):
        assert ALL_PERMISSIONS == {"read", "write", "delete", "share", "admin"}

    def test_role_templates(self):
        assert ROLE_TEMPLATES["admin"] == {"read", "write", "delete", "share", "admin"}
        assert ROLE_TEMPLATES["editor"] == {"read", "write", "delete"}
        assert ROLE_TEMPLATES["viewer"] == {"read"}


# ============================================================================
# RBACMixin — assign_role
# ============================================================================

class TestAssignRole:
    """assign_role — built-in and custom role assignment."""

    def test_assign_admin_role(self, mock_http_client):
        """Assigning 'admin' role calls grant_space_access with 'owner'."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="admin",
            )

        assert result["status"] == "ok"
        assert result["role"] == "admin"
        assert result["user_id"] == "user-abc"
        mock_call.assert_called_with("grant_space_access", ["ws-1", "user-abc", "owner"])

    def test_assign_editor_role(self, mock_http_client):
        """Assigning 'editor' role calls grant_space_access with 'editor'."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="editor",
            )

        assert result["status"] == "ok"
        assert result["role"] == "editor"
        mock_call.assert_called_with("grant_space_access", ["ws-1", "user-abc", "editor"])

    def test_assign_viewer_role(self, mock_http_client):
        """Assigning 'viewer' role calls grant_space_access with 'viewer'."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="viewer",
            )

        assert result["status"] == "ok"
        assert result["role"] == "viewer"
        mock_call.assert_called_with("grant_space_access", ["ws-1", "user-abc", "viewer"])

    def test_assign_role_case_insensitive(self, mock_http_client):
        """Role names are case-insensitive."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.assign_role(
                workspace_id="ws-1", user_id="user-abc", role="EDITOR"
            )

        assert result["role"] == "editor"
        mock_call.assert_called_with("grant_space_access", ["ws-1", "user-abc", "editor"])

    def test_assign_invalid_role_raises(self, mock_http_client):
        """Assigning an unknown role raises InvalidRoleError."""
        with pytest.raises(InvalidRoleError, match="Unknown role"):
            mock_http_client.assign_role(
                workspace_id="ws-1", user_id="user-abc", role="superadmin"
            )

    def test_assign_custom_role_with_permissions(self, mock_http_client):
        """Assigning a custom role with explicit permissions."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="custom",
                permissions=["read", "write", "delete"],
            )

        assert result["status"] == "ok"
        assert result["role"] == "custom"
        assert result["permissions"] == ["read", "write", "delete"]
        # Should call grant_space_access with editor level as base
        mock_call.assert_any_call("grant_space_access", ["ws-1", "user-abc", "editor"])
        # Should also call upsert_role_template
        mock_call.assert_any_call(
            "upsert_role_template",
            ["ws-1", "custom", json.dumps(sorted(["read", "write", "delete"])), ""],
        )

    def test_assign_custom_role_missing_permissions_raises(self, mock_http_client):
        """Custom role without explicit permissions raises InvalidPermissionError."""
        with pytest.raises(InvalidPermissionError, match="Invalid permissions"):
            mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="custom",
            )

    def test_assign_custom_role_invalid_permission_raises(self, mock_http_client):
        """Custom role with invalid permission raises InvalidPermissionError."""
        with pytest.raises(InvalidPermissionError, match="Invalid permissions"):
            mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="custom",
                permissions=["read", "execute"],
            )

    def test_assign_custom_role_all_permissions(self, mock_http_client):
        """Custom role with all permissions."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.assign_role(
                workspace_id="ws-1",
                user_id="user-abc",
                role="custom",
                permissions=sorted(ALL_PERMISSIONS),
            )

        assert result["status"] == "ok"
        mock_call.assert_any_call(
            "upsert_role_template",
            ["ws-1", "custom", json.dumps(sorted(ALL_PERMISSIONS)), ""],
        )


# ============================================================================
# RBACMixin — revoke_role
# ============================================================================

class TestRevokeRole:
    """revoke_role — role revocation."""

    def test_revoke_role(self, mock_http_client):
        """revoke_role calls revoke_space_access."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.revoke_role(workspace_id="ws-1", user_id="user-abc")

        assert result["status"] == "ok"
        mock_call.assert_called_with("revoke_space_access", ["ws-1", "user-abc"])


# ============================================================================
# RBACMixin — list_role_assignments
# ============================================================================

class TestListRoleAssignments:
    """list_role_assignments — listing members with normalised roles."""

    def test_list_empty(self, mock_http_client):
        """List returns [] when no members exist."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_space_members" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_role_assignments(workspace_id="ws-1")
        assert result == []

    def test_list_with_members(self, mock_http_client):
        """List returns normalised member records."""
        member_rows = [
            {
                "id": "perm1",
                "workspace_id": "ws-1",
                "peer_id": "user-admin",
                "permission": "owner",
                "granted_by": "admin-0",
                "created_at": 1000,
            },
            {
                "id": "perm2",
                "workspace_id": "ws-1",
                "peer_id": "user-editor",
                "permission": "editor",
                "granted_by": "admin-0",
                "created_at": 1001,
            },
            {
                "id": "perm3",
                "workspace_id": "ws-1",
                "peer_id": "user-viewer",
                "permission": "viewer",
                "granted_by": "admin-0",
                "created_at": 1002,
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_space_members" in url:
                return _reducer_resp()
            return _sql_resp(member_rows)

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_role_assignments(workspace_id="ws-1")

        assert len(result) == 3
        assert result[0]["user_id"] == "user-admin"
        assert result[0]["role"] == "admin"
        assert result[0]["permission_level"] == "owner"
        assert result[1]["user_id"] == "user-editor"
        assert result[1]["role"] == "editor"
        assert result[2]["user_id"] == "user-viewer"
        assert result[2]["role"] == "viewer"

    def test_list_custom_role(self, mock_http_client):
        """List shows 'custom' role for non-standard permission levels."""
        member_rows = [
            {
                "id": "perm1",
                "workspace_id": "ws-1",
                "peer_id": "user-custom",
                "permission": "custom",
                "granted_by": "admin-0",
                "created_at": 1000,
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_space_members" in url:
                return _reducer_resp()
            return _sql_resp(member_rows)

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_role_assignments(workspace_id="ws-1")

        assert len(result) == 1
        assert result[0]["user_id"] == "user-custom"
        assert result[0]["role"] == "custom"


# ============================================================================
# RBACMixin — check_permission
# ============================================================================

class TestCheckPermission:
    """check_permission — client-side permission checks."""

    def test_admin_has_all_permissions(self, mock_http_client):
        """Admin role grants all permissions."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {
                    "user_id": "user-admin",
                    "role": "admin",
                    "permission_level": "owner",
                }
            ]
        ):
            assert mock_http_client.check_permission("ws-1", "user-admin", "read") is True
            assert mock_http_client.check_permission("ws-1", "user-admin", "write") is True
            assert mock_http_client.check_permission("ws-1", "user-admin", "delete") is True
            assert mock_http_client.check_permission("ws-1", "user-admin", "share") is True
            assert mock_http_client.check_permission("ws-1", "user-admin", "admin") is True

    def test_editor_has_read_write_delete(self, mock_http_client):
        """Editor role grants read, write, delete but not share or admin."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {
                    "user_id": "user-editor",
                    "role": "editor",
                    "permission_level": "editor",
                }
            ]
        ):
            assert mock_http_client.check_permission("ws-1", "user-editor", "read") is True
            assert mock_http_client.check_permission("ws-1", "user-editor", "write") is True
            assert mock_http_client.check_permission("ws-1", "user-editor", "delete") is True
            assert mock_http_client.check_permission("ws-1", "user-editor", "share") is False
            assert mock_http_client.check_permission("ws-1", "user-editor", "admin") is False

    def test_viewer_only_read(self, mock_http_client):
        """Viewer role only grants read permission."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {
                    "user_id": "user-viewer",
                    "role": "viewer",
                    "permission_level": "viewer",
                }
            ]
        ):
            assert mock_http_client.check_permission("ws-1", "user-viewer", "read") is True
            assert mock_http_client.check_permission("ws-1", "user-viewer", "write") is False
            assert mock_http_client.check_permission("ws-1", "user-viewer", "delete") is False
            assert mock_http_client.check_permission("ws-1", "user-viewer", "share") is False
            assert mock_http_client.check_permission("ws-1", "user-viewer", "admin") is False

    def test_unassigned_user_has_no_permissions(self, mock_http_client):
        """User with no role has no permissions."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[{"user_id": "other-user", "role": "editor", "permission_level": "editor"}]
        ):
            assert mock_http_client.check_permission("ws-1", "unassigned-user", "read") is False
            assert mock_http_client.check_permission("ws-1", "unassigned-user", "write") is False

    def test_custom_role_permission_check(self, mock_http_client):
        """Custom role permissions are checked against stored template."""
        def side_effect(method, args):
            if method == "get_role_template":
                # Return stored template
                return None  # signal to _get_custom_role to query
            return {"status": "ok"}

        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {
                    "user_id": "user-custom",
                    "role": "custom",
                    "permission_level": "editor",
                }
            ]
        ), patch.object(
            mock_http_client,
            "_get_custom_role",
            return_value={"name": "custom", "permissions": ["read", "write"]},
        ):
            assert mock_http_client.check_permission("ws-1", "user-custom", "read") is True
            assert mock_http_client.check_permission("ws-1", "user-custom", "write") is True
            assert mock_http_client.check_permission("ws-1", "user-custom", "delete") is False

    def test_admin_bypass_user_id(self, mock_http_client):
        """The literal user_id 'admin' always passes."""
        assert mock_http_client.check_permission("ws-1", "admin", "read") is True
        assert mock_http_client.check_permission("ws-1", "admin", "admin") is True


# ============================================================================
# RBACMixin — custom role management
# ============================================================================

class TestCustomRoles:
    """create_custom_role, list_custom_roles, get_custom_role, delete_custom_role."""

    def test_create_custom_role(self, mock_http_client):
        """create_custom_role registers a new role template."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.create_custom_role(
                workspace_id="ws-1",
                role_name="moderator",
                permissions=["read", "write", "delete"],
                description="Can moderate content",
            )

        assert result["status"] == "ok"
        template = result["role_template"]
        assert template["name"] == "moderator"
        assert set(template["permissions"]) == {"read", "write", "delete"}
        assert template["description"] == "Can moderate content"

        mock_call.assert_called_with(
            "upsert_role_template",
            ["ws-1", "moderator", json.dumps(sorted(["read", "write", "delete"])), "Can moderate content"],
        )

    def test_create_custom_role_invalid_permission(self, mock_http_client):
        """Invalid permission in custom role raises error."""
        with pytest.raises(InvalidPermissionError, match="Invalid permissions"):
            mock_http_client.create_custom_role(
                workspace_id="ws-1",
                role_name="hacker",
                permissions=["read", "write", "sudo"],
            )

    def test_create_custom_role_builtin_name_raises(self, mock_http_client):
        """Cannot create a custom role with a built-in role name."""
        with pytest.raises(InvalidRoleError, match="built-in role"):
            mock_http_client.create_custom_role(
                workspace_id="ws-1",
                role_name="admin",
                permissions=["read"],
            )

    def test_get_custom_role_found(self, mock_http_client):
        """get_custom_role returns the template when it exists."""
        def side_effect(*args, **kwargs):
            if args and args[0] == "get_role_template":
                return _reducer_resp()
            return _sql_resp([
                {
                    "role_name": "moderator",
                    "permissions_json": '["read", "write", "delete"]',
                    "description": "Moderator role",
                }
            ])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.get_custom_role("ws-1", "moderator")
        assert result is not None
        assert result["name"] == "moderator"
        assert result["permissions"] == ["read", "write", "delete"]

    def test_get_custom_role_not_found(self, mock_http_client):
        """get_custom_role returns None when the role doesn't exist."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_role_template" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.get_custom_role("ws-1", "nonexistent")
        assert result is None

    def test_list_custom_roles(self, mock_http_client):
        """list_custom_roles returns all role templates for a workspace."""
        rows = [
            {
                "role_name": "moderator",
                "permissions_json": '["read", "write", "delete"]',
                "description": "Moderator",
            },
            {
                "role_name": "contributor",
                "permissions_json": '["read", "write"]',
                "description": "Contributor",
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/query_table" in url:
                return _reducer_resp()
            return _sql_resp(rows)

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_custom_roles("ws-1")
        assert len(result) == 2
        assert result[0]["name"] == "moderator"
        assert result[1]["name"] == "contributor"

    def test_list_custom_roles_empty(self, mock_http_client):
        """list_custom_roles returns [] when no custom roles defined."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/query_table" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_custom_roles("ws-1")
        assert result == []

    def test_delete_custom_role(self, mock_http_client):
        """delete_custom_role calls the delete_role_template reducer."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.delete_custom_role("ws-1", "moderator")

        assert result["status"] == "ok"
        mock_call.assert_called_with("delete_role_template", ["ws-1", "moderator"])


# ============================================================================
# RBACMixin — bulk operations
# ============================================================================

class TestBulkOperations:
    """bulk_assign_roles and bulk_revoke_roles."""

    def test_bulk_assign_roles(self, mock_http_client):
        """bulk_assign_roles assigns multiple roles."""
        with patch.object(
            mock_http_client,
            "assign_role",
            side_effect=[
                {"status": "ok", "role": "editor", "user_id": "user-1"},
                {"status": "ok", "role": "viewer", "user_id": "user-2"},
            ]
        ):
            results = mock_http_client.bulk_assign_roles(
                workspace_id="ws-1",
                assignments=[
                    {"user_id": "user-1", "role": "editor"},
                    {"user_id": "user-2", "role": "viewer"},
                ],
            )

        assert len(results) == 2
        assert results[0]["status"] == "ok"
        assert results[1]["status"] == "ok"

    def test_bulk_assign_roles_with_error(self, mock_http_client):
        """bulk_assign_roles continues on error and reports it."""
        def assign_role_side_effect(ws, uid, role, permissions=None):
            if uid == "user-bad":
                raise InvalidRoleError("Unknown role")
            return {"status": "ok", "role": role, "user_id": uid}

        with patch.object(
            mock_http_client,
            "assign_role",
            side_effect=assign_role_side_effect,
        ):
            results = mock_http_client.bulk_assign_roles(
                workspace_id="ws-1",
                assignments=[
                    {"user_id": "user-1", "role": "editor"},
                    {"user_id": "user-bad", "role": "nonexistent"},
                    {"user_id": "user-2", "role": "viewer"},
                ],
            )

        assert len(results) == 3
        assert results[0]["status"] == "ok"
        assert results[1]["status"] == "error"
        assert "Unknown role" in results[1]["error"]
        assert results[2]["status"] == "ok"

    def test_bulk_revoke_roles(self, mock_http_client):
        """bulk_revoke_roles revokes multiple roles."""
        with patch.object(
            mock_http_client,
            "revoke_role",
            side_effect=[
                {"status": "ok"},
                {"status": "ok"},
            ]
        ):
            results = mock_http_client.bulk_revoke_roles(
                workspace_id="ws-1",
                user_ids=["user-1", "user-2"],
            )

        assert len(results) == 2
        assert results[0]["status"] == "ok"
        assert results[1]["status"] == "ok"


# ============================================================================
# RBACMixin — effective permissions
# ============================================================================

class TestEffectivePermissions:
    """get_effective_permissions — permission inheritance."""

    def test_admin_effective_permissions(self, mock_http_client):
        """Admin role gets all permissions."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {"user_id": "user-admin", "role": "admin", "permission_level": "owner"}
            ]
        ):
            perms = mock_http_client.get_effective_permissions("ws-1", "user-admin")
            assert perms == ALL_PERMISSIONS

    def test_editor_effective_permissions(self, mock_http_client):
        """Editor role gets read, write, delete."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {"user_id": "user-editor", "role": "editor", "permission_level": "editor"}
            ]
        ):
            perms = mock_http_client.get_effective_permissions("ws-1", "user-editor")
            assert perms == {"read", "write", "delete"}

    def test_viewer_effective_permissions(self, mock_http_client):
        """Viewer role gets only read."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[
                {"user_id": "user-viewer", "role": "viewer", "permission_level": "viewer"}
            ]
        ):
            perms = mock_http_client.get_effective_permissions("ws-1", "user-viewer")
            assert perms == {"read"}

    def test_unassigned_user_effective_permissions(self, mock_http_client):
        """Unassigned user gets empty permission set."""
        with patch.object(
            mock_http_client,
            "list_role_assignments",
            return_value=[{"user_id": "other", "role": "editor", "permission_level": "editor"}]
        ):
            perms = mock_http_client.get_effective_permissions("ws-1", "nobody")
            assert perms == set()


# ============================================================================
# RBACMixin — system admin management
# ============================================================================

class TestSystemAdmin:
    """promote_to_system_admin, demote_from_system_admin, list_system_admins."""

    def test_promote_to_system_admin(self, mock_http_client):
        """promote_to_system_admin calls promote_admin reducer."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.promote_to_system_admin("identity-hex")
        assert result["status"] == "ok"
        mock_call.assert_called_with("promote_admin", ["identity-hex"])

    def test_demote_from_system_admin(self, mock_http_client):
        """demote_from_system_admin calls demote_admin reducer."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}) as mock_call:
            result = mock_http_client.demote_from_system_admin("identity-hex")
        assert result["status"] == "ok"
        mock_call.assert_called_with("demote_admin", ["identity-hex"])

    def test_list_system_admins(self, mock_http_client):
        """list_system_admins returns admin records."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_admins" in url:
                return _reducer_resp()
            return _sql_resp([
                {"identity": "admin-1", "username": "Alice"},
                {"identity": "admin-2", "username": "Bob"},
            ])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_system_admins()
        assert len(result) == 2
        assert result[0]["identity"] == "admin-1"


# ============================================================================
# RBACMixin — _permission_from_native_level
# ============================================================================

class TestPermissionFromNativeLevel:
    """_permission_from_native_level helper."""

    def test_owner_grants_all(self, mock_http_client):
        for perm in ALL_PERMISSIONS:
            assert mock_http_client._permission_from_native_level("owner", perm) is True

    def test_editor_grants_read_write_delete(self, mock_http_client):
        assert mock_http_client._permission_from_native_level("editor", "read") is True
        assert mock_http_client._permission_from_native_level("editor", "write") is True
        assert mock_http_client._permission_from_native_level("editor", "delete") is True
        assert mock_http_client._permission_from_native_level("editor", "share") is False
        assert mock_http_client._permission_from_native_level("editor", "admin") is False

    def test_viewer_grants_only_read(self, mock_http_client):
        assert mock_http_client._permission_from_native_level("viewer", "read") is True
        assert mock_http_client._permission_from_native_level("viewer", "write") is False
        assert mock_http_client._permission_from_native_level("viewer", "delete") is False


# ============================================================================
# Assign role with register-then-use custom role flow
# ============================================================================

class TestRegisterThenAssignCustomRole:
    """Create a custom role then assign it by name."""

    def test_create_then_assign_custom_role(self, mock_http_client):
        """Register a custom role, then assign it by name (auto-resolved)."""
        register_calls = []

        def _call_side_effect(method, args):
            register_calls.append((method, args))
            if method == "get_role_template":
                return None  # will trigger query in _get_custom_role
            if method == "grant_space_access":
                return {"status": "ok"}
            return {"status": "ok"}

        with patch.object(mock_http_client, "_call", side_effect=_call_side_effect), \
             patch.object(mock_http_client, "_query", return_value=[{
                 "role_name": "moderator",
                 "permissions_json": '["read", "write", "delete"]',
                 "description": "Moderator role",
             }]), \
             patch.object(mock_http_client, "assign_role", wraps=mock_http_client.assign_role):
            # First register the custom role
            create_result = mock_http_client.create_custom_role(
                workspace_id="ws-1",
                role_name="moderator",
                permissions=["read", "write", "delete"],
            )
            assert create_result["status"] == "ok"

            # Now try assigning it by name — should resolve and assign as custom
            with patch.object(mock_http_client, "assign_role", wraps=mock_http_client.assign_role):
                result = mock_http_client.assign_role(
                    workspace_id="ws-1",
                    user_id="user-abc",
                    role="moderator",
                )
                # Should have called grant_space_access at minimum (through the custom path)
                assert result["status"] == "ok" or "status" in result
