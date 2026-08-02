"""Deep integration tests for client.py — Embedding module.

Includes: _mk_embed helpers, TestEmbedMethods, TestExtractEntities,
TestStoreEntityExtraction, TestStoreBatchIndexing, TestLLMRerank,
TestLLMRerankDeep.
"""

from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import httpx
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]


# ── Embed method helpers ─────────────────────────────


def _mk_embed_success(*embeddings):
    """Mock HTTP client that returns successful embedding responses."""
    data = {"data": [{"embedding": e} for e in embeddings]}
    mock_http = Mock(spec=httpx.Client)
    mock_resp = Mock(spec=httpx.Response, status_code=200)
    mock_resp.json.return_value = data
    mock_resp.raise_for_status.return_value = None
    mock_http.post.return_value = mock_resp
    return mock_http


def _mk_embed_error(status=500):
    """Mock HTTP client that raises HTTPStatusError."""
    mock_http = Mock(spec=httpx.Client)
    mock_resp = Mock(spec=httpx.Response, status_code=status)
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "error", request=Mock(), response=mock_resp
    )
    mock_http.post.return_value = mock_resp
    return mock_http


def _mk_embed_timeout():
    mock_http = Mock(spec=httpx.Client)
    mock_http.post.side_effect = httpx.TimeoutException("timeout")
    return mock_http


def _mk_embed_badjson():
    mock_http = Mock(spec=httpx.Client)
    mock_resp = Mock(spec=httpx.Response, status_code=200)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
    mock_http.post.return_value = mock_resp
    return mock_http


# =====================================================================
# Embed method coverage
# =====================================================================


