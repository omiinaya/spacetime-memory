"""Tests for server/mcp/tools/directory.py — Directory tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_get_client():
    """Patch get_client at the module level where directory.py imports it."""
    with patch("server.mcp.tools.directory.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# create_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateDirectory:
    """Tests for the create_directory MCP tool."""

    def test_creates(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import create_directory

        result = create_directory(
            workspace_id="ws1",
            name="Projects",
            path="/projects",
            parent_id="",
            description="Project directories",
        )
        assert "Projects" in result
        assert "created" in result
        _patch_get_client.create_directory.assert_called_once_with(
            "ws1", "Projects", "/projects", "", "Project directories"
        )

    def test_with_parent(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import create_directory

        create_directory(
            workspace_id="ws1",
            name="AI",
            path="/projects/ai",
            parent_id="dir_root",
            description="",
        )
        _patch_get_client.create_directory.assert_called_once_with(
            "ws1", "AI", "/projects/ai", "dir_root", ""
        )

    def test_empty_path(self, _patch_get_client: MagicMock):
        """create_directory handles empty path string."""
        from server.mcp.tools.directory import create_directory

        result = create_directory(
            workspace_id="ws1",
            name="Root",
            path="",
            parent_id="",
            description="",
        )
        assert "Root" in result
        assert "created" in result
        _patch_get_client.create_directory.assert_called_once_with(
            "ws1", "Root", "", "", ""
        )

    def test_special_chars_in_name(self, _patch_get_client: MagicMock):
        """create_directory handles special characters in name."""
        from server.mcp.tools.directory import create_directory

        result = create_directory(
            workspace_id="ws1",
            name="My Folder (2026) — Test!",
            path="/special/test!",
            parent_id="",
            description="Special chars: $@#",
        )
        assert "My Folder (2026) — Test!" in result
        assert "created" in result
        _patch_get_client.create_directory.assert_called_once_with(
            "ws1", "My Folder (2026) — Test!", "/special/test!", "", "Special chars: $@#"
        )

    def test_propagates_client_error(self, _patch_get_client: MagicMock):
        """create_directory propagates exceptions from the client."""
        from server.mcp.tools.directory import create_directory

        _patch_get_client.create_directory.side_effect = RuntimeError("DB error")

        with pytest.raises(RuntimeError, match="DB error"):
            create_directory(
                workspace_id="ws1",
                name="Fail",
                path="/fail",
                parent_id="",
                description="",
            )


# ---------------------------------------------------------------------------
# traverse_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraverseDirectory:
    """Tests for the traverse_directory MCP tool."""

    def test_traverses(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import traverse_directory

        expected = [
            {"id": "dir_a", "name": "A", "children": []},
            {"id": "dir_b", "name": "B", "children": []},
        ]
        _patch_get_client.traverse_directory.return_value = expected

        result = traverse_directory(workspace_id="ws1", root_directory_id="dir_root")
        assert json.loads(result) == expected
        _patch_get_client.traverse_directory.assert_called_once_with(
            "ws1", "dir_root"
        )

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import traverse_directory

        _patch_get_client.traverse_directory.return_value = []
        result = traverse_directory("ws1", "empty")
        assert json.loads(result) == []

    def test_propagates_error(self, _patch_get_client: MagicMock):
        """traverse_directory propagates client exceptions."""
        from server.mcp.tools.directory import traverse_directory

        _patch_get_client.traverse_directory.side_effect = ConnectionError("Timeout")

        with pytest.raises(ConnectionError, match="Timeout"):
            traverse_directory("ws1", "bad")


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListDirectory:
    """Tests for the list_directory MCP tool."""

    def test_lists_children(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import list_directory

        expected = [{"id": "child1", "name": "Child 1"}]
        _patch_get_client.list_directory.return_value = expected

        result = list_directory(directory_id="dir_root")
        assert json.loads(result) == expected
        _patch_get_client.list_directory.assert_called_once_with("dir_root")

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import list_directory

        _patch_get_client.list_directory.return_value = []
        result = list_directory("empty")
        assert json.loads(result) == []

    def test_propagates_error(self, _patch_get_client: MagicMock):
        """list_directory propagates client exceptions."""
        from server.mcp.tools.directory import list_directory

        _patch_get_client.list_directory.side_effect = ValueError("Invalid ID")

        with pytest.raises(ValueError, match="Invalid ID"):
            list_directory("bad-id")


# ---------------------------------------------------------------------------
# get_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDirectory:
    """Tests for the get_directory MCP tool."""

    def test_gets_by_id(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import get_directory

        expected = [{"id": "dir_abc", "path": "/root"}]
        _patch_get_client.get_directory.return_value = expected

        result = get_directory(workspace_id="ws1", path_or_id="dir_abc")
        assert json.loads(result) == expected
        _patch_get_client.get_directory.assert_called_once_with("ws1", "dir_abc")

    def test_gets_by_path(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import get_directory

        expected = [{"id": "dir_xyz", "path": "/projects/ai"}]
        _patch_get_client.get_directory.return_value = expected

        result = get_directory(workspace_id="ws1", path_or_id="/projects/ai")
        assert json.loads(result) == expected
        _patch_get_client.get_directory.assert_called_once_with("ws1", "/projects/ai")

    def test_empty_result(self, _patch_get_client: MagicMock):
        """get_directory returns empty list when nothing matches."""
        from server.mcp.tools.directory import get_directory

        _patch_get_client.get_directory.return_value = []

        result = get_directory(workspace_id="ws1", path_or_id="nonexistent")
        assert json.loads(result) == []

    def test_propagates_error(self, _patch_get_client: MagicMock):
        """get_directory propagates client exceptions."""
        from server.mcp.tools.directory import get_directory

        _patch_get_client.get_directory.side_effect = KeyError("Not found")

        with pytest.raises(KeyError, match="Not found"):
            get_directory("ws1", "bad")


# ---------------------------------------------------------------------------
# link_memory_to_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkMemoryToDirectory:
    """Tests for the link_memory_to_directory MCP tool."""

    def test_links(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import link_memory_to_directory

        result = link_memory_to_directory(
            directory_id="dir_abc",
            memory_id="mem_xyz",
            workspace_id="ws1",
        )
        assert "linked" in result
        _patch_get_client.link_memory_to_directory.assert_called_once_with(
            "dir_abc", "mem_xyz", "ws1"
        )

    def test_empty_ids(self, _patch_get_client: MagicMock):
        """link_memory_to_directory handles empty directory/memory IDs."""
        from server.mcp.tools.directory import link_memory_to_directory

        result = link_memory_to_directory(
            directory_id="",
            memory_id="",
            workspace_id="ws1",
        )
        assert "linked" in result
        _patch_get_client.link_memory_to_directory.assert_called_once_with(
            "", "", "ws1"
        )

    def test_propagates_error(self, _patch_get_client: MagicMock):
        """link_memory_to_directory propagates client exceptions."""
        from server.mcp.tools.directory import link_memory_to_directory

        _patch_get_client.link_memory_to_directory.side_effect = PermissionError("Forbidden")

        with pytest.raises(PermissionError, match="Forbidden"):
            link_memory_to_directory("dir_a", "mem_b", "ws1")


# ---------------------------------------------------------------------------
# unlink_memory_from_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnlinkMemoryFromDirectory:
    """Tests for the unlink_memory_from_directory MCP tool."""

    def test_unlinks(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import unlink_memory_from_directory

        result = unlink_memory_from_directory(
            directory_id="dir_abc",
            memory_id="mem_xyz",
        )
        assert "unlinked" in result
        _patch_get_client.unlink_memory_from_directory.assert_called_once_with(
            "dir_abc", "mem_xyz"
        )

    def test_empty_ids(self, _patch_get_client: MagicMock):
        """unlink_memory_from_directory handles empty IDs."""
        from server.mcp.tools.directory import unlink_memory_from_directory

        result = unlink_memory_from_directory(
            directory_id="",
            memory_id="",
        )
        assert "unlinked" in result
        _patch_get_client.unlink_memory_from_directory.assert_called_once_with(
            "", ""
        )

    def test_propagates_error(self, _patch_get_client: MagicMock):
        """unlink_memory_from_directory propagates client exceptions."""
        from server.mcp.tools.directory import unlink_memory_from_directory

        _patch_get_client.unlink_memory_from_directory.side_effect = RuntimeError("Unlink failed")

        with pytest.raises(RuntimeError, match="Unlink failed"):
            unlink_memory_from_directory("dir_a", "mem_b")


# ---------------------------------------------------------------------------
# search_directory_contents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchDirectoryContents:
    """Tests for the search_directory_contents MCP tool."""

    def test_searches(self, _patch_get_client: MagicMock):
        from server.mcp.tools.directory import search_directory_contents

        expected = {
            "directory_id": "dir_root",
            "subdirectory_ids_json": '["dir_a", "dir_b"]',
            "memory_ids_json": '["mem_1", "mem_2"]',
            "directory_path": "/projects/ai",
            "workspace_id": "ws1",
        }
        _patch_get_client.search_directory_contents.return_value = expected

        result = search_directory_contents(
            workspace_id="ws1", directory_path="/projects/ai"
        )
        assert json.loads(result) == expected
        _patch_get_client.search_directory_contents.assert_called_once_with(
            "ws1", "/projects/ai"
        )

    def test_propagates_error(self, _patch_get_client: MagicMock):
        """search_directory_contents propagates client exceptions."""
        from server.mcp.tools.directory import search_directory_contents

        _patch_get_client.search_directory_contents.side_effect = RuntimeError("Search error")

        with pytest.raises(RuntimeError, match="Search error"):
            search_directory_contents("ws1", "/bad/path")
