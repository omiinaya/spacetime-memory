"""Backup/restore integration tests.

These tests require a running SpacetimeDB standalone...
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from spacetime_memory import Client

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def client(stdb_session) -> Client:
    c = Client(host=stdb_session["host"], port=stdb_session["port"], database=stdb_session["database"])
    suffix = os.urandom(4).hex()
    try:
        c._call("register", [f"backup_test_{suffix}", "Backup Test", "testpass"])
    except RuntimeError:
        pass
    return c


def test_backup_structure(client):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        result = client.backup(output_path=path)
        assert result["status"] == "ok"
        assert "total_rows" in result
        assert "tables" in result
        assert result["path"] == path
        with open(path) as f:
            data = json.load(f)
        assert "version" in data
        assert "stats" in data
        assert data["version"] == "0.3.0"
        assert "created_at" in data
        assert data["stats"]["total_rows"] >= 0
    finally:
        os.unlink(path)


def test_backup_with_data(client):
    ws_id = "bu-ws-" + os.urandom(4).hex()
    client._call("create_workspace", ["bu-ws", "backup test", ws_id])
    r = client.store(workspace_id=ws_id, peer_id="bu-peer", content="backup test content", memory_type="experience")
    assert r["status"] == "ok"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        result = client.backup(output_path=path)
        assert result["status"] == "ok"
        assert result["total_rows"] > 0
        with open(path) as f:
            data = json.load(f)
        assert any("backup test content" in str(m) for m in data["tables"].get("memory", []))
    finally:
        os.unlink(path)


def test_backup_output_path_default(client):
    result = client.backup()
    assert result["status"] == "ok"
    assert "spacetime-memory-backup" in result["path"]
    assert result["path"].endswith(".json")
    assert os.path.exists(result["path"])
    with open(result["path"]) as f:
        data = json.load(f)
    assert data["version"] == "0.3.0"
    os.unlink(result["path"])


def test_restore_invalid_path(client):
    with pytest.raises(FileNotFoundError):
        client.restore(input_path="/tmp/nonexistent-backup.json")


def test_backup_restore_partial_tables(client):
    ws_id = "part-ws-" + os.urandom(4).hex()
    client._call("create_workspace", ["part-ws", "partial", ws_id])
    path = f"/tmp/backup-partial-{os.urandom(4).hex()}.json"
    client.backup(output_path=path)
    with open(path) as f:
        data = json.load(f)
    minimal = {"version": "0.3.0", "created_at": data["created_at"], "tables": {"workspace": data["tables"].get("workspace", [])}, "stats": {"table_count": 1, "total_rows": len(data["tables"].get("workspace", []))}}
    min_path = path.replace(".json", "-min.json")
    with open(min_path, "w") as f:
        json.dump(minimal, f)
    result = client.restore(input_path=min_path)
    assert result["status"] == "ok"
    os.unlink(path)
    os.unlink(min_path)


def test_backup_restore_roundtrip(client):
    suffix = os.urandom(4).hex()
    ws_id = f"rt-ws-{suffix}"
    client._call("create_workspace", ["rt-ws", "roundtrip", ws_id])
    client.store(workspace_id=ws_id, peer_id="rt-peer", content=f"roundtrip content {suffix}", memory_type="experience")
    path = f"/tmp/backup-rt-{suffix}.json"
    br = client.backup(output_path=path)
    assert br["status"] == "ok"
    assert br["total_rows"] > 0
    with open(path) as f:
        raw = json.load(f)
    assert "workspace" in raw["tables"]
    assert "memory" in raw["tables"]
    os.unlink(path)


def test_backup_multiple_workspaces(client):
    ids = []
    for i in range(3):
        ws_id = f"bmw-{i}-{os.urandom(4).hex()}"
        client._call("create_workspace", [f"bmw-{i}", f"multi ws {i}", ws_id])
        client.store(workspace_id=ws_id, peer_id="p1", content=f"data-{i}", memory_type="experience")
        ids.append(ws_id)
    path = f"/tmp/backup-multi-{os.urandom(4).hex()}.json"
    try:
        result = client.backup(output_path=path)
        assert result["status"] == "ok"
        assert result["total_rows"] >= 3
        with open(path) as f:
            data = json.load(f)
        backed_up_ids = {w["id"] for w in data["tables"].get("workspace", [])}
        for ws_id in ids:
            assert ws_id in backed_up_ids
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_backup_idempotent(client):
    path1 = f"/tmp/backup-idem-1-{os.urandom(4).hex()}.json"
    path2 = f"/tmp/backup-idem-2-{os.urandom(4).hex()}.json"
    try:
        r1 = client.backup(output_path=path1)
        r2 = client.backup(output_path=path2)
        assert r1["status"] == "ok" and r2["status"] == "ok"
        with open(path1) as f:
            json.load(f)
        with open(path2) as f:
            json.load(f)
    finally:
        for p in [path1, path2]:
            if os.path.exists(p):
                os.unlink(p)


# ════════════════════════════════════════════════════════════════════════════
# Mock-based unit tests (no SpacetimeDB required)
# ════════════════════════════════════════════════════════════════════════════


def _write_backup_json(path, data):
    """Write a backup JSON file for restore tests."""
    with open(path, "w") as f:
        json.dump(data, f)


class TestBackupUnit:
    """Backup/restore unit tests using a mocked Client.

    These tests mock ``client._query`` and ``client._sql`` so no
    SpacetimeDB instance is needed.  They validate the backup file
    structure, restore logic, and error handling.
    """

    @pytest.fixture
    def backup_dir(self, tmp_path):
        """Return a temp directory for backup files."""
        return tmp_path

    # ── mock_http_client-based tests ──────────────────────────────────

    def test_backup_empty_tables_ok(self, mock_http_client, backup_dir):
        """backup() with no data produces valid empty JSON."""
        # mock_http_client._http already returns empty SQL result sets
        path = str(backup_dir / "empty-backup.json")
        result = mock_http_client.backup(output_path=path)
        assert result["status"] == "ok"
        assert result["tables"] == []
        assert result["total_rows"] == 0

        with open(path) as f:
            payload = json.load(f)
        assert payload["version"] == "0.3.0"
        assert isinstance(payload["tables"], dict)
        assert payload["stats"]["total_rows"] == 0

    def test_backup_output_path_default(self, mock_http_client, backup_dir, monkeypatch):
        """backup() without output_path generates a sensible default filename."""
        monkeypatch.chdir(str(backup_dir))
        result = mock_http_client.backup()
        assert result["status"] == "ok"
        assert "spacetime-memory-backup" in result["path"]
        assert result["path"].endswith(".json")
        assert os.path.exists(result["path"])
        os.unlink(result["path"])

    def test_restore_empty_manifest(self, mock_http_client, backup_dir):
        """restore() with an empty manifest returns restored=[]."""
        path = str(backup_dir / "empty-restore.json")
        _write_backup_json(path, {
            "version": "0.3.0",
            "created_at": "2024-01-01T00:00:00",
            "tables": {},
            "stats": {"table_count": 0, "total_rows": 0},
        })
        result = mock_http_client.restore(input_path=path)
        assert result["status"] == "ok"
        assert result["tables"] == []
        assert result["total_rows"] == 0

    def test_restore_corrupt_json_raises(self, mock_http_client, backup_dir):
        """restore() with malformed JSON raises JSONDecodeError."""
        path = str(backup_dir / "corrupt.json")
        with open(path, "w") as f:
            f.write("this is not json at all")
        with pytest.raises(json.JSONDecodeError):
            mock_http_client.restore(input_path=path)

    def test_restore_missing_file_raises(self, mock_http_client):
        """restore() with a nonexistent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            mock_http_client.restore(input_path="/tmp/definitely-nonexistent-backup.json")

    def test_backup_version_field(self, mock_http_client, backup_dir):
        """backup() output includes the version field."""
        path = str(backup_dir / "version-test.json")
        result = mock_http_client.backup(output_path=path)
        assert result["status"] == "ok"
        with open(path) as f:
            payload = json.load(f)
        assert payload["version"] == "0.3.0"
        assert "created_at" in payload

    def test_backup_and_restore_empty_noop(self, mock_http_client, backup_dir):
        """backup of empty DB then restore of empty data is a no-op."""
        back_path = str(backup_dir / "noop-backup.json")
        bresult = mock_http_client.backup(output_path=back_path)
        assert bresult["status"] == "ok"

        # Restore from that file
        rresult = mock_http_client.restore(input_path=back_path)
        assert rresult["status"] == "ok"
        assert isinstance(rresult["tables"], list)


