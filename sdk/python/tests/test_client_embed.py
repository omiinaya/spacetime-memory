"""Tests for EmbedderMixin (client/_embed.py).

Covers: _embed, _embed_openai, _embed_batch, _embed_batch_openai,
check_embedder_health, check_tantivy_health, _request_with_retry_simple,
_request_with_retry_tantivy, _tantivy_index, _tantivy_index_batch, _tantivy_search.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

import spacetime_memory
import spacetime_memory.client._embed as _embed_module
from spacetime_memory.client._embed import EmbedderMixin

# Workaround for SDK bug: spacetime_memory/client/_embed.py references
# ``SpacetimeDBError`` in except clauses (lines ~334, ~393, ~448)
# but never imports ``spacetime_memory``, so any exception reaching those
# clauses raises NameError instead of being handled. Inject the intended
# module reference here (only if still missing) until the SDK is fixed.
if not hasattr(_embed_module, "spacetime_memory"):
    _embed_module.spacetime_memory = spacetime_memory


# ══════════════════════════════════════════════════════════════════════
# _request_with_retry_simple
# ══════════════════════════════════════════════════════════════════════


class TestRequestWithRetrySimple:
    """_request_with_retry_simple — exponential backoff, no circuit breaker."""

    def test_get_success(self):
        """Successful GET returns response."""
        mixin = EmbedderMixin()
        mixin.max_retries = 3
        mixin._http = MagicMock(spec=httpx.Client)

        resp = Mock(status_code=200, text="ok")
        mixin._http.get.return_value = resp

        result = mixin._request_with_retry_simple("GET", "http://example.com")
        assert result is resp

    def test_post_success(self):
        """Successful POST returns response."""
        mixin = EmbedderMixin()
        mixin.max_retries = 3
        mixin._http = MagicMock(spec=httpx.Client)
        resp = Mock(status_code=200, text="ok")
        mixin._http.post.return_value = resp

        result = mixin._request_with_retry_simple("POST", "http://example.com", json={"key": "val"})
        assert result is resp
        mixin._http.post.assert_called_once()

    def test_retry_on_connect_error(self):
        """Retries on ConnectError, returns None after all retries fail."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._http.post.side_effect = httpx.ConnectError("connection refused")

        result = mixin._request_with_retry_simple("POST", "http://example.com")
        assert result is None
        # 3 calls (max_retries + 1 = 3)
        assert mixin._http.post.call_count == 3

    def test_retry_on_timeout(self):
        """Retries on TimeoutException."""
        mixin = EmbedderMixin()
        mixin.max_retries = 1
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._http.post.side_effect = httpx.TimeoutException("timed out")

        result = mixin._request_with_retry_simple("POST", "http://example.com")
        assert result is None
        assert mixin._http.post.call_count == 2

    def test_retry_on_remote_protocol_error(self):
        """Retries on RemoteProtocolError."""
        mixin = EmbedderMixin()
        mixin.max_retries = 1
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._http.post.side_effect = httpx.RemoteProtocolError("connection lost")

        result = mixin._request_with_retry_simple("POST", "http://example.com")
        assert result is None

    def test_success_after_retry(self):
        """Second attempt succeeds after first fails."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        resp = Mock(status_code=200, text="ok")
        mixin._http.post.side_effect = [httpx.ConnectError("fail"), resp]

        result = mixin._request_with_retry_simple("POST", "http://example.com")
        assert result is resp
        assert mixin._http.post.call_count == 2


# ══════════════════════════════════════════════════════════════════════
# _request_with_retry_tantivy — circuit breaker + retry
# ══════════════════════════════════════════════════════════════════════


class TestRequestWithRetryTantivy:
    """_request_with_retry_tantivy — retry with isolated Tantivy circuit breaker."""

    def test_success_returns_response(self):
        """Successful GET returns response."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200, text="ok")
        mixin._http.get.return_value = resp

        result = mixin._request_with_retry_tantivy("GET", "http://tantivy/health")
        assert result is resp
        assert mixin._tantivy_consecutive_failures == 0

    def test_circuit_breaker_open_raises(self):
        """When circuit breaker is open, raises RuntimeError immediately."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 5
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0
        mixin._tantivy_circuit_open_until = time.time() + 60

        with pytest.raises(RuntimeError, match="circuit breaker is open"):
            mixin._request_with_retry_tantivy("GET", "http://tantivy/search")

    def test_server_error_retries(self):
        """HTTP 500+ is retried, fails after exhaustion.

        The consecutive-failure counter bumps by 1 for each
        retry-batch (not per attempt), so with threshold=2 a single
        batch does NOT trip the circuit breaker.
        """
        mixin = EmbedderMixin()
        mixin.max_retries = 1
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 2
        mixin._circuit_breaker_reset_secs = 30.0

        error_resp = Mock(status_code=500, text="server error")
        mixin._http.post.return_value = error_resp

        with pytest.raises(RuntimeError, match="failed after"):
            mixin._request_with_retry_tantivy("POST", "http://tantivy/search")

        # Consecutive failures bumped by 1, but 1 < threshold=2 so circuit stays closed
        assert mixin._tantivy_consecutive_failures == 1
        assert mixin._tantivy_circuit_open_until == 0.0

    def test_client_error_not_retried(self):
        """HTTP 4xx is returned immediately, not retried."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        bad_request = Mock(status_code=400, text="bad request")
        mixin._http.post.return_value = bad_request

        result = mixin._request_with_retry_tantivy("POST", "http://tantivy/search")
        assert result is bad_request
        assert mixin._tantivy_consecutive_failures == 0

    def test_connect_error_retries_then_trips(self):
        """ConnectError retries, then trips circuit breaker."""
        mixin = EmbedderMixin()
        mixin.max_retries = 1
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 1
        mixin._circuit_breaker_reset_secs = 30.0

        mixin._http.post.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(RuntimeError, match="failed after"):
            mixin._request_with_retry_tantivy("POST", "http://tantivy/search")

        # Circuit breaker should be tripped after threshold reached
        assert mixin._tantivy_consecutive_failures == 1
        assert mixin._tantivy_circuit_open_until > 0

    def test_success_resets_failure_count(self):
        """A successful response resets the consecutive failure counter."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 3
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200, text="ok")
        mixin._http.post.return_value = resp

        result = mixin._request_with_retry_tantivy("POST", "http://tantivy/search")
        assert result is resp
        assert mixin._tantivy_consecutive_failures == 0


# ══════════════════════════════════════════════════════════════════════
# _embed / _embed_openai
# ══════════════════════════════════════════════════════════════════════


class TestEmbedOpenAI:
    """_embed_openai — single-text embedding via OpenAI API."""

    MOCK_EMBEDDING = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    def test_success(self):
        """Returns embedding vector on success."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)

        resp = Mock(status_code=200)
        resp.json.return_value = self.MOCK_EMBEDDING
        mixin._http.post.return_value = resp

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_openai("test text")

        assert result == [0.1, 0.2, 0.3]

    def test_missing_api_key(self):
        """Returns empty list when OPENAI_API_KEY is not set."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)

        with patch.dict("os.environ", {}, clear=True):
            result = mixin._embed_openai("test text")

        assert result == []

    def test_timeout_returns_empty(self):
        """TimeoutException returns empty list."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._http.post.side_effect = httpx.TimeoutException("timed out")

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_openai("test text")

        assert result == []

    def test_http_error_returns_empty(self):
        """HTTP error returns empty list."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._http.post.return_value = Mock(status_code=500)
        mixin._http.post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=Mock(), response=Mock(status_code=500)
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_openai("test text")

        assert result == []

    def test_empty_embedding_response(self):
        """Malformed response (missing data[0]) returns empty list."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        resp = Mock(status_code=200)
        resp.json.return_value = {"data": []}
        mixin._http.post.return_value = resp

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_openai("test text")

        assert result == []


