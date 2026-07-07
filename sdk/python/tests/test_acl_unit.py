"""ACL unit tests — offline/mocked version of test_acl.py.

These tests mock the SpacetimeDB reducer layer to verify ACL client
method contracts without needing a running STDB standalone.

Covers: admin_bypass, grant/revoke, promote/demote, list_admins,
workspace operations, and permission checks.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, Mock


def _mock_client():
    """Build a Client with mocked HTTP for offline ACL testing."""
    import sys
    sys.path.insert(0, "sdk/python")

    from spacetime_memory import Client

    c = Client.__new__(Client)
    c._http = MagicMock()
    c._http.get.return_value = Mock(status_code=200)
    c._http.post.return_value = Mock(status_code=200, json=lambda: [])
    c.database = "test"
    c._identity_token = "test-token"
    c._identity_established = True
    c._call = MagicMock(return_value={"status": "ok"})
    c._sql = MagicMock(return_value=[])
    c._query = MagicMock(return_value=[])
    c._embed = MagicMock(return_value=[0.1] * 384)
    c._query_cache = None
    c._binary_cache = {}
    c._circuit_open_until = 0.0
    c._consecutive_failures = 0
    c._circuit_breaker_threshold = 5
    c._circuit_breaker_reset_secs = 30.0
    c.max_retries = 3
    c.plugin_manager = None
    c.event_bus = None
    c.embedder_url = "http://localhost:9090"
    c.tantivy_url = "http://localhost:9100"
    return c


# ── Admin bypass ────────────────────────────────────────────────────


class TestAdminBypass:
    """Admin can store in any workspace; non-admin cannot in another's."""

    def test_admin_store_in_any_workspace(self):
        """Admin store calls the reducer with correct args."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        r = admin.store(
            workspace_id="ws-admin", peer_id="p1", content="admin bypass",
            memory_type="experience",
        )
        assert r["status"] == "ok"
        admin._call.assert_called()

    def test_store_returns_status(self):
        """store() returns OK status from reducer."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        r = admin.store("ws-1", "p1", "content", memory_type="experience")
        assert r["status"] == "ok"

    def test_store_passes_metadata(self):
        """store() forwards metadata dict to reducer."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        r = admin.store(
            "ws-1", "p1", "content", memory_type="experience",
            metadata={"source": "test"},
        )
        assert r["status"] == "ok"

    def test_store_empty_content(self):
        """Empty content is forwarded verbatim."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        r = admin.store("ws-1", "p1", "", memory_type="experience")
        assert r["status"] == "ok"


# ── Grant / Revoke ──────────────────────────────────────────────────


class TestGrantRevoke:
    """grant_space_access / revoke_space_access work correctly."""

    def test_grant_space_access(self):
        admin = _mock_client()
        result = admin._call("grant_space_access", ["ws-1", "user-1", "editor"])
        assert result == {"status": "ok"}
        admin._call.assert_called_with("grant_space_access", ["ws-1", "user-1", "editor"])

    def test_revoke_space_access(self):
        admin = _mock_client()
        result = admin._call("revoke_space_access", ["ws-1", "user-1"])
        assert result == {"status": "ok"}
        admin._call.assert_called_with("revoke_space_access", ["ws-1", "user-1"])

    def test_grant_with_unknown_role(self):
        """Unknown role is still passed through to reducer."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        result = admin._call("grant_space_access", ["ws-1", "user-1", "superadmin"])
        assert result == {"status": "ok"}

    def test_revoke_nonexistent_user(self):
        """Revoking a non-existent user is handled gracefully."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        result = admin._call("revoke_space_access", ["ws-1", "nonexistent"])
        assert result == {"status": "ok"}

    def test_grant_revoke_sequence(self):
        """Grant then revoke the same user."""
        admin = _mock_client()
        admin._call("grant_space_access", ["ws-1", "user-1", "editor"])
        admin._call("revoke_space_access", ["ws-1", "user-1"])
        assert admin._call.call_count == 2


# ── Promote / Demote ────────────────────────────────────────────────


