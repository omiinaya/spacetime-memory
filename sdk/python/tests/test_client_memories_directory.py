"""Unit tests for DirectoryMixin — directory tree management.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestDirectoryMixin:
    """DirectoryMixin methods (directory listing, traversal, CRUD)."""

    # ------------------------------------------------------------------ #
    # list_directory
    # ------------------------------------------------------------------ #

    def test_list_directory(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[
                 {"query_hash": "dir-1", "id": "child-1", "name": "Subdir 1"}
             ]):
            result = mock_http_client.list_directory("dir-1")
        assert len(result) == 1
        assert result[0]["name"] == "Subdir 1"
        assert result[0]["id"] == "child-1"

    def test_list_directory_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.list_directory("dir-1")
        assert result == []

    def test_list_directory_error(self, mock_http_client):
        """_call failure propagates to caller."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("conn failed")):
            with pytest.raises(RuntimeError, match="conn failed"):
                mock_http_client.list_directory("dir-1")

    def test_list_directory_sql_error(self, mock_http_client):
        """_sql failure propagates to caller."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", side_effect=RuntimeError("sql err")):
            with pytest.raises(RuntimeError, match="sql err"):
                mock_http_client.list_directory("dir-1")

    def test_list_directory_with_empty_id(self, mock_http_client):
        """Empty directory_id is passed through."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.list_directory("")
        assert result == []

    # ------------------------------------------------------------------ #
    # traverse_directory
    # ------------------------------------------------------------------ #

    def test_traverse_directory(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[
                 {"query_hash": "root-1", "id": "child-1", "name": "File 1"}
             ]):
            result = mock_http_client.traverse_directory("ws-1", "root-1")
        assert len(result) == 1
        assert result[0]["name"] == "File 1"

    def test_traverse_directory_empty_result(self, mock_http_client):
        """Traversing an empty subtree returns empty list."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.traverse_directory("ws-1", "empty-root")
        assert result == []

    def test_traverse_directory_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("traverse err")):
            with pytest.raises(RuntimeError, match="traverse err"):
                mock_http_client.traverse_directory("ws-1", "root-1")

    # ------------------------------------------------------------------ #
    # get_directory
    # ------------------------------------------------------------------ #

    def test_get_directory_by_id(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[
                 {"workspace_id": "ws-1", "id": "dir-1", "name": "Root"}
             ]):
            result = mock_http_client.get_directory("ws-1", "dir-1")
        assert len(result) == 1
        assert result[0]["name"] == "Root"
        assert result[0]["workspace_id"] == "ws-1"

    def test_get_directory_not_found(self, mock_http_client):
        """Directory not found returns empty list."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.get_directory("ws-1", "nonexistent")
        assert result == []

    def test_get_directory_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("get err")):
            with pytest.raises(RuntimeError, match="get err"):
                mock_http_client.get_directory("ws-1", "dir-1")

    # ------------------------------------------------------------------ #
    # create_directory
    # ------------------------------------------------------------------ #

    def test_create_directory(self, mock_http_client):
        result = mock_http_client.create_directory(
            "ws-1", "My Dir", "/my/dir", parent_id="parent-1", description="A test dir"
        )
        assert result == {"status": "ok"}

    def test_create_directory_minimal(self, mock_http_client):
        """Create directory with only required params."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.create_directory(
                "ws-1", "Min Dir", "/min/dir", parent_id="", description=""
            )
        assert result == {"status": "ok"}

    def test_create_directory_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("create err")):
            with pytest.raises(RuntimeError, match="create err"):
                mock_http_client.create_directory(
                    "ws-1", "Fail", "/fail", parent_id="p1", description=""
                )

    # ------------------------------------------------------------------ #
    # link_memory_to_directory
    # ------------------------------------------------------------------ #

    def test_link_memory_to_directory(self, mock_http_client):
        result = mock_http_client.link_memory_to_directory("dir-1", "mem-1", "ws-1")
        assert result == {"status": "ok"}

    def test_link_memory_to_directory_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("link err")):
            with pytest.raises(RuntimeError, match="link err"):
                mock_http_client.link_memory_to_directory("dir-1", "mem-1", "ws-1")

    # ------------------------------------------------------------------ #
    # unlink_memory_from_directory
    # ------------------------------------------------------------------ #

    def test_unlink_memory_from_directory(self, mock_http_client):
        result = mock_http_client.unlink_memory_from_directory("dir-1", "mem-1")
        assert result == {"status": "ok"}

    def test_unlink_memory_from_directory_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("unlink err")):
            with pytest.raises(RuntimeError, match="unlink err"):
                mock_http_client.unlink_memory_from_directory("dir-1", "mem-1")

    # ------------------------------------------------------------------ #
    # search_directory_contents
    # ------------------------------------------------------------------ #

    def test_search_directory_contents(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[
                 {"workspace_id": "ws-1", "directory_path": "/test", "directory_id": "dir-1",
                  "subdirectory_ids_json": "[]", "memory_ids_json": '["mem-1"]'}
             ]):
            result = mock_http_client.search_directory_contents("ws-1", "/test")
        assert len(result) == 1
        assert result[0]["directory_path"] == "/test"
        assert result[0]["directory_id"] == "dir-1"

    def test_search_directory_contents_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.search_directory_contents("ws-1", "/empty")
        assert result == []

    def test_search_directory_contents_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("search err")):
            with pytest.raises(RuntimeError, match="search err"):
                mock_http_client.search_directory_contents("ws-1", "/test")

    def test_search_directory_contents_sql_error(self, mock_http_client):
        """_sql failure propagates."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", side_effect=RuntimeError("sql fail")):
            with pytest.raises(RuntimeError, match="sql fail"):
                mock_http_client.search_directory_contents("ws-1", "/test")

    # ------------------------------------------------------------------ #
    # delete_directory
    # ------------------------------------------------------------------ #

    def test_delete_directory(self, mock_http_client):
        result = mock_http_client.delete_directory("/path/to/dir")
        assert result == {"status": "ok"}

    def test_delete_directory_empty_path(self, mock_http_client):
        """Empty path is passed through."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_directory("")
        assert result == {"status": "ok"}

    def test_delete_directory_error(self, mock_http_client):
        """_call failure propagates."""
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("delete err")):
            with pytest.raises(RuntimeError, match="delete err"):
                mock_http_client.delete_directory("/path/to/dir")
