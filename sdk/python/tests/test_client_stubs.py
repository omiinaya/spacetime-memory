"""Tests for the SDK Client — stub and delegation tests."""

import json
from unittest.mock import Mock, patch

import httpx
import pytest

from spacetime_memory import Client

# ── Store with plugin manager ──────────────────────────────────────────


class TestStorePluginDispatch:
    """store() plugin manager dispatch (line 801)."""

    def test_store_dispatches_to_plugin_manager(self):
        """When plugin_manager is set, dispatch_store is called."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        c._embed = Mock(return_value=[])  # empty → skip post-store indexing
        c._emit_event = Mock()
        c._query_cache = None

        pm = Mock()
        pm.dispatch_store.return_value = ("modified content", {"extra": True})
        c.plugin_manager = pm

        result = c.store("ws1", content="hello")
        assert result["status"] == "ok"
        pm.dispatch_store.assert_called_once()
        assert pm.dispatch_store.call_args[0][0] == "hello"


# ── Batch store response parsing ───────────────────────────────────────


class TestStoreBatchResponse:
    """store_batch() response parsing (lines 973-978)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value=[{"status": "ok"}])
        c._embed = Mock(return_value=[[0.1] * 1024])
        c._query = Mock(return_value=[])
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        # Mock the entire _http attribute
        c._http = Mock()
        return c

    def test_batch_store_with_embeddings_response(self, client):
        """Batch store parses 'embeddings' key from LLM embedder response."""
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"embeddings": [[0.1] * 1024, [0.2] * 1024]}
        client._http.post.return_value = mock_resp

        items = [
            {"content": "a", "memory_type": "experience"},
            {"content": "b", "memory_type": "experience"},
        ]
        result = client.store_batch("ws1", items)
        assert isinstance(result, list)

    def test_batch_single_embedding_fallback(self, client):
        """Batch store handles 'embedding' (singular) response key."""
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"embedding": [0.5] * 1024}
        client._http.post.return_value = mock_resp

        items = [
            {"content": "single", "memory_type": "experience"},
        ]
        result = client.store_batch("ws1", items)
        assert isinstance(result, list)


# ── Batch store indexing loop ──────────────────────────────────────────


