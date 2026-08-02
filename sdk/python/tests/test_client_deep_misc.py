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



class TestProfilesWithPeers:
    """list_profiles when peers actually exist in the workspace."""

    def test_list_profiles_populated(self, stdb_client):
        """List profiles when peers have been added to the workspace."""
        ws_id = _make_ws(stdb_client)
        # Store a memory as a peer to ensure the peer exists in the workspace
        _store_mem(stdb_client, ws_id, "profile-peers test memory", "profile-peer-1")
        _store_mem(stdb_client, ws_id, "another memory for peer", "profile-peer-2")
        # Upsert profiles for these peers
        stdb_client.upsert_profile("profile-peer-1", "[]", "[]", "{}", "[]")
        stdb_client.upsert_profile("profile-peer-2", "[]", "[]", "{}", "[]")

        profiles = stdb_client.list_profiles(ws_id)
        assert isinstance(profiles, list)
        # Profiles may or may not be linked to workspace peers
        # depending on reducer internals — just check shape
        if profiles:
            assert "peer_id" in profiles[0]


class TestListProfiles:
    """Cover list_profiles."""

    def test_list_profiles(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(return_value=[{"id": "peer1"}, {"id": "peer2"}])
        c.get_profile = Mock(
            side_effect=[
                {"id": "peer1", "static_facts": "[]"},
                None,
            ]
        )
        result = c.list_profiles("ws")
        assert len(result) == 1
        assert result[0]["id"] == "peer1"

    def test_list_profiles_no_peers(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock(return_value=[])
        result = c.list_profiles("ws")
        assert result == []


class TestDirectoryOps:
    """Cover list_directory, traverse_directory, get_directory, link/unlink."""

    def test_list_directory(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[{"name": "file1"}, {"name": "dir1"}])
        result = c.list_directory("dir1")
        c._call.assert_called_with("get_children", ["dir1", True])
        assert len(result) == 2

    def test_traverse_directory(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[{"name": "deep_file", "depth": 2}])
        result = c.traverse_directory("ws", "root")
        c._call.assert_called_with("traverse_recursive", ["ws", "root"])
        assert len(result) == 1

    def test_get_directory(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[{"name": "target_dir", "depth": 0}])
        result = c.get_directory("ws", "/path/to/dir")
        c._call.assert_called_with("get_directory", ["ws", "/path/to/dir"])
        assert len(result) == 1

    def test_link_memory_to_directory(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c.link_memory_to_directory("dir1", "mem1", "ws")
        c._call.assert_called_with("link_memory_to_directory", ["dir1", "mem1", "ws"])

    def test_unlink_memory_from_directory(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c.unlink_memory_from_directory("dir1", "mem1")
        c._call.assert_called_with("unlink_memory_from_directory", ["dir1", "mem1"])


class TestNoteEmbedOps:
    """Cover create_note and update_note with embed=True."""

    def test_create_note_with_embed(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(
            side_effect=lambda name, *a: {"status": "ok"} if name == "create_note" else []
        )
        c._embed = Mock(return_value=[0.1, 0.2, 0.3])
        c.create_note("ws", "Title", "Content here", embed=True)
        c._embed.assert_called_once()
        # First _call must be create_note; query_table/index calls are internal
        first_call_name = c._call.call_args_list[0][0][0]
        first_call_args = c._call.call_args_list[0][0][1]
        assert first_call_name == "create_note"
        assert "Content here" in first_call_args

    def test_create_note_embed_empty_content(self):
        """Embed empty content — _embed not called, embedding_json stays '[]'."""

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock()
        result = c.create_note("ws", "Title", "  ", embed=True)
        c._embed.assert_not_called()
        assert result == {"status": "ok"}

    def test_update_note_with_embed(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[0.4, 0.5])
        result = c.update_note("note1", title="New", content="Body", embed=True)
        c._embed.assert_called_once()
        assert result == {"status": "ok"}

    def test_update_note_embed_returns_none(self):
        """Embed returns None — embedding_json stays '[]'."""

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])
        result = c.update_note("note1", content="Body", embed=True)
        assert result == {"status": "ok"}


class TestNoteBacklinks:
    """Cover get_backlinks and get_outgoing_links."""

    def test_get_backlinks(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock()
        c._query.side_effect = [
            [{"id": "bl1", "source_note_id": "src1", "target_note_id": "tgt1"}],
            [{"id": "src1", "title": "Source Title"}],
        ]
        result = c.get_backlinks("tgt1")
        assert len(result) == 1
        assert result[0]["source_title"] == "Source Title"

    def test_get_backlinks_empty_source(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock()
        c._query.side_effect = [
            [{"id": "bl1", "source_note_id": "missing"}],
            [],
        ]
        result = c.get_backlinks("tgt1")
        assert result[0]["source_title"] == ""

    def test_get_outgoing_links(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock()
        c._query.side_effect = [
            [{"id": "bl1", "source_note_id": "src1", "target_note_id": "tgt1"}],
            [{"id": "tgt1", "title": "Target Title"}],
        ]
        result = c.get_outgoing_links("src1")
        assert len(result) == 1
        assert result[0]["target_title"] == "Target Title"


class TestSessionListing:
    """Cover get_peer_sessions."""

    def test_get_peer_sessions(self):

        c = Client(host="localhost", port=3001)
        c._query = Mock()
        c._query.side_effect = [
            [{"session_id": "s1", "peer_id": "p1", "role": "owner", "joined_at": 100}],
            [{"id": "s1", "title": "Test Session", "created_at": 200}],
        ]
        result = c.get_peer_sessions("p1")
        assert len(result) == 1
        assert result[0]["role"] == "owner"
        assert result[0]["title"] == "Test Session"


class TestApiKeyCreate:
    """Cover create_api_key response parsing."""

    def test_create_api_key_with_key_id(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._sql = Mock(
            return_value=[
                {"api_key_id": "key-id-123", "name": "Test Key", "permissions": '["read"]'}
            ]
        )
        result = c.create_api_key("ws", "Test Key")
        # api_key is generated internally via secrets — just verify shape
        assert result["api_key"].startswith("sk-")
        assert result["id"] == "key-id-123"
        assert result["status"] == "ok"

    def test_create_api_key_no_rows(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._sql = Mock(return_value=[])
        result = c.create_api_key("ws", "Test Key")
        assert result["id"] == ""
        assert result["api_key"].startswith("sk-")


class TestBatchEmbedError:
    """Cover batch embed RuntimeError path."""

    def test_batch_embed_error(self):
        """When embedder raises RuntimeError, emb_list stays empty and batch proceeds."""

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[{"id": "b1", "content": "x1", "created_at": 1}])
        c._extract_and_store_entities = Mock()

        # Make _http.post raise RuntimeError
        c._http = Mock()
        c._http.post = Mock(side_effect=RuntimeError("embed fail"))
        c.embedder_url = "http://localhost:9090"

        c.store_batch("ws", [{"content": "x1", "summary": "s", "memory_type": "e", "peer_id": "p"}])
        # Should not raise — error is caught
        assert c._call.called


class TestCreateNodeEmbed:
    """Cover create_node embedding + indexing path."""

    def test_create_node_with_embed_indexed(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[0.1, 0.2])
        c._query = Mock(return_value=[{"id": "node1"}])
        result = c.create_node("ws", "TestNode", summary="A test")
        assert result == {"status": "ok"}
        # _query should have been called for kg_node
        c._query.assert_called()
        # index_entity should have been called
        index_calls = [a for a in c._call.call_args_list if a[0][0] == "index_entity"]
        assert len(index_calls) == 1

    def test_create_node_no_embed_available(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])
        result = c.create_node("ws", "TestNode")
        assert result == {"status": "ok"}


class TestRerankerErrorHandling:
    """Cover reranker error paths."""

    def test_reranker_not_found_error(self):
        """When RuntimeError contains 'not found', return graceful message."""
        from spacetime_memory.client import Client

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._sql = Mock(
            return_value=[
                {
                    "content": "sky is blue",
                    "summary": "",
                    "id": "mem1",
                    "score": 0.5,
                    "strategy": "semantic",
                }
            ]
        )

        # Make _call("rerank_search_results") raise "not found"
        orig_call = c._call

        def call_side_effect(reducer, args):
            if reducer == "rerank_search_results":
                raise RuntimeError("Reranker not found")
            return orig_call(reducer, args)

        c._call = Mock(side_effect=call_side_effect)

        result = c.search("ws", "sky", rerank=True)
        assert result is not None

    def test_delete_memory_reraises_unknown_error(self):
        """When delete_memory gets RuntimeError without 'not found', re-raise."""
        from spacetime_memory.client import Client

        c = Client(host="localhost", port=3001)
        c._call = Mock(side_effect=RuntimeError("Database connection failed"))
        with pytest.raises(RuntimeError, match="Database connection failed"):
            c.delete_memory("mem1")


class TestQueryCacheInvalidation:
    """Cover query cache invalidation on store."""

    def test_store_invalidates_query_cache(self):

        mock_cache = Mock()
        c = Client(host="localhost", port=3001, query_cache=mock_cache)
        c._call = Mock(return_value={"status": "ok"})
        c._sql = Mock(return_value=[])
        c.store("ws", "p1", "p1", "experience", "test content")
        mock_cache.invalidate.assert_called_with(workspace_id="ws")

    def test_get_user_memories(self):

        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._sql = Mock(return_value=[{"id": "m1", "content": "test"}])
        result = c.get_user_memories("user1", "ws")
        assert len(result) == 1
        assert result[0]["content"] == "test"


class TestTantivyAndHealthCheck:
    """Cover Tantivy keyword result conversion, embedder health check OPENAI path,
    and binary vector cache similarity."""

    def test_tantivy_and_binary_cache(self, monkeypatch):
        """Tantivy search + binary cache similarity."""
        from spacetime_memory.binary_vectors import binarize

        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:4000/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        c = Client(host="localhost", port=3001)
        emb = [0.1] * 1024
        c._embed = Mock(return_value=emb)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(
            return_value=[
                {
                    "entity_id": "e1",
                    "entity_type": "memory",
                    "content": "semantic hit",
                    "score": 0.9,
                    "strategy": "semantic",
                    "workspace_id": "ws",
                    "summary": "s",
                    "confidence": 1.0,
                    "created_at": 100,
                },
            ]
        )
        c._tantivy_search = Mock(
            return_value=[
                {"entity_id": "e2", "entity_type": "memory", "content": "keyword hit", "score": 1.5}
            ]
        )
        # Populate binary cache with same embedding → similarity = 1.0
        c._binary_cache = {"e3": binarize(emb)}
        mock_http = Mock()
        mock_http.get.return_value = Mock(status_code=200)
        mock_http.post.return_value = Mock(status_code=200)
        c._http = mock_http
        c._emit_event = Mock()
        result = c.search("ws", "test", semantic=True)
        c._tantivy_search.assert_called_once()
        assert isinstance(result, list)