class TestEmbedMethods:
    """Tests for _embed_openai, _embed_batch_openai, and _embed."""

    _env = {"OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": "http://mock/v1"}

    def test_embed_openai_success(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_success([0.1, 0.2])
        with patch.dict(os.environ, self._env):
            assert c._embed_openai("hello") == [0.1, 0.2]

    def test_embed_openai_no_key(self):
        c = Client(host="localhost", port=3001)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=True):
            assert c._embed_openai("hello") == []

    def test_embed_openai_http_error(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_error(503)
        with patch.dict(os.environ, self._env):
            assert c._embed_openai("hello") == []

    def test_embed_openai_timeout(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_timeout()
        with patch.dict(os.environ, self._env):
            assert c._embed_openai("hello") == []

    def test_embed_openai_bad_json(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_badjson()
        with patch.dict(os.environ, self._env):
            assert c._embed_openai("hello") == []

    def test_embed_batch_success(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_success([1.0, 2.0], [3.0, 4.0])
        with patch.dict(os.environ, self._env):
            assert c._embed_batch_openai(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]

    def test_embed_batch_empty(self):
        c = Client(host="localhost", port=3001)
        assert c._embed_batch_openai([]) == []

    def test_embed_batch_no_key(self):
        c = Client(host="localhost", port=3001)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=True):
            assert c._embed_batch_openai(["x"]) == []

    def test_embed_batch_timeout(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_timeout()
        with patch.dict(os.environ, self._env):
            assert c._embed_batch_openai(["x"]) == []

    def test_embed_batch_http_error(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_error(502)
        with patch.dict(os.environ, self._env):
            assert c._embed_batch_openai(["x"]) == []

    def test_embed_batch_bad_json(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_badjson()
        with patch.dict(os.environ, self._env):
            assert c._embed_batch_openai(["x"]) == []

    def test_embed_success(self):
        c = Client(host="localhost", port=3001)
        c._http = _mk_embed_success([0.5, 0.6])
        with patch.dict(os.environ, self._env):
            assert c._embed("hi") == [0.5, 0.6]


# ── Entity extraction coverage ───────────────────────


class TestExtractEntities:
    """Mock-based tests for _extract_and_store_entities."""

    def test_extract_entities_with_llm(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"ok": True})

        class ML:
            available = True

            def extract_entities_llm(self, content):
                return [
                    {
                        "name": "Alice",
                        "entity_type": "person",
                        "aliases": ["Al"],
                        "description": "A person",
                    }
                ]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws-1", "mem-1", "Alice went")
        create_calls = [a[0][0] for a in c._call.call_args_list if a[0][0] == "create_entity_link"]
        assert len(create_calls) == 1

    def test_extract_entities_runtime_error_resilience(self):
        c = Client(host="localhost", port=3001)
        log = []

        def mc(r, a):
            log.append(r)
            if r == "create_entity_link":
                raise RuntimeError("exists")
            return {"ok": True}

        c._call = mc

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return [{"name": "Bob", "entity_type": "person", "aliases": [], "description": "B"}]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws", "mem", "Bob")
        assert "link_entity_to_memory" in log

    def test_extract_entities_regex_fallback(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"ok": True})

        class ML:
            available = False

            def extract_entities_llm(self, c):
                return None

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws", "mem", "content")
        ec = [a[0][0] for a in c._call.call_args_list if a[0][0] == "extract_entities"]
        assert len(ec) == 1

    def test_extract_entities_null_llm_result(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"ok": True})

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return None

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws", "mem", "content")
        ec = [a[0][0] for a in c._call.call_args_list if a[0][0] == "extract_entities"]
        assert len(ec) == 1

    def test_extract_entities_regex_error_caught(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(side_effect=RuntimeError("nope"))

        class ML:
            available = False

            def extract_entities_llm(self, c):
                return None

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws", "mem", "content")
        # Should not raise

    def test_extract_entities_empty_name_skipped(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"ok": True})

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return [{"name": "", "entity_type": "x", "aliases": [], "description": "x"}]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws", "mem", "content")
        create6 = [a[0][0] for a in c._call.call_args_list if a[0][0] == "create_entity_link"]
        assert len(create6) == 0

    def test_extract_entities_link_error_caught(self):
        c = Client(host="localhost", port=3001)

        def mc(r, a):
            if r == "link_entity_to_memory":
                raise RuntimeError("no link")
            return {"ok": True}

        c._call = mc

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return [{"name": "Eve", "entity_type": "person", "aliases": [], "description": "E"}]

        with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
            c._extract_and_store_entities("ws", "mem", "Eve")
        # Should not raise


# ── Store entity extraction coverage ────────────────


class TestStoreEntityExtraction:
    """Mock tests for store() entity extraction + binary cache + indexing."""

    def test_store_with_entity_extraction(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok", "id": "mem-123"})
        c._query = Mock(return_value=[{"id": "mem-123", "content": "test"}])
        c._tantivy_index = Mock()
        c._embed = lambda t: [0.1] * 768

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return [{"name": "E", "entity_type": "concept", "aliases": [], "description": "E"}]

        with patch("spacetime_memory.binary_vectors.binarize", return_value=b"\x00" * 32):
            with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
                c.store("ws", "test", summary="s", memory_type="experience", peer_id="p")
        calls = [a[0][0] for a in c._call.call_args_list if isinstance(a[0], (list, tuple))]
        assert "index_entity" in calls
        assert "index_terms" in calls
        assert c._tantivy_index.call_count >= 1

    def test_store_binarize_failure_non_critical(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[{"id": "mem-456", "content": "test"}])
        c._tantivy_index = Mock()
        c._embed = lambda t: [0.1] * 768

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return [{"name": "E", "entity_type": "c", "aliases": [], "description": "E"}]

        with patch("spacetime_memory.binary_vectors.binarize", side_effect=ValueError("bad")):
            with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
                c.store("ws", "test", summary="s", memory_type="experience", peer_id="p")
        # Should not raise

    def test_store_with_tier_update(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[{"id": "mem-789", "content": "test"}])
        c._tantivy_index = Mock()
        c._embed = lambda t: [0.1] * 768

        class ML:
            available = True

            def extract_entities_llm(self, c):
                return [{"name": "E", "entity_type": "c", "aliases": [], "description": "E"}]

        with patch("spacetime_memory.binary_vectors.binarize", return_value=b"\x00"):
            with patch("spacetime_memory.client.llm.LLMClient", return_value=ML()):
                c.store("ws", "test", summary="s", memory_type="experience", peer_id="p", tier="L1")
        tc = [a[0][0] for a in c._call.call_args_list if a[0][0] == "update_memory_tier"]
        assert len(tc) == 1

    def test_store_no_matching_memory_skips_indexing(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._query = Mock(return_value=[])
        c._tantivy_index = Mock()
        c.store("ws", "bare content", summary="s", memory_type="experience", peer_id="p")
        # Should succeed without indexing


# ── Store batch indexing coverage ───────────────────


class TestStoreBatchIndexing:
    """Mock tests for store_batch embedding and indexing."""

    def test_store_batch_with_embeddings(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        c._http = Mock()
        c._http.post.return_value = mock_resp
        c._query = Mock(return_value=[
            {"id": "b1", "content": "item1", "created_at": 1000},
            {"id": "b2", "content": "item2", "created_at": 1001},
        ])
        c._extract_and_store_entities = Mock()
        items = [
            {"content": "item1", "summary": "s1", "memory_type": "experience", "peer_id": "p1"},
            {"content": "item2", "summary": "s2", "memory_type": "experience", "peer_id": "p2"},
        ]
        c.store_batch("ws", items)
        bc = [a[0][0] for a in c._call.call_args_list if a[0][0] == "store_memory_batch"]
        ebc = [a[0][0] for a in c._call.call_args_list if a[0][0] == "index_entity_batch"]
        assert len(bc) == 1, "expected 1 store_memory_batch call"
        assert len(ebc) == 1, "expected 1 index_entity_batch call"

    def test_store_batch_embedder_error(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        c._http = Mock()
        c._http.post.return_value = Mock(status_code=500)
        c._query = Mock(return_value=[
            {"id": "b1", "content": "x", "created_at": 1000},
        ])
        c._extract_and_store_entities = Mock()
        c.store_batch("ws", [{"content": "x", "summary": "s", "memory_type": "e", "peer_id": "p"}])
        bc = [a[0][0] for a in c._call.call_args_list if a[0][0] == "store_memory_batch"]
        ebc = [a[0][0] for a in c._call.call_args_list if a[0][0] == "index_entity_batch"]
        assert len(bc) == 1, "expected 1 store_memory_batch call"
        assert len(ebc) == 0, "expected 0 index_entity_batch calls (no embeddings)"

    def test_store_batch_single_embedding_response(self):
        c = Client(host="localhost", port=3001)
        c._call = Mock(return_value={"status": "ok"})
        mock = Mock(status_code=200)
        mock.json.return_value = {"data": [{"embedding": [0.9]}]}
        c._http = Mock()
        c._http.post.return_value = mock
        c._query = Mock(return_value=[{"id": "b1", "content": "x1", "created_at": 1}])
        c._extract_and_store_entities = Mock()
        c.store_batch("ws", [{"content": "x1", "summary": "s", "memory_type": "e", "peer_id": "p"}])
        ebc = [a[0][0] for a in c._call.call_args_list if a[0][0] == "index_entity_batch"]
        assert len(ebc) == 1, "expected 1 index_entity_batch call"


# =====================================================================
# MCP-style helpers: llm_rerank
# =====================================================================


class TestLLMRerank:
    """Test llm_rerank standalone function with mocked HTTP."""

    def _get_fn(self):
        from spacetime_memory.client import llm_rerank

        return llm_rerank

    def test_llm_rerank_empty_results(self):
        """Empty results list returns immediately."""
        fn = self._get_fn()
        result = fn("test query", [])
        assert result == []

    def test_llm_rerank_no_endpoint_available(self):
        """llm_rerank gracefully falls back when LLM is unreachable."""
        fn = self._get_fn()
        results = [
            {"content": "Result A about dogs", "score": 0.8},
            {"content": "Result B about cats", "score": 0.7},
        ]
        # With no real LLM endpoint, this should fall back and return
        # the original results
        result = fn(
            "dogs and cats",
            results,
            endpoint="http://127.0.0.1:19999/v1",  # nonexistent
            model="test-model",
            api_key="",
            timeout=2,
        )
        # Should return the original results (fallback behavior)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_llm_rerank_with_mock_success(self):
        """llm_rerank with a mocked successful LLM response."""
        fn = self._get_fn()
        import json as _json

        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": _json.dumps(
                            [
                                {"index": 0, "score": 9, "reason": "highly relevant"},
                                {"index": 1, "score": 5, "reason": "somewhat relevant"},
                            ]
                        )
                    }
                }
            ]
        }

        results = [
            {"content": "Important document about AI", "score": 0.8},
            {"content": "Random unrelated text", "score": 0.7},
        ]

        with patch("httpx.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None
            mock_post.return_value = mock_resp

            result = fn(
                "AI document",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
            )

        assert len(result) == 2
        # The reranked results should have rerank_reason
        assert "rerank_reason" in result[0]
        assert "score" in result[0]

    def test_llm_rerank_reasoning_content_fallback(self):
        """llm_rerank falls back to reasoning_content when content is empty."""
        fn = self._get_fn()
        import json as _json

        # Simulate a reasoning model that puts output in reasoning_content
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": _json.dumps(
                            [
                                {"index": 0, "score": 10, "reason": "perfect match"},
                            ]
                        ),
                    }
                }
            ]
        }

        results = [{"content": "Critical security patch", "score": 0.9}]

        with patch("httpx.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None
            mock_post.return_value = mock_resp

            result = fn(
                "security",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="reasoning-model",
                api_key="sk-test",
            )

        assert len(result) == 1
        assert result[0]["rerank_reason"] == "perfect match"
        assert result[0]["score"] == 1.0  # 10/10

    def test_llm_rerank_rate_limit_then_success(self):
        """llm_rerank retries on 429 and succeeds."""
        fn = self._get_fn()
        import json as _json

        success_response = {
            "choices": [
                {
                    "message": {
                        "content": _json.dumps(
                            [
                                {"index": 0, "score": 8, "reason": "good"},
                            ]
                        ),
                    }
                }
            ]
        }

        results = [{"content": "Test content", "score": 0.5}]

        with patch("httpx.post") as mock_post:
            rate_limit = Mock()
            rate_limit.status_code = 429

            success = Mock()
            success.status_code = 200
            success.json.return_value = success_response
            success.raise_for_status = lambda: None

            mock_post.side_effect = [rate_limit, success]

            result = fn(
                "test",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
            )

        assert len(result) == 1
        assert result[0]["score"] == 0.8
        assert mock_post.call_count == 2

    def test_llm_rerank_http_error_fallback(self):
        """llm_rerank falls back gracefully on HTTP error."""
        fn = self._get_fn()

        results = [
            {"content": "Important content A", "score": 0.9},
            {"content": "Important content B", "score": 0.8},
        ]

        with patch("httpx.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 500
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=Mock(),
                response=mock_resp,
            )
            mock_post.return_value = mock_resp

            result = fn(
                "important",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
                timeout=2,
            )

        # Should fall back to original results
        assert len(result) == 2
        assert result[0]["content"] == "Important content A"

    def test_llm_rerank_connect_error_fallback(self):
        """llm_rerank falls back on connection error."""
        fn = self._get_fn()

        results = [{"content": "Solo result", "score": 0.6}]

        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            result = fn(
                "solo",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
                timeout=2,
            )

        assert len(result) == 1
        assert result[0]["content"] == "Solo result"

    def test_llm_rerank_malformed_json_fallback(self):
        """llm_rerank raises ValueError when LLM returns truly malformed JSON
        that cannot be parsed by any strategy. The _parse_rerank_json helper
        raises ValueError after all 6 strategies fail, and llm_rerank does
        NOT swallow ValueError (it only catches JSONDecodeError, HTTP errors,
        and connection errors)."""
        fn = self._get_fn()

        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": "This is not JSON at all, just garbage output with no braces",
                    }
                }
            ]
        }

        results = [{"content": "Test content", "score": 0.5}]

        with patch("httpx.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None
            mock_post.return_value = mock_resp

            with pytest.raises(ValueError, match="JSON parse failed"):
                fn(
                    "test",
                    results,
                    endpoint="http://mock-llm:4000/v1",
                    model="mock-model",
                    api_key="sk-test",
                )


# =====================================================================
# llm_rerank remaining branches
# =====================================================================


class TestLLMRerankDeep:
    """Cover remaining llm_rerank branches: rate-limit exhaustion,
    markdown code fence stripping, unranked result penalty."""

    def _get_fn(self):
        from spacetime_memory.client import llm_rerank

        return llm_rerank

    def test_llm_rerank_markdown_fence_stripping(self):
        """llm_rerank strips ``` fences from content."""
        fn = self._get_fn()

        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '```json\\n[{"index": 0, "score": 8, "reason": "fenced"}]\\n```',
                    }
                }
            ]
        }

        results = [{"content": "Fenced test content", "score": 0.7}]

        with patch("httpx.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None
            mock_post.return_value = mock_resp

            result = fn(
                "test",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
            )

        assert len(result) == 1
        assert result[0]["rerank_reason"] == "fenced"
        assert result[0]["score"] == 0.8

    def test_llm_rerank_rate_limit_exhaustion(self):
        """llm_rerank raises after 3 retries all return 429."""
        fn = self._get_fn()

        results = [{"content": "Rate limited test", "score": 0.5}]

        with patch("httpx.post") as mock_post:
            rate_limit = Mock()
            rate_limit.status_code = 429

            # All 3 attempts return 429
            mock_post.side_effect = [rate_limit, rate_limit, rate_limit]

            # Should fall back gracefully (the for/else block raises
            # HTTPStatusError which is caught by the except handler)
            result = fn(
                "test",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
                timeout=1,
            )

        # Should return original results (fallback behavior)
        assert len(result) == 1
        assert result[0]["content"] == "Rate limited test"

    def test_llm_rerank_unranked_penalty(self):
        """llm_rerank penalizes results not found in LLM response."""
        fn = self._get_fn()
        import json as _json

        # LLM only returns score for index 0, not index 1
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": _json.dumps(
                            [
                                {"index": 0, "score": 9, "reason": "ranked"},
                            ]
                        ),
                    }
                }
            ]
        }

        results = [
            {"content": "Ranked result", "score": 0.9},
            {"content": "Unranked result", "score": 0.8},  # Not in LLM output
        ]

        with patch("httpx.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None
            mock_post.return_value = mock_resp

            result = fn(
                "test",
                results,
                endpoint="http://mock-llm:4000/v1",
                model="mock-model",
                api_key="sk-test",
            )

        assert len(result) == 2
        # Unranked result should be penalized (score * 0.5 = 0.4)
        unranked = next(r for r in result if r["content"] == "Unranked result")
        assert unranked["score"] == 0.4  # 0.8 * 0.5
        assert unranked["rerank_reason"] == "not reranked by LLM"
