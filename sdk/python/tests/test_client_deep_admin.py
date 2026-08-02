"""Deep integration tests for client.py — Advanced module.

Includes: ParseRerankJson, ParseSqlResponse, ProfilesWithPeers,
MemoryRetrieval, FuzzyGet, GlobGet, UserMemories, Decay, DecayDeep,
PluginDispatch, GraphTraversalDeep, GraphStatsDeep, AdminDeep,
GraphNeighborsDeep, QueryHash, ParseRerankJsonDeep,
ParseRerankJsonFinal, DeleteMemoryDeep, UpdateMemoryDeep,
GetterMethods, ClientUnitCoverage, SearchWithFilters,
SearchSessionsSemantic, Recommend, TestDecay,
SearchWithFiltersUnit, ConfigAndReputation, KgStats, MemoryStats,
DirectoryOps, NoteEmbedOps, NoteBacklinks, SessionListing,
ListProfiles, ApiKeyCreate, FuzzyGetEdgeCases, MemoryHistory,
BatchEmbedError, CreateNodeEmbed, RerankerErrorHandling,
QueryCacheInvalidation, TantivyAndHealthCheck, RestoreManifest,
and standalone functions.
"""

from __future__ import annotations

import json
import os
from unittest.mock import Mock

import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]


def _unique(prefix: str = "deep") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Helper: create a unique workspace and return its ID."""
    ws_name = _unique("deep-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for w in workspaces:
        if w.get("name") == ws_name:
            return w["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


def _store_mem(client: Client, ws_id: str, content: str, peer: str = "deep-bot") -> dict:
    """Store a memory and return the result."""
    return client.store(
        workspace_id=ws_id,
        content=content,
        peer_id=peer,
        memory_type="experience",
    )


def _get_first_memory_id(client: Client, ws_id: str) -> str | None:
    """Get the ID of the first memory in a workspace."""
    mems = client.list_memories(workspace_id=ws_id, limit=5)
    return mems[0]["id"] if mems else None



class TestPluginDispatch:
    """Test backup() and restore() with a PluginManager attached."""

    @pytest.fixture
    def plugin_client(self, stdb_session):
        """Create a Client with a real PluginManager and a spy plugin."""
        from spacetime_memory.plugin_manager import BasePlugin, PluginManager

        class SpyPlugin(BasePlugin):
            name = "spy"
            version = "1.0.0"

            def __init__(self):
                super().__init__()
                self.export_calls: list[list[dict]] = []
                self.import_calls: list[list[dict]] = []

            def on_export(self, data):
                self.export_calls.append(list(data))
                return data

            def on_import(self, data):
                self.import_calls.append(list(data))
                return data

        pm = PluginManager()
        spy = SpyPlugin()
        pm.register(spy)

        c = Client(
            host=stdb_session["host"],
            port=stdb_session["port"],
            database=stdb_session["database"],
            plugin_manager=pm,
        )
        # Register and self-promote to admin
        import os

        suffix = os.urandom(4).hex()
        uname = f"plugin_{suffix}"
        try:
            c._call("register", [uname, "Plugin User", "testpass"])
        except RuntimeError:
            pass
        my_id = c._whoami()
        if my_id:
            try:
                c._call("set_initial_admin", [my_id])
            except RuntimeError:
                pass

        c._spy = spy
        return c

    def test_backup_dispatches_to_plugin(self, plugin_client, tmp_path):
        """backup() calls plugin_manager.dispatch_export()."""
        ws_id = _make_ws(plugin_client)
        _store_mem(plugin_client, ws_id, "plugin backup test memory")

        backup_path = tmp_path / "plugin_backup.json"
        result = plugin_client.backup(str(backup_path))
        assert result["status"] == "ok"

        # The spy plugin should have received export data
        spy = plugin_client._spy
        assert len(spy.export_calls) >= 1
        exported = spy.export_calls[0]
        assert isinstance(exported, list)
        # At least the memory we stored should be in the exported data
        contents = [r.get("content", "") for r in exported]
        assert any("plugin backup test memory" in c for c in contents), (
            f"Exported data didn't contain test memory: {contents[:5]}"
        )

    def test_restore_dispatches_to_plugin(self, plugin_client, tmp_path):
        """restore() calls plugin_manager.dispatch_import()."""
        ws_id = _make_ws(plugin_client)
        _store_mem(plugin_client, ws_id, "plugin restore test memory")

        backup_path = tmp_path / "plugin_restore.json"
        plugin_client.backup(str(backup_path))

        # Reset spy call tracking after backup
        plugin_client._spy.import_calls.clear()

        try:
            plugin_client.restore(str(backup_path))
        except RuntimeError:
            pass  # Duplicates expected

        spy = plugin_client._spy
        assert len(spy.import_calls) >= 1
        imported = spy.import_calls[0]
        assert isinstance(imported, list)


class TestAdminDeep:
    """Deeper admin operations: escalate with real data, maintenance,
    dedup with similar content."""

    def test_escalate_memories_with_multiple_tiers(self, stdb_client):
        """escalate_memories with memories at different tiers."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "L0 tier memory A", "esc-deep-bot")
        _store_mem(stdb_client, ws_id, "L0 tier memory B", "esc-deep-bot")
        _store_mem(stdb_client, ws_id, "L0 tier memory C", "esc-deep-bot")

        try:
            result = stdb_client.escalate_memories(ws_id, l2_to_l1=3, l1_to_l0=10)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access not configured for this test user")
            raise

    def test_run_maintenance_after_operations(self, stdb_client):
        """run_maintenance after creating some workspaces and memories."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "maintenance test data")

        try:
            result = stdb_client.run_maintenance()
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise

    def test_dedup_with_similar_memories(self, stdb_client):
        """dedup with nearly identical memories."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "The cat sat on the mat")
        _store_mem(stdb_client, ws_id, "The cat sat on the mat.")
        _store_mem(stdb_client, ws_id, "The cat sat on the mat!")

        try:
            result = stdb_client.dedup(ws_id)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise


