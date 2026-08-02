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
from unittest.mock import patch

import httpx
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
class TestClientUnitCoverage:
    """Unit tests for missed lines in client.py — pure mocking, no backend.

    Part 3 of 4: fuzzy_get, list_memories, context chain, workspace,
    embedder health, MMR rerank, binary vectors.
    """

    def test_fuzzy_get_no_rows(self):
        """Line 1515: fuzzy_get returns None when no rows."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_query", return_value=[]):
            result = client.fuzzy_get("ws1", "name")
            assert result is None

    # ── list_memories (simple call) ──

    def test_list_memories(self):
        """Test list_memories with query."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_query", return_value=[{"id": "m1", "content": "hi"}]):
            result = client.list_memories(workspace_id="ws1", limit=5)
            assert result == [{"id": "m1", "content": "hi"}]

    # ── get_context_chain (line 1616) ──

    def test_get_context_chain_no_memories(self):
        """Line 1616: get_context_chain returns empty dicts when no memories."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_query", return_value=[]):
            result = client.get_context_chain("nonexistent")
            assert result == {"workspace_context": "", "memory_context": ""}

    # ── create_workspace, list_workspaces ──

    def test_create_workspace(self):
        """Simple create_workspace call."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_call", return_value={"status": "ok"}) as m:
            result = client.create_workspace("test-ws")
            m.assert_called_once()
            assert result["status"] == "ok"
            assert "id" in result

    def test_list_workspaces(self):
        """Simple list_workspaces call."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_query", return_value=[{"id": "ws1", "name": "w1"}]):
            result = client.list_workspaces()
            assert result == [{"id": "ws1", "name": "w1"}]

    # ── check_embedder_health error (lines 608-609) ──

    def test_check_embedder_health_connect_error(self):
        """Lines 608-609: check_embedder_health catches ConnectError."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("refused")
        client._http = mock_http
        result = client.check_embedder_health()
        assert result["reachable"] is False
        assert result["status"] == "error"

    def test_check_embedder_health_error_status(self):
        """Lines 607: check_embedder_health on non-200."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_http.get.return_value = mock_resp
        client._http = mock_http
        result = client.check_embedder_health()
        # _request_with_retry_simple returns the response immediately with
        # the error status — the server IS reachable, it just returned an error.
        assert result["status"] == "error"
        assert result.get("code") == 503
        assert result.get("reachable") is True

    # ── search with MMR rerank (line 1385-1386) ──

    def test_search_with_mmr_rerank(self):
        """Line 1385-1386: search applies MMR reranking."""

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        client._query_cache = None
        client.event_bus = None

        mock_rows = [{"entity_id": "r1", "score": 0.8, "strategy": "semantic"}]
        mmr_rows = [{"entity_id": "r1", "score": 0.9}]
        with patch("spacetime_memory.mmr.mmr_rerank", return_value=mmr_rows):
            with patch.object(client, "_embed", return_value=[0.1, 0.2]):
                with patch.object(client, "_call", return_value={"status": "ok"}):
                    with patch.object(client, "_sql", return_value=mock_rows):
                        with patch.object(client, "_tantivy_search", return_value=[]):
                            with patch.object(
                                client, "_fuse_and_deduplicate", return_value=mock_rows
                            ):
                                with patch.object(
                                    client, "_enrich_content", return_value=mock_rows
                                ):
                                    result = client.search(
                                        "ws1",
                                        "pizza",
                                        semantic=True,
                                        limit=5,
                                        mmr_lambda=0.7,
                                    )
                                    assert result == mmr_rows

    # ── search with binary vector similarity (lines 1322-1339) ──

    def test_search_binary_vectors(self):
        """Lines 1322-1339: search uses binary vector cache when available."""

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        client._query_cache = None
        client.event_bus = None
        client._binary_cache = {"m1": b"\\x00" * 32}

        mock_rows = [{"entity_id": "r1", "score": 0.8, "strategy": "semantic"}]
        with patch.object(client, "_embed", return_value=[0.1] * 1024):
            with patch.object(client, "_call", return_value={"status": "ok"}):
                with patch.object(client, "_sql", return_value=mock_rows):
                    with patch.object(client, "_tantivy_search", return_value=[]):
                        with patch.object(client, "_fuse_and_deduplicate", return_value=mock_rows):
                            with patch.object(client, "_enrich_content", return_value=mock_rows):
                                result = client.search("ws1", "pizza", semantic=True, limit=5)
                                assert result == mock_rows

    # ── search with binary vector ValueError fallback (line 1338-1339) ──

    def test_search_binary_vectors_error_fallback(self):
        """Lines 1338-1339: binary scoring ValueError becomes best-effort."""

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        client._query_cache = None
        client.event_bus = None
        client._binary_cache = {"m1": b"\\x00" * 32}

        mock_rows = [{"entity_id": "r1", "score": 0.8, "strategy": "semantic"}]
        with patch.object(client, "_embed", return_value=[0.1] * 1024):
            # Make binarize raise ValueError
            with patch("spacetime_memory.binary_vectors.binarize", side_effect=ValueError("bad")):
                with patch.object(client, "_call", return_value={"status": "ok"}):
                    with patch.object(client, "_sql", return_value=mock_rows):
                        with patch.object(client, "_tantivy_search", return_value=[]):
                            with patch.object(
                                client, "_fuse_and_deduplicate", return_value=mock_rows
                            ):
                                with patch.object(
                                    client, "_enrich_content", return_value=mock_rows
                                ):
                                    result = client.search("ws1", "pizza", semantic=True, limit=5)
                                    assert result == mock_rows
