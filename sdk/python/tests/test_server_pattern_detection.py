"""Tests for server-side pattern detection SDK wrappers.

These tests verify the Python SDK wrapper methods that call the
server-side pattern detection reducers.

NOTE: These are unit tests that mock the _call and _query methods.
Integration tests (connecting to a live STDB) are in test_client_deep_*.py.
"""

from unittest.mock import MagicMock

from spacetime_memory.client._pattern_detection import PatternDetectionMixin

# ── Helpers ───────────────────────────────────────────────────────────


class MockClient(PatternDetectionMixin):
    """Minimal mock that provides only _call and _query for mixin testing."""

    def __init__(self) -> None:
        self._call = MagicMock()  # type: ignore[method-assign]
        self._query = MagicMock()  # type: ignore[method-assign]


SAMPLE_TEMPORAL_CLUSTER = {
    "id": "tc-001",
    "workspace_id": "ws-test",
    "start_time": 1000000,
    "end_time": 1001800,
    "count": 3,
    "memory_ids": '["m1","m2","m3"]',
    "summary_terms": '["deploy","server","production"]',
    "created_at": 2000000,
}

SAMPLE_COOCCURRENCE = {
    "id": "ec-001",
    "workspace_id": "ws-test",
    "entity_a": "alice",
    "entity_b": "bob",
    "count": 5,
    "strength": 0.625,
    "created_at": 2000000,
}

SAMPLE_TOPIC_CLUSTER = {
    "id": "tp-001",
    "workspace_id": "ws-test",
    "topic": "python",
    "count": 4,
    "memory_ids": '["m1","m2","m3","m4"]',
    "top_terms": '["python","code","test","deploy","server"]',
    "avg_confidence": 0.85,
    "created_at": 2000000,
}


# ── detect_temporal_clusters ──────────────────────────────────────────


class TestDetectTemporalClusters:
    def test_calls_reducer_and_queries_result(self):
        client = MockClient()
        client._query.return_value = [SAMPLE_TEMPORAL_CLUSTER]

        result = client.detect_temporal_clusters("ws-test")

        client._call.assert_called_once_with(
            "detect_temporal_clusters", ["ws-test"]
        )
        client._query.assert_called_once_with(
            "temporal_cluster_result", workspace_id="ws-test"
        )
        assert len(result) == 1
        assert result[0]["start_time"] == 1000000
        assert result[0]["count"] == 3

    def test_empty_result(self):
        client = MockClient()
        client._query.return_value = []

        result = client.detect_temporal_clusters("ws-empty")

        assert result == []

    def test_returns_list_of_dicts(self):
        client = MockClient()
        client._query.return_value = [SAMPLE_TEMPORAL_CLUSTER]

        result = client.detect_temporal_clusters("ws-test")

        assert isinstance(result, list)
        assert all(isinstance(r, dict) for r in result)


# ── detect_entity_cooccurrences ───────────────────────────────────────


class TestDetectEntityCooccurrences:
    def test_calls_reducer_and_queries_result(self):
        client = MockClient()
        client._query.return_value = [SAMPLE_COOCCURRENCE]

        result = client.detect_entity_cooccurrences("ws-test")

        client._call.assert_called_once_with(
            "detect_entity_cooccurrences", ["ws-test"]
        )
        client._query.assert_called_once_with(
            "entity_cooccurrence_result", workspace_id="ws-test"
        )
        assert len(result) == 1
        assert result[0]["entity_a"] == "alice"
        assert result[0]["entity_b"] == "bob"
        assert result[0]["count"] == 5

    def test_empty_result(self):
        client = MockClient()
        client._query.return_value = []

        result = client.detect_entity_cooccurrences("ws-empty")

        assert result == []

    def test_strength_is_float(self):
        client = MockClient()
        client._query.return_value = [SAMPLE_COOCCURRENCE]

        result = client.detect_entity_cooccurrences("ws-test")

        assert isinstance(result[0]["strength"], float)


# ── detect_topic_clusters ─────────────────────────────────────────────


class TestDetectTopicClusters:
    def test_calls_reducer_and_queries_result(self):
        client = MockClient()
        client._query.return_value = [SAMPLE_TOPIC_CLUSTER]

        result = client.detect_topic_clusters("ws-test")

        client._call.assert_called_once_with(
            "detect_topic_clusters", ["ws-test"]
        )
        client._query.assert_called_once_with(
            "topic_cluster_result", workspace_id="ws-test"
        )
        assert len(result) == 1
        assert result[0]["topic"] == "python"
        assert result[0]["count"] == 4

    def test_empty_result(self):
        client = MockClient()
        client._query.return_value = []

        result = client.detect_topic_clusters("ws-empty")

        assert result == []

    def test_avg_confidence_is_float(self):
        client = MockClient()
        client._query.return_value = [SAMPLE_TOPIC_CLUSTER]

        result = client.detect_topic_clusters("ws-test")

        assert isinstance(result[0]["avg_confidence"], float)
