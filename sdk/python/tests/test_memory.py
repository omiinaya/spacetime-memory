"""Tests for memory CRUD operations via Client."""

from unittest.mock import Mock
from tests.conftest import make_sql_response


def _make_sql_resp(rows):
    """Create a mock response returning a SQL result set."""
    resp = Mock(status_code=200)
    resp.text = make_sql_response(rows)
    return resp


def _make_tantivy_resp(hits=None):
    """Create a mock response for tantivy BM25 search returning a list."""
    hits = hits or []
    import json
    resp = Mock(status_code=200)
    resp.text = json.dumps(hits)
    resp.json = lambda: hits
    return resp


def _make_embedder_resp():
    """Create a mock response for the embedding endpoint."""
    resp = Mock(status_code=200)
    resp.json = lambda: {"data": [{"embedding": [0.0]}]}
    return resp


def _search_side_effect(tantivy_hits=None, sql_rows=None):
    """Build a side_effect that handles all HTTP calls during search()."""
    tantivy_hits = tantivy_hits or []
    sql_rows = sql_rows or []

    def _side_effect(*args, **kwargs):
        url = str(args[0]) if args else ""
        if "/search" in url:
            return _make_tantivy_resp(tantivy_hits)
        if "/embeddings" in url:
            return _make_embedder_resp()
        return _make_sql_resp(sql_rows)

    return _side_effect


class TestMemoryStore:
    """store() method — persists a memory and optionally indexes it."""

    def test_store_calls_reducer(self, mock_http_client):
        """store() calls the store_memory reducer and returns status."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )
        mock_http_client._embed = Mock(return_value=[])

        result = mock_http_client.store(
            workspace_id="ws1",
            content="test memory",
            peer_id="peer1",
        )

        assert result["status"] == "ok"
        assert mock_http_client._http.post.call_count >= 1
        first_call = mock_http_client._http.post.call_args_list[0]
        assert "/v1/database/test-db/call/store_memory" in first_call.args[0]

    def test_store_with_auto_index(self, mock_http_client, monkeypatch):
        """store() auto-indexes when embedder returns a vector."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        def post_side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/embeddings" in url:
                resp = Mock(status_code=200)
                resp.json = lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
                return resp
            red_resp = Mock(status_code=200)
            red_resp.text = "{}"
            return red_resp

        mock_http_client._http.post.side_effect = post_side_effect

        original_sql = mock_http_client._sql

        def sql_side_effect(query):
            if "SELECT id FROM memory" in query:
                return [{"id": "mem-123"}]
            return original_sql(query)

        mock_http_client._sql = sql_side_effect

        result = mock_http_client.store(
            workspace_id="ws1",
            content="test memory to index",
            peer_id="peer1",
        )

        assert result["status"] == "ok"
        assert mock_http_client._http.post.call_count >= 3

    def test_store_with_tier(self, mock_http_client, monkeypatch):
        """store() updates tier when tier is L0/L1/L2."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        def post_side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/embeddings" in url:
                resp = Mock(status_code=200)
                resp.json = lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
                return resp
            red_resp = Mock(status_code=200)
            red_resp.text = "{}"
            return red_resp

        mock_http_client._http.post.side_effect = post_side_effect

        def sql_side_effect(query):
            return [{"id": "mem-456"}]

        mock_http_client._sql = sql_side_effect

        result = mock_http_client.store(
            workspace_id="ws1",
            content="tiered memory",
            peer_id="peer1",
            tier="L1",
        )

        assert result["status"] == "ok"
        assert mock_http_client._http.post.call_count >= 4


class TestMemorySearch:
    """search() method — hybrid and keyword search."""

    def test_search_semantic(self, mock_http_client, monkeypatch):
        """search() with semantic=True uses the hybrid path."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_http_client._http.post.side_effect = _search_side_effect()

        result = mock_http_client.search(
            workspace_id="ws1",
            query="test query",
            semantic=True,
        )

        assert isinstance(result, list)

    def test_search_keyword(self, mock_http_client):
        """search() with semantic=False does a keyword Tantivy BM25 search."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[{"id": "1", "content": "pizza is great", "created_at": 100}],
        )

        result = mock_http_client.search(
            workspace_id="ws1",
            query="pizza",
            semantic=False,
        )

        assert isinstance(result, list)

    def test_search_keyword_with_results(self, mock_http_client):
        """search() keyword returns tantivy hits when they match."""
        hits = [
            {"entity_id": "mem-1", "entity_type": "memory",
             "content": "pizza is great", "score": 5.2},
            {"entity_id": "mem-2", "entity_type": "memory",
             "content": "I love pizza", "score": 3.1},
        ]
        mock_http_client._http.post.side_effect = _search_side_effect(
            tantivy_hits=hits,
            sql_rows=[{"id": "1", "content": "pizza is great", "created_at": 100}],
        )

        result = mock_http_client.search(
            workspace_id="ws1",
            query="pizza",
            semantic=False,
        )

        assert len(result) >= 1

    def test_search_empty_query(self, mock_http_client):
        """search() with an empty query still returns a list."""
        mock_http_client._http.post.side_effect = _search_side_effect()

        result = mock_http_client.search(
            workspace_id="ws1",
            query="",
            semantic=False,
        )
        assert isinstance(result, list)

    def test_search_keyword_tantivy_error(self, mock_http_client):
        """search() keyword handles tantivy error gracefully."""
        def _side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/search" in url:
                return Mock(status_code=503, text="Service Unavailable")
            if "/embeddings" in url:
                return _make_embedder_resp()
            return _make_sql_resp([
                {"id": "1", "content": "fallback", "created_at": 100},
            ])

        mock_http_client._http.post.side_effect = _side_effect

        result = mock_http_client.search(
            workspace_id="ws1",
            query="pizza",
            semantic=False,
        )
        assert isinstance(result, list)

    def test_search_with_filters(self, mock_http_client, monkeypatch):
        """search_with_filters applies metadata and location filters."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_http_client._http.post.side_effect = _search_side_effect()

        result = mock_http_client.search_with_filters(
            workspace_id="ws1",
            query="test",
            metadata_filter='{"source": "web"}',
        )

        assert isinstance(result, list)