class TestStoreBatchIndexing:
    """store_batch() post-indexing loop (lines 998-1009)."""

    def test_batch_store_indexes_each_item(self):
        """When embeddings are available, each item gets indexed."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value=[{"status": "ok"}])
        c._embed = Mock(return_value=[[0.1] * 1024])
        c._query = Mock(
            return_value=[
                {"id": "mem-1", "created_at": 200},
                {"id": "mem-2", "created_at": 100},
            ]
        )
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        c._http = Mock()

        # store_batch calls self._embed_batch_local, not self._embed_batch
        c._embed_batch_local = Mock(return_value=[[0.1] * 1024, [0.2] * 1024])

        items = [
            {"content": "first item", "memory_type": "experience"},
            {"content": "second", "memory_type": "experience"},
        ]
        result = c.store_batch("ws1", items)
        assert isinstance(result, list)
        # store_memory_batch + index_entity_batch (+ index_terms_batch when ids match)
        assert c._call.call_count >= 2
        batch_calls = [c.args[0] for c in c._call.call_args_list]
        assert "store_memory_batch" in batch_calls
        assert "index_entity_batch" in batch_calls


# ── LLM rerank rate-limit handling ─────────────────────────────────────


class TestLLMRerankRateLimit:
    """llm_rerank() rate-limit retry (lines 3027-3045)."""

    def test_rate_limit_retry_then_success(self):
        """Rate-limited → retries → succeeds."""
        from spacetime_memory.client import llm_rerank

        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            resp = Mock(spec=httpx.Response)
            if call_count[0] < 3:
                resp.status_code = 429
                resp.request = Mock()
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "choices": [{"message": {"content": '[{"index":0,"score":9.0}]'}}]
                }
                resp.request = Mock()
            return resp

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("httpx.post", mock_post)
            mp.setattr("time.sleep", lambda s: None)
            results = llm_rerank("query", [{"id": "a", "content": "x"}], api_key="sk-test")
            assert len(results) >= 1
            assert results[0]["score"] == pytest.approx(0.9)

    def test_rate_limit_exhausted_falls_back(self):
        """All retries rate-limited → falls back to original results."""
        from spacetime_memory.client import llm_rerank

        resp_429 = Mock()
        resp_429.status_code = 429
        resp_429.request = Mock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("httpx.post", Mock(return_value=resp_429))
            mp.setattr("time.sleep", lambda s: None)
            original = [{"id": "a", "content": "x", "score": 0.5}]
            results = llm_rerank("query", original, api_key="sk-test")
            # Falls back to original results
            assert results == original

    def test_reasoning_model_fallback(self):
        """Reasoning models put output in reasoning_content, not content."""
        from spacetime_memory.client import llm_rerank

        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": '[{"index":0,"score":8.8}]',
                    }
                }
            ]
        }
        resp.request = Mock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("httpx.post", Mock(return_value=resp))
            results = llm_rerank(
                "query", [{"id": "r1", "content": "reasoning test"}], api_key="sk-test"
            )
            assert len(results) >= 1
            assert results[0]["score"] == pytest.approx(0.88)


# ── Post-store indexing ────────────────────────────────────────────────


class TestStorePostIndexing:
    """store() post-store indexing path (lines 834-856)."""

    def test_store_indexes_entities_when_embedding_available(self):
        """When _embed returns non-empty, post-store indexing runs."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[0.1] * 1024)  # non-empty → triggers indexing
        c._query = Mock(
            return_value=[
                {"id": "mem-1", "content": "hello world"},
            ]
        )
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None

        result = c.store("ws1", content="hello world")
        assert result["status"] == "ok"
        # Verify indexing calls — check actual call args
        calls = [args[0] for args, _ in c._call.call_args_list]
        assert "index_entity" in calls
        assert "index_terms" in calls
        c._tantivy_index.assert_called_once()
        c._extract_and_store_entities.assert_called_once()

    def test_store_with_tier_L0(self):
        """store with tier='L0' triggers update_memory_tier."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])  # skip indexing
        c._query = Mock(return_value=[{"id": "mem-1"}])
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None

        result = c.store("ws1", content="test", peer_id="user1", tier="L0")
        assert result["status"] == "ok"
        c._call.assert_any_call("update_memory_tier", ["mem-1", "L0"])

    def test_store_binary_compression_error_caught(self):
        """Binary compression error in post-store indexing is caught (lines 841-842)."""

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[0.1] * 1024)
        c._query = Mock(
            return_value=[
                {"id": "mem-1", "content": "hello world"},
            ]
        )
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None

        with patch("spacetime_memory.binary_vectors.binarize", side_effect=ValueError("bad")):
            result = c.store("ws1", content="hello world")
            assert result["status"] == "ok"  # store still succeeds


# ── Entity extraction ──────────────────────────────────────────────────


class TestExtractAndStoreEntities:
    """_extract_and_store_entities() (lines 878-913)."""

    def test_llm_extraction_with_entities(self):
        """LLM available → extracts and stores entities."""

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {
                "name": "Alice",
                "entity_type": "person",
                "aliases": ["Al"],
                "description": "A person",
            },
            {"name": "Bob", "entity_type": "person", "aliases": [], "description": "Another"},
        ]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "Alice and Bob met")

        # create_entity_link should be called for each entity
        assert c._call.call_count >= 2

    def test_regex_fallback_when_llm_unavailable(self):
        """LLM unavailable → falls back to regex extraction reducer."""

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = False

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "some content")

        c._call.assert_called_with("extract_entities", ["ws1", "some content"])

    def test_entity_link_error_caught(self):
        """RuntimeError in create_entity_link is caught, not propagated."""

        c = Client(host="localhost", port="3001", database="test-db")
        # First call fails, others succeed
        c._call = Mock(side_effect=[RuntimeError("fail"), None, None])
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Bad", "entity_type": "concept"},
        ]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "Bad entity")

        # Should have tried create_entity_link (failed) and link_entity_to_memory
        assert c._call.call_count >= 2

    def test_link_entity_error_caught(self):
        """RuntimeError in link_entity_to_memory is caught (lines 906-907)."""

        c = Client(host="localhost", port="3001", database="test-db")
        # create_entity_link succeeds, link_entity_to_memory fails
        c._call = Mock(side_effect=[{"status": "ok"}, RuntimeError("link fail")])
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Entity", "entity_type": "concept"},
        ]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "Entity content")

        assert c._call.call_count == 2  # both called

    def test_regex_fallback_error_caught(self):
        """RuntimeError in extract_entities fallback is caught (lines 912-913)."""

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(side_effect=RuntimeError("extract fail"))
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = False  # triggers fallback

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "content")

        # Called extract_entities (which failed) but no exception propagated
        c._call.assert_called_once_with("extract_entities", ["ws1", "content"])


# ── Entity extraction edge cases ───────────────────────────────────────


class TestExtractEntitiesSkip:
    """Entity extraction skips invalid names."""

    def test_skips_short_names(self):
        """Names <2 chars are skipped."""

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "A", "entity_type": "letter"},  # too short
            {"name": "OK", "entity_type": "word"},  # ok
        ]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "A and OK")

        # Only "OK" should trigger a call
        # create_entity_link for OK + link_entity_to_memory for OK = 2 calls
        assert c._call.call_count == 2

    def test_skips_empty_names(self):
        """Empty names are skipped."""

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "", "entity_type": "empty"},
            {"name": None, "entity_type": "none"},
        ]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "nothing useful")

        assert c._call.call_count == 0  # all skipped


# ── Graph traversal ────────────────────────────────────────────────────


class TestGraphTraversal:
    """Graph traversal methods (lines 2573-2583)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        return c

    def test_graph_bfs(self, client):
        client.graph_bfs("ws1", "node-1", max_depth=3)
        client._call.assert_called_with("graph_bfs", ["ws1", "node-1", 3])

    def test_shortest_path(self, client):
        client.shortest_path("ws1", "src", "tgt", max_hops=4)
        client._call.assert_called_with("shortest_path", ["ws1", "src", "tgt", 4])

    def test_get_neighbors_via_reducer(self, client):
        client.get_neighbors_via_reducer("ws1", "node-1")
        client._call.assert_called_with("get_neighbors", ["ws1", "node-1"])


