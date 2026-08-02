"""MemFS — virtual filesystem for SpacetimeDB-backed hierarchical storage.

Provides a ``MemfsMixin`` that exposes MemFS operations — entries,
mounts, paths — as methods on the ``Client`` class.

The Rust module at ``server/spacetimedb/src/memfs.rs`` defines three
tables (``memfs_entry``, ``memfs_mount``, ``memfs_result``) and ten
reducers that implement a virtual filesystem inside SpacetimeDB.

Typical usage::

    client = Client(...)

    # Create directories and files
    client.create_memfs_entry("ws-1", "", "docs", "directory", "")
    entry = client.create_memfs_entry("ws-1", parent_id, "readme.md", "file", "text/markdown", "# Hello")

    # Read a file
    content = client.read_memfs_file("ws-1", entry_id)

    # List a directory
    children = client.get_memfs_entries("ws-1", parent_id)

    # Mount a source
    client.create_memfs_mount("ws-1", "/memories", "memory", '{"filter": {"memory_type": "experience"}}')
"""
from __future__ import annotations

import json
from typing import Any


class MemfsMixin:
    """Mixin for MemFS — virtual filesystem operations.

    Provides methods to create, read, update, delete files and directories,
    list directory contents, resolve paths, and manage mount points that
    bridge MemFS to other SpacetimeDB data sources.
    """

    # -----------------------------------------------------------------------
    # Entry operations
    # -----------------------------------------------------------------------

    def create_memfs_entry(
        self,
        workspace_id: str,
        parent_id: str,
        name: str,
        entry_type: str,
        mime_type: str = "",
        data: str = "",
    ) -> dict[str, Any]:
        """Create a file or directory entry.

        Args:
            workspace_id: Target workspace.
            parent_id: Parent directory ID (empty string for root).
            name: Entry name (no path separators allowed).
            entry_type: ``"file"`` or ``"directory"``.
            mime_type: MIME type for files (optional).
            data: File content (for files; ignored for directories).

        Returns:
            Reducer status dict.
        """
        return self._call(
            "create_memfs_entry",
            [workspace_id, parent_id, name, entry_type, mime_type, data],
        )

    def delete_memfs_entry(
        self,
        workspace_id: str,
        entry_id: str,
    ) -> dict[str, Any]:
        """Delete an entry (recursive for directories).

        Args:
            workspace_id: Target workspace.
            entry_id: Entry ID to delete.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "delete_memfs_entry",
            [workspace_id, entry_id],
        )

    def update_memfs_entry(
        self,
        workspace_id: str,
        entry_id: str,
        name: str = "",
        data: str = "",
        mime_type: str = "",
    ) -> dict[str, Any]:
        """Update an entry's name, data, and/or MIME type.

        Only non-empty fields are updated.  Pass empty strings for fields
        that should remain unchanged.

        Args:
            workspace_id: Target workspace.
            entry_id: Entry ID to update.
            name: New name (empty = keep current).
            data: New file content (empty = keep current).
            mime_type: New MIME type (empty = keep current).

        Returns:
            Reducer status dict.
        """
        return self._call(
            "update_memfs_entry",
            [workspace_id, entry_id, name, data, mime_type],
        )

    def get_memfs_entries(
        self,
        workspace_id: str,
        parent_id: str,
    ) -> list[dict[str, Any]]:
        """List children of a directory.

        Results are written to the ``memfs_result`` table by the reducer
        and read back via SQL.

        Args:
            workspace_id: Target workspace.
            parent_id: Parent directory ID (empty string for root).

        Returns:
            List of child entries as dicts.
        """
        self._call("get_memfs_entries", [workspace_id, parent_id])
        rows = self._sql(
            "SELECT id, data FROM memfs_result "
            f"WHERE id != '_count_{parent_id}'"
        )
        return [_parse_memfs_row(r) for r in rows]

    def get_memfs_entry_by_path(
        self,
        workspace_id: str,
        path: str,
    ) -> dict[str, Any] | None:
        """Look up an entry by its full virtual path.

        Args:
            workspace_id: Target workspace.
            path: Full virtual path (e.g. ``"/docs/readme.md"``).

        Returns:
            Entry dict if found, ``None`` otherwise.
        """
        self._call("get_memfs_entry_by_path", [workspace_id, path])
        rows = self._sql(
            "SELECT id, data FROM memfs_result "
            "WHERE id LIKE 'found_%'"
        )
        if not rows:
            return None
        return _parse_memfs_row(rows[0])

    def read_memfs_file(
        self,
        workspace_id: str,
        entry_id: str,
    ) -> dict[str, Any] | None:
        """Read a file's content.

        Args:
            workspace_id: Target workspace.
            entry_id: Entry ID of the file.

        Returns:
            Entry dict with ``data`` containing the file content,
            or ``None`` if not found.
        """
        self._call("read_memfs_file", [workspace_id, entry_id])
        rows = self._sql(
            "SELECT id, data FROM memfs_result "
            f"WHERE id = 'read_{entry_id}'"
        )
        if not rows:
            return None
        return _parse_memfs_row(rows[0])

    def write_memfs_file(
        self,
        workspace_id: str,
        entry_id: str,
        data: str,
    ) -> dict[str, Any]:
        """Write data to an existing file entry.

        Args:
            workspace_id: Target workspace.
            entry_id: Entry ID of the file.
            data: New file content.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "write_memfs_file",
            [workspace_id, entry_id, data],
        )

    # -----------------------------------------------------------------------
    # Mount operations
    # -----------------------------------------------------------------------

    def create_memfs_mount(
        self,
        workspace_id: str,
        mount_path: str,
        source_type: str,
        source_config: dict[str, Any] | str = "",
        filter_query: str = "",
    ) -> dict[str, Any]:
        """Create a mount point.

        Mount points map virtual paths to SpacetimeDB data sources so that
        listing the directory returns records from the mounted source.

        Args:
            workspace_id: Target workspace.
            mount_path: Virtual path to mount at (e.g. ``"/memories"``).
            source_type: One of ``"workspace"``, ``"memory"``, ``"note"``,
                ``"session"``, ``"custom"``.
            source_config: JSON-serialisable config dict or raw JSON string.
            filter_query: Optional query filter.

        Returns:
            Reducer status dict.
        """
        if isinstance(source_config, dict):
            source_config = json.dumps(source_config)
        return self._call(
            "create_memfs_mount",
            [workspace_id, mount_path, source_type, source_config, filter_query],
        )

    def delete_memfs_mount(
        self,
        workspace_id: str,
        mount_id: str,
    ) -> dict[str, Any]:
        """Remove a mount point.

        Args:
            workspace_id: Target workspace.
            mount_id: Mount point ID to delete.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "delete_memfs_mount",
            [workspace_id, mount_id],
        )

    def get_memfs_mounts(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List all mount points for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of mount point dicts.
        """
        self._call("get_memfs_mounts", [workspace_id])
        rows = self._sql(
            "SELECT id, data FROM memfs_result "
            f"WHERE id != '_mount_count_{workspace_id}'"
        )
        return [_parse_memfs_row(r) for r in rows]

    # -----------------------------------------------------------------------
    # Convenience methods
    # -----------------------------------------------------------------------

    def mount_workspace(
        self,
        workspace_id: str,
        mount_path: str = "/workspace",
        filter_query: str = "",
    ) -> dict[str, Any]:
        """Mount a workspace at a virtual path.

        Shortcut for ``create_memfs_mount`` with ``source_type="workspace"``.

        Args:
            workspace_id: Target workspace.
            mount_path: Virtual path (default: ``"/workspace"``).
            filter_query: Optional query filter.

        Returns:
            Reducer status dict.
        """
        return self.create_memfs_mount(
            workspace_id,
            mount_path,
            source_type="workspace",
            filter_query=filter_query,
        )

    def mount_memories(
        self,
        workspace_id: str,
        mount_path: str = "/memories",
        filter_query: str = "",
    ) -> dict[str, Any]:
        """Mount memories at a virtual path.

        Shortcut for ``create_memfs_mount`` with ``source_type="memory"``.

        Args:
            workspace_id: Target workspace.
            mount_path: Virtual path (default: ``"/memories"``).
            filter_query: Optional query filter.

        Returns:
            Reducer status dict.
        """
        return self.create_memfs_mount(
            workspace_id,
            mount_path,
            source_type="memory",
            filter_query=filter_query,
        )

    def get_virtual_path(
        self,
        workspace_id: str,
        entry_id: str,
    ) -> str | None:
        """Resolve the full virtual path of an entry by its ID.

        Queries the ``memfs_entry`` table directly via SQL to retrieve
        the entry's path field.

        Args:
            workspace_id: Target workspace.
            entry_id: Entry ID.

        Returns:
            Full virtual path string, or ``None`` if not found.
        """
        rows = self._sql(
            "SELECT path FROM memfs_entry "
            f"WHERE id = '{entry_id}' AND workspace_id = '{workspace_id}'"
        )
        if not rows:
            return None
        return rows[0].get("path", "")

    def export_tree(
        self,
        workspace_id: str,
        parent_id: str = "",
        indent: int = 0,
    ) -> list[str]:
        """Export the MemFS tree as a list of indented path strings.

        Recursively walks entries starting from ``parent_id`` and returns
        a human-readable tree representation.

        Args:
            workspace_id: Target workspace.
            parent_id: Starting directory (empty string for root).
            indent: Initial indentation level (used by recursion).

        Returns:
            List of indented path-like strings.
        """
        lines: list[str] = []
        children = self.get_memfs_entries(workspace_id, parent_id)
        prefix = "  " * indent
        for child in sorted(children, key=lambda c: (c.get("entry_type", ""), c.get("name", ""))):
            name = child.get("name", "?")
            entry_type = child.get("entry_type", "?")
            if entry_type == "directory":
                lines.append(f"{prefix}{name}/")
                lines.extend(
                    self.export_tree(workspace_id, child.get("id", ""), indent + 1)
                )
            else:
                size = child.get("size", 0)
                lines.append(f"{prefix}{name}  ({size} bytes)")
        return lines


def _parse_memfs_row(row: dict[str, Any]) -> dict[str, Any]:
    """Parse a ``memfs_result`` row returned by SQL.

    The ``data`` column contains a JSON string of the entry or mount.
    Where possible, the parsed dict is returned directly; otherwise
    the raw row is returned.
    """
    raw_data = row.get("data", "")
    if isinstance(raw_data, str) and raw_data:
        try:
            return json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            pass
    return row