class TestConfigAndReputation:
    """Cover get_workspace_config and get_peer_reputation."""

    def test_get_decay_config_found(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(return_value=[{"id": "ws", "decay_model": "linear"}])
        result = c.get_decay_config("ws")
        assert result == {"id": "ws", "decay_model": "linear"}

    def test_get_decay_config_not_found(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(return_value=[])
        result = c.get_decay_config("ws")
        assert result is None

    def test_get_peer_reputation_found(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock()
        c._query = Mock(return_value=[{"id": "uuid-1", "peer_id": "peer1", "reputation_score": 0.85}])
        result = c.get_peer_reputation("peer1")
        c._call.assert_any_call("get_peer_reputation", ["peer1"])
        assert result == {"id": "uuid-1", "peer_id": "peer1", "reputation_score": 0.85}

    def test_get_peer_reputation_not_found(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock()
        c._query = Mock(return_value=[])
        result = c.get_peer_reputation("peer1")
        c._call.assert_any_call("get_peer_reputation", ["peer1"])
        assert result is None


class TestRestoreManifest:
    """Cover restore() edge cases: empty first row, NULL values, RuntimeError skip."""

    def test_restore_empty_and_null_handling(self, tmp_path):
        """Cover lines 2710 (falsy rows[0]), 2719 (NULL value append),
        and 2733-2734 (outer except Exception skip)."""

        manifest = {
            "tables": {
                "empty_table": [],  # hits line 2708
                "none_first": [None, {"col": "x"}],  # hits line 2710
                "valid_table": [{"col1": "val1", "col2": None}],  # hits line 2719
                "bad_table": [
                    {"col": "v"},
                    "not a dict",
                ],  # 2nd row has no .keys() → AttributeError → hits 2733
            }
        }
        backup_path = tmp_path / "backup.json"
        backup_path.write_text(json.dumps(manifest))

        c = Client(host="localhost", port=3001)
        c._identity_established = True  # skip live identity handshake (no real STDB)
        c._http = Mock()
        c._http.post.return_value = Mock(status_code=200, text="[]")
        result = c.restore(str(backup_path))
        assert result["status"] == "ok"
        assert "valid_table" in result["tables"]