# ── Pattern detection ──────────────────────────────────────────────────


class TestPatternDetection:
    """detect_memory_patterns() (lines 1432-1440)."""

    def test_detects_patterns(self):

        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(
            return_value=[
                {"id": "1", "content": "a"},
                {"id": "2", "content": "b"},
            ]
        )

        mock_detect = Mock(return_value={"patterns": [], "clusters": []})
        with patch("spacetime_memory.pattern_detection.detect_patterns", mock_detect):
            result = c.detect_patterns("ws1", limit=10)
            mock_detect.assert_called_once()
            assert isinstance(result, dict)


# ── Batch update memories ──────────────────────────────────────────────


class TestBatchUpdateMemoriesSuccess:
    """batch_update_memories() success path (lines 1758-1769)."""

    def test_batch_update_success(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(
            return_value=[
                {"id": "m1", "content": "old", "summary": "s", "confidence": 0.5},
            ]
        )
        c.update_memory = Mock(return_value={"status": "ok"})

        result = c.batch_update_memories("ws1", ["m1"], {"content": "new"})
        c.update_memory.assert_called_once_with("m1", "new", "s", 0.5, 0)
        assert result["status"] == "ok"

    def test_batch_update_missing_memory(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])  # memory not found
        c.update_memory = Mock()

        result = c.batch_update_memories("ws1", ["missing"], {"content": "new"})
        c.update_memory.assert_not_called()
        assert result["status"] == "partial"
        assert "not found" in result["errors"][0]

    def test_batch_update_exception(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(side_effect=RuntimeError("boom"))

        result = c.batch_update_memories("ws1", ["m1"], {"content": "new"})
        assert result["status"] == "partial"
        assert result["errors"]


# ── Profile stubs ──────────────────────────────────────────────────────


class TestProfileStubs:
    """Simple profile delegation methods (lines 2294, 2298, 2320-2328)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        return c

    def test_add_profile_fact(self, client):
        client.add_profile_fact("peer-1", "likes coffee")
        client._call.assert_called_with("add_profile_fact", ["peer-1", "likes coffee"])

    def test_add_dynamic_context(self, client):
        client.add_dynamic_context("peer-1", "just woke up")
        client._call.assert_called_with("add_dynamic_context", ["peer-1", "just woke up"])

    def test_search_profiles(self, client):
        """search_profiles filters client-side by static_facts_json."""
        client.list_profiles = Mock(
            return_value=[
                {"peer_id": "p1", "static_facts_json": "likes coffee"},
                {"peer_id": "p2", "static_facts_json": "prefers tea"},
            ]
        )
        results = client.search_profiles("ws1", "coffee")
        assert len(results) == 1
        assert results[0]["peer_id"] == "p1"


# ── Fact stubs ──────────────────────────────────────────────────────────


class TestFactStubs:
    """Simple fact delegation methods (delete_fact, update_fact, search_facts)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        return c

    def test_delete_fact(self, client):
        client.delete_fact("fact-1")
        client._call.assert_called_with("delete_fact", ["fact-1"])

    def test_update_fact(self, client):
        client.update_fact("fact-1", content="new content", confidence=0.9, category="updated", tier="L1")
        client._call.assert_called_with("update_fact", ["fact-1", "new content", 0.9, "updated", "L1"])

    def test_update_fact_defaults(self, client):
        client.update_fact("fact-1")
        client._call.assert_called_with("update_fact", ["fact-1", "", 0.0, "", ""])

    def test_search_facts(self, client):
        client._query = Mock(return_value=[{"json_data": '[{"id":"f1","content":"hello"}]'}])
        result = client.search_facts("ws1", "hello", tier="L1")
        client._call.assert_called_with("search_facts", ["ws1", "hello", "L1"])
        assert result == [{"id": "f1", "content": "hello"}]

    def test_search_facts_empty(self, client):
        client._query = Mock(return_value=[])
        result = client.search_facts("ws1", "nonexistent")
        assert result == []


# ── Tour stubs ─────────────────────────────────────────────────────────


class TestTourStubs:
    """Simple tour delegation methods (lines 2591, 2595, 2599)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        return c

    def test_create_tour(self, client):
        client.create_tour("ws1", "My Tour", "A nice tour")
        client._call.assert_called_with("create_tour", ["ws1", "My Tour", "A nice tour"])

    def test_add_tour_stop(self, client):
        client.add_tour_stop("tour-1", "node-1", "Stop 1", "desc")
        client._call.assert_called_with("add_tour_stop", ["tour-1", "node-1", "Stop 1", "desc"])

    def test_delete_tour(self, client):
        client.delete_tour("tour-1")
        client._call.assert_called_with("delete_tour", ["tour-1"])


# ── Entity link stubs ──────────────────────────────────────────────────


class TestEntityLinkStubs:
    """Simple entity-link delegation methods (lines 2613, 2619, 2623)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        return c

    def test_create_entity_link(self, client):
        client.create_entity_link("ws1", "Alice", "person", "Alice in Wonderland")
        client._call.assert_called_with(
            "create_entity_link",
            [
                "ws1",
                "Alice",
                "[]",
                "person",
                "Alice in Wonderland",
            ],
        )

    def test_add_alias(self, client):
        client.add_alias("link-1", "Alias")
        client._call.assert_called_with("add_alias", ["link-1", "Alias"])

    def test_resolve_entity(self, client):
        client.resolve_entity("ws1", "Alice")
        client._call.assert_called_with("resolve_entity", ["ws1", "Alice"])


# ── get_context_chain ──────────────────────────────────────────────────


class TestGetContextChain:
    """get_context_chain() method (lines 1615-1632)."""

    def test_returns_context(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(
            side_effect=[
                [{"id": "mem-1", "workspace_id": "ws1", "context": "mem context"}],
                [{"id": "ws1", "context": "ws context"}],
            ]
        )
        result = c.get_context_chain("mem-1")
        assert result["memory_context"] == "mem context"
        assert result["workspace_context"] == "ws context"

    def test_memory_not_found_returns_empty(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])
        result = c.get_context_chain("nonexistent")
        assert result["workspace_context"] == ""
        assert result["memory_context"] == ""

    def test_no_workspace_context(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(
            side_effect=[
                [{"id": "mem-1", "workspace_id": "ws1", "context": "mem ctx"}],
                [],  # workspace lookup returns empty
            ]
        )
        result = c.get_context_chain("mem-1")
        assert result["memory_context"] == "mem ctx"
        assert result["workspace_context"] == ""


# ── _whoami ────────────────────────────────────────────────────────────


class TestWhoami:
    """_whoami() method (line 266)."""

    def test_returns_identity_header(self):
        c = Client(host="localhost", port="3001", database="test-db")
        mock_resp = Mock()
        mock_resp.headers.get.return_value = "c200abc123"
        c._ensure_identity = Mock()
        c._http.get = Mock(return_value=mock_resp)
        c._headers = Mock(return_value={})

        ident = c._whoami()
        assert ident == "c200abc123"
        c._http.get.assert_called_once()


# ── Remaining stubs ────────────────────────────────────────────────────


class TestMethodStubs:
    """Remaining delegation stubs (<10 lines each)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        c._sql = Mock(return_value=[])
        return c

    def test_get_citations(self, client):
        client.get_citations("ws1", "entity-1", "concept")
        client._call.assert_called_with("get_citations", ["ws1", "entity-1", "concept"])
        client._query.assert_called_once()

    def test_add_node_citation(self, client):
        client.add_node_citation("ws1", "node-1", "mem-1", "citation desc")
        client._call.assert_called_with(
            "add_node_citation", ["ws1", "node-1", "mem-1", "citation desc"]
        )

    def test_add_edge_citation(self, client):
        client.add_edge_citation("ws1", "src", "tgt", "desc")
        client._call.assert_called_with("add_edge_citation", ["ws1", "src", "tgt", "desc"])

    def test_get_edge_history(self, client):
        client.get_edge_history("eg-1")
        client._call.assert_called_with("get_edge_history", ["eg-1"])
        client._sql.assert_called_once()

    def test_create_document(self, client):
        client.create_document("ws1", "title", "content", {"key": "val"})
        client._call.assert_called()

    def test_detect_communities(self, client):
        client.detect_communities("ws1")
        client._call.assert_called_with("detect_communities", ["ws1"])

    def test_seed_communities(self, client):
        client.seed_communities("ws1")
        client._call.assert_called_with("seed_communities", ["ws1"])

    def test_get_edges_with_labels(self, client):
        """get_neighbors resolves node IDs to labels."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])
        c._call = Mock(
            return_value=[
                {"source_node_id": "n1", "target_node_id": "n2", "weight": 1.0},
            ]
        )
        # _query side-effect: edges_src, edges_tgt, then node resolutions
        calls = []

        def mock_query(*args, **kw):
            calls.append((args, kw))
            if "source_node_id" in str(kw.get("filter_dict", {})):
                return [{"id": "e1", "source_node_id": "n1", "target_node_id": "n2", "weight": 1.0}]
            if "target_node_id" in str(kw.get("filter_dict", {})):
                return []
            # Node ID resolution — return both labels
            filt = kw.get("filter_dict", {})
            nid = filt.get("id", "")
            return [{"id": nid, "label": f"Label-{nid}"}]

        c._query = mock_query

        edges = c.get_neighbors("n1", "ws1")
        assert len(edges) == 1
        assert edges[0]["source_label"] == "Label-n1"
        assert edges[0]["target_label"] == "Label-n2"

    def test_run_maintenance(self, client):
        client.run_maintenance()
        client._call.assert_called_with("manual_maintenance", [])

    def test_dedup(self, client):
        client.dedup("ws1")
        client._call.assert_called_with("dedup_memories", ["ws1"])

    def test_suggest_merges(self, client):
        client.suggest_merges("ws1", 0.85)
        client._call.assert_called_with("suggest_merges", ["ws1", 0.85])

    def test_consolidate_memories(self, client):
        """consolidate_memories calls reducer with JSON-serialized source_ids."""
        source_ids = ["mem-1", "mem-2", "mem-3"]
        client.consolidate_memories("ws1", source_ids, "merged content", "merged summary")
        client._call.assert_called_with(
            "consolidate_memories",
            ["ws1", json.dumps(source_ids), "merged content", "merged summary"],
        )

    def test_get_profile_context(self, client):
        """get_profile_context calls the reducer and reads the result table."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[{"peer_id": "p1", "context": "profile data"}])
        result = c.get_profile_context("p1")
        c._call.assert_called_with("get_profile_context", ["p1"])
        assert result["context"] == "profile data"

    def test_get_profile_context_empty(self, client):
        """get_profile_context returns None when no rows."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        result = c.get_profile_context("unknown")
        assert result is None


# ── More stubs ─────────────────────────────────────────────────────────


class TestMoreStubs:
    """Remaining one-liner stubs."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_list_memories(self, client):
        client.list_memories("ws1", memory_type="experience")
        client._query.assert_called()

    def test_list_memories_no_filter(self, client):
        client.list_memories("ws1")
        client._query.assert_called()

    def test_set_decay_model_raises_on_bad_model(self):
        c = Client(host="localhost", port="3001", database="test-db")
        with pytest.raises(ValueError, match="model"):
            c.set_decay_model("ws1", "bad_model")

    def test_set_decay_model_linear(self, client):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        result = c.set_decay_model("ws1", "linear")
        assert result["status"] == "ok"

    def test_set_decay_model_weibull(self, client):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[])  # store() id-resolution hits _query; keep off the wire
        result = c.set_decay_model("ws1", "weibull", weibull_shape=0.8, weibull_scale=25.0)
        assert result["status"] == "ok"

    def test_approve_merge(self, client):
        client.approve_merge("sug-1")
        client._call.assert_called_with("approve_merge", ["sug-1"])

    def test_reject_merge(self, client):
        client.reject_merge("sug-1")
        client._call.assert_called_with("reject_merge", ["sug-1"])

    def test_get_node(self, client):
        client.get_node("node-1")
        client._query.assert_called_with("kg_node", filter_dict={"id": "node-1"})

    def test_get_community(self, client):
        client.get_community(42)
        client._query.assert_any_call("kg_community", filter_dict={"id": "42"})
        client._query.assert_any_call("kg_node", filter_dict={"community_id": "42"})


# ── Note CRUD ──────────────────────────────────────────────────────────


class TestNoteCrudStubs:
    """Note CRUD methods (lines 2525, 2531-2548)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_delete_note(self, client):
        client.delete_note("note-1")
        client._call.assert_called_with("delete_note", ["note-1"])

    def test_list_notes(self, client):
        client.list_notes("ws1")
        client._query.assert_called()

    def test_list_notes_include_inactive(self, client):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])
        c.list_notes("ws1", include_inactive=True)
        c._query.assert_called()

    def test_get_note(self, client):
        client.get_note("note-1")
        client._query.assert_called_with("note", filter_dict={"id": "note-1"})

    def test_get_note_by_date(self, client):
        client.get_note_by_date("2026-06-22")
        client._query.assert_called_with(
            "note", filter_dict={"note_date": "2026-06-22", "is_active": "true"}
        )

    def test_get_note_by_title(self, client):
        client.get_note_by_title("My Note")
        client._query.assert_called_with(
            "note", workspace_id="", filter_dict={"title": "My Note", "is_active": "true"}
        )


