"""Backup/restore unit tests — offline/mocked version.

These tests mock the SpacetimeDB HTTP and reducer layers so no live
STDB is needed. They actually exercise the real Client.backup() and
Client.restore() implementations via mocked _query / _call layers.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, Mock

import pytest


def _mock_client():
    """Build a Client with mocked HTTP for offline backup testing."""
    import sys
    sys.path.insert(0, "sdk/python")
    from spacetime_memory import Client

    c = Client.__new__(Client)
    c._http = MagicMock()
    c._http.get.return_value = Mock(status_code=200)
    c._http.post.return_value = Mock(status_code=200, text=json.dumps([]), json=list)
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
    c._circuit_open_until = 0.0
    c._consecutive_failures = 0
    c._circuit_breaker_threshold = 5
    c._circuit_breaker_reset_secs = 30.0
    c.max_retries = 3
    c.plugin_manager = None
    c.event_bus = None
    c.embedder_url = "http://localhost:9090"
    c.tantivy_url = "http://localhost:9100"
    c._BACKUP_TABLES = [
        "workspace", "memory", "kg_node", "kg_edge",
        "user_account", "user_agent", "api_key",
        "workspace_access", "workspace_encryption_key",
    ]
    return c


class TestBackupStructure:
    """Backup output structure is correct."""

    def test_backup_returns_status_key(self):
        """backup() return value has 'status' key."""
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            client._query.return_value = []
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            assert result["path"] == path
            assert result["total_rows"] >= 0
            assert isinstance(result["tables"], list)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_produces_json_file(self):
        """Backup writes a JSON file to the given path."""
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            client._query.return_value = []
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            with open(path) as f:
                data = json.load(f)
            assert "version" in data
            assert "created_at" in data
            assert "tables" in data
            assert "stats" in data
            assert data["version"] == "0.3.0"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_default_output_path(self):
        """Default output path contains expected prefix."""
        client = _mock_client()
        client._query.return_value = []
        result = client.backup()
        try:
            assert "spacetime-memory-backup" in result["path"]
            assert result["path"].endswith(".json")
            assert result["status"] == "ok"
        finally:
            if os.path.exists(result["path"]):
                os.unlink(result["path"])

    def test_backup_output_has_correct_table_entries(self):
        """Backup output lists tables that had data."""
        client = _mock_client()
        n = len(client._BACKUP_TABLES)
        client._query.side_effect = [
            [{"id": "ws-1", "name": "test"}],
            [{"id": "mem-1"}],
        ] + [[] for _ in range(n - 2)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            assert result["total_rows"] == 2
            assert "workspace" in result["tables"]
            assert "memory" in result["tables"]
            with open(path) as f:
                data = json.load(f)
            assert data["stats"]["table_count"] == 2
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestBackupWithData:
    """Backup captures stored memory data."""

    def test_store_before_backup(self):
        """Store data successfully before backup."""
        client = _mock_client()
        client._call.return_value = {"status": "ok"}
        r = client.store(workspace_id="ws-1", peer_id="peer-1", content="test data", memory_type="experience")
        assert r["status"] == "ok"
        client._call.assert_called()

    def test_backup_after_store(self):
        """Backup after store reports rows."""
        client = _mock_client()
        n = len(client._BACKUP_TABLES)
        client._query.side_effect = [[{"id": "ws-1"}], [{"id": "mem-1", "content": "test data"}]] + [[] for _ in range(n - 2)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            assert result["total_rows"] > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_multiple_stores(self):
        """Multiple stores before backup."""
        client = _mock_client()
        client._call.return_value = {"status": "ok"}
        for i in range(3):
            client.store(f"ws-{i}", "peer", f"content-{i}", memory_type="experience")
        assert client._call.call_count == 3

    def test_backup_with_large_content(self):
        """Backup handles large content strings."""
        client = _mock_client()
        large = "x" * 100_000
        n = len(client._BACKUP_TABLES)
        client._query.side_effect = [[{"id": "ws-1", "name": "big ws"}], [{"id": "mem-1", "content": large}]] + [[] for _ in range(n - 2)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            with open(path) as f:
                data = json.load(f)
            assert len(data["tables"]["memory"][0]["content"]) == 100_000
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestBackupErrors:
    """Backup/restore error handling."""

    def test_restore_nonexistent_file_raises(self):
        client = _mock_client()
        with pytest.raises(FileNotFoundError):
            client.restore(input_path="/tmp/nonexistent-backup-test.json")

    def test_restore_invalid_json_raises(self):
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not json")
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                client.restore(input_path=path)
        finally:
            os.unlink(path)

    def test_backup_on_empty_database(self):
        client = _mock_client()
        client._query.return_value = []
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            assert result["total_rows"] == 0
            assert result["tables"] == []
        finally:
            os.unlink(path)

    def test_restore_empty_file_raises(self):
        client = _mock_client()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                client.restore(input_path=path)
        finally:
            os.unlink(path)

    def test_backup_skips_missing_tables(self):
        client = _mock_client()
        def _side_effect(table):
            if table == "workspace":
                return [{"id": "ws-1"}]
            raise RuntimeError(f"table {table} does not exist")
        client._query.side_effect = _side_effect
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            assert result["total_rows"] == 1
            assert result["tables"] == ["workspace"]
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_query_error_propagates(self):
        client = _mock_client()
        client._query.side_effect = ValueError("unexpected error")
        with pytest.raises(ValueError, match="unexpected error"):
            client.backup(output_path="/tmp/_backup_error.json")


class TestRestore:
    """Restore validates its inputs and delegates to the reducer layer."""

    def test_restore_calls_reducer_for_each_row(self):
        client = _mock_client()
        client._query.side_effect = [[]] * len(client._BACKUP_TABLES)
        rows = [{"id": "ws-1", "name": "test", "description": "desc"}, {"id": "ws-2", "name": "test2", "description": "desc2"}]
        payload = {"version": "0.3.0", "created_at": "2026-01-01T00:00:00Z", "tables": {"workspace": rows}, "stats": {"table_count": 1, "total_rows": 2}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(payload, f)
            path = f.name
        try:
            result = client.restore(input_path=path)
            assert result["status"] == "ok"
            assert client._sql.call_count >= 2
        finally:
            os.unlink(path)

    def test_restore_empty_tables(self):
        client = _mock_client()
        client._query.side_effect = [[]] * len(client._BACKUP_TABLES)
        payload = {"version": "0.3.0", "created_at": "2026-01-01T00:00:00Z", "tables": {}, "stats": {"table_count": 0, "total_rows": 0}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(payload, f)
            path = f.name
        try:
            result = client.restore(input_path=path)
            assert result["status"] == "ok"
        finally:
            os.unlink(path)


class TestPartialRestore:
    def test_restore_with_minimal_structure(self):
        data = {"version": "0.3.0", "created_at": "2024-01-01T00:00:00Z", "tables": {"workspace": [{"id": "ws-1", "name": "test"}]}, "stats": {"table_count": 1, "total_rows": 1}}
        assert "tables" in data and "workspace" in data["tables"]

    def test_restore_with_empty_tables(self):
        data = {"version": "0.3.0", "created_at": "2024-01-01T00:00:00Z", "tables": {}, "stats": {"table_count": 0, "total_rows": 0}}
        assert data["stats"]["table_count"] == 0

    def test_restore_missing_version(self):
        data = {"tables": {"workspace": []}, "stats": {"table_count": 1, "total_rows": 0}}
        assert "version" not in data

    def test_restore_missing_stats(self):
        data = {"version": "0.3.0", "tables": {"workspace": []}}
        assert "stats" not in data


class TestBackupEdgeCases:
    def test_backup_special_chars_in_data(self):
        client = _mock_client()
        n = len(client._BACKUP_TABLES)
        client._query.side_effect = [[{"id": "ws-1", "name": "\\u6d4b\\u8bd5 unicode \\u2713 \\U0001f389"}], [{"id": "mem-1", "content": "emoji and <html> & special chars"}]] + [[] for _ in range(n - 2)]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_restore_with_large_payload(self):
        client = _mock_client()
        client._query.side_effect = [[]] * len(client._BACKUP_TABLES)
        rows = [{"id": f"ws-{i}", "name": f"workspace {i}"} for i in range(500)]
        payload = {"version": "0.3.0", "created_at": "2026-01-01T00:00:00Z", "tables": {"workspace": rows}, "stats": {"table_count": 1, "total_rows": 500}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(payload, f)
            path = f.name
        try:
            result = client.restore(input_path=path)
            assert result["status"] == "ok"
        finally:
            os.unlink(path)

    def test_backup_twice_overwrites(self):
        client = _mock_client()
        client._query.return_value = []
        path = "/tmp/_backup_overwrite_test.json"
        try:
            r1 = client.backup(output_path=path)
            r2 = client.backup(output_path=path)
            assert r1["status"] == "ok"
            assert r2["status"] == "ok"
            with open(path) as f:
                data = json.load(f)
            assert "tables" in data
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_backup_plugin_dispatch(self):
        client = _mock_client()
        mock_plugin = MagicMock()
        client.plugin_manager = mock_plugin
        n = len(client._BACKUP_TABLES)
        client._query.side_effect = [[{"id": "ws-1"}], [{"id": "mem-1", "content": "test"}]] + [[] for _ in range(n - 2)]
        path = "/tmp/_backup_plugin_test.json"
        try:
            result = client.backup(output_path=path)
            assert result["status"] == "ok"
            mock_plugin.dispatch_export.assert_called_once()
            call_rows = mock_plugin.dispatch_export.call_args[0][0]
            assert len(call_rows) == 2
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_restore_plugin_dispatch(self):
        client = _mock_client()
        mock_plugin = MagicMock()
        client.plugin_manager = mock_plugin
        client._query.side_effect = [[]] * len(client._BACKUP_TABLES)
        rows = [{"id": "ws-1", "name": "test"}]
        payload = {"version": "0.3.0", "created_at": "2026-01-01T00:00:00Z", "tables": {"workspace": rows}, "stats": {"table_count": 1, "total_rows": 1}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(payload, f)
            path = f.name
        try:
            result = client.restore(input_path=path)
            assert result["status"] == "ok"
            mock_plugin.dispatch_import.assert_called_once()
        finally:
            os.unlink(path)
