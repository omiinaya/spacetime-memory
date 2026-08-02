"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestCreateDirectory:
    """Tests for the create_directory MCP tool."""

    def test_creates(self, mock_mcp_client):
        from server.mcp.main import create_directory

        result = create_directory(
            workspace_id="ws1",
            name="Projects",
            path="/projects",
            parent_id="root",
            description="Project dirs",
        )
        assert "Projects" in result
        mock_mcp_client.create_directory.assert_called_once_with(
            "ws1", "Projects", "/projects", "root", "Project dirs"
        )



# ── TestTraverseDirectory ────────────────────────────────────────────────────────

class TestTraverseDirectory:
    """Tests for the traverse_directory MCP tool."""

    def test_traverses(self, mock_mcp_client):
        from server.mcp.main import traverse_directory

        mock_mcp_client.traverse_directory.return_value = [
            {"id": "d1", "name": "subdir", "level": 1},
        ]
        result = traverse_directory(workspace_id="ws1", root_directory_id="d1")
        assert "d1" in result
        mock_mcp_client.traverse_directory.assert_called_once_with("ws1", "d1")



# ── TestListDirectoryMCP ────────────────────────────────────────────────────────

class TestListDirectoryMCP:
    """Tests for the list_directory MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_directory

        mock_mcp_client.list_directory.return_value = [
            {"id": "child1", "name": "Child Dir"},
        ]
        result = list_directory(directory_id="d1")
        assert "child1" in result
        mock_mcp_client.list_directory.assert_called_once_with("d1")



# ── TestSearchDirectoryContents ────────────────────────────────────────────────────────

class TestSearchDirectoryContents:
    """Tests for the search_directory_contents MCP tool."""

    def test_searches(self, mock_mcp_client):
        from server.mcp.main import search_directory_contents

        mock_mcp_client.search_directory_contents.return_value = {
            "directory_id": "d1",
            "subdirectory_ids_json": "[]",
            "memory_ids_json": '["m1"]',
        }
        result = search_directory_contents(
            workspace_id="ws1", directory_path="/projects"
        )
        assert "d1" in result
        mock_mcp_client.search_directory_contents.assert_called_once_with(
            "ws1", "/projects"
        )


# ── Space access tools ────────────────────────────────────────────────────



# ── TestGrantSpaceAccess ────────────────────────────────────────────────────────

class TestGrantSpaceAccess:
    """Tests for the grant_space_access MCP tool."""

    def test_grants(self, mock_mcp_client):
        from server.mcp.main import grant_space_access

        result = grant_space_access(workspace_id="ws1", peer_id="p1", permission="editor")
        assert "editor" in result
        mock_mcp_client.grant_space_access.assert_called_once_with("ws1", "p1", "editor")



# ── TestRevokeSpaceAccess ────────────────────────────────────────────────────────

class TestRevokeSpaceAccess:
    """Tests for the revoke_space_access MCP tool."""

    def test_revokes(self, mock_mcp_client):
        from server.mcp.main import revoke_space_access

        result = revoke_space_access(workspace_id="ws1", peer_id="p1")
        assert "Revoked" in result
        mock_mcp_client.revoke_space_access.assert_called_once_with("ws1", "p1")



# ── TestListSpaceMembers ────────────────────────────────────────────────────────

class TestListSpaceMembers:
    """Tests for the list_space_members MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_space_members

        mock_mcp_client.list_space_members.return_value = [
            {"peer_id": "p1", "permission": "owner"},
            {"peer_id": "p2", "permission": "editor"},
        ]
        result = list_space_members(workspace_id="ws1")
        assert len(result) == 2
        mock_mcp_client.list_space_members.assert_called_once_with("ws1")


# ── Agent step tools ──────────────────────────────────────────────────────



# ── TestAddAgentStep ────────────────────────────────────────────────────────

class TestAddAgentStep:
    """Tests for the add_agent_step MCP tool."""

    def test_adds_step(self, mock_mcp_client):
        from server.mcp.main import add_agent_step

        result = add_agent_step(
            session_id="sess1",
            workspace_id="ws1",
            step_type="thought",
            content="I should search for X",
            summary="Search intent",
        )
        assert "Agent step recorded" in result
        mock_mcp_client.add_agent_step.assert_called_once_with(
            session_id="sess1",
            workspace_id="ws1",
            step_type="thought",
            content="I should search for X",
            summary="Search intent",
        )



# ── TestGetSessionSteps ────────────────────────────────────────────────────────

class TestGetSessionSteps:
    """Tests for the get_session_steps MCP tool."""

    def test_gets_steps(self, mock_mcp_client):
        from server.mcp.main import get_session_steps

        mock_mcp_client.get_session_steps.return_value = [
            {"step_type": "thought", "content": "Thinking..."},
        ]
        result = get_session_steps(session_id="sess1")
        assert len(result) == 1
        mock_mcp_client.get_session_steps.assert_called_once_with("sess1")


# ── Connector tools ───────────────────────────────────────────────────────
