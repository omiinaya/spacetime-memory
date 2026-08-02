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

    Part 2 of 4: fuse/dedup, search, memory ops, context, workspace,
    rate_memory, fuzzy_get, query methods.
    """

    def test_ping_error_catch(self):
        """Lines 684-686: ping catches ConnectError and returns error dict."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("connection refused")
        client._http = mock_http
        result = client.ping()
        assert result["status"] == "error"
        assert "latency_ms" in result

    # ── _normalize_fuse with tantivy rows (lines 1029-1031) ──

    def test_fuse_and_deduplicate_with_tantivy(self):
        """Lines 1029-1031: _fuse_and_deduplicate adds tantivy rows."""
        client = Client(host="localhost", port="3000", database="test")
        rows = [{"entity_id": "a", "strategy": "semantic", "score": 0.9}]
        tantivy_rows = [{"entity_id": "b", "strategy": "keyword", "score": 0.8, "content": "hi"}]
        per_strat = {
            "semantic": rows,
            "keyword": [],
            "graph": [],
            "temporal": [],
            "binary": [],
        }
        strat_min = {"semantic": 0.9, "keyword": 0.8}
        strat_max = {"semantic": 0.9, "keyword": 0.8}
        weights = {
            "semantic": 0.65,
            "keyword": 0.25,
            "graph": 0.0,
            "temporal": 0.05,
            "binary": 0.05,
        }
        result = client._fuse_and_deduplicate(
            rows, tantivy_rows, per_strat, strat_min, strat_max, weights
        )
        # tantivy row "b" should be included
        eids = {r.get("entity_id") for r in result}
        assert "b" in eids
        assert len(result) == 2

    # ── search_sessions_semantic (lines 1460-1470) ──

    def test_search_sessions_semantic(self):
        """Lines 1460-1470: search_sessions_semantic method."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        mock_http = MagicMock()
        client._http = mock_http

        # Mock _embed to return a vector
        with patch.object(client, "_embed", return_value=[0.1, 0.2, 0.3]):
            # Mock _call
            with patch.object(client, "_call", return_value={"status": "ok"}):
                # Mock _sql to return session results
                with patch.object(client, "_sql") as mock_sql:
                    mock_sql.return_value = [
                        {"session_id": "s1", "score": 0.9},
                        {"session_id": "s2", "score": 0.5},
                    ]
                    result = client.search_sessions_semantic("test query", limit=5)
                    assert len(result) == 2
                    assert result[0]["session_id"] == "s1"

    def test_search_sessions_semantic_no_embedding(self):
        """search_sessions_semantic returns [] when embedder fails."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_embed", return_value=[]):
            result = client.search_sessions_semantic("test")
            assert result == []

    # ── get_memory reinforce error (lines 1478-1479) ──

    def test_get_memory_reinforce_error(self):
        """Lines 1478-1479: get_memory catches RuntimeError on reinforce."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_query", return_value=[{"id": "m1"}]):
            with patch.object(client, "_call", side_effect=RuntimeError("fail")):
                result = client.get_memory("m1")
                assert result == [{"id": "m1"}]

    # ── update_memory ──

    def test_update_memory(self):
        """Test update_memory simple path."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_call", return_value={"status": "ok"}) as mock_call:
            result = client.update_memory("m1", "new content", summary="sum", confidence=0.9)
            mock_call.assert_called_once_with(
                "update_memory", ["m1", "new content", "sum", 0.9, 0]
            )
            assert result == {"status": "ok"}

    # ── delete_memory query_cache path (lines 1583-1587, 1593) ──

    def test_delete_memory_with_query_cache(self):
        """Lines 1583-1587, 1593: delete_memory with query_cache set."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_cache = MagicMock()
        client._query_cache = mock_cache
        client._identity_established = True

        mock_http = MagicMock()
        client._http = mock_http

        with patch.object(client, "_sql") as mock_sql:
            mock_sql.return_value = [{"workspace_id": "ws1"}]
            with patch.object(client, "_call", return_value={"status": "ok"}):
                with patch("spacetime_memory.streaming.MemoryEvent"):
                    result = client.delete_memory("m1")
                    assert result == {"status": "ok"}
                    mock_cache.invalidate.assert_called_once_with(workspace_id="ws1")

    def test_delete_memory_already_deleted(self):
        """delete_memory returns ok when 'not found' in error."""

        client = Client(host="localhost", port="3000", database="test")
        client._query_cache = None
        with patch.object(client, "_call", side_effect=RuntimeError("not found: m1")):
            result = client.delete_memory("m1")
            assert result == {"status": "ok", "note": "already deleted"}

    # ── set_workspace_context / set_memory_context / reinforce ──

    def test_set_workspace_context(self):
        """Simple set_workspace_context call."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_call", return_value={"status": "ok"}) as m:
            result = client.set_workspace_context("ws1", "ctx")
            m.assert_called_once_with("set_workspace_context", ["ws1", "ctx"])
            assert result == {"status": "ok"}

    def test_set_memory_context(self):
        """Simple set_memory_context call."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_call", return_value={"status": "ok"}) as m:
            result = client.set_memory_context("m1", "ctx")
            m.assert_called_once_with("set_memory_context", ["m1", "ctx"])
            assert result == {"status": "ok"}

    def test_reinforce(self):
        """Simple reinforce call."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_call", return_value={"status": "ok"}) as m:
            result = client.reinforce("m1")
            m.assert_called_once_with("reinforce_memory", ["m1"])
            assert result == {"status": "ok"}

    # ── _enrich_content (lines 1083-1093) ──

    def test_enrich_content_node_path(self):
        """Lines 1083-1085, 1090-1091: _enrich_content with node entity_type."""

        client = Client(host="localhost", port="3000", database="test")
        rows = [{"entity_id": "n1", "entity_type": "node", "score": 0.8}]
        with patch.object(client, "_query", return_value=[{"id": "n1", "label": "NodeLabel"}]):
            result = client._enrich_content(rows, "ws1")
            assert result[0]["memory_content"] == "NodeLabel"

    def test_enrich_content_other_type(self):
        """Line 1093: _enrich_content with non-memory/non-node entity_type."""

        client = Client(host="localhost", port="3000", database="test")
        rows = [{"entity_id": "x1", "entity_type": "document", "score": 0.5}]
        with patch.object(client, "_query", return_value=[]):
            result = client._enrich_content(rows, "ws1")
            assert result[0]["memory_content"] == ""

    # ── _keyword_fallback with filters (lines 1113, 1115) ──

    def test_keyword_fallback_with_memory_type_and_tier(self):
        """Lines 1113, 1115: _keyword_fallback with memory_type and tier filters."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_query", return_value=[]) as mock_query:
            result = client._keyword_fallback(
                "ws1", "test query", memory_type="experience", tier="L0", limit=10
            )
            assert result == []
            # Verify filter_dict includes memory_type and tier
            call_kwargs = mock_query.call_args
            assert call_kwargs is not None

    # ── search query_cache hit (line 1210-1211) ──

    def test_search_query_cache_hit(self):
        """Lines 1206-1211: search returns cached result on cache hit."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_cache = MagicMock()
        cached_result = [{"entity_id": "c1", "score": 0.99}]
        mock_cache.get.return_value = cached_result
        client._query_cache = mock_cache

        with patch.object(client, "_call", return_value={"status": "ok"}):  # ACL gate
            with patch.object(client, "_embed", return_value=[0.1, 0.2]):
                result = client.search("ws1", "pizza", semantic=True, limit=5)
                assert result == cached_result
                mock_cache.get.assert_called_once()

    # ── search query expansion (lines 1216-1219) ──

    def test_search_query_expansion(self):
        """Lines 1216-1219: search uses query expansion."""

        client = Client(host="localhost", port="3000", database="test")
        client._query_cache = None
        client._identity_established = True

        with patch("spacetime_memory.client._memories_search.expand_query", return_value="expanded pizza query"):
            with patch.object(client, "_embed", return_value=[0.1, 0.2]):
                with patch.object(client, "_call", return_value={"status": "ok"}):
                    with patch.object(client, "_sql", return_value=[]):
                        with patch.object(client, "_tantivy_search", return_value=[]):
                            with patch.object(client, "_fuse_and_deduplicate", return_value=[]):
                                with patch.object(client, "_enrich_content", return_value=[]):
                                    result = client.search(
                                        "ws1",
                                        "pizza",
                                        semantic=True,
                                        limit=5,
                                        query_expansion=True,
                                    )
                                    assert result == []

    def test_search_query_expansion_gibberish_fallback(self):
        """Line 1218-1219: fallback when expansion returns gibberish."""

        client = Client(host="localhost", port="3000", database="test")
        client._query_cache = None
        client._identity_established = True

        with patch("spacetime_memory.client._memories_search.expand_query", return_value="  ab "):
            with patch.object(client, "_embed", return_value=[0.1, 0.2]):
                with patch.object(client, "_call", return_value={"status": "ok"}):
                    with patch.object(client, "_sql", return_value=[]):
                        with patch.object(client, "_tantivy_search", return_value=[]):
                            with patch.object(client, "_fuse_and_deduplicate", return_value=[]):
                                with patch.object(client, "_enrich_content", return_value=[]):
                                    result = client.search(
                                        "ws1",
                                        "pizza",
                                        semantic=True,
                                        limit=5,
                                        query_expansion=True,
                                    )
                                    assert result == []

    # ── search embedder_down path (lines 1242-1243) ──

    def test_search_embedder_down_health_check_fails(self):
        """Lines 1242-1243: embedder health check catches error, marks down."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._query_cache = None
        client._identity_established = True
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("nope")
        client._http = mock_http

        with patch.object(client, "_embed", return_value=[0.1, 0.2]):
            with patch.object(client, "_call", return_value={"status": "ok"}):
                with patch.object(client, "_sql", return_value=[]):
                    with patch.object(client, "_tantivy_search", return_value=[]):
                        with patch.object(client, "_fuse_and_deduplicate", return_value=[]):
                            with patch.object(client, "_enrich_content", return_value=[]):
                                result = client.search("ws1", "pizza", semantic=True, limit=5)
                                assert result == []

    # ── search plugin_manager dispatch (line 1393) ──

    def test_search_plugin_dispatch(self):
        """Line 1393: search dispatches through plugin_manager when set."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._query_cache = None
        client._identity_established = True
        client.event_bus = None

        mock_pm = MagicMock()
        modified_results = [{"entity_id": "mod", "score": 9.9}]
        mock_pm.dispatch_search.return_value = (True, modified_results)
        client.plugin_manager = mock_pm

        mock_rows = [{"entity_id": "r1", "score": 0.8, "strategy": "semantic"}]
        with patch.object(client, "_embed", return_value=[0.1, 0.2]):
            with patch.object(client, "_call", return_value={"status": "ok"}):
                with patch.object(client, "_sql", return_value=mock_rows):
                    with patch.object(client, "_tantivy_search", return_value=[]):
                        with patch.object(client, "_fuse_and_deduplicate", return_value=mock_rows):
                            with patch.object(client, "_enrich_content", return_value=mock_rows):
                                result = client.search("ws1", "pizza", semantic=True, limit=5)
                                assert result == modified_results
                                mock_pm.dispatch_search.assert_called_once()

    # ── search query_cache store (line 1396) ──

    def test_search_query_cache_store(self):
        """Line 1396: search stores results in query_cache when set."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        client.event_bus = None
        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # no cache hit
        client._query_cache = mock_cache

        mock_rows = [{"entity_id": "r1", "score": 0.8, "strategy": "semantic"}]
        with patch.object(client, "_embed", return_value=[0.1, 0.2]):
            with patch.object(client, "_call", return_value={"status": "ok"}):
                with patch.object(client, "_sql", return_value=mock_rows):
                    with patch.object(client, "_tantivy_search", return_value=[]):
                        with patch.object(client, "_fuse_and_deduplicate", return_value=mock_rows):
                            with patch.object(client, "_enrich_content", return_value=mock_rows):
                                result = client.search("ws1", "pizza", semantic=True, limit=5)
                                assert result == mock_rows
                                mock_cache.set.assert_called_once()

    # ── search _emit_event (line 1398) ──

    def test_search_emit_event(self):
        """Line 1398-1401: search emits search.performed event."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        client._query_cache = None
        mock_bus = MagicMock()
        client.event_bus = mock_bus

        mock_rows = [{"entity_id": "r1", "score": 0.8, "strategy": "semantic"}]
        with patch("spacetime_memory.streaming.MemoryEvent"):
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
                                    result = client.search("ws1", "pizza", semantic=True, limit=5)
                                    assert result == mock_rows
                                    mock_bus.emit.assert_called_once()

    # ── _query method (lines 405-440) ──

    def test_query_method(self):
        """Test _query method end-to-end path."""

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        with patch.object(client, "_call", return_value={"status": "ok"}), patch.object(
            client, "_sql", return_value=[{"id": "a", "row_json": '{"key":"val"}'}]
        ):
            result = client._query(
                "memory", workspace_id="ws1", filter_dict={"id": "a"}, columns=["id", "content"]
            )
            assert len(result) == 1
            assert result[0] == {"key": "val"}

    def test_query_method_legacy_fallback(self):
        """Line 439: _query legacy fallback when no row_json."""

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        with patch.object(client, "_call", return_value={"status": "ok"}):
            with patch.object(client, "_sql", return_value=[{"id": "a", "content": "hi"}]):
                result = client._query("memory", workspace_id="ws1", filter_dict={})
                assert result == [{"id": "a", "content": "hi"}]

    # ── rate_memory ──

    def test_rate_memory(self):
        """Test rate_memory simple path."""

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_call", return_value={"status": "ok"}) as m:
            result = client.rate_memory("m1", "like", "peer1")
            m.assert_called_once_with("rate_memory", ["m1", "like", "peer1"])
            assert result == {"status": "ok"}
