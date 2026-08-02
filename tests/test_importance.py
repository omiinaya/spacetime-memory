"""Tests for memory importance scoring."""

from __future__ import annotations

import json
import math

import pytest

from spacetime_memory.importance import (
    importance_from_signals,
    llm_estimate_importance,
    importance_search_boost,
    IMPORTANCE_PROMPT,
)


class TestImportanceFromSignals:
    """Pure signal-based importance — no LLM needed."""

    def test_critical_high_strength(self):
        result = importance_from_signals(
            strength=0.98,
            access_count=200,
            trust_score=0.95,
            tier="L0",
            confidence=0.98,
        )
        assert result["label"] == "critical"
        assert result["score"] >= 0.85

    def test_trivial_low_signal(self):
        result = importance_from_signals(
            strength=0.05,
            access_count=0,
            trust_score=0.1,
            tier="L2",
            confidence=0.1,
        )
        assert result["label"] == "trivial"
        assert result["score"] < 0.4

    def test_normal_mid_range(self):
        result = importance_from_signals(
            strength=0.5,
            access_count=5,
            trust_score=0.5,
            tier="L1",
            confidence=0.5,
        )
        assert result["label"] in ("normal", "important")
        assert 0.3 <= result["score"] <= 0.8

    def test_old_memory_gets_lower_score(self):
        fresh = importance_from_signals(
            strength=0.5, access_count=1, trust_score=0.5,
            tier="L1", confidence=0.5, n_days_since_created=1,
        )
        old = importance_from_signals(
            strength=0.5, access_count=1, trust_score=0.5,
            tier="L1", confidence=0.5, n_days_since_created=1000,
        )
        assert fresh["score"] >= old["score"]

    def test_high_access_increases_score(self):
        low_access = importance_from_signals(
            strength=0.5, access_count=0, trust_score=0.5,
            tier="L1", confidence=0.5,
        )
        high_access = importance_from_signals(
            strength=0.5, access_count=100, trust_score=0.5,
            tier="L1", confidence=0.5,
        )
        assert high_access["score"] >= low_access["score"]

    def test_l0_tier_boosts_score(self):
        l0 = importance_from_signals(
            strength=0.5, access_count=0, trust_score=0.5,
            tier="L0", confidence=0.5,
        )
        l2 = importance_from_signals(
            strength=0.5, access_count=0, trust_score=0.5,
            tier="L2", confidence=0.5,
        )
        assert l0["score"] >= l2["score"]

    def test_always_bounded(self):
        for strength in [0.0, 0.5, 1.0]:
            result = importance_from_signals(strength, 0, 0.5, "L1", 0.5)
            assert 0.0 <= result["score"] <= 1.0


class TestImportanceLLM:
    """LLM-based importance estimation."""

    def test_llm_fallback_no_llm(self):
        """Without LLM function, falls back to signal-based."""
        result = llm_estimate_importance(
            content="Hello world",
            summary="test",
            memory_type="world_fact",
            access_count=0,
            strength=0.5,
            tier="L1",
            llm_func=None,
        )
        assert "score" in result
        assert "reasoning" in result
        assert 0.0 <= result["score"] <= 1.0

    def test_llm_parse_success(self):
        def mock_llm(prompt: str) -> str:
            return json.dumps({"score": 0.85, "label": "important", "reasoning": "test"})
        result = llm_estimate_importance(
            content="user prefers dark mode",
            summary="preference",
            memory_type="world_fact",
            access_count=3,
            strength=0.7,
            tier="L0",
            llm_func=mock_llm,
        )
        assert result["score"] >= 0.8
        assert result["label"] == "important"

    def test_llm_parse_failure_fallback(self):
        """Invalid LLM response falls back to signal-based."""
        def bad_llm(prompt: str) -> str:
            return "this is not json"
        result = llm_estimate_importance(
            content="test", summary="", memory_type="world_fact",
            access_count=0, strength=0.5, tier="L1",
            llm_func=bad_llm,
        )
        # Falls back to signal-based, which should still give valid values
        assert "score" in result
        assert "reasoning" in result
        assert isinstance(result["score"], float)

    def test_llm_label_validation(self):
        def mock_llm(prompt: str) -> str:
            return json.dumps({"score": 0.5, "label": "invalid_label", "reasoning": "test"})
        result = llm_estimate_importance(
            content="test", summary="", memory_type="world_fact",
            access_count=0, strength=0.5, tier="L1",
            llm_func=mock_llm,
        )
        # Invalid labels default to "normal"
        assert result["label"] == "normal"


class TestImportanceSearchBoost:
    """Importance-boosted search result re-ranking."""

    def test_boosted_results_sorted(self):
        results = [
            {"id": "1", "_score": 0.9, "extra_json": json.dumps({"score": 0.2})},
            {"id": "2", "_score": 0.5, "extra_json": json.dumps({"score": 0.9})},
        ]
        boosted = importance_search_boost(results, importance_weight=0.5)
        # Item 2 should rank higher because its importance outweighs the
        # original score gap
        assert boosted[0]["id"] == "2"

    def test_no_boost_change_when_importance_equal(self):
        results = [
            {"id": "1", "_score": 0.9, "extra_json": json.dumps({"score": 0.5})},
            {"id": "2", "_score": 0.5, "extra_json": json.dumps({"score": 0.9})},
            {"id": "3", "_score": 0.7, "extra_json": json.dumps({"score": 0.3})},
        ]
        boosted = importance_search_boost(results, importance_weight=0.0)
        # With weight=0, original score order is preserved (1, 3, 2)
        assert boosted[0]["id"] == "1"
        assert boosted[1]["id"] == "3"
        assert boosted[2]["id"] == "2"

    def test_missing_extra_json_defaults(self):
        results = [
            {"id": "1", "_score": 0.8},
            {"id": "2", "_score": 0.6, "extra_json": "invalid json"},
        ]
        boosted = importance_search_boost(results)
        # Both default to score=0.5, so original score dominates
        assert boosted[0]["id"] == "1"

    def test_empty_results(self):
        assert importance_search_boost([]) == []