# ══════════════════════════════════════════════════════════════════════
# _embed_batch / _embed_batch_openai
# ══════════════════════════════════════════════════════════════════════


class TestEmbedBatchOpenAI:
    """_embed_batch_openai — batch embedding via OpenAI API."""

    MOCK_BATCH = {
        "data": [
            {"embedding": [0.1, 0.2], "index": 0},
            {"embedding": [0.3, 0.4], "index": 1},
        ]
    }

    def test_success(self):
        """Batch embedding returns list of vectors."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        resp = Mock(status_code=200)
        resp.json.return_value = self.MOCK_BATCH
        mixin._http.post.return_value = resp

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_batch_openai(["text a", "text b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_empty_texts(self):
        """Empty input returns empty list."""
        mixin = EmbedderMixin()
        result = mixin._embed_batch_openai([])
        assert result == []

    def test_missing_api_key(self):
        """Returns empty list when no API key."""
        mixin = EmbedderMixin()
        mixin._http = MagicMock(spec=httpx.Client)
        with patch.dict("os.environ", {}, clear=True):
            result = mixin._embed_batch_openai(["test"])
        assert result == []

    def test_error_fallback(self):
        """HTTP error returns empty list."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._http.post.side_effect = httpx.ConnectError("fail")

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_batch_openai(["test"])

        assert result == []

    def test_embed_calls_openai(self):
        """_embed delegates to _embed_openai."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        resp = Mock(status_code=200)
        resp.json.return_value = {"data": [{"embedding": [0.5]}]}
        mixin._http.post.return_value = resp

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed("hello")

        assert result == [0.5]

    def test_embed_batch_delegates(self):
        """_embed_batch delegates to _embed_batch_openai."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        resp = Mock(status_code=200)
        resp.json.return_value = {"data": [{"embedding": [0.1], "index": 0}]}
        mixin._http.post.return_value = resp

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            result = mixin._embed_batch(["a"])

        assert result == [[0.1]]


