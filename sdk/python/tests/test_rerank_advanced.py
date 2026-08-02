"""Advanced tests for multi-reranker search (Gap #4).

Tests cross-encoder, MMR, node-distance, fusion reranking, SearchFilterDSL
parsing, and all 18 search recipes.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spacetime_memory.client._rerank import (
    RECIPE_REGISTRY,
    BaseReranker,
    CrossEncoderReranker,
    FusionReranker,
    MMRReranker,
    NodeDistanceReranker,
    SearchFilter,
    SearchFilterDSL,
    SearchRecipe,
    get_reranker_for_recipe,
    list_recipes,
    resolve_recipe,
)

# =====================================================================
# Sample data
# =====================================================================

SAMPLE_CANDIDATES = [
    {"entity_id": "1", "content": "Machine learning is a subset of artificial intelligence",
     "memory_content": "Machine learning is a subset of artificial intelligence", "score": 0.9},
    {"entity_id": "2", "content": "Deep learning uses neural networks with many layers",
     "memory_content": "Deep learning uses neural networks with many layers", "score": 0.8},
    {"entity_id": "3", "content": "Reinforcement learning trains agents via rewards",
     "memory_content": "Reinforcement learning trains agents via rewards", "score": 0.7},
    {"entity_id": "4", "content": "Python is a programming language for data science",
     "memory_content": "Python is a programming language for data science", "score": 0.2},
    {"entity_id": "5", "content": "Statistics provides tools for data analysis",
     "memory_content": "Statistics provides tools for data analysis", "score": 0.1},
]


# =====================================================================
# Base Reranker
# =====================================================================


class TestBaseReranker:
    def test_abstract_not_implemented(self):
        class IncompleteReranker(BaseReranker):
            pass
        r = IncompleteReranker()
        with pytest.raises(NotImplementedError):
            r.rerank("test", [])

    def test_concrete_subclass(self):
        class SimpleReranker(BaseReranker):
            def rerank(self, query, candidates, **kwargs):
                return sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)
        r = SimpleReranker()
        result = r.rerank("test", SAMPLE_CANDIDATES)
        assert result[0]["entity_id"] == "1"


# =====================================================================
# Cross-Encoder Reranker
# =====================================================================


class TestCrossEncoderReranker:
    def test_init_defaults(self):
        r = CrossEncoderReranker()
        assert r._endpoint == "http://localhost:9090/v1/rerank"
        assert r._model == "bge-reranker-large"

    def test_empty_candidates(self):
        r = CrossEncoderReranker()
        assert r.rerank("test", []) == []

    def test_rerank_fallback_to_llm(self):
        """When the embedder service is unreachable, fall back to LLM scoring."""
        r = CrossEncoderReranker(endpoint="http://localhost:1/rerank")
        # With no LLM endpoint available either, it should still return results
        result = r.rerank("machine learning", SAMPLE_CANDIDATES)
        assert len(result) == len(SAMPLE_CANDIDATES)
        # All should have cross_encoder_score
        for item in result:
            assert "cross_encoder_score" in item

    def test_content_key_override(self):
        """Test using a custom content_key."""
        candidates = [
            {"entity_id": "a", "text": "Some content here", "score": 0.5},
            {"entity_id": "b", "text": "More content", "score": 0.3},
        ]
        r = CrossEncoderReranker(endpoint="http://localhost:1/rerank")
        result = r.rerank("test", candidates, content_key="text")
        assert len(result) == 2


# =====================================================================
# Node Distance Reranker
# =====================================================================


class TestNodeDistanceReranker:
    def test_init(self):
        r = NodeDistanceReranker()
        assert r._client is None

    def test_no_client_returns_unchanged(self):
        r = NodeDistanceReranker()
        result = r.rerank("test", SAMPLE_CANDIDATES)
        assert len(result) == len(SAMPLE_CANDIDATES)

    def test_with_mock_client(self):
        """Test with a mock client that returns empty KG results gracefully."""
        mock = MagicMock()
        mock._sql = MagicMock(return_value=[])
        r = NodeDistanceReranker(client=mock)
        result = r.rerank("machine learning", SAMPLE_CANDIDATES, workspace_id="ws-1")
        # Should not crash
        assert len(result) == len(SAMPLE_CANDIDATES)

    def test_with_mock_client_and_nodes(self):
        """Test with a mock client that returns some KG nodes."""
        mock = MagicMock()
        # First call for _find_query_entities
        mock._sql = MagicMock(return_value=[
            {"label": "Machine Learning", "node_id": "n1"},
            {"label": "Deep Learning", "node_id": "n2"},
        ])
        r = NodeDistanceReranker(client=mock)
        result = r.rerank("machine learning", SAMPLE_CANDIDATES, workspace_id="ws-1")
        assert len(result) == len(SAMPLE_CANDIDATES)

    def test_esc_sql_helper(self):
        from spacetime_memory.client._rerank import _esc_sql
        assert _esc_sql("hello") == "hello"
        assert _esc_sql("O'Brien") == "O''Brien"
        assert _esc_sql("") == ""


# =====================================================================
# MMR Reranker
# =====================================================================


class TestMMRReranker:
    def test_empty_and_single(self):
        r = MMRReranker()
        assert r.rerank("test", []) == []
        single = [{"entity_id": "1", "content": "test", "score": 0.5}]
        assert r.rerank("test", single) == single

    def test_diversity_selection(self):
        """MMR with low lambda should favour diversity."""
        candidates = [
            {"entity_id": "1", "content": "Python for data science and machine learning",
             "memory_content": "Python for data science and machine learning", "score": 0.9},
            {"entity_id": "2", "content": "Python libraries numpy pandas scikit-learn",
             "memory_content": "Python libraries numpy pandas scikit-learn", "score": 0.8},
            {"entity_id": "3", "content": "Rust systems programming language performance",
             "memory_content": "Rust systems programming language performance", "score": 0.3},
        ]
        r = MMRReranker(lambda_param=0.0)  # pure diversity
        result = r.rerank("programming", candidates, top_k=3)
        assert len(result) == 3
        # With pure diversity, the most different result (entity 3) should appear
        # before the second similar result
        top_ids = [r["entity_id"] for r in result[:2]]
        assert "3" in top_ids, "MMR should rank diverse result higher at lambda=0"

    def test_relevance_focus(self):
        """MMR with high lambda should favour relevance."""
        candidates = [
            {"entity_id": "1", "content": "Machine learning fundamentals",
             "memory_content": "Machine learning fundamentals", "score": 0.9},
            {"entity_id": "2", "content": "More machine learning content",
             "memory_content": "More machine learning content", "score": 0.85},
            {"entity_id": "3", "content": "Unrelated topic entirely",
             "memory_content": "Unrelated topic entirely", "score": 0.1},
        ]
        r = MMRReranker(lambda_param=0.95)  # high lambda = favour relevance
        result = r.rerank("machine learning", candidates, top_k=3)
        assert result[0]["entity_id"] == "1"  # highest relevance first

    def test_mmr_scores_field(self):
        """Check that mmr_score and mmr_rank are set."""
        r = MMRReranker()
        result = r.rerank("test", SAMPLE_CANDIDATES[:3], top_k=3)
        for item in result:
            assert "mmr_score" in item
            assert "mmr_rank" in item


# =====================================================================
# Fusion Reranker
# =====================================================================


class TestFusionReranker:
    def test_empty(self):
        r = FusionReranker()
        assert r.rerank("test", []) == []

    def test_no_rerankers_returns_unchanged(self):
        r = FusionReranker()
        result = r.rerank("test", SAMPLE_CANDIDATES)
        assert len(result) == len(SAMPLE_CANDIDATES)

    def test_with_mock_rerankers(self):
        """Fusion with two mock rerankers should combine scores."""
        class MockRerankerA(BaseReranker):
            def rerank(self, query, candidates, **kwargs):
                for i, c in enumerate(candidates):
                    c["score"] = 1.0 - (i * 0.1)
                return candidates

        class MockRerankerB(BaseReranker):
            def rerank(self, query, candidates, **kwargs):
                for i, c in enumerate(candidates):
                    c["score"] = 0.5 + (i * 0.1)
                return candidates

        r = FusionReranker()
        r.add(MockRerankerA(), 0.5).add(MockRerankerB(), 0.5)
        result = r.rerank("test", SAMPLE_CANDIDATES[:3])
        assert len(result) == 3
        for item in result:
            assert "fusion_score" in item
            assert isinstance(item["fusion_score"], float)

    def test_add_returns_self(self):
        r = FusionReranker()
        # Test method chaining
        assert r.add(MMRReranker(), 1.0) is r

    def test_with_real_mmr_reranker(self):
        """Fusion with real MMR reranker."""
        r = FusionReranker()
        r.add(MMRReranker(lambda_param=0.5), 1.0)
        result = r.rerank("machine learning", SAMPLE_CANDIDATES[:3], top_k=3)
        assert len(result) == 3
        for item in result:
            assert "fusion_score" in item


# =====================================================================
# SearchFilter DSL
# =====================================================================


class TestSearchFilter:
    def test_empty(self):
        f = SearchFilter()
        where, params = f.to_sql_where()
        assert where == "1=1"
        assert params == []

    def test_empty_parse(self):
        f = SearchFilter.parse("")
        assert f.node_labels == []
        assert f.edge_types == []

    def test_parse_node_labels(self):
        f = SearchFilter.parse('node_labels:["Person","Org"]')
        assert f.node_labels == ["Person", "Org"]

    def test_parse_edge_types(self):
        f = SearchFilter.parse('edge_types:["knows","works_at"]')
        assert f.edge_types == ["knows", "works_at"]

    def test_parse_temporal(self):
        f = SearchFilter.parse('temporal:{"after": 1700000000, "before": 1800000000}')
        assert f.temporal_after == 1700000000
        assert f.temporal_before == 1800000000

    def test_parse_property_filters(self):
        f = SearchFilter.parse('property_filters:{"confidence": {"gte": 0.5}}')
        assert "confidence" in f.property_filters
        assert f.property_filters["confidence"]["gte"] == 0.5

    def test_parse_memory_types(self):
        f = SearchFilter.parse('memory_types:["fact","observation"]')
        assert f.memory_types == ["fact", "observation"]

    def test_parse_entity_ids(self):
        f = SearchFilter.parse('entity_ids:["e1","e2"]')
        assert f.entity_ids == ["e1", "e2"]

    def test_parse_combined(self):
        f = SearchFilter.parse(
            'node_labels:["Person"] edge_types:["knows"] '
            'temporal:{"after": 1700000000} '
            'property_filters:{"confidence": {"gte": 0.5}}'
        )
        assert f.node_labels == ["Person"]
        assert f.edge_types == ["knows"]
        assert f.temporal_after == 1700000000
        assert "confidence" in f.property_filters

    def test_to_sql_where(self):
        f = SearchFilter(
            node_labels=["Person", "Org"],
            edge_types=["knows"],
            temporal_after=1700000000.0,
            temporal_before=1800000000.0,
            memory_types=["fact"],
            entity_ids=["e1"],
        )
        where, params = f.to_sql_where()
        assert "label IN" in where
        assert "relation IN" in where
        assert "created_at >=" in where
        assert "memory_type IN" in where
        assert "entity_id IN" in where

    def test_to_sql_where_with_table_alias(self):
        f = SearchFilter(node_labels=["Person"])
        where, _ = f.to_sql_where(table_alias="n")
        assert "n.label IN" in where

    def test_parse_property_filters_with_in(self):
        f = SearchFilter.parse('property_filters:{"status": {"in": ["active", "pending"]}}')
        assert "status" in f.property_filters
        assert f.property_filters["status"]["in"] == ["active", "pending"]

    def test_legacy_alias(self):
        """SearchFilterDSL should be the same as SearchFilter."""
        assert SearchFilterDSL is SearchFilter


# =====================================================================
# Recipe Registry — all 18 recipes
# =====================================================================


class TestRecipeRegistry:
    def test_registry_has_18_recipes(self):
        """There should be exactly 18 search recipes."""
        assert len(RECIPE_REGISTRY) == 18

    def test_all_recipes_have_required_fields(self):
        for name, recipe in RECIPE_REGISTRY.items():
            assert recipe.name == name, f"Recipe '{name}' name mismatch"
            assert isinstance(recipe.description, str), f"Recipe '{name}' missing description"
            assert recipe.strategy in (
                "keyword", "semantic", "hybrid", "temporal", "graph"
            ), f"Recipe '{name}' invalid strategy: {recipe.strategy}"
            assert isinstance(recipe.top_k, int) and recipe.top_k > 0

    def test_keyword_recipe(self):
        recipe = RECIPE_REGISTRY["keyword"]
        assert recipe.strategy == "keyword"

    def test_semantic_recipe(self):
        recipe = RECIPE_REGISTRY["semantic"]
        assert recipe.strategy == "semantic"

    def test_hybrid_recipe(self):
        recipe = RECIPE_REGISTRY["hybrid"]
        assert recipe.strategy == "hybrid"

    def test_temporal_recipe(self):
        recipe = RECIPE_REGISTRY["temporal"]
        assert recipe.strategy == "temporal"

    def test_entity_focused_recipe(self):
        recipe = RECIPE_REGISTRY["entity_focused"]
        assert recipe.reranker == "node-distance"

    def test_recency_boosted_recipe(self):
        recipe = RECIPE_REGISTRY["recency_boosted"]
        assert "recency_boost" in recipe.kwargs

    def test_exact_phrase_recipe(self):
        recipe = RECIPE_REGISTRY["exact_phrase"]
        assert recipe.kwargs.get("exact_phrase") is True

    def test_boolean_recipe(self):
        recipe = RECIPE_REGISTRY["boolean"]
        assert recipe.kwargs.get("boolean_mode") is True

    def test_fuzzy_recipe(self):
        recipe = RECIPE_REGISTRY["fuzzy"]
        assert recipe.kwargs.get("fuzzy") is True
        assert recipe.kwargs.get("fuzzy_distance") == 2

    def test_structured_recipe(self):
        recipe = RECIPE_REGISTRY["structured"]
        assert recipe.strategy == "hybrid"

    def test_multi_hop_recipe(self):
        recipe = RECIPE_REGISTRY["multi_hop"]
        assert recipe.strategy == "graph"

    def test_semantic_graph_recipe(self):
        recipe = RECIPE_REGISTRY["semantic_graph"]
        assert recipe.reranker == "fusion"
        assert "rerankers" in recipe.reranker_params
        assert "weights" in recipe.reranker_params

    def test_adaptive_recipe(self):
        recipe = RECIPE_REGISTRY["adaptive"]
        assert recipe.reranker == "cross-encoder"

    def test_conversation_recipe(self):
        recipe = RECIPE_REGISTRY["conversation"]
        assert recipe.reranker == "mmr"
        assert recipe.reranker_params.get("lambda") == 0.6

    def test_factoid_recipe(self):
        recipe = RECIPE_REGISTRY["factoid"]
        assert recipe.reranker == "cross-encoder"

    def test_summary_recipe(self):
        recipe = RECIPE_REGISTRY["summary"]
        assert recipe.reranker == "mmr"
        assert recipe.reranker_params.get("lambda") == 0.4
        assert recipe.top_k == 30

    def test_question_answering_recipe(self):
        recipe = RECIPE_REGISTRY["question_answering"]
        assert recipe.strategy == "semantic"
        assert recipe.reranker == "cross-encoder"

    def test_exploratory_recipe(self):
        recipe = RECIPE_REGISTRY["exploratory"]
        assert recipe.reranker == "mmr"
        assert recipe.reranker_params.get("lambda") == 0.3
        assert recipe.top_k == 30


class TestResolveRecipe:
    def test_resolve_by_name(self):
        recipe = resolve_recipe("hybrid")
        assert recipe is not None
        assert recipe.name == "hybrid"

    def test_resolve_nonexistent(self):
        assert resolve_recipe("nonexistent") is None

    def test_resolve_aliases(self):
        # Check some aliases
        qa = resolve_recipe("qa")
        assert qa is not None
        assert qa.name == "question_answering"
        explore = resolve_recipe("explore")
        assert explore is not None
        assert explore.name == "exploratory"
        graph = resolve_recipe("graph")
        assert graph is not None
        assert graph.name == "multi_hop"


class TestListRecipes:
    def test_list_recipes_returns_list_of_dicts(self):
        recipes = list_recipes()
        assert isinstance(recipes, list)
        assert len(recipes) == 18
        for r in recipes:
            assert "name" in r
            assert "description" in r
            assert "strategy" in r
            assert "reranker" in r
            assert "top_k" in r

    def test_list_recipes_contains_all_names(self):
        names = {r["name"] for r in list_recipes()}
        expected = set(RECIPE_REGISTRY.keys())
        assert names == expected


class TestGetRerankerForRecipe:
    def test_no_reranker_returns_none(self):
        recipe = SearchRecipe(name="test", description="", strategy="keyword", reranker="")
        assert get_reranker_for_recipe(recipe) is None

    def test_cross_encoder_reranker(self):
        recipe = SearchRecipe(name="test", description="", strategy="hybrid",
                              reranker="cross-encoder")
        r = get_reranker_for_recipe(recipe)
        assert isinstance(r, CrossEncoderReranker)

    def test_mmr_reranker(self):
        recipe = SearchRecipe(name="test", description="", strategy="hybrid",
                              reranker="mmr", reranker_params={"lambda": 0.5})
        r = get_reranker_for_recipe(recipe)
        assert isinstance(r, MMRReranker)
        assert r._lambda == 0.5

    def test_node_distance_reranker(self):
        recipe = SearchRecipe(name="test", description="", strategy="hybrid",
                              reranker="node-distance")
        r = get_reranker_for_recipe(recipe, client=MagicMock())
        assert isinstance(r, NodeDistanceReranker)

    def test_fusion_reranker(self):
        recipe = SearchRecipe(
            name="test", description="", strategy="hybrid",
            reranker="fusion",
            reranker_params={
                "rerankers": ["cross-encoder", "mmr"],
                "weights": [0.6, 0.4],
            },
        )
        r = get_reranker_for_recipe(recipe)
        assert isinstance(r, FusionReranker)
        assert len(r._rerankers) == 2

    def test_unknown_reranker_returns_none(self):
        recipe = SearchRecipe(name="test", description="", strategy="hybrid",
                              reranker="nonexistent")
        assert get_reranker_for_recipe(recipe) is None


# =====================================================================
# Recipe dataclass
# =====================================================================


class TestSearchRecipe:
    def test_defaults(self):
        r = SearchRecipe(name="test", description="desc")
        assert r.name == "test"
        assert r.strategy == "hybrid"
        assert r.reranker == ""
        assert r.top_k == 20

    def test_custom_values(self):
        r = SearchRecipe(
            name="custom",
            description="Custom recipe",
            strategy="keyword",
            reranker="mmr",
            reranker_params={"lambda": 0.7},
            filter_dsl='node_labels:["Person"]',
            top_k=15,
            kwargs={"some_opt": True},
        )
        assert r.name == "custom"
        assert r.strategy == "keyword"
        assert r.reranker == "mmr"
        assert r.reranker_params == {"lambda": 0.7}
        assert r.top_k == 15
        assert r.kwargs == {"some_opt": True}