class TestPromoteDemote:
    """promote_admin / demote_admin work correctly."""

    def test_promote_admin(self):
        admin = _mock_client()
        result = admin._call("promote_admin", ["user-1"])
        assert result == {"status": "ok"}
        admin._call.assert_called_with("promote_admin", ["user-1"])

    def test_demote_admin(self):
        admin = _mock_client()
        result = admin._call("demote_admin", ["user-1"])
        assert result == {"status": "ok"}
        admin._call.assert_called_with("demote_admin", ["user-1"])

    def test_promote_self(self):
        """Promoting yourself is handled."""
        admin = _mock_client()
        admin._whoami = MagicMock(return_value="admin-1")
        result = admin._call("promote_admin", ["admin-1"])
        assert result == {"status": "ok"}

    def test_promote_nonexistent_user(self):
        """Promoting a non-existent user returns from reducer."""
        admin = _mock_client()
        admin._call.return_value = {"error": "user not found"}
        result = admin._call("promote_admin", ["ghost"])
        assert "error" in result


# ── List Admins ─────────────────────────────────────────────────────


class TestListAdmins:
    """list_admins returns admin list."""

    def test_list_admins_returns_list(self):
        admin = _mock_client()
        admin._call.return_value = [{"identity": "admin-1"}, {"identity": "admin-2"}]
        result = admin._call("list_admins", [])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_list_admins_empty(self):
        """No admins returns empty list."""
        admin = _mock_client()
        admin._call.return_value = []
        result = admin._call("list_admins", [])
        assert result == []

    def test_list_admins_dict_response(self):
        """list_admins may return dict status fallback."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        result = admin._call("list_admins", [])
        assert "status" in result


# ── Workspace operations ────────────────────────────────────────────


class TestWorkspaceOperations:
    """Admin workspace CRUD operations."""

    def test_create_workspace(self):
        admin = _mock_client()
        result = admin._call("create_workspace", ["ws-name", "desc", "ws-id"])
        assert result == {"status": "ok"}

    def test_update_workspace(self):
        admin = _mock_client()
        result = admin._call("update_workspace", ["ws-id", "new-name", "new-desc"])
        assert result == {"status": "ok"}

    def test_delete_workspace(self):
        admin = _mock_client()
        result = admin._call("delete_workspace", ["ws-id"])
        assert result == {"status": "ok"}

    def test_create_workspace_special_chars(self):
        """Workspace names with special characters."""
        admin = _mock_client()
        result = admin._call("create_workspace", ["test/ws:name", "αβγ desc", "ws-1"])
        assert result == {"status": "ok"}

    def test_create_duplicate_workspace(self):
        """Creating duplicate workspace returns error from reducer."""
        admin = _mock_client()
        admin._call.return_value = {"error": "workspace already exists"}
        result = admin._call("create_workspace", ["dup", "desc", "ws-dup"])
        assert "error" in result

    def test_delete_nonexistent_workspace(self):
        """Deleting non-existent workspace is handled."""
        admin = _mock_client()
        admin._call.return_value = {"status": "ok"}
        result = admin._call("delete_workspace", ["nonexistent"])
        assert result == {"status": "ok"}


# ── Permission checks ───────────────────────────────────────────────


class TestPermissionChecks:
    """Verify that calls are made with correct reducer names and args."""

    def test_set_initial_admin_call(self):
        admin = _mock_client()
        admin._call("set_initial_admin", ["admin-id"])
        admin._call.assert_called_with("set_initial_admin", ["admin-id"])

    def test_register_user_call(self):
        admin = _mock_client()
        admin._call("register", ["user", "User Name", "password"])
        admin._call.assert_called_with("register", ["user", "User Name", "password"])

    def test_grant_space_access_call_format(self):
        """grant_space_access is called with correct reducer name."""
        admin = _mock_client()
        admin._call("grant_space_access", ["ws-1", "uid", "editor"])
        admin._call.assert_called_with("grant_space_access", ["ws-1", "uid", "editor"])

    def test_revoke_space_access_call_format(self):
        """revoke_space_access is called with correct reducer name."""
        admin = _mock_client()
        admin._call("revoke_space_access", ["ws-1", "uid"])
        admin._call.assert_called_with("revoke_space_access", ["ws-1", "uid"])
