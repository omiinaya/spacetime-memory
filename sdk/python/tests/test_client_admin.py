"""Unit tests for AdminMixin — admin operations, tours, connectors, encryption, etc.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

import json
from unittest.mock import patch


class TestAdminMixin:
    """AdminMixin methods (maintenance, notes, tours, connectors, encryption, backup, etc.)."""

    # --- Maintenance ---

    def test_run_maintenance(self, mock_http_client):
        result = mock_http_client.run_maintenance()
        assert result == {"status": "ok"}

    def test_expire_memories(self, mock_http_client):
        result = mock_http_client.expire_memories()
        assert result == {"status": "ok"}

    def test_dedup(self, mock_http_client):
        result = mock_http_client.dedup("ws-1")
        assert result == {"status": "ok"}

    def test_dedup_memories_delegates(self, mock_http_client):
        """dedup_memories delegates to dedup (same reducer)."""
        result = mock_http_client.dedup_memories("ws-1")
        assert result == {"status": "ok"}

    def test_consolidate_memories(self, mock_http_client):
        result = mock_http_client.consolidate_memories(
            "ws-1", ["m1", "m2"], "merged content", "merged summary"
        )
        assert result == {"status": "ok"}

    def test_suggest_merges_default_threshold(self, mock_http_client):
        result = mock_http_client.suggest_merges("ws-1")
        assert result == {"status": "ok"}

    def test_suggest_merges_custom_threshold(self, mock_http_client):
        result = mock_http_client.suggest_merges("ws-1", threshold=0.9)
        assert result == {"status": "ok"}

    def test_approve_merge(self, mock_http_client):
        result = mock_http_client.approve_merge("sug-1")
        assert result == {"status": "ok"}

    def test_reject_merge(self, mock_http_client):
        result = mock_http_client.reject_merge("sug-1")
        assert result == {"status": "ok"}

    # --- Tours ---

    def test_create_tour(self, mock_http_client):
        result = mock_http_client.create_tour("ws-1", "My Tour", "A guided tour")
        assert result is None

    def test_add_tour_stop(self, mock_http_client):
        result = mock_http_client.add_tour_stop("tour-1", "node-1", "Welcome")
        assert result is None

    def test_delete_tour(self, mock_http_client):
        result = mock_http_client.delete_tour("tour-1")
        assert result is None

    def test_delete_tour_stop(self, mock_http_client):
        result = mock_http_client.delete_tour_stop("stop-1")
        assert result is None

    # --- Connector registration ---

    def test_register_connector(self, mock_http_client):
        result = mock_http_client.register_connector(
            "My Connector", "webhook", '{"port": 8080}', "ws-1", 60
        )
        assert result is None

    def test_update_connector(self, mock_http_client):
        result = mock_http_client.update_connector(
            "conn-1", "My Connector", "webhook", '{"port": 8081}', "ws-1", 120, True
        )
        assert result is None

    def test_delete_connector(self, mock_http_client):
        result = mock_http_client.delete_connector("conn-1")
        assert result is None

    # --- Entity extraction ---

    def test_extract_entities(self, mock_http_client):
        result = mock_http_client.extract_entities("ws-1", "Alice works at Acme Corp")
        assert result is None

    # --- Entity links ---

    def test_create_entity_link(self, mock_http_client):
        result = mock_http_client.create_entity_link("ws-1", "Acme Corp", "organization", "A company")
        assert result is None

    def test_add_alias(self, mock_http_client):
        result = mock_http_client.add_alias("el-1", "Acme")
        assert result is None

    def test_resolve_entity(self, mock_http_client):
        result = mock_http_client.resolve_entity("ws-1", "Acme Corp")
        assert result is None

    # --- Encryption ---

    def test_init_workspace_encryption(self, mock_http_client):
        result = mock_http_client.init_workspace_encryption("ws-1")
        assert result == {"status": "ok"}

    def test_set_workspace_encryption_enabled(self, mock_http_client):
        result = mock_http_client.set_workspace_encryption_enabled("ws-1", True)
        assert result == {"status": "ok"}

    def test_rotate_workspace_encryption_key(self, mock_http_client):
        result = mock_http_client.rotate_workspace_encryption_key("ws-1")
        assert result == {"status": "ok"}

    def test_encrypt_existing_memories(self, mock_http_client):
        result = mock_http_client.encrypt_existing_memories("ws-1")
        assert result == {"status": "ok"}

    def test_get_decrypted_memory(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[{"content": "decrypted content"}]):
            result = mock_http_client.get_decrypted_memory("mem-1")
        assert result == {"content": "decrypted content"}

    def test_get_decrypted_memory_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_decrypted_memory("mem-1")
        assert result == {}

    # --- Backup & Restore ---

    def test_backup(self, mock_http_client, tmp_path):
        """backup() writes JSON file and returns correct metadata."""
        with patch.object(mock_http_client, "_query", return_value=[]):
            output = tmp_path / "backup.json"
            result = mock_http_client.backup(output_path=str(output))
        assert result["status"] == "ok"
        assert result["path"] == str(output)
        assert output.exists()
        with open(output) as f:
            payload = json.load(f)
        assert "tables" in payload
        assert payload["version"] == "0.3.0"

    def test_backup_with_data(self, mock_http_client, tmp_path):
        """backup() includes table data."""
        def _query_side(table, **kw):
            return [{"id": "r1", "name": "test"}] if table == "workspace" else []
        with patch.object(mock_http_client, "_query", side_effect=_query_side):
            output = tmp_path / "backup2.json"
            result = mock_http_client.backup(output_path=str(output))
        assert result["total_rows"] == 1

    def test_backup_default_path(self, mock_http_client):
        """backup() generates default path when none given."""
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.backup()
        assert result["status"] == "ok"
        assert result["path"].startswith("spacetime-memory-backup-")

    def test_restore(self, mock_http_client, tmp_path):
        """restore() reads a backup JSON and returns metadata."""
        backup = tmp_path / "restore_test.json"
        backup.write_text(
            json.dumps(
                {
                    "version": "0.3.0",
                    "created_at": "2026-01-01T00:00:00",
                    "tables": {
                        "workspace": [{"id": "ws-1", "name": "Test"}],
                        "memory": [],
                    },
                    "stats": {"table_count": 2, "total_rows": 1},
                }
            )
        )
        with patch.object(mock_http_client, "_sql", return_value=[]):
            result = mock_http_client.restore(str(backup))
        assert result["status"] == "ok"
        assert "total_rows" in result
        assert "tables" in result

    # --- Harmonic beliefs ---

    def test_store_harmonic_beliefs(self, mock_http_client):
        result = mock_http_client.store_harmonic_beliefs(
            "ws-1", "peer-1", '[{"belief": "test"}]', "cluster-1"
        )
        assert result is None

    def test_clear_harmonic_beliefs(self, mock_http_client):
        result = mock_http_client.clear_harmonic_beliefs("ws-1", 0.5)
        assert result is None

    def test_log_resonance_session(self, mock_http_client):
        result = mock_http_client.log_resonance_session(
            "ws-1", "peer-1", 5, 10, 2, 0.85, 1200
        )
        assert result is None

    # --- Context packs ---

    def test_store_context_pack(self, mock_http_client):
        result = mock_http_client.store_context_pack(
            "ws-1", "My Pack", ["mem-1", "mem-2"], "context text"
        )
        assert result == {"status": "ok"}

    def test_remove_tour_stop(self, mock_http_client):
        result = mock_http_client.remove_tour_stop("stop-1")
        assert result == {"status": "ok"}

    # --- Decay ---

    def test_decay_weak_memories(self, mock_http_client):
        result = mock_http_client.decay_weak_memories("ws-1", decay_rate=0.5, threshold=0.1)
        assert result == {"status": "ok"}

    def test_admin_deactivate_account(self, mock_http_client):
        result = mock_http_client.admin_deactivate_account("identity-hex")
        assert result == {"status": "ok"}

    def test_delete_api_key(self, mock_http_client):
        result = mock_http_client.delete_api_key("key-1")
        assert result == {"status": "ok"}

    def test_manual_decay(self, mock_http_client):
        result = mock_http_client.manual_decay("ws-1", '["mem-1", "mem-2"]')
        assert result == {"status": "ok"}