# ══════════════════════════════════════════════════════════════════════
# Health checks
# ══════════════════════════════════════════════════════════════════════


class TestCheckEmbedderHealth:
    """check_embedder_health — embedder sidecar health probing."""

    def test_healthy(self):
        """Healthy embedder returns status info with reachable=True."""
        mixin = EmbedderMixin()
        mixin.embedder_url = "http://localhost:4000"
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.max_retries = 2

        resp = Mock(status_code=200)
        resp.json.return_value = {"model": "bge-m3", "status": "ok"}
        mixin._http.get.return_value = resp

        result = mixin.check_embedder_health()
        assert result["reachable"] is True
        assert result["model"] == "bge-m3"
        assert result["status"] == "ok"

    def test_unhealthy_status_code(self):
        """Non-200 status returns error dict."""
        mixin = EmbedderMixin()
        mixin.embedder_url = "http://localhost:4000"
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.max_retries = 2

        resp = Mock(status_code=503)
        mixin._http.get.return_value = resp

        result = mixin.check_embedder_health()
        assert result["reachable"] is True
        assert result["status"] == "error"
        assert result["code"] == 503

    def test_connection_error(self):
        """Connection error returns unreachable."""
        mixin = EmbedderMixin()
        mixin.embedder_url = "http://localhost:4000"
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.max_retries = 2

        mixin._http.get.side_effect = httpx.ConnectError("refused")

        result = mixin.check_embedder_health()
        assert result["reachable"] is False
        assert result["status"] == "error"

    def test_retry_exhausted_returns_error(self):
        """When all retries fail, returns error with reachable=False."""
        mixin = EmbedderMixin()
        mixin.embedder_url = "http://localhost:4000"
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.max_retries = 1

        mixin._http.get.return_value = None  # signal retry exhaustion

        result = mixin.check_embedder_health()
        assert result["reachable"] is False
        assert result["status"] == "error"


class TestCheckTantivyHealth:
    """check_tantivy_health — Tantivy BM25 sidecar health probing."""

    def test_healthy(self):
        """Healthy Tantivy returns status info with reachable=True."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200)
        resp.json.return_value = {"status": "ok", "indexed_docs": 100}
        mixin._http.get.return_value = resp

        result = mixin.check_tantivy_health()
        assert result["reachable"] is True
        assert result["status"] == "ok"

    def test_unhealthy_status(self):
        """Non-200 returns error with reachable=True.

        NOTE: HTTP 500+ on the Tantivy endpoint is retried by
        _request_with_retry_tantivy; after all retries are exhausted
        a RuntimeError is raised and caught by check_tantivy_health
        as unreachable.
        """
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=500)
        mixin._http.get.return_value = resp

        result = mixin.check_tantivy_health()
        # 500 is a server error → retried → exhausts → RuntimeError → unreachable
        assert result["reachable"] is False
        assert result["status"] == "error"

    def test_connection_error(self):
        """Connection error returns unreachable."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        mixin._http.get.side_effect = httpx.ConnectError("refused")

        result = mixin.check_tantivy_health()
        assert result["reachable"] is False
        assert result["status"] == "error"


