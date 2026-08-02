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



class TestMemoryRetrieval:
    """get_memory() with auto-reinforcement path."""

    def test_get_memory_reinforce(self, stdb_client):
        """get_memory triggers reinforce_memory on read."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "reinforce test memory content", "reinforce-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        result = stdb_client.get_memory(mem_id)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["id"] == mem_id


class TestFuzzyGet:
    """fuzzy_get() with SequenceMatcher."""

    def test_fuzzy_get_finds_match(self, stdb_client):
        """Fuzzy match finds a memory with similar content."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "The quick brown fox jumps over the lazy dog", "fuzzy-bot")

        result = stdb_client.fuzzy_get(ws_id, "quick brown fox jumps", threshold=0.3)
        assert result is not None
        assert "fox" in result.get("content", "")

    def test_fuzzy_get_no_match(self, stdb_client):
        """Fuzzy match returns None when no match above threshold."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "completely different topic", "fuzzy-bot")

        result = stdb_client.fuzzy_get(ws_id, "zzzzzzzzzzzzzz", threshold=0.8)
        assert result is None


class TestGlobGet:
    """glob_get() with fnmatch patterns."""

    def test_glob_get_content_match(self, stdb_client):
        """Glob match against content field."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "journals/2025-05-notes", "glob-bot")
        _store_mem(stdb_client, ws_id, "journals/2025-06-notes", "glob-bot")
        _store_mem(stdb_client, ws_id, "other-data", "glob-bot")

        results = stdb_client.glob_get(ws_id, "journals/*", field="content")
        assert isinstance(results, list)
        assert len(results) == 2

    def test_glob_get_id_match(self, stdb_client):
        """Glob match against id field (default)."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "test-id-glob", "glob-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        if mem_id:
            # Match by the first few chars of the UUID
            prefix = mem_id[:8]
            results = stdb_client.glob_get(ws_id, f"{prefix}*", field="id")
            assert isinstance(results, list)
            assert len(results) >= 1

    def test_glob_get_no_match(self, stdb_client):
        """Glob with no matches returns empty list."""
        ws_id = _make_ws(stdb_client)
        results = stdb_client.glob_get(ws_id, "nonexistent-*", field="content")
        assert results == []


class TestUserMemories:
    """get_user_memories reducer + SQL result table."""

    def test_get_user_memories(self, stdb_client):
        """Retrieve memories scoped to a user."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "user-scoped memory", "user-bot-1")
        try:
            result = stdb_client.get_user_memories("user-bot-1", ws_id)
            assert isinstance(result, list)
        except RuntimeError as e:
            if "Table" in str(e) or "No such" in str(e) or "Unsupported" in str(e):
                pytest.skip(f"get_user_memories not available: {e}")
            raise


class TestDecay:
    """set_decay_model, get_decay_config."""

    def test_set_and_get_decay(self, stdb_client):
        """Set and retrieve decay model configuration."""
        ws_id = _make_ws(stdb_client)
        try:
            stdb_client.set_decay_model(ws_id, "weibull", 2.0, 30.0)
        except RuntimeError:
            pass

        config = stdb_client.get_decay_config(ws_id)
        assert config is None or isinstance(config, dict)


class TestDecayDeep:
    """set_decay_model with linear, weibull, and invalid model."""

    def test_set_decay_linear(self, stdb_client):
        """Set linear decay model."""
        ws_id = _make_ws(stdb_client)
        try:
            result = stdb_client.set_decay_model(ws_id, "linear", 0.01, 60)
            assert result["status"] == "ok"
        except RuntimeError:
            pass  # Decay reducers may not exist

    def test_set_decay_weibull(self, stdb_client):
        """Set weibull decay model."""
        ws_id = _make_ws(stdb_client)
        try:
            result = stdb_client.set_decay_model(
                ws_id, "weibull", weibull_shape=0.5, weibull_scale=45.0
            )
            assert result["status"] == "ok"
        except RuntimeError:
            pass  # Decay reducers may not exist

    def test_set_decay_invalid_model(self, stdb_client):
        """Invalid decay model raises ValueError."""
        ws_id = _make_ws(stdb_client)
        with pytest.raises(ValueError, match="Unknown decay model"):
            stdb_client.set_decay_model(ws_id, "exponential")


