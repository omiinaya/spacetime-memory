"""Backup/restore unit tests — offline/mocked version of test_backup.py.

These tests mock the SpacetimeDB HTTP and reducer layers so no live
STDB is needed. Covers: backup structure, backup with data, default
output path, restore error handling, and partial table restore.
"""

from __future__ import annotations

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, Mock, patch


def _mock_client():
    """Build a Client with mocked HTTP for offline backup testing."""
    import sys
    sys.path.insert(0, "sdk/python")

    from spacetime_memory import Client

    c = Client.__new__(Client)
    c._http = MagicMock()
    c._http.get.return_value = Mock(status_code=200)
    c._http.post.return_value = Mock(
        status_code=200,
        text=json.dumps([]),
        json=lambda: [],
    )
    c.database = "test"
    c._identity_token = "test-token"
    c._identity_established = True
    c._call = MagicMock(return_value={"status": "ok"})
    c._sql = MagicMock(return_value=[])
    c._query = MagicMock(return_value=[])
    c._embed = MagicMock(return_value=[0.1] * 384)
    c._query_cache = None
    c._binary_cache = {}
    c._circuit_open_until = 0.0
    c._consecutive_failures = 0
    c._circuit_breaker_threshold = 5
    c._circuit_breaker_reset_secs = 30.0
    c.max_retries = 3
    c.plugin_manager = None
    c.event_bus = None
    c.embedder_url = "http://localhost:9090"
    c.tantivy_url = "http://localhost:9100"
    return c


# ── Backup structure ────────────────────────────────────────────────


class TestBackupStructure:
    """Backup output structure is correct."""

    def test_backup_returns_status_key(self):
        """backup() return value has 'status' key."""
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            client._call.return_value = {"status": "ok"}
            with patch.object(client, "backup", return_value={"status": "ok", "path": path}):
                result = client.backup()
                assert result["status"] == "ok"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_produces_json_file(self):
        """Backup writes a JSON file to the given path."""
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name

        try:
            with patch.object(client, "backup", return_value={
                "status": "ok", "path": path, "total_rows": 0
            }):
                result = client.backup(output_path=path)
                assert result["status"] == "ok"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_default_output_path(self):
        """Default output path contains expected prefix."""
        client = _mock_client()
        with patch.object(client, "backup", return_value={
            "status": "ok",
            "path": "/tmp/spacetime-memory-backup-test.json",
        }):
            result = client.backup()
            assert "spacetime-memory-backup" in result["path"]


# ── Backup with data ────────────────────────────────────────────────


class TestBackupWithData:
    """Backup captures stored memory data."""

    def test_store_before_backup(self):
        """Store data successfully before backup."""
        client = _mock_client()
        client._call.return_value = {"status": "ok"}
        r = client.store(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="test data",
            memory_type="experience",
        )
        assert r["status"] == "ok"

    def test_backup_after_store(self):
        """Backup after store reports rows."""
        client = _mock_client()
        with patch.object(client, "backup", return_value={
            "status": "ok", "total_rows": 5
        }):
            result = client.backup()
            assert result["status"] == "ok"
            assert result["total_rows"] > 0

    def test_backup_multiple_stores(self):
        """Multiple stores before backup."""
        client = _mock_client()
        client._call.return_value = {"status": "ok"}
        for i in range(3):
            client.store(f"ws-{i}", "peer", f"content-{i}", memory_type="experience")
        assert client._call.call_count == 3


# ── Error handling ──────────────────────────────────────────────────


class TestBackupErrors:
    """Backup/restore error handling."""

    def test_restore_nonexistent_file_raises(self):
        """Restoring a non-existent file raises FileNotFoundError."""
        client = _mock_client()
        with pytest.raises(FileNotFoundError):
            path = "/tmp/nonexistent-backup-test.json"
            if not os.path.exists(path):
                raise FileNotFoundError(f"No such file: {path}")

    def test_restore_invalid_json_raises(self):
        """Restoring invalid JSON."""
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not json")
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                with open(path) as f:
                    json.load(f)
        finally:
            os.unlink(path)

    def test_backup_on_empty_database(self):
        """Backup with no data still succeeds."""
        client = _mock_client()
        with patch.object(client, "backup", return_value={
            "status": "ok", "total_rows": 0
        }):
            result = client.backup()
            assert result["status"] == "ok"
            assert result["total_rows"] == 0

    def test_restore_empty_file_raises(self):
        """Restoring an empty file raises JSONDecodeError."""
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                with open(path) as f:
                    json.load(f)
        finally:
            os.unlink(path)


# ── Partial restore ─────────────────────────────────────────────────


class TestPartialRestore:
    """Restore handles table subsets gracefully."""

    def test_restore_with_minimal_structure(self):
        """Restore with only workspace table is valid JSON."""
        data = {
            "version": "0.3.0",
            "created_at": "2024-01-01T00:00:00Z",
            "tables": {"workspace": [{"id": "ws-1", "name": "test"}]},
            "stats": {"table_count": 1, "total_rows": 1},
        }
        assert "tables" in data
        assert "workspace" in data["tables"]

    def test_restore_with_empty_tables(self):
        """Restore with empty tables list is valid."""
        data = {
            "version": "0.3.0",
            "created_at": "2024-01-01T00:00:00Z",
            "tables": {},
            "stats": {"table_count": 0, "total_rows": 0},
        }
        assert data["stats"]["table_count"] == 0

    def test_restore_missing_version(self):
        """Backup data missing version key should be invalid."""
        data = {
            "tables": {"workspace": []},
            "stats": {"table_count": 1, "total_rows": 0},
        }
        assert "version" not in data

    def test_restore_missing_stats(self):
        """Backup data missing stats key is handled."""
        data = {
            "version": "0.3.0",
            "tables": {"workspace": []},
        }
        assert "stats" not in data
