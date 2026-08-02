"""Unit tests for WorkspaceMixin — workspace CRUD, auth, users, API keys.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestWorkspaceMixin:
    """WorkspaceMixin methods (workspace CRUD, members, auth, API keys, users)."""

    # --- Workspace CRUD ---

    def test_create_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.create_workspace("My Workspace", "A description")
        assert result["status"] == "ok"
        assert "id" in result
        assert len(result["id"]) == 32

    def test_create_workspace_with_id(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.create_workspace(
                "My Workspace", "A description", id="custom-id"
            )
        assert result["status"] == "ok"
        assert result["id"] == "custom-id"

    def test_list_workspaces(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_workspaces()
        assert result == []

    def test_list_workspaces_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "ws-1", "name": "Workspace 1"}
        ]):
            result = mock_http_client.list_workspaces()
        assert len(result) == 1
        assert result[0]["id"] == "ws-1"

    def test_delete_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_workspace("ws-1")
        assert result == {"status": "ok"}

    def test_update_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_workspace("ws-1", "New Name", "New desc")
        assert result == {"status": "ok"}

    def test_set_workspace_visibility(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.set_workspace_visibility("ws-1", True)
        assert result == {"status": "ok"}

    # --- Workspace context ---

    def test_get_workspace_context(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_workspace_context("ws-1")
        assert result == {"workspace_id": "ws-1", "context": "", "queried_at": 0}

    def test_get_workspace_context_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"workspace_id": "ws-1", "context": "some context", "queried_at": 12345}
             ]):
            result = mock_http_client.get_workspace_context("ws-1")
        assert result["context"] == "some context"

    # --- Space members ---

    def test_list_space_members(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_space_members("ws-1")
        assert result == []

    def test_list_space_members_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "m1", "peer_id": "peer-1", "permission": "editor", "created_at": 100}
             ]):
            result = mock_http_client.list_space_members("ws-1")
        assert len(result) == 1
        assert result[0]["peer_id"] == "peer-1"

    def test_grant_space_access(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.grant_space_access("ws-1", "peer-1", "editor")
        assert result == {"status": "ok"}

    def test_revoke_space_access(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.revoke_space_access("ws-1", "peer-1")
        assert result == {"status": "ok"}

    # --- Auth / Account ---

    def test_register(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.register("alice", "Alice", "securepass")
        assert result == {"status": "ok"}

    def test_login(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.login("alice", "securepass")
        assert result == {"status": "ok"}

    def test_logout(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.logout()
        assert result == {"status": "ok"}

    def test_update_account(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_account(
                display_name="Alice Updated",
                current_password="oldpass",
                new_password="newpass",
            )
        assert result == {"status": "ok"}

    def test_deactivate_account(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.deactivate_account("securepass")
        assert result == {"status": "ok"}

    def test_promote_admin(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.promote_admin("identity-hex")
        assert result == {"status": "ok"}

    def test_demote_admin(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.demote_admin("identity-hex")
        assert result == {"status": "ok"}

    def test_list_admins(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_admins()
        assert result == []

    def test_list_admins_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[{"identity": "id-1", "username": "admin"}]):
            result = mock_http_client.list_admins()
        assert len(result) == 1

    # --- API Keys ---

    def test_create_api_key(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[{"api_key_id": "key-1"}]):
            result = mock_http_client.create_api_key(
                "ws-1", "My Key", '["read", "write"]', '["ws-1"]'
            )
        assert result["status"] == "ok"
        assert "api_key" in result
        assert result["api_key"].startswith("sk-")

    def test_create_api_key_defaults(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[{"api_key_id": "key-1"}]):
            result = mock_http_client.create_api_key("ws-1", "Admin Key")
        assert result["status"] == "ok"
        assert result["scope"] == "*"

    def test_verify_api_key_valid(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {
                     "api_key_id": "key-1",
                     "workspace_id": "ws-1",
                     "name": "My Key",
                     "permissions": '["read"]',
                     "scope": "*",
                     "is_active": True,
                     "created_at": 0,
                     "last_used_at": 0,
                     "verified_at": 100,
                 }
             ]):
            result = mock_http_client.verify_api_key("sk-test")
        assert result["valid"] is True
        assert result["api_key_id"] == "key-1"

    def test_verify_api_key_not_found(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.verify_api_key("sk-invalid")
        assert result["valid"] is False

    def test_verify_api_key_call_error(self, mock_http_client):
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("call failed")):
            result = mock_http_client.verify_api_key("sk-test")
        assert result["valid"] is False
        assert "error" in result

    def test_update_api_key(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_api_key(
                "key-1", name="Renamed", permissions='["read"]', scope="*", is_active=True
            )
        assert result == {"status": "ok"}

    def test_deactivate_api_key(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.deactivate_api_key("key-1")
        assert result == {"status": "ok"}

    def test_list_api_keys(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_api_keys("ws-1")
        assert result == []

    def test_list_api_keys_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"api_key_id": "key-1", "name": "My Key"}
             ]):
            result = mock_http_client.list_api_keys("ws-1")
        assert len(result) == 1

    # --- Users ---

    def test_add_user(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.add_user(
                "user-1", "user@example.com", "Alice", "Smith", '{"role": "admin"}'
            )
        assert result == {"status": "ok"}

    def test_get_user_found(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[{"id": "user-1", "email": "user@example.com"}]):
            result = mock_http_client.get_user("user-1")
        assert result["id"] == "user-1"

    def test_get_user_not_found(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            with pytest.raises(RuntimeError, match="not found"):
                mock_http_client.get_user("nonexistent")

    def test_update_user(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_user(
                "user-1", email="new@example.com", first_name="Bob"
            )
        assert result == {"status": "ok"}

    def test_delete_user(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_user("user-1")
        assert result == {"status": "ok"}

    def test_list_users(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_users()
        assert result == []

    def test_list_users_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "list_users:someuser", "email": "user@example.com"}
             ]):
            result = mock_http_client.list_users()
        assert len(result) == 1

    def test_get_user_sessions(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_user_sessions("user-1")
        assert result == []

    def test_get_user_sessions_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"session_id": "sess-1", "workspace_id": "ws-1"}
             ]):
            result = mock_http_client.get_user_sessions("user-1")
        assert len(result) == 1

    # --- Peers ---

    def test_list_peers(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_peers()
        assert result == []

    def test_list_peers_filtered(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"id": "peer-1", "workspace_id": "ws-1"}]):
            result = mock_http_client.list_peers("ws-1")
        assert len(result) == 1

    # --- Context packs ---

    def test_list_context_packs(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_context_packs("ws-1")
        assert result == []

    def test_list_context_entries(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_context_entries("pack-1")
        assert result == []

    def test_list_context_deltas(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_context_deltas("prev-pack-1")
        assert result == []

    # --- Overview ---

    def test_generate_overview(self, mock_http_client):
        with patch.object(mock_http_client, "_sql", side_effect=[
            [{"cnt": 10}],  # memories
            [{"cnt": 5}],   # nodes
            [{"cnt": 15}],  # edges
            [{"cnt": 3}],   # notes
            [{"cnt": 2}],   # sessions
        ]):
            result = mock_http_client.generate_overview("ws-1")
        assert result["memories"] == 10
        assert result["nodes"] == 5
        assert result["edges"] == 15
        assert result["notes"] == 3
        assert result["sessions"] == 2

    # --- Export ---

    def test_export_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_sql", return_value=[
            {"title": "Note 1", "content": "Content 1"},
            {"title": "Note 2", "content": "Content 2"},
        ]):
            result = mock_http_client.export_workspace("ws-1")
        assert "# Note 1" in result
        assert "# Note 2" in result

    def test_export_workspace_json(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.export_workspace_json("ws-1")
        assert result["status"] == "ok"
        assert result["workspace_id"] == "ws-1"
        assert "json" in result

    def test_export_workspace_json_with_output(self, mock_http_client, tmp_path):
        with patch.object(mock_http_client, "_query", return_value=[]), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            output = tmp_path / "export.json"
            result = mock_http_client.export_workspace_json("ws-1", output_path=str(output))
        assert result["status"] == "ok"
        assert output.exists()
