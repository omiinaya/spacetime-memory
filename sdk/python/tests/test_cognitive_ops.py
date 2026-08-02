"""Tests for CognitiveOpMixin — cognitive operations management.

Tests the Python SDK wrappers for cognitive op operations
by mocking the underlying HTTP/STDB calls.
"""

from __future__ import annotations

import json

from spacetime_memory.client._cognitive_ops import CognitiveOpMixin


class QueryCounter:
    """Rotates through _query_return entries each time _query is called."""

    def __init__(self, entries: list):
        self.entries = entries
        self.index = 0

    def next(self) -> list[dict]:
        if self.index < len(self.entries):
            val = self.entries[self.index]
            self.index += 1
            return val if isinstance(val, list) else [val]
        return []


class MockClient(CognitiveOpMixin):
    """Minimal mock client that implements the ClientBase interface methods
    needed by CognitiveOpMixin."""

    def __init__(self):
        self._call_log: list[tuple[str, list]] = []
        self._query_log: list[tuple[str, str, dict | None]] = []
        self._query_return: list[dict] = []
        self._query_counter: QueryCounter | None = None

    def _call(self, reducer: str, args: list) -> dict:
        self._call_log.append((reducer, args))
        return {"status": "ok"}

    def _query(self, table: str, workspace_id: str = "", filter_dict: dict | None = None) -> list[dict]:
        self._query_log.append((table, workspace_id, filter_dict))
        if self._query_counter:
            return self._query_counter.next()
        return self._query_return

    def _sql(self, query: str) -> list[dict]:
        return []


