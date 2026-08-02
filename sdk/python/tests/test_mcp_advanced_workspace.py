"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestCreateWorkspace:
    """Tests for the create_workspace MCP tool."""

    def test_creates_workspace(self, mock_mcp_client):
        from server.mcp.main import create_workspace

        mock_mcp_client.create_workspace.return_value = {
            "id": "ws_new",
            "name": "Test",
            "description": "A test workspace",
        }
        result = create_workspace(name="Test", description="A test workspace")
        assert result["name"] == "Test"
        mock_mcp_client.create_workspace.assert_called_once_with(
            "Test", "A test workspace"
        )

    def test_creates_with_default_description(self, mock_mcp_client):
        from server.mcp.main import create_workspace

        mock_mcp_client.create_workspace.return_value = {"id": "ws2", "name": "Minimal"}
        result = create_workspace(name="Minimal")
        assert result["name"] == "Minimal"
        mock_mcp_client.create_workspace.assert_called_once_with("Minimal", "")



# ── TestListWorkspaces ────────────────────────────────────────────────────────

class TestListWorkspaces:
    """Tests for the list_workspaces MCP tool."""

    def test_lists_all(self, mock_mcp_client):
        from server.mcp.main import list_workspaces

        mock_mcp_client.list_workspaces.return_value = [
            {"id": "ws1", "name": "Alpha"},
            {"id": "ws2", "name": "Beta"},
        ]
        result = list_workspaces()
        assert len(result) == 2
        assert result[0]["name"] == "Alpha"
        mock_mcp_client.list_workspaces.assert_called_once_with()

    def test_empty_list(self, mock_mcp_client):
        from server.mcp.main import list_workspaces

        mock_mcp_client.list_workspaces.return_value = []
        result = list_workspaces()
        assert result == []



# ── TestUpdateWorkspace ────────────────────────────────────────────────────────

class TestUpdateWorkspace:
    """Tests for the update_workspace MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_workspace

        mock_mcp_client.update_workspace.return_value = {"status": "ok"}
        result = update_workspace(id="ws1", name="New Name", description="New desc")
        assert result["status"] == "ok"
        mock_mcp_client.update_workspace.assert_called_once_with(
            "ws1", "New Name", "New desc"
        )



# ── TestSetWorkspaceVisibility ────────────────────────────────────────────────────────

class TestSetWorkspaceVisibility:
    """Tests for the set_workspace_visibility MCP tool."""

    def test_set_public(self, mock_mcp_client):
        from server.mcp.main import set_workspace_visibility

        mock_mcp_client.set_workspace_visibility.return_value = {"status": "ok"}
        result = set_workspace_visibility(workspace_id="ws1", is_public=True)
        assert result["status"] == "ok"
        mock_mcp_client.set_workspace_visibility.assert_called_once_with("ws1", True)

    def test_set_private(self, mock_mcp_client):
        from server.mcp.main import set_workspace_visibility

        mock_mcp_client.set_workspace_visibility.return_value = {"status": "ok"}
        set_workspace_visibility(workspace_id="ws1", is_public=False)
        mock_mcp_client.set_workspace_visibility.assert_called_once_with("ws1", False)



# ── TestGetWorkspaceContext ────────────────────────────────────────────────────────

class TestGetWorkspaceContext:
    """Tests for the get_workspace_context MCP tool."""

    def test_gets_context(self, mock_mcp_client):
        from server.mcp.main import get_workspace_context

        mock_mcp_client.get_workspace_context.return_value = {
            "workspace_id": "ws1",
            "context": "Project context",
        }
        result = get_workspace_context(workspace_id="ws1")
        assert result["context"] == "Project context"
        mock_mcp_client.get_workspace_context.assert_called_once_with("ws1")


# ── Memory tools ──────────────────────────────────────────────────────────



# ── TestCreateWorkspaceDefaults ────────────────────────────────────────────────────────

class TestCreateWorkspaceDefaults:
    """Tests for the create_workspace MCP tool."""

    def test_creates_workspace(self, mock_mcp_client):
        from server.mcp.main import create_workspace

        mock_mcp_client.create_workspace.return_value = {
            "id": "ws-abc", "name": "Test", "status": "created"
        }
        result = create_workspace(name="Test", description="A test workspace")
        assert result["name"] == "Test"
        mock_mcp_client.create_workspace.assert_called_once_with("Test", "A test workspace")

    def test_creates_without_description(self, mock_mcp_client):
        from server.mcp.main import create_workspace

        mock_mcp_client.create_workspace.return_value = {"id": "ws-xyz", "name": "Minimal", "status": "created"}
        result = create_workspace(name="Minimal")
        assert result["name"] == "Minimal"
        mock_mcp_client.create_workspace.assert_called_once_with("Minimal", "")


# ── list_workspaces (uses get_client directly) ─────────────────────────────



# ── TestListWorkspacesEmpty ────────────────────────────────────────────────────────

class TestListWorkspacesEmpty:
    """Tests for the list_workspaces MCP tool."""

    def test_lists_all(self, mock_mcp_client):
        from server.mcp.main import list_workspaces

        mock_mcp_client.list_workspaces.return_value = [
            {"id": "ws1", "name": "Alpha"},
            {"id": "ws2", "name": "Beta"},
        ]
        result = list_workspaces()
        assert len(result) == 2
        assert result[0]["name"] == "Alpha"
        mock_mcp_client.list_workspaces.assert_called_once_with()

    def test_empty_list(self, mock_mcp_client):
        from server.mcp.main import list_workspaces

        mock_mcp_client.list_workspaces.return_value = []
        result = list_workspaces()
        assert result == []


# ── store_batch (JSON parsing + get_client) ────────────────────────────────



# ── TestDeleteWorkspaceDirect ────────────────────────────────────────────────────────

class TestDeleteWorkspaceDirect:
    """Tests for delete_workspace via mock_mcp_client (skipping mock_compounder)."""

    def test_deletes_workspace(self, mock_mcp_client):
        from server.mcp.main import delete_workspace

        mock_mcp_client.delete_workspace.return_value = {
            "status": "ok", "workspace_id": "ws-1"
        }
        result = delete_workspace(workspace_id="ws-1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_workspace.assert_called_once_with("ws-1")
