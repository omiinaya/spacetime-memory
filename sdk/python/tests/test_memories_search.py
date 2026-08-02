"""Tests for spacetime_memory.client._memories_search — SearchMixin.

All tests use mocked client methods (_call, _query, _embed, _emit_event)
so no live SpacetimeDB is required.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


class TestBoostWithEntitySignal:
    """Entity-aware search result boosting."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        m._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        m._call = MagicMock()
        m._query = MagicMock(return_value=[])
        m._emit_event = MagicMock()
        return m

    def test_empty_rows_returns_unchanged(self, mixin):
        result = mixin._boost_with_entity_signal("query", [], "ws-1")
        assert result == []

    def test_empty_query_returns_unchanged(self, mixin):
        result = mixin._boost_with_entity_signal("", [{"id": "1"}], "ws-1")
        assert result == [{"id": "1"}]

    def test_no_kg_nodes_no_links_returns_unchanged(self, mixin):
        mixin._query = MagicMock(return_value=[])
        rows = [{"memory_content": "hello world", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("hello", rows, "ws-1")
        assert result == rows

    def test_kg_nodes_raise_error_returns_unchanged(self, mixin):
        mixin._query = MagicMock(side_effect=RuntimeError("no kg"))
        rows = [{"memory_content": "hello", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("hello", rows, "ws-1")
        assert result == rows

    def test_entity_link_raise_still_uses_nodes(self, mixin):
        def _side_effect(table, **kw):
            if table == "kg_node":
                return [{"id": "n1", "label": "AI", "summary": "", "node_type": "concept"}]
            raise RuntimeError("no entity_link")

        mixin._query = MagicMock(side_effect=_side_effect)
        rows = [{"memory_content": "AI is transforming the world", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("Tell me about AI", rows, "ws-1")
        assert len(result) == 1
        # Should have boosted the score
        assert result[0]["fused_score"] > 1.0
        assert "entity_boost" in result[0]

    def test_exact_label_match_boosts_score(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "n1", "label": "Reinforcement Learning", "summary": "", "node_type": "concept"},
        ])
        rows = [{"memory_content": "Reinforcement Learning from human feedback", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal(
            "What is Reinforcement Learning?", rows, "ws-1"
        )
        assert result[0]["fused_score"] > 1.0
        assert result[0]["entity_boost"] > 0

    def test_alias_matching_boosts_score(self, mixin):
        # Return empty kg_node, but entity_link with aliases
        def _query_side(table, **kw):
            if table == "kg_node":
                return []
            if table == "entity_link":
                return [{
                    "id": "el-1",
                    "entity_name": "RLHF",
                    "aliases_json": json.dumps(["reinforcement learning from human feedback"]),
                    "entity_type": "method",
                }]
            return []

        mixin._query = MagicMock(side_effect=_query_side)
        rows = [{"memory_content": "reinforcement learning from human feedback is a key technique",
                 "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("Tell me about RLHF", rows, "ws-1")
        assert result[0]["fused_score"] > 1.0

    def test_no_matching_entities_no_boost(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "n1", "label": "Python", "summary": "", "node_type": "language"},
        ])
        rows = [{"memory_content": "JavaScript is a programming language", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("JavaScript", rows, "ws-1")
        # No boost since the content doesn't mention "Python"
        assert result[0]["fused_score"] == 1.0

    def test_multiple_entity_hits_capped_boost(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "n1", "label": "AI", "summary": "", "node_type": "concept"},
            {"id": "n2", "label": "ML", "summary": "", "node_type": "concept"},
        ])
        rows = [{"memory_content": "AI and ML are related fields", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("Tell me about AI and ML", rows, "ws-1")
        # Both entities matched — proportion = min(2/2, 1.0) = 1.0 → boost = 0.15
        assert result[0]["entity_boost"] == pytest.approx(0.15, 0.01)
        assert result[0]["fused_score"] == pytest.approx(1.0 * 1.15, 0.01)

    def test_word_level_overlap_works(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "n1", "label": "Deep Learning", "summary": "", "node_type": "concept"},
        ])
        rows = [{"memory_content": "deep learning models need data", "fused_score": 1.0}]
        # "deep" and "learning" appear in both query and label
        result = mixin._boost_with_entity_signal("deep learning concepts", rows, "ws-1")
        assert len(result) == 1
        assert result[0].get("entity_boost", 0) > 0

    def test_summary_match_works(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "n1", "label": "RL", "summary": "reinforcement learning techniques",
             "node_type": "concept"},
        ])
        rows = [{"memory_content": "RL is used in games", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal(
            "reinforcement learning techniques", rows, "ws-1"
        )
        assert result[0]["entity_boost"] > 0

    def test_content_field_fallback_from_memory_content(self, mixin):
        """When memory_content is absent, falls back to 'content' key."""
        mixin._query = MagicMock(return_value=[
            {"id": "n1", "label": "AI", "summary": "", "node_type": "concept"},
        ])
        rows = [{"content": "AI is cool", "fused_score": 1.0}]
        result = mixin._boost_with_entity_signal("Tell me about AI", rows, "ws-1")
        assert result[0]["entity_boost"] > 0


class TestFuseAndDeduplicate:
    """Min-max normalization, weighted fusion, and deduplication."""

    def test_empty_inputs(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        weights = {"semantic": 1.0, "keyword": 0.0, "graph": 0.0, "temporal": 0.0, "binary": 0.0}
        result = m._fuse_and_deduplicate([], [], {}, {}, {}, weights)
        assert result == []

    def test_basic_fusion(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        rows = [
            {"entity_id": "e1", "strategy": "semantic", "score": 0.9},
            {"entity_id": "e2", "strategy": "keyword", "score": 0.5},
        ]
        tantivy_rows = []
        per_strat = {
            "semantic": [{"entity_id": "e1", "score": 0.9, "strategy": "semantic"}],
            "keyword": [{"entity_id": "e2", "score": 0.5, "strategy": "keyword"}],
        }
        strat_min = {"semantic": 0.9, "keyword": 0.5}
        strat_max = {"semantic": 0.9, "keyword": 0.5}
        weights = {"semantic": 0.6, "keyword": 0.4, "graph": 0.0, "temporal": 0.0, "binary": 0.0}
        result = m._fuse_and_deduplicate(rows, tantivy_rows, per_strat, strat_min, strat_max, weights)
        assert len(result) == 2
        # Each entity should have a fused_score
        for r in result:
            assert "fused_score" in r

    def test_deduplication_by_entity_id(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        rows = [
            {"entity_id": "e1", "strategy": "semantic", "score": 0.9},
            {"entity_id": "e1", "strategy": "keyword", "score": 0.5},  # same entity
        ]
        tantivy_rows = []
        per_strat = {
            "semantic": [{"entity_id": "e1", "score": 0.9, "strategy": "semantic"}],
            "keyword": [{"entity_id": "e1", "score": 0.5, "strategy": "keyword"}],
        }
        strat_min = {"semantic": 0.9, "keyword": 0.5}
        strat_max = {"semantic": 0.9, "keyword": 0.5}
        weights = {"semantic": 0.6, "keyword": 0.4, "graph": 0.0, "temporal": 0.0, "binary": 0.0}
        result = m._fuse_and_deduplicate(rows, tantivy_rows, per_strat, strat_min, strat_max, weights)
        # e1 should appear only once
        assert len(result) == 1

    def test_tantivy_rows_merged(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        rows = [
            {"entity_id": "e1", "strategy": "semantic", "score": 0.9},
        ]
        tantivy_rows = [
            {"entity_id": "e2", "strategy": "keyword", "score": 0.7},
        ]
        per_strat = {
            "semantic": [{"entity_id": "e1", "score": 0.9, "strategy": "semantic"}],
            "keyword": [{"entity_id": "e2", "score": 0.7, "strategy": "keyword"}],
        }
        strat_min = {"semantic": 0.9, "keyword": 0.7}
        strat_max = {"semantic": 0.9, "keyword": 0.7}
        weights = {"semantic": 0.5, "keyword": 0.5, "graph": 0.0, "temporal": 0.0, "binary": 0.0}
        result = m._fuse_and_deduplicate(rows, tantivy_rows, per_strat, strat_min, strat_max, weights)
        assert len(result) == 2
        eids = {r["entity_id"] for r in result}
        assert eids == {"e1", "e2"}

    def test_results_sorted_by_fused_score(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        rows = [
            {"entity_id": "e1", "strategy": "semantic", "score": 0.3},
            {"entity_id": "e2", "strategy": "keyword", "score": 0.9},
        ]
        tantivy_rows = []
        per_strat = {
            "semantic": [{"entity_id": "e1", "score": 0.3, "strategy": "semantic"}],
            "keyword": [{"entity_id": "e2", "score": 0.9, "strategy": "keyword"}],
        }
        strat_min = {"semantic": 0.0, "keyword": 0.0}
        strat_max = {"semantic": 1.0, "keyword": 1.0}
        weights = {"semantic": 0.5, "keyword": 0.5, "graph": 0.0, "temporal": 0.0, "binary": 0.0}
        result = m._fuse_and_deduplicate(rows, tantivy_rows, per_strat, strat_min, strat_max, weights)
        assert result[0]["entity_id"] == "e2"  # higher score first


class TestEnrichContent:
    """Content lookup with batch confidence and veracity weighting."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        m._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        m._call = MagicMock()
        m._query = MagicMock(return_value=[])
        m._emit_event = MagicMock()
        return m

    def test_empty_rows(self, mixin):
        result = mixin._enrich_content([], "ws-1")
        assert result == []

    def test_memory_rows_get_confidence_veracity(self, mixin):
        def _query_side(table, **kw):
            if table == "memory":
                return [{"id": "m1", "confidence": 0.9}]
            return []

        mixin._query = MagicMock(side_effect=_query_side)
        rows = [{"entity_id": "m1", "entity_type": "memory", "content": "test", "fused_score": 1.0}]
        result = mixin._enrich_content(rows, "ws-1")
        assert len(result) == 1
        assert result[0]["memory_content"] == "test"
        assert "veracity_multiplier" in result[0]
        assert "snippet" in result[0]

    def test_node_rows_get_label(self, mixin):
        def _query_side(table, **kw):
            if table == "kg_node":
                return [{"id": "n1", "label": "AI Concept"}]
            return []

        mixin._query = MagicMock(side_effect=_query_side)
        rows = [{"entity_id": "n1", "entity_type": "node", "fused_score": 1.0}]
        result = mixin._enrich_content(rows, "ws-1")
        assert result[0]["memory_content"] == "AI Concept"

    def test_memory_query_failure_graceful(self, mixin):
        def _query_side(table, **kw):
            if table == "memory":
                raise RuntimeError("db error")
            return []

        mixin._query = MagicMock(side_effect=_query_side)
        rows = [{"entity_id": "m1", "entity_type": "memory", "content": "test", "fused_score": 1.0}]
        result = mixin._enrich_content(rows, "ws-1")
        assert len(result) == 1
        assert result[0]["memory_content"] == "test"

    def test_note_rows_get_content(self, mixin):
        def _query_side(table, **kw):
            if table == "note":
                return [{"id": "note-1", "title": "Title", "content": "Body content"}]
            return []

        mixin._query = MagicMock(side_effect=_query_side)
        rows = [{"entity_id": "note-1", "entity_type": "note", "fused_score": 1.0}]
        result = mixin._enrich_content(rows, "ws-1")
        assert "Title" in result[0]["memory_content"]
        assert "Body content" in result[0]["memory_content"]

    def test_unknown_entity_type_gets_empty_content(self, mixin):
        mixin._query = MagicMock(return_value=[])
        rows = [{"entity_id": "x1", "entity_type": "unknown", "fused_score": 1.0}]
        result = mixin._enrich_content(rows, "ws-1")
        assert result[0]["memory_content"] == ""


class TestKeywordFallback:
    """Non-semantic keyword-only search fallback."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        m._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        m._call = MagicMock()
        m._query = MagicMock(return_value=[])
        m._emit_event = MagicMock()
        return m

    def test_returns_empty_when_no_data(self, mixin):
        result = mixin._keyword_fallback("ws-1", "query", "", "", 10)
        assert result == []

    def test_returns_memories_matching_keywords(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "m1", "content": "hello world", "entity_type": "memory", "created_at": 100.0},
            {"id": "m2", "content": "goodbye world", "entity_type": "memory", "created_at": 200.0},
        ])
        result = mixin._keyword_fallback("ws-1", "hello", "", "", 10)
        assert len(result) == 1
        assert result[0]["id"] == "m1"

    def test_date_range_filtering(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "m1", "content": "hello", "entity_type": "memory", "created_at": 100.0},
            {"id": "m2", "content": "world", "entity_type": "memory", "created_at": 200.0},
        ])
        # after=150 → only m2 (200 > 150)
        result = mixin._keyword_fallback("ws-1", "", "", "", 10, after=150.0)
        assert len(result) == 1
        assert result[0]["id"] == "m2"

        # before=150 → only m1 (100 < 150)
        result = mixin._keyword_fallback("ws-1", "", "", "", 10, before=150.0)
        assert len(result) == 1
        assert result[0]["id"] == "m1"

    def test_memory_type_and_tier_filters(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "m1", "content": "test", "entity_type": "memory", "created_at": 100.0},
        ])
        result = mixin._keyword_fallback("ws-1", "", "experience", "L1", 10)
        assert len(result) == 1

    def test_emits_search_performed_event(self, mixin):
        mixin._query = MagicMock(return_value=[])
        mixin._keyword_fallback("ws-1", "query", "", "", 10)
        mixin._emit_event.assert_called_once()
        args = mixin._emit_event.call_args[0]
        assert args[0] == "search.performed"

    def test_deduplicates_by_entity_type_and_id(self, mixin):
        def _query_side(table, **kw):
            if table == "memory":
                return [
                    {"id": "m1", "content": "hello world", "entity_type": "memory",
                     "created_at": 100.0},
                ]
            if table == "note":
                return [
                    {"id": "m1", "content": "note content", "title": "Note",
                     "created_at": 200.0},
                ]
            return []

        mixin._query = MagicMock(side_effect=_query_side)
        result = mixin._keyword_fallback("ws-1", "", "", "", 10)
        # Both entities present (one memory, one note — different entity_types)
        assert len(result) == 2

    def test_fused_score_assigned(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "m1", "content": "test", "entity_type": "memory", "created_at": 100.0},
        ])
        result = mixin._keyword_fallback("ws-1", "", "", "", 10)
        assert result[0].get("fused_score", 0) > 0


class TestSearch:
    """Main search entry point — basic integration tests."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.client._memories_search import SearchMixin

        m = SearchMixin()
        m._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        m._call = MagicMock()
        m._query = MagicMock(return_value=[])
        m._emit_event = MagicMock()
        m._tantivy_search = MagicMock(return_value=[])
        m.embedder_url = "http://localhost:9090"
        m._http = MagicMock()
        m._http.get.return_value = MagicMock(status_code=200)
        m._binary_cache = {}
        m.plugin_manager = None
        m._query_cache = None
        m._sql = MagicMock(return_value=[])
        return m

    def test_empty_workspace_returns_empty(self, mixin):
        result = mixin.search(workspace_id="ws-1", query="test")
        assert isinstance(result, list)

    def test_temporal_filter_resolves(self, mixin):
        result = mixin.search(
            workspace_id="ws-1",
            query="test",
            temporal_filter={"from": 100.0, "to": 200.0},
        )
        assert isinstance(result, list)

    def test_semantic_false_uses_tantivy(self, mixin):
        mixin._tantivy_search = MagicMock(return_value=[
            {"entity_id": "m1", "entity_type": "memory", "content": "test", "score": 0.5},
        ])
        result = mixin.search(workspace_id="ws-1", query="test", semantic=False)
        assert isinstance(result, list)

    def test_return_schema_llm(self, mixin):
        mixin._query = MagicMock(return_value=[
            {"id": "m1", "content": "test", "entity_type": "memory", "created_at": 100.0},
        ])
        result = mixin.search(workspace_id="ws-1", query="test", return_schema="llm")
        assert isinstance(result, list)
        if result:
            assert "relevance" in result[0]