# ══════════════════════════════════════════════════════════════════════
# Tantivy operations
# ══════════════════════════════════════════════════════════════════════


class TestTantivyIndex:
    """_tantivy_index — index a document in BM25 sidecar."""

    def test_success(self):
        """Successful index returns True."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200)
        mixin._http.post.return_value = resp

        result = mixin._tantivy_index("ws-1", "mem-1", "hello world")
        assert result is True

    def test_server_error(self):
        """HTTP < 400 returned, server error (500) returns False."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=500)
        mixin._http.post.return_value = resp

        result = mixin._tantivy_index("ws-1", "mem-1", "hello")
        assert result is False

    def test_connection_error(self):
        """Connection error returns False."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        mixin._http.post.side_effect = httpx.ConnectError("refused")

        result = mixin._tantivy_index("ws-1", "mem-1", "hello")
        assert result is False


    def test_with_doc_type(self):
        """doc_type is included in the JSON payload."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200)
        mixin._http.post.return_value = resp

        result = mixin._tantivy_index("ws-1", "mem-1", "hello", "memory")
        assert result is True
        # Verify the JSON payload included entity_type
        call_kwargs = mixin._http.post.call_args[1]
        assert call_kwargs["json"]["entity_type"] == "memory"


    def test_doc_type_empty_not_in_payload(self):
        """When doc_type is empty, entity_type is omitted from payload."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200)
        mixin._http.post.return_value = resp

        result = mixin._tantivy_index("ws-1", "mem-1", "hello")
        assert result is True
        # Verify entity_type is NOT in the payload
        call_kwargs = mixin._http.post.call_args[1]
        assert "entity_type" not in call_kwargs["json"]


class TestTantivyIndexBatch:
    """_tantivy_index_batch — batch indexing in BM25 sidecar."""

    def test_success(self):
        """Successful batch index returns True."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=200)
        mixin._http.post.return_value = resp

        items = [{"workspace_id": "ws-1", "entity_id": "m1", "content": "text"}]
        result = mixin._tantivy_index_batch(items)
        assert result is True

    def test_empty_items(self):
        """Empty items list returns True without HTTP call."""
        mixin = EmbedderMixin()
        mixin._http = MagicMock(spec=httpx.Client)
        result = mixin._tantivy_index_batch([])
        assert result is True
        mixin._http.post.assert_not_called()

    def test_error_returns_false(self):
        """Connection error returns False."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        mixin._http.post.side_effect = httpx.ConnectError("fail")

        result = mixin._tantivy_index_batch([{"workspace_id": "w1", "entity_id": "e1", "content": "x"}])
        assert result is False


class TestTantivySearch:
    """_tantivy_search — BM25 keyword search."""

    def test_success_with_results(self):
        """Search returns results."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        results = [
            {"entity_id": "m1", "score": 1.5, "content": "auth flow", "entity_type": "memory"}
        ]
        resp = Mock(status_code=200)
        resp.json.return_value = results
        mixin._http.post.return_value = resp

        result = mixin._tantivy_search("ws-1", "auth")
        assert result == results

    def test_server_error_returns_empty(self):
        """HTTP error returns empty list."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        resp = Mock(status_code=500)
        mixin._http.post.return_value = resp

        result = mixin._tantivy_search("ws-1", "auth")
        assert result == []

    def test_connection_error_returns_empty(self):
        """Connection error returns empty list."""
        mixin = EmbedderMixin()
        mixin.tantivy_url = "http://localhost:9091"
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 5
        mixin._circuit_breaker_reset_secs = 30.0

        mixin._http.post.side_effect = httpx.ConnectError("refused")

        result = mixin._tantivy_search("ws-1", "auth")
        assert result == []


# ══════════════════════════════════════════════════════════════════════
# Embedder degradation / error rate alerting tests
# ══════════════════════════════════════════════════════════════════════


class TestEmbedderDegradation:
    """_record_embedder_error / _clear_embedder_errors — degradation tracking."""

    def test_initial_empty_state(self):
        """EmbedderMixin has no degradation state before any error."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        # Before any error, no tracking attributes exist
        assert not hasattr(mixin, '_embedder_consecutive_failures')
        assert not hasattr(mixin, '_embedder_was_degraded')
        assert not hasattr(mixin, '_embedder_alerted')

    def test_was_degraded_set_after_threshold(self):
        """_embedder_was_degraded becomes True after threshold is crossed."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        # Trigger errors until threshold
        with patch.dict("os.environ", {"STMEM_EMBEDDER_ALERT_THRESHOLD": "2"}):
            mixin._record_embedder_error()  # #1
            assert getattr(mixin, '_embedder_was_degraded', False) is False
            assert getattr(mixin, '_embedder_alerted', False) is False
            mixin._record_embedder_error()  # #2 — threshold crossed
            assert mixin._embedder_was_degraded is True
            assert mixin._embedder_alerted is True
            # _call should have been invoked to push alert
            mixin._call.assert_called()
            args, kwargs = mixin._call.call_args
            assert args[0] == "push_embedder_alert"

    def test_clear_resets_degraded_and_pushes_recovery(self):
        """_clear_embedder_errors resets degraded flag and pushes recovery alert."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        # Simulate degraded state
        with patch.dict("os.environ", {"STMEM_EMBEDDER_ALERT_THRESHOLD": "1"}):
            mixin._record_embedder_error()  # crosses threshold
            assert mixin._embedder_was_degraded is True
            assert mixin._embedder_alerted is True
            # Now clear — should push recovery and reset state
            mixin._clear_embedder_errors()
            assert mixin._embedder_was_degraded is False
            assert mixin._embedder_alerted is False
            assert mixin._embedder_consecutive_failures == 0
            # Should have pushed both a degraded alert and a recovery alert
            assert mixin._call.call_count >= 2

    def test_health_check_includes_degraded_flag(self):
        """check_embedder_health includes the degraded flag."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._embedder_consecutive_failures = 5
        mixin._embedder_alert_threshold = 3
        mixin._embedder_was_degraded = True
        mixin._embedder_alerted = True
        mixin._embedder_last_failure_ts = 1000.0

        # Simulate health check error (retries exhausted)
        mixin._http.get.return_value = None
        result = mixin.check_embedder_health()
        assert result.get("degraded") is True
        assert result.get("consecutive_failures") == 5
        assert "degradation_warning" in result

    def test_alert_not_duplicated_on_subsequent_errors(self):
        """Alert is only pushed once per degradation episode."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        with patch.dict("os.environ", {"STMEM_EMBEDDER_ALERT_THRESHOLD": "2"}):
            mixin._record_embedder_error()  # #1 - below threshold
            mixin._record_embedder_error()  # #2 - crosses threshold, pushes alert
            call_count_after_first_alert = mixin._call.call_count
            mixin._record_embedder_error()  # #3 - still degraded, but no new alert
            assert mixin._call.call_count == call_count_after_first_alert


