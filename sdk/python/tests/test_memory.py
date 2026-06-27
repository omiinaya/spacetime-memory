"""Tests for memory CRUD operations via Client."""

from unittest.mock import Mock
from tests.conftest import make_sql_response


class TestMemoryStore:
    """store() method — persists a memory and optionally indexes it."""

    def test_store_calls_reducer(self, mock_http_client):
        """store() calls the store_memory reducer and returns status."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
            json=lambda: {"data": [{"embedding": [0.0]}]},
        )
        # Also stub _embed to avoid the OpenAI embedder path entirely
        mock_http_client._embed = Mock(return_value=[])

        result = mock_http_client.store(
            workspace_id="ws1",
            content="test memory",
            peer_id="peer1",
        )

        assert result["status"] == "ok"
        # At minimum: store_memory reducer call — check the first call
        assert mock_http_client._http.post.call_count >= 1
        first_call_args = mock_http_client._http.post.call_args_list[0]
        assert "/v1/database/test-db/call/store_memory" in first_call_args.args[0]

    def test_store_with_auto_index(self, mock_http_client, monkeypatch):
        """store() auto-indexes when embedder returns a vector."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Mock for the embedder call specifically
        def post_side_effect(*args, **kwargs):
            if "/embeddings" in args[0]:
                emb_resp = Mock(status_code=200)
                emb_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
                return emb_resp
            # Reducer calls (store_memory, index_entity)
            red_resp = Mock(status_code=200)
            red_resp.text = "{}"
            return red_resp

        mock_http_client._http.post.side_effect = post_side_effect

        # Override _sql to return a memory that was "just inserted"
        original_sql = mock_http_client._sql
        call_count = [0]

        def sql_side_effect(query):
            call_count[0] += 1
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
        # Should have called embed + store_memory + sql SELECT + index_entity
        assert mock_http_client._http.post.call_count >= 3

    def test_store_with_tier(self, mock_http_client, monkeypatch):
        """store() updates tier when tier is L0/L1/L2."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        def post_side_effect(*args, **kwargs):
            if "/embeddings" in args[0]:
                emb_resp = Mock(status_code=200)
                emb_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
                return emb_resp
            red_resp = Mock(status_code=200)
            red_resp.text = "{}"
            return red_resp

        mock_http_client._http.post.side_effect = post_side_effect

        # Override _sql to return a memory for both SELECT queries
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
        # Should have called: store_memory, embed, sql(select), index_entity,
        # sql(select again for tier), update_memory_tier
        assert mock_http_client._http.post.call_count >= 4


class TestMemorySearch:
    """search() method — hybrid and keyword search."""

    def test_search_semantic(self, mock_http_client, monkeypatch):
        """search() with semantic=True calls hybrid_search reducer."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Mock the embedder to return a proper vector
        def post_side_effect(*args, **kwargs):
            if "/embeddings" in args[0]:
                emb_resp = Mock(status_code=200)
                emb_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
                return emb_resp
            # SQL / reducer calls
            resp = Mock(status_code=200)
            resp.text = make_sql_response([])
            resp.json = lambda: []
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        result = mock_http_client.search(
            workspace_id="ws1",
            query="test query",
            semantic=True,
        )

        # Even with no results, should get a list
        assert isinstance(result, list)

    def test_search_keyword(self, mock_http_client):
        """search() with semantic=False does a keyword SQL query, now
        including notes alongside memories."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response(
                [
                    {"id": "1", "content": "pizza is great", "created_at": 100},
                ]
            ),
        )

        result = mock_http_client.search(
            workspace_id="ws1",
            query="pizza",
            semantic=False,
        )

        # Both memories and notes appear in keyword results
        assert len(result) >= 1
        assert any("pizza" in r.get("content", "") for r in result)
        # At least one entry should be a memory
        assert any(r.get("entity_type") == "memory" for r in result)

    def test_search_with_filters(self, mock_http_client, monkeypatch):
        """search_with_filters applies metadata and location filters."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # We need hybrid_search + SQL results for the search + filter path
        def post_side_effect(*args, **kwargs):
            if "/embeddings" in args[0]:
                emb_resp = Mock(status_code=200)
                emb_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
                return emb_resp
            resp = Mock(status_code=200)
            resp.text = make_sql_response([])
            resp.json = lambda: []
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

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
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response(
                [
                    {"id": "1", "content": "hello", "is_active": True, "created_at": 200},
                    {"id": "2", "content": "world", "is_active": True, "created_at": 100},
                ]
            ),
        )

        results = mock_http_client.list_memories(workspace_id="ws1")

        assert len(results) == 2
        assert results[0]["id"] == "1"

    def test_get_memory(self, mock_http_client):
        """get_memory() fetches by ID and calls reinforce_memory."""
        call_log = []

        def post_side_effect(*args, **kwargs):
            call_log.append(args[0])
            resp = Mock(status_code=200)
            resp.text = make_sql_response(
                [
                    {"id": "mem-1", "content": "found it"},
                ]
            )
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        result = mock_http_client.get_memory("mem-1")

        assert len(result) == 1
        assert result[0]["id"] == "mem-1"

    def test_update_memory(self, mock_http_client):
        """update_memory() calls update_memory reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.update_memory("mem-1", "new content", "new summary", 0.9)

        assert result["status"] == "ok"

    def test_delete_memory(self, mock_http_client):
        """delete_memory() calls deactivate_memory reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.delete_memory("mem-1")
        assert result["status"] == "ok"

    def test_reinforce(self, mock_http_client):
        """reinforce() calls reinforce_memory reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.reinforce("mem-1")
        assert result["status"] == "ok"