class TestCognitiveOpMixin:

    def test_register_cognitive_op(self):
        """Test register_cognitive_op passes correct args in correct order."""
        client = MockClient()
        result = client.register_cognitive_op(
            "ws-123", "entity_extract", "extract",
            description="Extract entities from text",
            config_json='{"model": "default"}',
            pipeline_stage_type="entity_extraction",
        )
        assert result == {"status": "ok"}
        assert len(client._call_log) == 1
        reducer, args = client._call_log[0]
        assert reducer == "register_cognitive_op"
        assert args[0] == "ws-123"               # workspace_id
        assert args[1] == ""                     # peer_id (empty)
        assert args[2] == "entity_extract"       # name
        assert args[3] == "extract"              # op_type
        assert args[4] == "Extract entities from text"  # description
        assert args[5] == '{"model": "default"}'  # config_json
        assert args[6] == "entity_extraction"    # pipeline_stage_type

    def test_register_cognitive_op_defaults(self):
        """Test register with minimal args uses defaults."""
        client = MockClient()
        client.register_cognitive_op("ws-123", "simple_op", "observe")
        reducer, args = client._call_log[0]
        assert args[2] == "simple_op"
        assert args[3] == "observe"
        assert args[4] == ""     # default description
        assert args[5] == "{}"   # default config_json
        assert args[6] == ""     # default pipeline_stage_type

    def test_unregister_cognitive_op(self):
        """Test unregister_cognitive_op passes correct args."""
        client = MockClient()
        result = client.unregister_cognitive_op("ws-123", "op-456")
        assert result == {"status": "ok"}
        assert client._call_log[0] == ("unregister_cognitive_op", ["ws-123", "op-456"])

    def test_get_cognitive_ops(self):
        """Test get_cognitive_ops returns parsed JSON from result table."""
        client = MockClient()
        ops_data = [
            {"id": "op-1", "name": "entity_extract", "op_type": "extract"},
            {"id": "op-2", "name": "semantic_search", "op_type": "observe"},
        ]
        client._query_return = [
            {"result_id": "r1", "data": json.dumps(ops_data), "created_at": 100}
        ]
        result = client.get_cognitive_ops("ws-123")
        assert result == ops_data
        assert client._call_log[0] == ("get_cognitive_ops", ["ws-123", ""])
        assert client._query_log[0][0] == "cognitive_op_result"
        assert client._query_log[0][1] == "ws-123"

    def test_get_cognitive_ops_empty(self):
        """Test get_cognitive_ops returns empty list on no data."""
        client = MockClient()
        client._query_return = []
        result = client.get_cognitive_ops("ws-123")
        assert result == []

    def test_get_cognitive_ops_with_filter(self):
        """Test get_cognitive_ops passes op_type_filter to _call."""
        client = MockClient()
        client._query_return = [
            {"result_id": "r1", "data": json.dumps([]), "created_at": 100}
        ]
        result = client.get_cognitive_ops("ws-123", op_type_filter="extract")
        assert result == []
        assert client._call_log[0] == ("get_cognitive_ops", ["ws-123", "extract"])

    def test_execute_cognitive_op(self):
        """Test execute_cognitive_op calls reducer and returns parsed result."""
        client = MockClient()
        result_data = {"status": "ok", "output": "processed"}
        client._query_return = [
            {"result_id": "r1", "data": json.dumps(result_data), "created_at": 100}
        ]
        result = client.execute_cognitive_op(
            "ws-123", "op-456", input_data={"query": "test"}
        )
        assert result == result_data
        reducer, args = client._call_log[0]
        assert reducer == "execute_cognitive_op"
        assert args[0] == "ws-123"
        assert args[1] == "op-456"
        assert json.loads(args[2]) == {"query": "test"}

    def test_execute_cognitive_op_no_result(self):
        """Test execute_cognitive_op returns error dict when no result found."""
        client = MockClient()
        client._query_return = []
        result = client.execute_cognitive_op("ws-123", "op-456")
        assert result == {"status": "error", "message": "No result found"}

    def test_get_cognitive_pipeline(self):
        """Test get_cognitive_pipeline returns ordered list of ops."""
        client = MockClient()
        pipeline_data = [
            {"id": "op-1", "name": "semantic_search", "op_type": "observe"},
            {"id": "op-2", "name": "entity_extract", "op_type": "extract"},
            {"id": "op-3", "name": "categorize", "op_type": "classify"},
        ]
        client._query_return = [
            {"result_id": "r1", "data": json.dumps(pipeline_data), "created_at": 100}
        ]
        result = client.get_cognitive_pipeline("ws-123")
        assert result == pipeline_data
        assert client._call_log[0] == ("get_cognitive_pipeline", ["ws-123"])

    def test_get_cognitive_pipeline_empty(self):
        """Test get_cognitive_pipeline returns empty list on no data."""
        client = MockClient()
        client._query_return = []
        result = client.get_cognitive_pipeline("ws-123")
        assert result == []

    def test_observe_convenience(self):
        """Test observe convenience calls get_cognitive_ops then execute."""
        client = MockClient()
        ops_data = [
            {"id": "op-1", "name": "semantic_search", "op_type": "observe"},
        ]
        client._query_counter = QueryCounter([
            # First _query call from get_cognitive_ops
            [{"result_id": "r1", "data": json.dumps(ops_data), "created_at": 100}],
            # Second _query call from execute_cognitive_op
            [{"result_id": "r2", "data": json.dumps({"result": "found"}), "created_at": 200}],
        ])
        result = client.observe("ws-123", "test query")
        assert len(result) == 1
        assert result[0] == {"result": "found"}
        # Should have called get_cognitive_ops with observe filter
        assert client._call_log[0] == ("get_cognitive_ops", ["ws-123", "observe"])
        # Should have called execute_cognitive_op with query
        assert client._call_log[1] == (
            "execute_cognitive_op",
            ["ws-123", "op-1", json.dumps({"query": "test query"})],
        )

    def test_observe_convenience_no_ops(self):
        """Test observe returns empty list when no observe ops registered."""
        client = MockClient()
        client._query_return = [{"result_id": "r1", "data": json.dumps([]), "created_at": 100}]
        result = client.observe("ws-123", "test query")
        assert result == []

    def test_extract_convenience(self):
        """Test extract convenience calls get_cognitive_ops then execute."""
        client = MockClient()
        ops_data = [
            {"id": "op-1", "name": "entity_extract", "op_type": "extract"},
        ]
        client._query_counter = QueryCounter([
            [{"result_id": "r1", "data": json.dumps(ops_data), "created_at": 100}],
            [{"result_id": "r2", "data": json.dumps({"entities": ["Alice", "Bob"]}), "created_at": 200}],
        ])
        result = client.extract("ws-123", "Alice and Bob went home")
        assert len(result) == 1
        assert result[0] == {"entities": ["Alice", "Bob"]}
        assert client._call_log[0] == ("get_cognitive_ops", ["ws-123", "extract"])
        assert client._call_log[1] == (
            "execute_cognitive_op",
            ["ws-123", "op-1", json.dumps({"content": "Alice and Bob went home"})],
        )

    def test_classify_convenience(self):
        """Test classify convenience calls get_cognitive_ops then execute."""
        client = MockClient()
        ops_data = [
            {"id": "op-1", "name": "categorize", "op_type": "classify"},
        ]
        client._query_counter = QueryCounter([
            [{"result_id": "r1", "data": json.dumps(ops_data), "created_at": 100}],
            [{"result_id": "r2", "data": json.dumps({"category": "news"}), "created_at": 200}],
        ])
        result = client.classify("ws-123", "Some content to classify")
        assert len(result) == 1
        assert result[0] == {"category": "news"}
        assert client._call_log[0] == ("get_cognitive_ops", ["ws-123", "classify"])

    def test_rank_convenience(self):
        """Test rank convenience calls execute and returns ranked results."""
        client = MockClient()
        ops_data = [
            {"id": "op-1", "name": "re-ranker", "op_type": "rank"},
        ]
        input_results = [{"id": "a", "score": 1}, {"id": "b", "score": 2}]
        ranked_data = {"ranked": [{"id": "b", "score": 2}, {"id": "a", "score": 1}]}
        client._query_counter = QueryCounter([
            [{"result_id": "r1", "data": json.dumps(ops_data), "created_at": 100}],
            [{"result_id": "r2", "data": json.dumps(ranked_data), "created_at": 200}],
        ])
        result = client.rank("ws-123", input_results)
        assert len(result) == 1
        assert result[0] == ranked_data
        assert client._call_log[1] == (
            "execute_cognitive_op",
            ["ws-123", "op-1", json.dumps({"results": input_results})],
        )

    def test_rank_convenience_passthrough(self):
        """Test rank returns input as-is when no rank ops registered."""
        client = MockClient()
        input_results = [{"id": "a", "score": 1}, {"id": "b", "score": 2}]
        client._query_return = [{"result_id": "r1", "data": json.dumps([]), "created_at": 100}]
        result = client.rank("ws-123", input_results)
        assert result == input_results  # passthrough

    def test_store_convenience(self):
        """Test store convenience calls execute and returns storage results."""
        client = MockClient()
        ops_data = [
            {"id": "op-1", "name": "persist", "op_type": "store"},
        ]
        results_to_store = [{"id": "1", "content": "test"}]
        store_data = {"stored": ["1"]}
        client._query_counter = QueryCounter([
            [{"result_id": "r1", "data": json.dumps(ops_data), "created_at": 100}],
            [{"result_id": "r2", "data": json.dumps(store_data), "created_at": 200}],
        ])
        result = client.store("ws-123", results_to_store)
        assert len(result) == 1
        assert result[0] == store_data
        assert client._call_log[1] == (
            "execute_cognitive_op",
            ["ws-123", "op-1", json.dumps({"results": results_to_store})],
        )

    def test_store_convenience_no_ops(self):
        """Test store returns empty list when no store ops registered."""
        client = MockClient()
        client._query_return = [{"result_id": "r1", "data": json.dumps([]), "created_at": 100}]
        result = client.store("ws-123", [{"id": "1"}])
        assert result == []