class TestBackupPluginDispatch:
    """Verify plugin dispatch during backup/restore."""

    def test_backup_dispatches_on_export(self, mock_http_client, tmp_path, monkeypatch):
        """backup() calls plugin_manager.dispatch_export when plugin_manager is set."""
        from unittest.mock import MagicMock

        pm = MagicMock()
        mock_client = mock_http_client
        mock_client.plugin_manager = pm

        path = str(tmp_path / "plugin-export.json")
        mock_client.backup(output_path=path)
        pm.dispatch_export.assert_called_once()
        # Called with a list of rows (empty in this case)
        args, _ = pm.dispatch_export.call_args
        assert isinstance(args[0], list)
        os.unlink(path)

    def test_restore_dispatches_on_import(self, mock_http_client, tmp_path):
        """restore() calls plugin_manager.dispatch_import when plugin_manager is set."""
        from unittest.mock import MagicMock

        pm = MagicMock()
        mock_client = mock_http_client
        mock_client.plugin_manager = pm

        path = str(tmp_path / "plugin-import.json")
        _write_backup_json(path, {
            "version": "0.3.0",
            "created_at": "2024-01-01",
            "tables": {"workspace": [{"id": "ws-1", "name": "test"}]},
            "stats": {"table_count": 1, "total_rows": 1},
        })

        mock_client.restore(input_path=path)
        pm.dispatch_import.assert_called_once()
        args, _ = pm.dispatch_import.call_args
        assert len(args[0]) == 1
