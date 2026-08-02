"""Tests for server/mcp/tools/directory.py - Directory MCP tools."""
import pytest
from server.mcp.tools.directory import (
    create_directory, get_directory, list_directory,
    search_directory_contents, link_memory_to_directory,
    traverse_directory, unlink_memory_from_directory,
)


class TestDirectoryModule:
    """Test suite for directory.py - verify all expected exports exist."""

    def test_create_directory_exists(self):
        """create_directory should be callable."""
        assert callable(create_directory)

    def test_get_directory_exists(self):
        """get_directory should be callable."""
        assert callable(get_directory)

    def test_list_directory_exists(self):
        """list_directory should be callable."""
        assert callable(list_directory)

    def test_search_directory_contents_exists(self):
        """search_directory_contents should be callable."""
        assert callable(search_directory_contents)

    def test_link_memory_to_directory_exists(self):
        """link_memory_to_directory should be callable."""
        assert callable(link_memory_to_directory)

    def test_traverse_directory_exists(self):
        """traverse_directory should be callable."""
        assert callable(traverse_directory)

    def test_unlink_memory_from_directory_exists(self):
        """unlink_memory_from_directory should be callable."""
        assert callable(unlink_memory_from_directory)
