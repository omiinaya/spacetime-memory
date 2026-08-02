"""Directory tree management mixin."""
from __future__ import annotations

from typing import Any

from ._utils import _esc


class DirectoryMixin:
    """Spacetime-Memory directory tree mixin.

    Provides Client methods related to the context directory tree.
    Inherits from ClientBase for connection infrastructure.
    """

    def list_directory(self, directory_id: str) -> list[dict[str, Any]]:
        """Get children of a directory."""
        self._call("get_children", [directory_id, True])
        return self._query(
            "directory_result",
            filter_dict={"query_hash": directory_id},
        )

    def traverse_directory(self, workspace_id: str, root_directory_id: str) -> list[dict[str, Any]]:
        """Recursive BFS traversal of directory tree."""
        self._call("traverse_recursive", [workspace_id, root_directory_id])
        return self._query(
            "directory_result",
            filter_dict={"query_hash": root_directory_id},
        )

    def get_directory(self, workspace_id: str, path_or_id: str) -> list[dict[str, Any]]:
        """Get a directory by ID or path."""
        self._call("get_directory", [workspace_id, path_or_id])
        return self._query(
            "directory_result",
            workspace_id=workspace_id,
            filter_dict={},
        )

    def create_directory(
        self, workspace_id: str, name: str, path: str, parent_id: str = "", description: str = ""
    ) -> dict[str, Any]:
        """Create a directory in the context directory tree."""
        return self._call("create_directory", [workspace_id, name, path, parent_id, description])

    def link_memory_to_directory(
        self, directory_id: str, memory_id: str, workspace_id: str
    ) -> dict[str, Any]:
        """Link a memory to a directory."""
        return self._call("link_memory_to_directory", [directory_id, memory_id, workspace_id])

    def unlink_memory_from_directory(self, directory_id: str, memory_id: str) -> dict[str, Any]:
        """Unlink a memory from a directory."""
        return self._call("unlink_memory_from_directory", [directory_id, memory_id])

    def search_directory_contents(
        self, workspace_id: str, directory_path: str
    ) -> list[dict[str, Any]]:
        """Recursively search directory contents.

        Finds a directory by path, recursively collects all subdirectories
        and memory entries within the tree, and returns the result.

        Args:
            workspace_id: Target workspace.
            directory_path: Path of the root directory to search.

        Returns:
            List with a single DirectoryContentResult dict containing:
            id, workspace_id, directory_path, directory_id,
            subdirectory_ids_json (JSON array of sub-directory IDs),
            memory_ids_json (JSON array of contained memory IDs),
            created_at.
        """
        self._call("search_directory_contents", [workspace_id, directory_path])
        rows = self._query(
            "directory_content_result",
            workspace_id=workspace_id,
            filter_dict={"directory_path": directory_path},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            return rows[:1]
        return []

    def delete_directory(self, directory_path: str) -> dict[str, Any]:
        """Delete a directory by path.

        Args:
            directory_path: The path of the directory to delete.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_directory", [directory_path])