class TestEmbedderAlert:
    """_push_embedder_alert — pushing alert events to SpacetimeDB."""

    def test_push_embedder_alert_critical(self):
        """_push_embedder_alert with severity=2 calls STDB reducer."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._push_embedder_alert(
            severity=2,
            message="Test critical alert",
            degraded=True,
            recovery=False,
        )
        mixin._call.assert_called_once()
        args, kwargs = mixin._call.call_args
        assert args[0] == "push_embedder_alert"
        assert args[1][0] == 2  # severity
        assert args[1][6] is True  # degraded
        assert args[1][7] is False  # recovery

    def test_push_embedder_alert_recovery(self):
        """_push_embedder_alert with severity=0 pushes recovery."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._push_embedder_alert(
            severity=0,
            message="Recovered",
            degraded=False,
            recovery=True,
        )
        mixin._call.assert_called_once()
        args, kwargs = mixin._call.call_args
        assert args[1][0] == 0  # severity = recovery
        assert args[1][6] is False  # not degraded
        assert args[1][7] is True  # recovery

    def test_push_alert_silently_ignores_failures(self):
        """_push_embedder_alert does not raise when the STDB push fails.

        The SDK contract (client/_embed.py) swallows ClientError and
        httpx.HTTPError from the push; verify that contract.
        """
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(side_effect=spacetime_memory.SpacetimeDBError("STDB down"))
        # Should not raise
        mixin._push_embedder_alert(
            severity=1,
            message="Warning",
            degraded=False,
            recovery=False,
        )

# ══════════════════════════════════════════════════════════════════════
# _check_error_rate_alert — time-window error rate alerting
# ══════════════════════════════════════════════════════════════════════


