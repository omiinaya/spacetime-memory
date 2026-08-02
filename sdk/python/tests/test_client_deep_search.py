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



class TestSearchWithFilters:
    """search_with_filters method."""

    def test_search_with_filters(self, stdb_client):
        """Search with metadata/location filters."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "filtered search test alpha", "filt-bot")

        results = stdb_client.search_with_filters(
            workspace_id=ws_id,
            query="filtered search",
            memory_type="experience",
        )
        assert isinstance(results, list)


class TestSearchSessionsSemantic:
    """search_sessions_semantic method."""

    def test_search_sessions_semantic(self, stdb_client):
        """Semantically search across sessions. Falls back to empty
        when no embedder is available."""
        results = stdb_client.search_sessions_semantic("test query", limit=5)
        assert isinstance(results, list)


class TestRecommend:
    """recommend_memories, get_peer_reputation."""

    def test_recommend_memories(self, stdb_client):
        """Get memory recommendations."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "recommend test memory A", "rec-bot")
        _store_mem(stdb_client, ws_id, "recommend test memory B", "rec-bot")
        try:
            result = stdb_client.recommend_memories(ws_id, limit=5)
            assert isinstance(result, list)
        except RuntimeError as e:
            if "Table" in str(e):
                pytest.skip("memory_recommendation table not queryable")
            raise

    def test_get_peer_reputation(self, stdb_client):
        """Get peer reputation score."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "reputation test", "rep-bot")
        try:
            rep = stdb_client.get_peer_reputation("rep-bot")
            assert rep is None or isinstance(rep, dict)
        except RuntimeError as e:
            if "Table" in str(e):
                pytest.skip("peer_reputation table not queryable")
            raise


class TestSearchWithFiltersUnit:
    """Cover search_with_filters metadata and location filter paths."""

    def test_metadata_filter_matching(self):
        """Metadata filter: rows with matching metadata_json get included."""

        c = Client(host="localhost", port=3001)
        c.search = Mock(
            return_value=[
                {"content": "hello world", "metadata_json": '{"key": "val"}'},
                {"content": "other", "metadata_json": '{"key": "other_val"}'},
            ]
        )
        result = c.search_with_filters("ws", query="test", metadata_filter='{"key": "val"}')
        assert len(result) == 1
        assert result[0]["content"] == "hello world"

    def test_metadata_filter_invalid_json(self):
        """Metadata filter: invalid metadata_json gracefully falls back to {}."""

        c = Client(host="localhost", port=3001)
        c.search = Mock(
            return_value=[
                {"content": "hello world", "metadata_json": "not json"},
                {"content": "other", "metadata_json": '{"key": "val"}'},
            ]
        )
        result = c.search_with_filters("ws", query="test", metadata_filter='{"key": "val"}')
        # "not json" row has empty metadata → won't match {"key":"val"}
        assert len(result) == 1
        assert result[0]["content"] == "other"

    def test_metadata_filter_dict_input(self):
        """Metadata filter: dict input (not string) works directly."""

        c = Client(host="localhost", port=3001)
        c.search = Mock(
            return_value=[
                {"content": "hello", "metadata_json": '{"tag": "greeting"}'},
            ]
        )
        result = c.search_with_filters("ws", query="test", metadata_filter={"tag": "greeting"})
        assert len(result) == 1

    def test_location_filter(self):
        """Location filter: case-insensitive substring match on content/summary."""

        c = Client(host="localhost", port=3001)
        c.search = Mock(
            return_value=[
                {"content": "Paris is beautiful", "summary": "France"},
                {"content": "London bridge", "summary": "UK"},
            ]
        )
        result = c.search_with_filters("ws", query="test", location_filter="paris")
        assert len(result) == 1
        assert "Paris" in result[0]["content"]

    def test_location_filter_in_summary(self):
        """Location filter matches against summary field too."""

        c = Client(host="localhost", port=3001)
        c.search = Mock(
            return_value=[
                {"content": "Data center", "summary": "Tokyo facility"},
            ]
        )
        result = c.search_with_filters("ws", query="test", location_filter="tokyo")
        assert len(result) == 1

    def test_combined_filters(self):
        """Both metadata and location filters applied."""

        c = Client(host="localhost", port=3001)
        c.search = Mock(
            return_value=[
                {
                    "content": "Paris cafe",
                    "summary": "France visit",
                    "metadata_json": '{"tag": "food"}',
                },
                {
                    "content": "Paris museum",
                    "summary": "France culture",
                    "metadata_json": '{"tag": "art"}',
                },
                {"content": "London pub", "summary": "UK food", "metadata_json": '{"tag": "food"}'},
            ]
        )
        result = c.search_with_filters(
            "ws", query="test", metadata_filter='{"tag": "food"}', location_filter="paris"
        )
        assert len(result) == 1
        assert "cafe" in result[0]["content"]
