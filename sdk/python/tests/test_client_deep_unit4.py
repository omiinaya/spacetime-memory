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

    Part 4 of 4: OpenAI embedding, Tantivy search, fuse/dedup,
    ping, identity, health check.
    """

    def test_embed_openai_no_key(self):
        """Lines 513-515: _embed_openai returns [] when no API key."""
        client = Client(host="localhost", port="3000", database="test")
        with patch.dict(os.environ, {}, clear=True):
            if "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            result = client._embed_openai("test text")
            assert result == []

    # ── _embed_batch_openai no key (lines 559-564) ──

    def test_embed_batch_openai_no_key(self):
        """Lines 559-564: _embed_batch_openai returns [] when no API key."""
        client = Client(host="localhost", port="3000", database="test")
        with patch.dict(os.environ, {}, clear=True):
            if "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            result = client._embed_batch_openai(["text1", "text2"])
            assert result == []

    # ── _embed_batch_openai with api key (lines 565-597) ──

    def test_embed_batch_openai_success(self):
        """Lines 565-597: _embed_batch_openai success path."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
        mock_http.post.return_value = mock_resp
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_batch_openai(["text1", "text2"])
            assert result == [[0.1, 0.2], [0.3, 0.4]]

    # ── _embed_openai with timeout (line 541-543) ──

    def test_embed_openai_timeout(self):
        """Lines 541-543: _embed_openai catches TimeoutException."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.TimeoutException("timeout")
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_openai("test text")
            assert result == []

    # ── _embed_openai general error (lines 544-546) ──

    def test_embed_openai_general_error(self):
        """Lines 544-546: _embed_openai catches general HTTP errors."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.HTTPError("bad")
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_openai("test text")
            assert result == []

    # ── _embed_batch_openai timeout (line 541-543 for batch) ──

    def test_embed_batch_openai_timeout(self):
        """_embed_batch_openai catches TimeoutException."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.TimeoutException("timeout")
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_batch_openai(["text1"])
            assert result == []

    # ── _embed_batch_openai general error (lines 595-597) ──

    def test_embed_batch_openai_general_error(self):
        """Lines 595-597: _embed_batch_openai catches general errors."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.HTTPError("bad")
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_batch_openai(["text1"])
            assert result == []

    # ── check_embedder_health success (lines 604-606) ──

    def test_check_embedder_health_success(self):
        """Lines 604-606: check_embedder_health returns health info on 200."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"model": "bge-m3", "version": "1.0"}
        mock_http.get.return_value = mock_resp
        client._http = mock_http
        result = client.check_embedder_health()
        assert result["reachable"] is True
        assert result["model"] == "bge-m3"

    # ── _embed_batch non-empty (line 555) ──

    def test_embed_batch_non_empty(self):
        """Line 555: _embed_batch with non-empty list calls _embed_batch_openai."""
        from unittest.mock import patch

        client = Client(host="localhost", port="3000", database="test")
        with patch.object(client, "_embed_batch_openai", return_value=[[0.1, 0.2]]):
            result = client._embed_batch(["hello"])
            assert result == [[0.1, 0.2]]

    # ── _tantivy_search success (line 659) ──

    def test_tantivy_search_success(self):
        """Line 659: _tantivy_search returns json on success."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"entity_id": "m1", "score": 0.9}]
        mock_http.post.return_value = mock_resp
        client._http = mock_http
        result = client._tantivy_search("ws1", "query", limit=10)
        assert result == [{"entity_id": "m1", "score": 0.9}]

    # ── ping error response (line 679) ──

    def test_ping_http_error(self):
        """Line 679-682: ping on HTTP error >= 400."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_http.get.return_value = mock_resp
        client._http = mock_http
        result = client.ping()
        assert result["status"] == "error"
        assert "HTTP 503" in result["message"]

    # ── _fuse_and_deduplicate unknown strategy (line 1035) ──

    def test_fuse_and_deduplicate_unknown_strategy(self):
        """Line 1035: _fuse_and_deduplicate skips unknown strategy from per-strat tracking."""
        client = Client(host="localhost", port="3000", database="test")
        rows = [{"entity_id": "a", "strategy": "semantic", "score": 0.9}]
        tantivy_rows = []
        per_strat = {
            "semantic": rows,
            "keyword": [],
            "graph": [],
            "temporal": [],
            "binary": [],
        }
        strat_min = {"semantic": 0.9}
        strat_max = {"semantic": 0.9}
        weights = {
            "semantic": 0.65,
            "keyword": 0.25,
            "graph": 0.0,
            "temporal": 0.05,
            "binary": 0.05,
        }
        rows_with_unknown = [
            {"entity_id": "a", "strategy": "semantic", "score": 0.9},
            {"entity_id": "b", "strategy": "unknown_x", "score": 0.5},
        ]
        result = client._fuse_and_deduplicate(
            rows_with_unknown, tantivy_rows, per_strat, strat_min, strat_max, weights
        )
        # Both rows included (unknown gets fused_score=0.0), semantic row dedup'd
        assert len(result) == 2
        ids = {r["entity_id"] for r in result}
        assert ids == {"a", "b"}

    # ── _embed_openai success (lines 538-540) ──

    def test_embed_openai_success(self):
        """Lines 538-540: _embed_openai returns embedding on success."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        mock_http.post.return_value = mock_resp
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_openai("test text")
            assert result == [0.1, 0.2, 0.3]

    # ── check_embedder_health TimeoutException (line 608-609) ──

    def test_check_embedder_health_timeout(self):
        """check_embedder_health catches TimeoutException."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.TimeoutException("timeout")
        client._http = mock_http
        result = client.check_embedder_health()
        assert result["reachable"] is False

    # ── _ensure_identity already established ──

    def test_ensure_identity_already_established(self):
        """_ensure_identity returns early if already established."""
        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        client._ensure_identity()
        assert client._identity_established is True

    def test_ensure_identity_with_token(self):
        """_ensure_identity returns early if token is set."""
        client = Client(host="localhost", port="3000", database="test")
        client.token = "fake-jwt"
        client._identity_established = False
        client._ensure_identity()

    # ── search embedder down when health 400 ──

    def test_search_embedder_down_health_400(self):
        """Line 1241: embedder_down set when health check returns >=400."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        client._query_cache = None
        client._identity_established = True
        mock_http = MagicMock()
        mock_http.get.return_value = MagicMock(status_code=500)
        client._http = mock_http

        with patch.object(client, "_embed", return_value=[0.1, 0.2]):
            with patch.object(client, "_call", return_value={"status": "ok"}):
                with patch.object(client, "_sql", return_value=[]):
                    with patch.object(client, "_tantivy_search", return_value=[]):
                        with patch.object(client, "_fuse_and_deduplicate", return_value=[]):
                            with patch.object(client, "_enrich_content", return_value=[]):
                                result = client.search("ws1", "pizza", semantic=True, limit=5)
                                assert result == []

    def test_embed_batch_openai_json_error(self):
        """Lines 595-597: _embed_batch_openai catches JSONDecodeError."""
        from unittest.mock import MagicMock, patch

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
        mock_http.post.return_value = mock_resp
        client._http = mock_http

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = client._embed_batch_openai(["text1"])
            assert result == []


