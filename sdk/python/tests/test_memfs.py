"""Tests for the MemfsMixin — MemFS virtual filesystem operations.

Unit tests use the ``mock_http_client`` fixture (no SpacetimeDB required)
and monkeypatch to control ``_call`` / ``_sql`` return values.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

# ============================================================================
# Helpers
# ============================================================================


def _reducer_resp() -> Mock:
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _make_entry(
    entry_id: str = "entry_001",
    workspace_id: str = "ws_001",
    parent_id: str = "",
    name: str = "test.txt",
    path: str = "/test.txt",
    entry_type: str = "file",
    mime_type: str = "text/plain",
    data: str = "hello world",
    size: int = 11,
) -> dict:
    """Build a memfs entry dict for testing."""
    return {
        "id": entry_id,
        "workspace_id": workspace_id,
        "parent_id": parent_id,
        "name": name,
        "path": path,
        "entry_type": entry_type,
        "mime_type": mime_type,
        "data": data,
        "size": size,
        "is_mounted": False,
        "mount_source": "",
        "created_at": 1_000_000,
        "updated_at": 1_000_000,
    }


def _make_mount(
    mount_id: str = "mount_001",
    workspace_id: str = "ws_001",
    mount_path: str = "/mnt/workspace",
    source_type: str = "workspace",
    source_config: str = "{}",
    filter_query: str = "",
) -> dict:
    """Build a memfs mount dict for testing."""
    return {
        "id": mount_id,
        "workspace_id": workspace_id,
        "mount_path": mount_path,
        "source_type": source_type,
        "source_config": source_config,
        "filter_query": filter_query,
        "created_at": 1_000_000,
    }


def _make_result_row(entry: dict) -> dict:
    """Wrap an entry dict as a memfs_result row for SQL mock."""
    return {"id": entry["id"], "data": json.dumps(entry)}


# ============================================================================
# MemfsMixin tests
# ============================================================================


class TestMemfsMixin:
    """MemfsMixin — create, read, update, delete, list, mount."""

    # ── create_memfs_entry ───────────────────────────────────────────────

    def test_create_file_entry(self, mock_http_client):
        """create_memfs_entry calls the reducer with correct args for a file."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_memfs_entry(
            workspace_id="ws_001",
            parent_id="",
            name="readme.md",
            entry_type="file",
            mime_type="text/markdown",
            data="# Hello",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/create_memfs_entry" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "", "readme.md", "file", "text/markdown", "# Hello"]

    def test_create_directory_entry(self, mock_http_client):
        """create_memfs_entry works for directories."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_memfs_entry(
            workspace_id="ws_001",
            parent_id="",
            name="docs",
            entry_type="directory",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "", "docs", "directory", "", ""]

    # ── delete_memfs_entry ───────────────────────────────────────────────

    def test_delete_entry(self, mock_http_client):
        """delete_memfs_entry calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.delete_memfs_entry(
            workspace_id="ws_001",
            entry_id="entry_001",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/delete_memfs_entry" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "entry_001"]

    # ── update_memfs_entry ───────────────────────────────────────────────

    def test_update_entry_name(self, mock_http_client):
        """update_memfs_entry calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.update_memfs_entry(
            workspace_id="ws_001",
            entry_id="entry_001",
            name="newname.txt",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "entry_001", "newname.txt", "", ""]

    def test_update_entry_data(self, mock_http_client):
        """update_memfs_entry with new data."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.update_memfs_entry(
            workspace_id="ws_001",
            entry_id="entry_001",
            data="new content",
            mime_type="text/html",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "entry_001", "", "new content", "text/html"]

    # ── get_memfs_entries ────────────────────────────────────────────────

    def test_get_memfs_entries(self, mock_http_client, monkeypatch):
        """get_memfs_entries returns parsed entries from memfs_result."""
        children = [
            _make_entry("e1", "ws_001", parent_id="dir_1", name="a.txt", path="/docs/a.txt"),
            _make_entry("e2", "ws_001", parent_id="dir_1", name="b.txt", path="/docs/b.txt"),
        ]
        sql_rows = [_make_result_row(c) for c in children]

        def mock_call(reducer, args):
            assert reducer == "get_memfs_entries"
            assert args == ["ws_001", "dir_1"]
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: sql_rows)

        entries = mock_http_client.get_memfs_entries(
            workspace_id="ws_001",
            parent_id="dir_1",
        )

        assert len(entries) == 2
        assert entries[0]["name"] == "a.txt"
        assert entries[1]["name"] == "b.txt"

    def test_get_memfs_entries_empty(self, mock_http_client, monkeypatch):
        """get_memfs_entries returns empty list when directory is empty."""
        def mock_call(reducer, args):
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", mock_call)
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: [])

        entries = mock_http_client.get_memfs_entries("ws_001", "dir_empty")
        assert entries == []

    # ── get_memfs_entry_by_path ──────────────────────────────────────────

    def test_get_entry_by_path_found(self, mock_http_client, monkeypatch):
        """get_memfs_entry_by_path returns the entry when found."""
        entry = _make_entry("e1", "ws_001", path="/docs/readme.md")
        sql_rows = [{"id": "found_e1", "data": json.dumps(entry)}]

        monkeypatch.setattr(mock_http_client, "_call", lambda r, a: {"status": "ok"})
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: sql_rows)

        result = mock_http_client.get_memfs_entry_by_path("ws_001", "/docs/readme.md")
        assert result is not None
        assert result["path"] == "/docs/readme.md"
        assert result["name"] == "test.txt"

    def test_get_entry_by_path_not_found(self, mock_http_client, monkeypatch):
        """get_memfs_entry_by_path returns None when not found."""
        monkeypatch.setattr(mock_http_client, "_call", lambda r, a: {"status": "ok"})
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: [])

        result = mock_http_client.get_memfs_entry_by_path("ws_001", "/nonexistent")
        assert result is None

    # ── read_memfs_file ──────────────────────────────────────────────────

    def test_read_memfs_file(self, mock_http_client, monkeypatch):
        """read_memfs_file returns file entry with content."""
        entry = _make_entry("e1", "ws_001", data="file content here")
        sql_rows = [{"id": "read_e1", "data": json.dumps(entry)}]

        monkeypatch.setattr(mock_http_client, "_call", lambda r, a: {"status": "ok"})
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: sql_rows)

        result = mock_http_client.read_memfs_file("ws_001", "e1")
        assert result is not None
        assert result["data"] == "file content here"

    def test_read_memfs_file_not_found(self, mock_http_client, monkeypatch):
        """read_memfs_file returns None when file doesn't exist."""
        monkeypatch.setattr(mock_http_client, "_call", lambda r, a: {"status": "ok"})
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: [])

        result = mock_http_client.read_memfs_file("ws_001", "nonexistent")
        assert result is None

    # ── write_memfs_file ─────────────────────────────────────────────────

    def test_write_memfs_file(self, mock_http_client):
        """write_memfs_file calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.write_memfs_file(
            workspace_id="ws_001",
            entry_id="entry_001",
            data="updated content",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/write_memfs_file" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "entry_001", "updated content"]

    # ── create_memfs_mount ───────────────────────────────────────────────

    def test_create_memfs_mount(self, mock_http_client):
        """create_memfs_mount calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        config = {"filter": {"memory_type": "experience"}}
        result = mock_http_client.create_memfs_mount(
            workspace_id="ws_001",
            mount_path="/memories",
            source_type="memory",
            source_config=config,
            filter_query="memory_type = 'experience'",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/create_memfs_mount" in args[0]
        body = json.loads(kwargs["content"])
        assert body[0] == "ws_001"
        assert body[1] == "/memories"
        assert body[2] == "memory"
        sent_config = json.loads(body[3])
        assert sent_config == config
        assert body[4] == "memory_type = 'experience'"

    def test_create_memfs_mount_string_config(self, mock_http_client):
        """create_memfs_mount accepts raw JSON string as source_config."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_memfs_mount(
            workspace_id="ws_001",
            mount_path="/notes",
            source_type="note",
            source_config='{"workspace_only": true}',
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert json.loads(body[3]) == {"workspace_only": True}

    # ── delete_memfs_mount ───────────────────────────────────────────────

    def test_delete_memfs_mount(self, mock_http_client):
        """delete_memfs_mount calls reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.delete_memfs_mount(
            workspace_id="ws_001",
            mount_id="mount_001",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/delete_memfs_mount" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "mount_001"]

    # ── get_memfs_mounts ─────────────────────────────────────────────────

    def test_get_memfs_mounts(self, mock_http_client, monkeypatch):
        """get_memfs_mounts returns parsed mount list."""
        mounts = [
            _make_mount("m1", "ws_001", "/memories", "memory"),
            _make_mount("m2", "ws_001", "/notes", "note"),
        ]
        sql_rows = [_make_result_row(m) for m in mounts]

        monkeypatch.setattr(mock_http_client, "_call", lambda r, a: {"status": "ok"})
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: sql_rows)

        result = mock_http_client.get_memfs_mounts("ws_001")
        assert len(result) == 2
        assert result[0]["source_type"] == "memory"
        assert result[1]["mount_path"] == "/notes"

    def test_get_memfs_mounts_empty(self, mock_http_client, monkeypatch):
        """get_memfs_mounts returns empty list when no mounts."""
        monkeypatch.setattr(mock_http_client, "_call", lambda r, a: {"status": "ok"})
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: [])

        result = mock_http_client.get_memfs_mounts("ws_001")
        assert result == []

    # ── Convenience methods ──────────────────────────────────────────────

    def test_mount_workspace(self, mock_http_client, monkeypatch):
        """mount_workspace delegates to create_memfs_mount with source_type='workspace'."""
        mock_http_client._http.post.return_value = _reducer_resp()
        call_args = []

        def track_call(reducer, args):
            call_args.append((reducer, args))
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", track_call)

        result = mock_http_client.mount_workspace("ws_001", "/workspace")

        assert result["status"] == "ok"
        assert call_args[0][0] == "create_memfs_mount"
        assert call_args[0][1][2] == "workspace"  # source_type

    def test_mount_memories(self, mock_http_client, monkeypatch):
        """mount_memories delegates to create_memfs_mount with source_type='memory'."""
        mock_http_client._http.post.return_value = _reducer_resp()
        call_args = []

        def track_call(reducer, args):
            call_args.append((reducer, args))
            return {"status": "ok"}

        monkeypatch.setattr(mock_http_client, "_call", track_call)

        result = mock_http_client.mount_memories("ws_001")

        assert result["status"] == "ok"
        assert call_args[0][0] == "create_memfs_mount"
        assert call_args[0][1][2] == "memory"

    # ── get_virtual_path ─────────────────────────────────────────────────

    def test_get_virtual_path_found(self, mock_http_client, monkeypatch):
        """get_virtual_path returns path from SQL query."""
        monkeypatch.setattr(
            mock_http_client,
            "_sql",
            lambda q: [{"path": "/docs/readme.md"}],
        )

        path = mock_http_client.get_virtual_path("ws_001", "entry_001")
        assert path == "/docs/readme.md"

    def test_get_virtual_path_not_found(self, mock_http_client, monkeypatch):
        """get_virtual_path returns None when entry not found."""
        monkeypatch.setattr(mock_http_client, "_sql", lambda q: [])

        path = mock_http_client.get_virtual_path("ws_001", "nonexistent")
        assert path is None

    # ── export_tree ──────────────────────────────────────────────────────

    def test_export_tree_flat(self, mock_http_client, monkeypatch):
        """export_tree returns indented lines for a flat directory."""
        children = [
            _make_entry("e1", "ws_001", name="a.txt", path="/a.txt", data="aa", size=2),
            _make_entry("e2", "ws_001", name="b.txt", path="/b.txt", data="bbb", size=3),
        ]

        def mock_get_entries(ws, parent_id):
            if parent_id == "":
                return children
            return []

        monkeypatch.setattr(mock_http_client, "get_memfs_entries", mock_get_entries)

        lines = mock_http_client.export_tree("ws_001")
        assert len(lines) == 2
        assert "a.txt  (2 bytes)" in lines[0]
        assert "b.txt  (3 bytes)" in lines[1]

    def test_export_tree_nested(self, mock_http_client, monkeypatch):
        """export_tree handles nested directories."""
        dir_entry = _make_entry(
            "dir_1", "ws_001", name="docs", path="/docs",
            entry_type="directory", data="", size=0,
        )
        file_entry = _make_entry(
            "e1", "ws_001", parent_id="dir_1", name="readme.md",
            path="/docs/readme.md", data="# hello", size=7,
        )

        def mock_get_entries(ws, parent_id):
            if parent_id == "":
                return [dir_entry]
            if parent_id == "dir_1":
                return [file_entry]
            return []

        monkeypatch.setattr(mock_http_client, "get_memfs_entries", mock_get_entries)

        lines = mock_http_client.export_tree("ws_001")
        assert len(lines) >= 2
        assert "docs/" in lines[0]
        assert "readme.md  (7 bytes)" in lines[1]

    # ── Workspace isolation ──────────────────────────────────────────────

    def test_entries_isolated_by_workspace(self, mock_http_client, monkeypatch):
        """Entries in different workspaces are isolated."""
        calls = []

        def mock_call(reducer, args):
            calls.append((reducer, args[0]))
            return {"status": "ok"}

        def mock_sql(q):
            ws = calls[-1][1] if calls else ""
            if ws == "ws_001":
                return [_make_result_row(_make_entry("e1", "ws_001"))]
            return []

        monkeypatch.setattr(mock_http_client, "_call", mock_call)
        monkeypatch.setattr(mock_http_client, "_sql", mock_sql)

        ws1_entries = mock_http_client.get_memfs_entries("ws_001", "")
        ws2_entries = mock_http_client.get_memfs_entries("ws_002", "")

        assert len(ws1_entries) == 1
        assert len(ws2_entries) == 0