class TestNoteSearchIndexing:
    """Note search indexing: create_note, update_note, delete_note index
    into search_index so hybrid search returns notes alongside memories."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock()
        c._embed = Mock(return_value=[0.1, 0.2, 0.3])
        c._tantivy_index = Mock(return_value=True)
        return c

    def test_create_note_calls_index_entity(self, client):
        """create_note with content must call index_entity + index_terms."""
        client._query.side_effect = [
            # First call: resolve note ID by content match
            [{"id": "note-abc", "content": "My test content", "title": "Test"}],
        ]
        client.create_note(
            workspace_id="ws-1",
            title="Test Note",
            content="My test content",
            embed=True,
        )
        # Should call create_note reducer (embedding is [0.1,0.2,0.3] from mock)
        client._call.assert_any_call(
            "create_note",
            [
                "ws-1",
                "Test Note",
                "My test content",
                "",
                "[0.1, 0.2, 0.3]",
            ],
        )
        # Should call index_entity for search index
        client._call.assert_any_call(
            "index_entity",
            [
                "ws-1",
                "note",
                "note-abc",
                "My test content",
                "[0.1, 0.2, 0.3]",
            ],
        )
        # Should call index_terms for BM25
        client._call.assert_any_call(
            "index_terms",
            [
                "ws-1",
                "note",
                "note-abc",
                "My test content",
            ],
        )
        # Should index into Tantivy
        client._tantivy_index.assert_called_with(
            "ws-1",
            "note-abc",
            "My test content",
            "note",
        )

    def test_create_note_no_index_when_status_not_ok(self, client):
        """create_note must NOT call index_entity when reducer fails."""
        client._call = Mock(return_value={"error": "failed"})
        client._query = Mock(return_value=[])
        client.create_note(
            workspace_id="ws-1",
            title="Fail",
            content="any content",
            embed=True,
        )
        # Should only have called create_note
        calls = [c[0][0] for c in client._call.call_args_list]
        for cname in ("index_entity", "index_terms"):
            assert cname not in calls, f"{cname} should not be called on failure"

    def test_update_note_reindexes(self, client):
        """update_note must call remove_from_index + index_entity."""
        client._query.side_effect = [
            [{"id": "note-abc", "workspace_id": "ws-1", "content": "Updated content"}],
        ]
        client.update_note("note-abc", title="Updated", content="Updated content", embed=True)
        # Should remove old index entries
        client._call.assert_any_call("remove_from_index", ["note", "note-abc"])
        # Should re-index with new content
        client._call.assert_any_call(
            "index_entity",
            [
                "ws-1",
                "note",
                "note-abc",
                "Updated content",
                "[0.1, 0.2, 0.3]",
            ],
        )
        client._call.assert_any_call(
            "index_terms",
            [
                "ws-1",
                "note",
                "note-abc",
                "Updated content",
            ],
        )

    def test_update_note_resolves_workspace_id(self, client):
        """update_note queries the note to resolve workspace_id."""
        client._query.side_effect = [
            [{"id": "n1", "workspace_id": "ws-42", "content": "x"}],
        ]
        client.update_note("n1", content="x", embed=False)
        client._call.assert_any_call(
            "index_entity",
            [
                "ws-42",
                "note",
                "n1",
                "x",
                "[]",
            ],
        )

    def test_delete_note_removes_from_index(self, client):
        """delete_note must call remove_from_index."""
        client.delete_note("note-abc")
        client._call.assert_any_call("delete_note", ["note-abc"])
        client._call.assert_any_call("remove_from_index", ["note", "note-abc"])

    def test_delete_note_no_cleanup_on_failure(self, client):
        """delete_note must NOT call remove_from_index when deletion fails."""
        client._call = Mock(return_value={"error": "not found"})
        client.delete_note("note-missing")
        calls = [c[0][0] for c in client._call.call_args_list]
        assert "remove_from_index" not in calls

    def test_enrich_content_handles_note_entity_type(self):
        """_enrich_content must look up note content for entity_type='note'."""
        c = Client(host="h", port="1", database="d")
        c._query = Mock(
            return_value=[
                {"id": "n1", "title": "My Note", "content": "Hello world"},
            ]
        )
        rows = [
            {"entity_id": "n1", "entity_type": "note", "fused_score": 0.9},
        ]
        result = c._enrich_content(rows, "ws-1")
        assert result[0]["memory_content"] == "My Note\n\nHello world"
        c._query.assert_called_with(
            "note",
            workspace_id="ws-1",
            columns=["id", "title", "content"],
        )

    def test_keyword_fallback_includes_notes(self):
        """_keyword_fallback must merge notes with memories."""
        c = Client(host="h", port="1", database="d")
        c._query = Mock(
            side_effect=[
                # First call: memory query
                [{"id": "m1", "content": "alpha memory", "created_at": 100}],
                # Second call: note query
                [{"id": "n1", "content": "beta note", "title": "Beta", "created_at": 200}],
                # _boost_with_entity_signal: kg_node query
                [],
                # _boost_with_entity_signal: entity_link query
                [],
            ]
        )
        c._emit_event = Mock()
        results = c._keyword_fallback("ws-1", "beta", "", "", 10)
        # Must include the note
        ids = [r["id"] for r in results]
        assert "n1" in ids
        assert results[0]["entity_type"] == "note"
        # Note (200) sorted before memory (100) due to created_at desc
        assert results[0]["id"] == "n1"

    def test_keyword_fallback_applies_entity_boost(self):
        """_keyword_fallback calls _boost_with_entity_signal when query is set."""
        c = Client(host="h", port="1", database="d")
        c._query = Mock(
            side_effect=[
                # First call: memory query
                [{"id": "m1", "content": "RLHF is a technique", "created_at": 100}],
                # Second call: note query
                [],
                # _boost_with_entity_signal: kg_node query
                [],
                # _boost_with_entity_signal: entity_link query
                [],
            ]
        )
        c._emit_event = Mock()
        # Mock the boost method to track that it was called
        c._boost_with_entity_signal = Mock(wraps=c._boost_with_entity_signal)
        c._keyword_fallback("ws-1", "RLHF", "", "", 10)
        c._boost_with_entity_signal.assert_called_once()
        args, _ = c._boost_with_entity_signal.call_args
        assert args[0] == "RLHF"  # query
        assert len(args[1]) == 1  # rows
        assert args[2] == "ws-1"  # workspace_id

    def test_keyword_fallback_boost_no_crash_empty_query(self):
        """_keyword_fallback with empty query still works (no boost applied)."""
        c = Client(host="h", port="1", database="d")
        c._query = Mock(
            side_effect=[
                [{"id": "m1", "content": "test", "created_at": 100}],
                [],
            ]
        )
        c._emit_event = Mock()
        c._boost_with_entity_signal = Mock()
        results = c._keyword_fallback("ws-1", "", "", "", 10)
        c._boost_with_entity_signal.assert_not_called()
        assert len(results) == 1

    def test_keyword_fallback_boost_no_crash_no_entities(self):
        """_keyword_fallback with query but no KG entities doesn't crash."""
        c = Client(host="h", port="1", database="d")
        c._query = Mock(
            side_effect=[
                [{"id": "m1", "content": "hello world content", "created_at": 100}],
                [],
            ]
        )
        c._emit_event = Mock()
        c._boost_with_entity_signal = Mock(
            wraps=lambda q, rows, ws: rows  # passthrough
        )
        results = c._keyword_fallback("ws-1", "hello", "", "", 10)
        assert len(results) == 1
        # Should have fused_score from baseline assignment
        assert "fused_score" in results[0]