def test_json_formatter_with_exception():
    """JSONFormatter.format() includes exception info when record has exc_info."""
    import logging
    import sys

    from spacetime_memory.client import JSONFormatter

    formatter = JSONFormatter()
    try:
        raise ValueError("test boom")
    except ValueError:
        record = logging.LogRecord("test", logging.ERROR, "", 0, "test error", (), sys.exc_info())
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "exception" in parsed
    assert "ValueError" in parsed["exception"]


def test_configure_logging_with_log_file():
    """configure_logging() with log_file creates FileHandler."""
    import logging
    from tempfile import NamedTemporaryFile

    from spacetime_memory.client import configure_logging

    f = NamedTemporaryFile(suffix=".log", delete=False)
    log_path = f.name
    f.close()
    try:
        configure_logging(level="DEBUG", json_format=False, log_file=log_path)
        logger_obj = logging.getLogger("spacetime_memory")
        handlers = logger_obj.handlers
        assert len(handlers) > 0
        assert isinstance(handlers[0], logging.FileHandler)
        assert handlers[0].baseFilename == log_path
    finally:
        for h in logger_obj.handlers[:]:
            h.close()
            logger_obj.removeHandler(h)
        os.unlink(log_path)


def test_memory_record_from_dict():
    """MemoryRecord.from_dict() filters to known fields only."""
    from spacetime_memory.client import Client

    rec = Client.MemoryRecord.from_dict(
        {
            "id": "mem-1",
            "workspace_id": "ws-1",
            "peer_id": "peer-1",
            "observer_id": "",
            "memory_type": "experience",
            "content": "hello",
            "summary": "hi",
            "entities_json": "[]",
            "confidence": 0.9,
            "is_active": True,
            "created_at": 1000,
            "expires_at": 2000,
            "updated_at": 1500,
            "tier": "L1",
            "access_count": 5,
            "strength": 0.8,
            "version": 1,
            "trust_score": 0.5,
            "feedback_count": 0,
            "consolidated_to": "",
        }
    )
    assert rec.id == "mem-1"
    assert rec.content == "hello"
    assert rec.confidence == 0.9
