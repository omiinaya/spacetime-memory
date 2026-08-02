"""Pytest tests for spacetime_memory.shmr — pure functions and dataclass."""

from __future__ import annotations

import math

import numpy as np
import pytest

from spacetime_memory.shmr import (
    ResonanceResult,
    _cluster_by_similarity,
    _compute_harmony_score,
    _cosine_similarity,
    _extract_json_array,
    _format_cluster_for_llm,
)

# ── _cosine_similarity tests ─────────────────────────────────────────────


class TestCosineSimilarity:
    """Cosine similarity between two numpy vectors."""

    def test_identical_vectors(self):
        a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert _cosine_similarity(a, a) == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-5)

    def test_opposite_vectors(self):
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([-1.0, -2.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-5)

    def test_partial_similarity(self):
        a = np.array([1.0, 1.0], dtype=np.float32)
        b = np.array([1.0, 0.0], dtype=np.float32)
        result = _cosine_similarity(a, b)
        expected = 1.0 / math.sqrt(2.0)
        assert result == pytest.approx(expected, abs=1e-5)

    def test_zero_vector_safe(self):
        a = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        result = _cosine_similarity(a, b)
        assert result == pytest.approx(0.0, abs=1e-5)

    def test_both_zero_vectors(self):
        a = np.array([0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 0.0], dtype=np.float32)
        result = _cosine_similarity(a, b)
        assert result == pytest.approx(0.0, abs=1e-5)

    def test_high_dimensional(self):
        rng = np.random.default_rng(42)
        a = rng.random(128).astype(np.float32)
        b = rng.random(128).astype(np.float32)
        result = _cosine_similarity(a, b)
        assert -1.0 <= result <= 1.0

    def test_negative_values(self):
        a = np.array([-1.0, 2.0, -3.0], dtype=np.float32)
        b = np.array([1.0, -2.0, 3.0], dtype=np.float32)
        result = _cosine_similarity(a, b)
        assert -1.0 <= result <= 1.0

    def test_returns_float(self):
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([3.0, 4.0], dtype=np.float32)
        result = _cosine_similarity(a, b)
        assert isinstance(result, float)


# ── _cluster_by_similarity tests ────────────────────────────────────────


class TestClusterBySimilarity:
    """Connected-components clustering by cosine similarity."""

    def test_empty_items(self):
        assert _cluster_by_similarity([]) == []

    def test_single_item_below_min_size(self):
        items = [{"id": "1", "embedding": [1.0, 0.0, 0.0]}]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert result == []

    def test_two_similar_items(self):
        items = [
            {"id": "1", "embedding": [1.0, 0.0, 0.0]},
            {"id": "2", "embedding": [1.0, 0.01, 0.0]},
        ]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert len(result) == 1
        assert len(result[0]) == 2
        ids = {r["id"] for r in result[0]}
        assert ids == {"1", "2"}

    def test_two_dissimilar_items(self):
        items = [
            {"id": "1", "embedding": [1.0, 0.0, 0.0]},
            {"id": "2", "embedding": [0.0, 1.0, 0.0]},
        ]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert result == []

    def test_three_items_chain(self):
        items = [
            {"id": "A", "embedding": [1.0, 0.0, 0.0]},
            {"id": "B", "embedding": [0.9, 0.1, 0.0]},
            {"id": "C", "embedding": [0.8, 0.2, 0.0]},
        ]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_two_separate_clusters(self):
        items = [
            {"id": "A", "embedding": [1.0, 0.0, 0.0]},
            {"id": "B", "embedding": [0.95, 0.0, 0.0]},
            {"id": "C", "embedding": [0.0, 1.0, 0.0]},
            {"id": "D", "embedding": [0.0, 0.95, 0.0]},
        ]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert len(result) == 2
        assert all(len(c) == 2 for c in result)

    def test_threshold_sensitivity(self):
        items = [
            {"id": "A", "embedding": [1.0, 0.0]},
            {"id": "B", "embedding": [0.71, 0.71]},
        ]
        assert _cluster_by_similarity(items, threshold=0.8) == []
        result = _cluster_by_similarity(items, threshold=0.6)
        assert len(result) == 1

    def test_zero_length_embedding_ignored(self):
        items = [
            {"id": "A", "embedding": [1.0, 0.0]},
            {"id": "B", "embedding": []},
            {"id": "C", "embedding": [0.95, 0.0]},
        ]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert len(result) == 1
        ids = {r["id"] for r in result[0]}
        assert ids == {"A", "C"}

    def test_high_threshold_no_clusters(self):
        items = [
            {"id": "A", "embedding": [1.0, 0.0]},
            {"id": "B", "embedding": [0.999, 0.001]},
        ]
        result = _cluster_by_similarity(items, threshold=1.0)
        assert result == []

    def test_items_have_extra_keys(self):
        items = [
            {"id": "1", "embedding": [1.0, 0.0], "content": "hello", "score": 0.9},
            {"id": "2", "embedding": [0.98, 0.0], "content": "hi", "score": 0.8},
        ]
        result = _cluster_by_similarity(items, threshold=0.7)
        assert len(result) == 1
        for item in result[0]:
            assert "content" in item
            assert "score" in item


# ── _format_cluster_for_llm tests ───────────────────────────────────────


class TestFormatClusterForLLM:
    """Format memory clusters for LLM prompt."""

    def test_single_item(self):
        cluster = [
            {
                "content": "The user likes Python",
                "memory_type": "fact",
                "trust_score": 0.8,
                "created_at": 1234567890,
            }
        ]
        result = _format_cluster_for_llm(cluster)
        assert "=== MEMORY CLUSTER ===" in result
        assert "The user likes Python" in result
        assert "fact" in result
        assert "0.80" in result

    def test_multiple_items(self):
        cluster = [
            {"content": "Item A", "memory_type": "fact", "trust_score": 0.5},
            {"content": "Item B", "memory_type": "observation", "trust_score": 0.9},
        ]
        result = _format_cluster_for_llm(cluster)
        assert "[0]" in result
        assert "[1]" in result

    def test_missing_fields_default_values(self):
        cluster = [{"content": "Just content"}]
        result = _format_cluster_for_llm(cluster)
        assert "Just content" in result
        assert "0.50" in result
        assert "memory" in result

    def test_empty_cluster(self):
        result = _format_cluster_for_llm([])
        assert result == "=== MEMORY CLUSTER ==="

    def test_long_content_truncated(self):
        long_text = "x" * 300
        cluster = [{"content": long_text}]
        result = _format_cluster_for_llm(cluster)
        expected_prefix = "x" * 200
        assert expected_prefix in result
        assert "x" * 300 not in result

    def test_returns_string(self):
        cluster = [{"content": "hello"}]
        result = _format_cluster_for_llm(cluster)
        assert isinstance(result, str)

    def test_trust_score_formatting(self):
        cluster = [{"content": "x", "trust_score": 0.12345}]
        result = _format_cluster_for_llm(cluster)
        assert "0.12" in result


# ── _extract_json_array tests ───────────────────────────────────────────


class TestExtractJsonArray:
    """Robust JSON array extraction from LLM output."""

    def test_direct_json_array(self):
        text = '[{"subject": "x", "predicate": "y"}]'
        result = _extract_json_array(text)
        assert len(result) == 1
        assert result[0]["subject"] == "x"

    def test_json_with_beliefs_key(self):
        text = '{"beliefs": [{"subject": "a"}, {"subject": "b"}]}'
        result = _extract_json_array(text)
        assert len(result) == 2

    def test_markdown_json_block(self):
        text = 'Here are beliefs:\n```json\n[{"sub": "x"}]\n```\nDone.'
        result = _extract_json_array(text)
        assert len(result) == 1
        assert result[0]["sub"] == "x"

    def test_markdown_code_block_no_lang(self):
        text = '```\n[{"a": 1}]\n```'
        result = _extract_json_array(text)
        assert len(result) == 1
        assert result[0]["a"] == 1

    def test_bare_json_array_in_text(self):
        text = 'I found this: [{"key": "value"}] which is important.'
        result = _extract_json_array(text)
        assert len(result) == 1
        assert result[0]["key"] == "value"

    def test_individual_objects_fallback(self):
        text = 'Object1: {"a": 1}. Object2: {"b": 2}.'
        result = _extract_json_array(text)
        assert len(result) == 2

    def test_multiple_arrays_first_wins(self):
        text = '[{"first": true}] some text [{"second": false}]'
        result = _extract_json_array(text)
        assert len(result) == 1
        assert result[0]["first"] is True

    def test_complete_garbage(self):
        result = _extract_json_array("this is not json at all")
        assert result == []

    def test_empty_string(self):
        result = _extract_json_array("")
        assert result == []

    def test_multiple_objects_with_mixed_validity(self):
        text = '{"a": 1} {not valid} {"b": 2}'
        result = _extract_json_array(text)
        assert len(result) == 2

    def test_nested_json_in_objects(self):
        text = '[{"subject": "X", "meta": {"source": "test"}}]'
        result = _extract_json_array(text)
        assert len(result) == 1
        assert result[0]["meta"]["source"] == "test"

    def test_json_with_newlines(self):
        text = '[\n  {"key": "value"},\n  {"key2": "value2"}\n]'
        result = _extract_json_array(text)
        assert len(result) == 2

    def test_plain_dict_without_beliefs(self):
        """Plain dict without 'beliefs' key falls through to regex extraction."""
        text = '{"not_beliefs": []}'
        result = _extract_json_array(text)
        # Individual object fallback extracts {"not_beliefs": []}
        assert len(result) == 1
        assert result[0]["not_beliefs"] == []

    def test_number_as_json(self):
        """Non-dict/list JSON like a number falls through all parsers."""
        text = "42"
        result = _extract_json_array(text)
        assert result == []

    def test_markdown_json_block_with_invalid_json(self):
        """Markdown json block with invalid JSON inside falls through."""
        text = "```json\n[{invalid stuff here}]\n```"
        result = _extract_json_array(text)
        # Falls through to individual object fallback which may also fail
        assert result == []

    def test_bare_array_with_invalid_json(self):
        """Bare array regex matches but JSON is invalid inside."""
        text = "[{invalid json that won't parse}]"
        result = _extract_json_array(text)
        assert result == []


# ── _compute_harmony_score tests ────────────────────────────────────────


class TestComputeHarmonyScore:
    """Harmony score computation between beliefs and cluster."""

    def test_empty_beliefs(self):
        cluster = [{"embedding": [1.0, 0.0, 0.0]}]
        assert _compute_harmony_score([], cluster) == 0.0

    def test_empty_cluster(self):
        beliefs = [{"confidence": 0.8}]
        assert _compute_harmony_score(beliefs, []) == 0.0

    def test_both_empty(self):
        assert _compute_harmony_score([], []) == 0.0

    def test_single_belief_single_cluster_item(self):
        beliefs = [{"predicate": "likes", "object": "Python", "confidence": 0.9}]
        cluster = [{"embedding": [1.0, 0.0, 0.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert result == pytest.approx(0.63, abs=1e-5)

    def test_multiple_beliefs_same_subject(self):
        beliefs = [
            {"subject": "Alice", "predicate": "likes", "object": "Python", "confidence": 0.8},
            {"subject": "Alice", "predicate": "works at", "object": "Acme", "confidence": 0.7},
        ]
        cluster = [{"embedding": [1.0, 0.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert result == pytest.approx(0.525, abs=1e-5)

    def test_multiple_beliefs_different_subjects(self):
        beliefs = [
            {"subject": "Alice", "predicate": "likes", "object": "Python", "confidence": 0.8},
            {"subject": "Bob", "predicate": "likes", "object": "Rust", "confidence": 0.8},
        ]
        cluster = [{"embedding": [1.0, 0.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert result == pytest.approx(0.42, abs=1e-5)

    def test_default_confidence(self):
        beliefs = [{"predicate": "knows", "object": "Go"}]
        cluster = [{"embedding": [1.0, 0.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert result == pytest.approx(0.35, abs=1e-5)

    def test_cluster_items_missing_embeddings(self):
        beliefs = [{"confidence": 0.9}]
        cluster = [
            {"embedding": []},
            {"embedding": [1.0, 0.0]},
        ]
        result = _compute_harmony_score(beliefs, cluster)
        assert result == pytest.approx(0.63, abs=1e-5)

    def test_all_cluster_items_missing_embeddings(self):
        beliefs = [{"confidence": 0.9}]
        cluster = [{"no_embedding": True}, {"embedding": []}]
        assert _compute_harmony_score(beliefs, cluster) == 0.0

    def test_returns_float(self):
        beliefs = [{"confidence": 0.5}]
        cluster = [{"embedding": [1.0, 2.0, 3.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert isinstance(result, float)

    def test_high_confidence_beliefs(self):
        beliefs = [{"confidence": 1.0}]
        cluster = [{"embedding": [1.0, 0.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert result >= 0.69

    def test_low_confidence_beliefs(self):
        beliefs = [{"confidence": 0.1}]
        cluster = [{"embedding": [1.0, 0.0]}]
        result = _compute_harmony_score(beliefs, cluster)
        assert result <= 0.1

    def test_many_cluster_items(self):
        beliefs = [{"confidence": 0.8}]
        cluster = [
            {"embedding": [1.0, 0.0]},
            {"embedding": [0.0, 1.0]},
            {"embedding": [1.0, 1.0]},
        ]
        result = _compute_harmony_score(beliefs, cluster)
        assert 0.0 < result <= 0.56


# ── ResonanceResult dataclass tests ─────────────────────────────────────


class TestResonanceResult:
    """ResonanceResult dataclass behaviour."""

    def test_default_values(self):
        r = ResonanceResult(workspace_id="test-ws")
        assert r.workspace_id == "test-ws"
        assert r.clusters_found == 0
        assert r.beliefs_generated == 0
        assert r.contradictions_resolved == 0
        assert r.harmony_score_avg == 0.0
        assert r.duration_ms == 0
        assert r.errors == 0

    def test_field_assignment(self):
        r = ResonanceResult(workspace_id="ws-1")
        r.clusters_found = 5
        r.beliefs_generated = 12
        r.contradictions_resolved = 3
        r.harmony_score_avg = 0.75
        r.duration_ms = 1500
        r.errors = 1
        assert r.clusters_found == 5
        assert r.beliefs_generated == 12
        assert r.duration_ms == 1500

    def test_is_dataclass(self):
        from dataclasses import is_dataclass

        assert is_dataclass(ResonanceResult)
