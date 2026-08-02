"""Tests for server/mcp/tools/workspace.py - Workspace MCP tools."""
import pytest
from server.mcp.tools.workspace import (
    create_workspace, delete_workspace, list_workspaces,
    get_workspace_context, set_workspace_visibility,
)


class TestWorkspaceModule:
    """Test suite for workspace.py - verify all expected exports exist."""

    def test_create_workspace_exists(self):
        """create_workspace should be callable."""
        assert callable(create_workspace)

    def test_delete_workspace_exists(self):
        """delete_workspace should be callable."""
        assert callable(delete_workspace)

    def test_list_workspaces_exists(self):
        """list_workspaces should be callable."""
        assert callable(list_workspaces)

    def test_get_workspace_context_exists(self):
        """get_workspace_context should be callable."""
        assert callable(get_workspace_context)

    def test_set_workspace_visibility_exists(self):
        """set_workspace_visibility should be callable."""
        assert callable(set_workspace_visibility)
