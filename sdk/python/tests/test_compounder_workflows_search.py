"""Unit tests for CompounderWorkflowsSearch — search methods."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestCompounderWorkflowsSearch:
    """Tests for CompounderWorkflowsSearch.search_entities()."""

    def test_no_filters_returns_empty(self):
        """When no filters and no semantic query, returns empty list."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        result = obj.search_entities(workspace_id="ws1")
        assert result == []

    def test_filters_by_label(self):
        """search_entities with a label filter queries kg_node with that label."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"id": "n1", "label": "RLHF", "node_type": "concept"},
        ]
        result = obj.search_entities(workspace_id="ws1", label="RLHF")
        assert len(result) == 1
        assert result[0]["label"] == "RLHF"
        obj._client._query.assert_called_once_with(
            "kg_node", workspace_id="ws1", filter_dict={"label": "RLHF"}
        )

    def test_filters_by_node_type(self):
        """search_entities filters by node_type."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [{"id": "n1", "label": "Alice", "node_type": "person"}],
            [],  # semantic - all_nodes empty
        ]
        result = obj.search_entities(workspace_id="ws1", node_type="person")
        assert len(result) == 1
        assert result[0]["node_type"] == "person"

    def test_filters_by_label_and_type(self):
        """search_entities combines label and type filter."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"id": "n1", "label": "OpenAI", "node_type": "org"},
        ]
        result = obj.search_entities(
            workspace_id="ws1", label="OpenAI", node_type="org"
        )
        assert len(result) == 1
        obj._client._query.assert_called_once_with(
            "kg_node", workspace_id="ws1", filter_dict={"label": "OpenAI", "node_type": "org"}
        )

    def test_semantic_query_calls_search(self):
        """Semantic query calls client.search and looks up results."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_type": "node", "entity_id": "n1", "score": 0.9},
        ]
        obj._client._query.return_value = [
            {"id": "n1", "label": "RLHF", "node_type": "concept", "summary": "Reinforcement Learning from Human Feedback"},
        ]
        result = obj.search_entities(
            workspace_id="ws1", semantic_query="machine learning"
        )
        assert len(result) == 1
        assert result[0]["label"] == "RLHF"
        obj._client.search.assert_called_once()

    def test_semantic_ignores_non_node_results(self):
        """Semantic search results with entity_type != 'node' are ignored."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_type": "memory", "entity_id": "m1"},
            {"entity_type": "note", "entity_id": "n1"},
        ]
        obj._client._query.return_value = []  # no filter, no semantic nodes
        result = obj.search_entities(
            workspace_id="ws1", semantic_query="test"
        )
        assert result == []

    def test_merges_semantic_and_filtered_results(self):
        """Semantic results come first, then filtered, with dedup."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_type": "node", "entity_id": "n2", "score": 0.95},
        ]
        # First call: filter dict (label="RLHF") — returns n1
        # Second call: all_nodes lookup — returns n1, n2, n3
        obj._client._query.side_effect = [
            [{"id": "n1", "label": "RLHF", "node_type": "concept"}],  # filter
            [
                {"id": "n1", "label": "RLHF", "node_type": "concept"},
                {"id": "n2", "label": "PPO", "node_type": "concept"},
                {"id": "n3", "label": "DPO", "node_type": "concept"},
            ],  # all_nodes
        ]
        result = obj.search_entities(
            workspace_id="ws1", label="RLHF", semantic_query="optimization"
        )
        # Should be: n2 (semantic match), then n1 (filtered label match) — n2 first
        assert len(result) == 2
        assert result[0]["id"] == "n2"  # semantic first
        assert result[1]["id"] == "n1"  # filter second

    def test_respects_limit(self):
        """Result list should be truncated to limit."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_type": "node", "entity_id": f"n{i}", "score": 0.9}
            for i in range(1, 11)
        ]
        obj._client._query.return_value = [
            {"id": f"n{i}", "label": f"E{i}", "node_type": "concept"} for i in range(1, 11)
        ]
        result = obj.search_entities(
            workspace_id="ws1", semantic_query="test", limit=5
        )
        assert len(result) == 5

    def test_label_is_none_skips_label_filter(self):
        """Passing label=None should skip the label filter."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = []
        obj._client._query.side_effect = [
            [],  # no filter → empty
        ]
        result = obj.search_entities(
            workspace_id="ws1", label=None, node_type=None, semantic_query=None
        )
        assert result == []


@pytest.mark.unit
class TestFindNearDuplicates:
    """Tests for CompounderWorkflowsSearch.find_near_duplicates()."""

    def test_empty_content_returns_empty(self):
        """Empty or whitespace-only content returns empty list."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        assert obj.find_near_duplicates("") == []
        assert obj.find_near_duplicates("   ") == []

    def test_calls_search_with_content(self):
        """find_near_duplicates calls client.search with the content."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = []
        result = obj.find_near_duplicates("test content", workspace_id="ws1")
        obj._client.search.assert_called_once()
        args, kwargs = obj._client.search.call_args
        assert args[0] == "ws1"
        assert kwargs["query"] == "test content"
        assert kwargs["semantic"] is True
        assert result == []

    def test_filters_by_threshold(self):
        """Only results above threshold are returned."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_id": "m1", "content": "similar A", "score": 0.95, "entity_type": "memory"},
            {"entity_id": "m2", "content": "similar B", "score": 0.88, "entity_type": "memory"},
            {"entity_id": "m3", "content": "similar C", "score": 0.73, "entity_type": "memory"},
        ]
        dupes = obj.find_near_duplicates("test", threshold=0.92)
        assert len(dupes) == 1
        assert dupes[0]["entity_id"] == "m1"

    def test_all_below_threshold_returns_empty(self):
        """When all results are below threshold, returns empty list."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_id": "m1", "content": "vaguely related", "score": 0.45},
        ]
        assert obj.find_near_duplicates("test", threshold=0.92) == []

    def test_zero_threshold_returns_all(self):
        """Zero threshold returns all results."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_id": "m1", "score": 0.1},
            {"entity_id": "m2", "score": 0.2},
        ]
        dupes = obj.find_near_duplicates("test", threshold=0.0)
        assert len(dupes) == 2

    def test_custom_limit_passed_to_search(self):
        """Custom limit is passed through to client.search."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = []
        obj.find_near_duplicates("content", limit=10)
        _, kwargs = obj._client.search.call_args
        assert kwargs["limit"] == 10

    def test_default_threshold_used(self):
        """Default threshold of 0.92 is used when not specified."""
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        obj = CompounderWorkflowsSearch()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_id": "m1", "score": 0.95},
            {"entity_id": "m2", "score": 0.91},
        ]
        dupes = obj.find_near_duplicates("test")
        assert len(dupes) == 1  # Only 0.95 passes default 0.92 threshold