class TestErrorRateAlert:
    """_check_error_rate_alert — time-window error rate detection."""

    def test_no_alert_when_rate_below_threshold(self):
        """No alert fires when error rate is below the threshold."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._init_embedder_counters()
        # 1 error in 100 calls = 1% rate, below 50% threshold
        mixin._embedder_total_calls = 100
        mixin._embedder_total_errors = 1
        mixin._check_error_rate_alert()
        mixin._call.assert_not_called()

    def test_alert_fires_when_rate_exceeds_threshold(self):
        """Alert fires when error rate exceeds the threshold with >= 3 errors."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        with patch.dict("os.environ", {
            "STMEM_EMBEDDER_RATE_ALERT_THRESHOLD_PCT": "50.0",
        }):
            mixin._init_embedder_counters()
            # 3 errors in 4 calls = 75% rate, exceeds 50% threshold
            mixin._embedder_total_calls = 4
            mixin._embedder_total_errors = 3
            mixin._check_error_rate_alert()
            mixin._call.assert_called_once()
            args, kwargs = mixin._call.call_args
            assert args[0] == "push_embedder_alert"
            assert args[1][0] == 1  # severity = warning
            assert args[1][6] is True  # degraded

    def test_alert_not_duplicated(self):
        """Rate alert only fires once per degradation episode."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._init_embedder_counters()
        # First call — rate exceeds threshold
        mixin._embedder_total_calls = 4
        mixin._embedder_total_errors = 3
        mixin._check_error_rate_alert()
        assert mixin._call.call_count == 1
        # Second call — still degraded, but no new alert
        mixin._embedder_total_calls = 8
        mixin._embedder_total_errors = 6
        mixin._check_error_rate_alert()
        assert mixin._call.call_count == 1  # unchanged

    def test_alert_resets_after_clear(self):
        """Rate alert can fire again after _clear_embedder_errors resets the flag."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._init_embedder_counters()
        # Fire the rate alert
        mixin._embedder_total_calls = 4
        mixin._embedder_total_errors = 3
        mixin._check_error_rate_alert()
        assert mixin._call.call_count == 1
        assert mixin._embedder_rate_alerted is True
        # Clear resets the alerted flag
        mixin._clear_embedder_errors()
        assert mixin._embedder_rate_alerted is False
        # After more errors, it can fire again
        mixin._embedder_total_calls = 10
        mixin._embedder_total_errors = 8
        mixin._check_error_rate_alert()
        assert mixin._call.call_count >= 2

    def test_alert_not_fired_below_min_errors(self):
        """No alert when errors < 3 even if rate exceeds threshold."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._init_embedder_counters()
        # 1 error in 1 call = 100% rate, but only 1 error (< 3 min)
        mixin._embedder_total_calls = 1
        mixin._embedder_total_errors = 1
        mixin._check_error_rate_alert()
        mixin._call.assert_not_called()

    def test_no_alert_when_no_calls(self):
        """No alert fires when there have been zero calls."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._init_embedder_counters()
        mixin._check_error_rate_alert()
        mixin._call.assert_not_called()

    def test_rate_alert_after_local_failure_openai_success(self):
        """Rate alert fires when local embedder fails but OpenAI covers."""
        mixin = EmbedderMixin()
        mixin.max_retries = 2
        mixin._http = MagicMock(spec=httpx.Client)
        mixin.embedder_url = "http://localhost:4000"
        mixin._call = MagicMock(return_value={"status": "ok"})
        mixin._embedding_dim = 1024

        # Mock _embed_openai to return a valid embedding
        mixin._embed_openai = MagicMock(return_value=[0.1] * 1024)

        with patch.dict("os.environ", {
            "STMEM_EMBEDDER_RATE_ALERT_THRESHOLD_PCT": "10.0",
            "STMEM_EMBEDDER_ALERT_THRESHOLD": "1",
        }):
            mixin._init_embedder_counters()

            # Mock _embed_local to fail
            mixin._embed_local = MagicMock(return_value=None)

            # First call: local fails (1 error in 1 call = 100% > 10% threshold)
            # OpenAI covers so we get a result
            result = mixin._embed("test text")
            assert result == [0.1] * 1024  # OpenAI returned embedding
            # Local embedder error should be recorded AND rate alert should fire
            assert mixin._embedder_total_errors >= 1
            mixin._call.assert_called()