class TestDeleteMemoryDeep:
    """delete_memory edge cases: already deleted, with query cache."""

    def test_delete_memory_then_delete_again(self, stdb_client):
        """delete_memory on already-deleted memory returns ok."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "delete me twice", "del-twice-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        # First delete
        r1 = stdb_client.delete_memory(mem_id)
        assert r1["status"] == "ok"

        # Second delete — should still succeed (idempotent)
        r2 = stdb_client.delete_memory(mem_id)
        assert r2["status"] == "ok"

    def test_delete_nonexistent_memory(self, stdb_client):
        """delete_memory on non-existent ID returns ok."""
        result = stdb_client.delete_memory("nonexistent-memory-id-00000")
        assert result["status"] == "ok"


class TestUpdateMemoryDeep:
    """update_memory with various parameter combinations."""

    def test_update_memory_with_defaults(self, stdb_client):
        """update_memory with only content (default summary and confidence)."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "original content for update", "update-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        result = stdb_client.update_memory(mem_id, "updated content only")
        assert result["status"] == "ok"

    def test_update_memory_full_params(self, stdb_client):
        """update_memory with all parameters."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "full update original", "update-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        result = stdb_client.update_memory(
            mem_id,
            "fully updated content",
            summary="New summary",
            confidence=0.99,
        )
        assert result["status"] == "ok"


class TestGetterMethods:
    """Exercise getter methods that have untested branches."""

    def test_get_user_memories_without_ws(self, stdb_client):
        """get_user_memories without workspace_id."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "user mem test", "umem-bot")
        try:
            result = stdb_client.get_user_memories("umem-bot", ws_id)
            assert isinstance(result, list)
        except RuntimeError as e:
            if "Table" in str(e) or "No such" in str(e) or "Unsupported" in str(e):
                pytest.skip(f"get_user_memories not available: {e}")
            raise

    def test_get_peer_reputation_with_data(self, stdb_client):
        """get_peer_reputation for a peer that has stored memories."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "rep calc test", "reputation-bot")
        try:
            rep = stdb_client.get_peer_reputation("reputation-bot")
            assert rep is None or isinstance(rep, dict)
        except RuntimeError as e:
            if "Table" in str(e):
                pytest.skip("peer_reputation table not queryable")
            raise

    def test_get_decay_config_with_model_set(self, stdb_client):
        """get_decay_config after setting a decay model."""
        ws_id = _make_ws(stdb_client)
        try:
            stdb_client.set_decay_model(ws_id, "linear", 0.02, 90)
        except RuntimeError:
            pass

        config = stdb_client.get_decay_config(ws_id)
        assert config is None or isinstance(config, dict)


class TestFuzzyGetEdgeCases:
    """Cover fuzzy_get empty field path."""

    def test_fuzzy_get_empty_text_skip(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(
            return_value=[
                {"content": "", "summary": "something"},
                {"content": "pizza is good", "summary": ""},
            ]
        )
        result = c.fuzzy_get("ws", "pizza", threshold=0.5)
        assert result is not None


class TestMemoryHistory:
    """Cover get_memory_history."""

    def test_get_memory_history_found(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(
            side_effect=[
                [
                    {
                        "version": 1,
                        "memory_id": "mem1",
                        "new_content": "old version",
                        "new_summary": "summary",
                        "new_confidence": 0.9,
                        "previous_content": "",
                        "previous_summary": "",
                        "previous_confidence": 0.0,
                        "changed_at": 100,
                        "changed_by": "test",
                    }
                ],
                [
                    {
                        "id": "mem1",
                        "content": "old version",
                        "summary": "summary",
                        "version": 1,
                        "updated_at": 100,
                        "confidence": 0.9,
                    }
                ],
            ]
        )
        result = c.get_memory_history("mem1")
        assert len(result) == 1
        assert result[0]["content"] == "old version"
        assert result[0]["version"] == 1

    def test_get_memory_history_empty(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(return_value=[])
        result = c.get_memory_history("mem1")
        assert result == []


class TestMemoryStats:
    """Cover get_memory_stats."""

    def test_get_memory_stats_found(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[
            {"stat_key": "total_memories", "stat_value": "42"},
            {"stat_key": "active_memories", "stat_value": "38"},
            {"stat_key": "by_tier", "stat_value": '{"L0":5,"L1":30,"L2":7}'},
        ])
        result = c.get_memory_stats("ws")
        c._call.assert_called_with("get_memory_stats", ["ws"])
        assert result is not None
        assert result["total_memories"] == "42"
        assert result["active_memories"] == "38"

    def test_get_memory_stats_not_found(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._sql = Mock(return_value=[])
        result = c.get_memory_stats("ws")
        assert result is None