class TestMemoryCrud:
    """Individual memory CRUD methods."""

    def test_list_memories(self, mock_http_client):
        """list_memories() builds correct SQL query and parses results."""
        mock_http_client._http.post.return_value = _make_sql_resp([
            {"id": "1", "content": "hello", "is_active": True, "created_at": 200},
            {"id": "2", "content": "world", "is_active": True, "created_at": 100},
        ])

        results = mock_http_client.list_memories(workspace_id="ws1")

        assert len(results) == 2
        assert results[0]["id"] == "1"
        assert results[0]["created_at"] == 200

    def test_list_memories_empty(self, mock_http_client):
        """list_memories() returns [] when no memories exist."""
        mock_http_client._http.post.return_value = _make_sql_resp([])

        results = mock_http_client.list_memories(workspace_id="ws1")
        assert results == []

    def test_get_memory(self, mock_http_client):
        """get_memory() fetches by ID."""
        mock_http_client._http.post.side_effect = lambda *a, **kw: _make_sql_resp(
            [{"id": "mem-1", "content": "found it"}]
        )

        result = mock_http_client.get_memory("mem-1")

        assert len(result) == 1
        assert result[0]["id"] == "mem-1"

    def test_get_memory_not_found(self, mock_http_client):
        """get_memory() returns [] for a non-existent memory."""
        mock_http_client._http.post.return_value = _make_sql_resp([])

        result = mock_http_client.get_memory("nonexistent-id")
        assert result == []

    def test_update_memory(self, mock_http_client):
        """update_memory() calls update_memory reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.update_memory("mem-1", "new content", "new summary", 0.9)

        assert result["status"] == "ok"

    def test_update_memory_expires_at(self, mock_http_client):
        """update_memory() with explicit expires_at."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.update_memory(
            "mem-1", "new content", "new summary", 0.9, expires_at=2000000000
        )

        assert result["status"] == "ok"

    def test_delete_memory(self, mock_http_client):
        """delete_memory() calls deactivate_memory reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.delete_memory("mem-1")
        assert result["status"] == "ok"

    def test_delete_memory_double_delete(self, mock_http_client):
        """delete_memory() a second time still returns ok."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        r1 = mock_http_client.delete_memory("mem-1")
        r2 = mock_http_client.delete_memory("mem-1")
        assert r1["status"] == "ok"
        assert r2["status"] == "ok"

    def test_reinforce(self, mock_http_client):
        """reinforce() calls reinforce_memory reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.reinforce("mem-1")
        assert result["status"] == "ok"


class TestSearchTemporalFilter:
    """search() with temporal_filter / before / after parameters."""

    def test_search_temporal_filter_from(self, mock_http_client):
        """temporal_filter={'from': ts} filters out older results."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[
                {"id": "1", "content": "old memory", "created_at": 100},
                {"id": "2", "content": "new memory", "created_at": 200},
            ],
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query="memory",
            semantic=False,
            temporal_filter={"from": 150},
        )
        assert len(result) == 1
        assert result[0]["entity_id"] == "2"

    def test_search_temporal_filter_to(self, mock_http_client):
        """temporal_filter={'to': ts} filters out newer results."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[
                {"id": "1", "content": "old memory", "created_at": 100},
                {"id": "2", "content": "new memory", "created_at": 200},
            ],
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query="memory",
            semantic=False,
            temporal_filter={"to": 150},
        )
        assert len(result) == 1
        assert result[0]["entity_id"] == "1"

    def test_search_temporal_filter_both(self, mock_http_client):
        """temporal_filter with both from and to narrows the time window."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[
                {"id": "1", "content": "too old", "created_at": 50},
                {"id": "2", "content": "just right", "created_at": 120},
                {"id": "3", "content": "too new", "created_at": 200},
            ],
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query="memory",
            semantic=False,
            temporal_filter={"from": 100, "to": 150},
        )
        assert len(result) == 1
        assert result[0]["entity_id"] == "2"

    def test_search_explicit_before_overrides_temporal_filter(self, mock_http_client):
        """Explicit before= overrides temporal_filter['to']."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[
                {"id": "1", "content": "memory A", "created_at": 100},
                {"id": "2", "content": "memory B", "created_at": 200},
                {"id": "3", "content": "memory C", "created_at": 300},
            ],
        )
        # temporal_filter says to=250, but explicit before=150 overrides
        result = mock_http_client.search(
            workspace_id="ws1",
            query="memory",
            semantic=False,
            temporal_filter={"to": 250},
            before=150,
        )
        assert len(result) == 1
        assert result[0]["entity_id"] == "1"

    def test_search_explicit_after_overrides_temporal_filter(self, mock_http_client):
        """Explicit after= overrides temporal_filter['from']."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[
                {"id": "1", "content": "memory A", "created_at": 100},
                {"id": "2", "content": "memory B", "created_at": 200},
                {"id": "3", "content": "memory C", "created_at": 300},
            ],
        )
        # temporal_filter says from=50, but explicit after=250 overrides
        result = mock_http_client.search(
            workspace_id="ws1",
            query="memory",
            semantic=False,
            temporal_filter={"from": 50},
            after=250,
        )
        assert len(result) == 1
        assert result[0]["entity_id"] == "3"

    def test_search_no_created_at_filtered_out(self, mock_http_client):
        """Results missing created_at are excluded when temporal_filter is active."""
        mock_http_client._http.post.side_effect = _search_side_effect(
            sql_rows=[
                {"id": "1", "content": "no timestamp"},
                {"id": "2", "content": "has timestamp", "created_at": 100},
            ],
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query="memory",
            semantic=False,
            temporal_filter={"from": 50},
        )
        assert len(result) == 1
        assert result[0]["entity_id"] == "2"
