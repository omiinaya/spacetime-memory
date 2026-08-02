"""Tests for server/mcp/tools/workspace.py MCP tools.

Patches ``server.mcp.tools.workspace.get_client`` to verify delegation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.workspace.get_client`` to return a MagicMock."""
    with patch("server.mcp.tools.workspace.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


@pytest.mark.unit
class TestCreateWorkspace:
    """Tests for ``create_workspace``."""

    def test_with_description(self, mock_client):
        from server.mcp.tools.workspace import create_workspace

        mock_client.create_workspace.return_value = {
            "id": "ws-new",
            "name": "test-ws",
        }
        result = create_workspace(
            name="test-ws",
            description="A test workspace",
        )
        mock_client.create_workspace.assert_called_once_with(
            "test-ws", "A test workspace"
        )
        assert result["id"] == "ws-new"

    def test_without_description(self, mock_client):
        from server.mcp.tools.workspace import create_workspace

        mock_client.create_workspace.return_value = {"id": "ws-new", "name": "test"}
        result = create_workspace(name="test")
        mock_client.create_workspace.assert_called_once_with("test", "")
        assert result["name"] == "test"

    def test_empty_name(self, mock_client):
        """create_workspace passes empty name through to the client."""
        from server.mcp.tools.workspace import create_workspace

        mock_client.create_workspace.return_value = {"id": "ws-empty", "name": ""}
        result = create_workspace(name="")
        mock_client.create_workspace.assert_called_once_with("", "")
        assert result["name"] == ""

    def test_propagates_exception(self, mock_client):
        """Errors from the client propagate through create_workspace."""
        from server.mcp.tools.workspace import create_workspace

        mock_client.create_workspace.side_effect = RuntimeError("creation failed")
        with pytest.raises(RuntimeError, match="creation failed"):
            create_workspace(name="fail")


@pytest.mark.unit
class TestListWorkspaces:
    """Tests for ``list_workspaces``."""

    def test_returns_list(self, mock_client):
        from server.mcp.tools.workspace import list_workspaces

        mock_client.list_workspaces.return_value = [
            {"id": "ws-1", "name": "Workspace A"},
            {"id": "ws-2", "name": "Workspace B"},
        ]
        result = list_workspaces()
        mock_client.list_workspaces.assert_called_once_with()
        assert len(result) == 2

    def test_empty(self, mock_client):
        from server.mcp.tools.workspace import list_workspaces

        mock_client.list_workspaces.return_value = []
        result = list_workspaces()
        assert result == []

    def test_single_workspace(self, mock_client):
        """list_workspaces with a single workspace."""
        from server.mcp.tools.workspace import list_workspaces

        mock_client.list_workspaces.return_value = [
            {"id": "ws-1", "name": "Only WS"}
        ]
        result = list_workspaces()
        assert len(result) == 1
        assert result[0]["id"] == "ws-1"

    def test_propagates_exception(self, mock_client):
        """Errors from the client propagate through list_workspaces."""
        from server.mcp.tools.workspace import list_workspaces

        mock_client.list_workspaces.side_effect = ConnectionError("db unreachable")
        with pytest.raises(ConnectionError, match="db unreachable"):
            list_workspaces()


@pytest.mark.unit
class TestDeleteWorkspace:
    """Tests for ``delete_workspace``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.workspace import delete_workspace

        mock_client.delete_workspace.return_value = {
            "status": "ok",
            "workspace_id": "ws-1",
        }
        result = delete_workspace(workspace_id="ws-1")
        mock_client.delete_workspace.assert_called_once_with("ws-1")
        assert result["status"] == "ok"

    def test_error_response(self, mock_client):
        """delete_workspace handles error status from client."""
        from server.mcp.tools.workspace import delete_workspace

        mock_client.delete_workspace.return_value = {
            "status": "error",
            "workspace_id": "ws-1",
            "message": "not found",
        }
        result = delete_workspace(workspace_id="ws-1")
        assert result["status"] == "error"
        assert result["message"] == "not found"

    def test_propagates_exception(self, mock_client):
        """Errors from the client propagate through delete_workspace."""
        from server.mcp.tools.workspace import delete_workspace

        mock_client.delete_workspace.side_effect = PermissionError("forbidden")
        with pytest.raises(PermissionError, match="forbidden"):
            delete_workspace(workspace_id="ws-1")


@pytest.mark.unit
class TestUpdateWorkspace:
    """Tests for ``update_workspace``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.workspace import update_workspace

        mock_client.update_workspace.return_value = {"status": "ok"}
        result = update_workspace(
            id="ws-1",
            name="New Name",
            description="New description",
        )
        mock_client.update_workspace.assert_called_once_with(
            "ws-1", "New Name", "New description"
        )
        assert result["status"] == "ok"

    def test_empty_fields(self, mock_client):
        """update_workspace with empty name and description."""
        from server.mcp.tools.workspace import update_workspace

        mock_client.update_workspace.return_value = {"status": "ok"}
        result = update_workspace(id="ws-1", name="", description="")
        mock_client.update_workspace.assert_called_once_with("ws-1", "", "")
        assert result["status"] == "ok"

    def test_propagates_exception(self, mock_client):
        """Errors from the client propagate through update_workspace."""
        from server.mcp.tools.workspace import update_workspace

        mock_client.update_workspace.side_effect = ValueError("bad id")
        with pytest.raises(ValueError, match="bad id"):
            update_workspace(id="bad", name="n", description="d")


@pytest.mark.unit
class TestSetWorkspaceVisibility:
    """Tests for ``set_workspace_visibility``."""

    def test_public(self, mock_client):
        from server.mcp.tools.workspace import set_workspace_visibility

        mock_client.set_workspace_visibility.return_value = {"status": "ok"}
        result = set_workspace_visibility(
            workspace_id="ws-1",
            is_public=True,
        )
        mock_client.set_workspace_visibility.assert_called_once_with(
            "ws-1", True
        )
        assert result["status"] == "ok"

    def test_private(self, mock_client):
        from server.mcp.tools.workspace import set_workspace_visibility

        mock_client.set_workspace_visibility.return_value = {"status": "ok"}
        result = set_workspace_visibility(
            workspace_id="ws-1",
            is_public=False,
        )
        mock_client.set_workspace_visibility.assert_called_once_with(
            "ws-1", False
        )
        assert result["status"] == "ok"

    def test_error_response(self, mock_client):
        """set_workspace_visibility handles error response."""
        from server.mcp.tools.workspace import set_workspace_visibility

        mock_client.set_workspace_visibility.return_value = {
            "status": "error",
            "message": "not owner",
        }
        result = set_workspace_visibility(
            workspace_id="ws-1", is_public=True
        )
        assert result["status"] == "error"

    def test_propagates_exception(self, mock_client):
        """Errors from the client propagate through set_workspace_visibility."""
        from server.mcp.tools.workspace import set_workspace_visibility

        mock_client.set_workspace_visibility.side_effect = RuntimeError("visibility fail")
        with pytest.raises(RuntimeError, match="visibility fail"):
            set_workspace_visibility(workspace_id="ws-1", is_public=True)


@pytest.mark.unit
class TestGetWorkspaceContext:
    """Tests for ``get_workspace_context``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.workspace import get_workspace_context

        mock_client.get_workspace_context.return_value = {
            "workspace_id": "ws-1",
            "context": "some context",
            "queried_at": "2024-01-01T00:00:00",
        }
        result = get_workspace_context(workspace_id="ws-1")
        mock_client.get_workspace_context.assert_called_once_with("ws-1")
        assert result["workspace_id"] == "ws-1"
        assert result["context"] == "some context"

    def test_empty_context(self, mock_client):
        """get_workspace_context handles empty context string."""
        from server.mcp.tools.workspace import get_workspace_context

        mock_client.get_workspace_context.return_value = {
            "workspace_id": "ws-empty",
            "context": "",
            "queried_at": "2024-01-01T00:00:00",
        }
        result = get_workspace_context(workspace_id="ws-empty")
        assert result["context"] == ""
        assert result["workspace_id"] == "ws-empty"

    def test_propagates_exception(self, mock_client):
        """Errors from the client propagate through get_workspace_context."""
        from server.mcp.tools.workspace import get_workspace_context

        mock_client.get_workspace_context.side_effect = KeyError("missing")
        with pytest.raises(KeyError, match="missing"):
            get_workspace_context(workspace_id="ws-missing")
