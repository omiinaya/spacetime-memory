"""Backup/restore integration tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from spacetime_memory import Client  # noqa: E402 — intentional: after sys.path.insert

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def client(stdb_session) -> Client:
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )
    # Register to satisfy auth requirements
    suffix = os.urandom(4).hex()
    try:
        c._call("register", [f"backup_test_{suffix}", "Backup Test", "testpass"])
    except RuntimeError:
        pass
    return c


def test_backup_structure(client):
    """Backup produces valid JSON with expected structure."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        result = client.backup(output_path=path)
        assert result["status"] == "ok"
        with open(path) as f:
            data = json.load(f)
        assert "tables" in data
        assert "version" in data
        assert "stats" in data
    finally:
        os.unlink(path)


def test_backup_with_data(client):
    """Backup captures memory data."""
    ws_id = "bu-ws-" + os.urandom(4).hex()
    client._call("create_workspace", ["bu-ws", "backup test", ws_id])
    r = client.store(
        workspace_id=ws_id,
        peer_id="bu-peer",
        content="backup test content",
        memory_type="experience",
    )
    assert r["status"] == "ok"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        result = client.backup(output_path=path)
        assert result["status"] == "ok"
        assert result["total_rows"] > 0
        with open(path) as f:
            data = json.load(f)
        ws_table = data["tables"].get("workspace", [])
        assert any(w["id"] == ws_id for w in ws_table), f"Workspace {ws_id} not in backup"
    finally:
        os.unlink(path)


def test_backup_output_path_default(client):
    """Default output path is sensible."""
    result = client.backup()
    assert result["status"] == "ok"
    path = result["path"]
    assert "spacetime-memory-backup" in path
    assert os.path.exists(path)
    os.unlink(path)


def test_restore_invalid_path(client):
    """Non-existent file raises error."""
    with pytest.raises(FileNotFoundError):
        client.restore(input_path="/tmp/nonexistent-backup.json")


def test_backup_restore_partial_tables(client):
    """Restore handles table subsets gracefully."""
    ws_id = "part-ws-" + os.urandom(4).hex()
    client._call("create_workspace", ["part-ws", "partial", ws_id])

    path = f"/tmp/backup-partial-{os.urandom(4).hex()}.json"
    client.backup(output_path=path)

    with open(path) as f:
        data = json.load(f)

    minimal = {
        "version": "0.3.0",
        "created_at": data["created_at"],
        "tables": {"workspace": data["tables"].get("workspace", [])},
        "stats": {"table_count": 1, "total_rows": len(data["tables"].get("workspace", []))},
    }
    min_path = path.replace(".json", "-min.json")
    with open(min_path, "w") as f:
        json.dump(minimal, f)

    result = client.restore(input_path=min_path)
    assert result["status"] == "ok"

    os.unlink(path)
    os.unlink(min_path)
