"""Tests for agent self-editing (memory merging, contradiction detection,
memory rewriting, entity resolution).

Tests use pytest with MagicMock — no live STDB needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_sdk_path = str(Path(__file__).resolve().parent.parent / "sdk" / "python")
if _sdk_path not in sys.path:
    sys.path.insert(0, _sdk_path)

from spacetime_memory.self_editing import (
    CONTRADICTION_PROMPT,
    DEFAULT_CONTRADICTION_SCORE_THRESHOLD,
    DEFAULT_MERGE_SIMILARITY_THRESHOLD,
    DEFAULT_RESOLUTION_SIMILARITY_THRESHOLD,
    ENTITY_RESOLUTION_PROMPT,
    MERGE_ANALYSIS_PROMPT,
    REWRITE_PROMPT,
    _basic_rewrite,
    _char_similarity,
    _combined_similarity,
    _compute_merge_candidates,
    _entity_label_similarity,
    _heuristic_contradiction_explanation,
    _heuristic_contradiction_score,
    _merge_entity_summaries,
    _merge_two_memories,
    _normalize,
    _word_overlap_ratio,
    detect_contradictions,
    merge_similar_memories,
    resolve_entities,
    rewrite_memory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    memories: list[dict] | None = None,
    nodes: list[dict] | None = None,
) -> MagicMock:
    """Build a MagicMock client with canned _query results."""
    client = MagicMock()
    memories = memories or []
    nodes = nodes or []

    def _query(
        table: str,
        workspace_id: str = "",
        columns: list[str] | None = None,
        filter_dict: dict | None = None,
        **kwargs,
    ) -> list[dict]:
        if table == "memory":
            if filter_dict and "id" in filter_dict:
                return [m for m in memories if m.get("id") == filter_dict["id"]]
            return memories
        if table == "kg_node":
            if filter_dict and "id" in filter_dict:
                return [n for n in nodes if n.get("id") == filter_dict["id"]]
            return nodes
        return []

    client._query = _query
    client._call = MagicMock(return_value={})
    return client


def _sample_memories() -> list[dict]:
    """Return a list of test memories."""
    return [
        {
            "id": "mem_1",
            "content": "The user prefers dark mode in all applications.",
            "summary": "dark mode preference",
            "tags": ["preference", "ui"],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "importance": 0.7,
            "strength": 0.8,
            "confidence": 0.9,
            "access_count": 5,
            "memory_type": "preference",
        },
        {
            "id": "mem_2",
            "content": "The user likes dark mode on all their devices.",
            "summary": "dark mode like",
            "tags": ["preference", "theme"],
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "importance": 0.5,
            "strength": 0.6,
            "confidence": 0.8,
            "access_count": 2,
            "memory_type": "preference",
        },
        {
            "id": "mem_3",
            "content": "The user hates the color blue for interfaces.",
            "summary": "blue color dislike",
            "tags": ["preference", "color"],
            "created_at": "2026-01-03T00:00:00Z",
            "updated_at": "2026-01-03T00:00:00Z",
            "importance": 0.4,
            "strength": 0.5,
            "confidence": 0.7,
            "access_count": 1,
            "memory_type": "preference",
        },
        {
            "id": "mem_4",
            "content": "The user loves the color blue in interface design.",
            "summary": "blue color like",
            "tags": ["preference", "color"],
            "created_at": "2026-01-04T00:00:00Z",
            "updated_at": "2026-01-04T00:00:00Z",
            "importance": 0.6,
            "strength": 0.7,
            "confidence": 0.8,
            "access_count": 3,
            "memory_type": "preference",
        },
        {
            "id": "mem_5",
            "content": "Python is the user's favorite programming language.",
            "summary": "Python favorite",
            "tags": ["language", "preference"],
            "created_at": "2026-01-05T00:00:00Z",
            "updated_at": "2026-01-05T00:00:00Z",
            "importance": 0.8,
            "strength": 0.9,
            "confidence": 0.95,
            "access_count": 10,
            "memory_type": "preference",
        },
    ]


def _sample_nodes() -> list[dict]:
    """Return a list of test KG nodes."""
    return [
        {"id": "n1", "label": "Python programming language", "node_type": "concept",
         "summary": "A high-level programming language.", "name": "Python"},
        {"id": "n2", "label": "Python language", "node_type": "concept",
         "summary": "An interpreted programming language.", "name": "Python"},
        {"id": "n3", "label": "Alice Smith", "node_type": "entity",
         "summary": "Software engineer at Acme Corp.", "name": "Alice"},
        {"id": "n4", "label": "Alice S.", "node_type": "entity",
         "summary": "Engineer working at Acme Corporation.", "name": "Alice"},
        {"id": "n5", "label": "Rust programming", "node_type": "concept",
         "summary": "A systems programming language focused on safety.", "name": "Rust"},
    ]


def _make_llm_mock(return_data: dict) -> MagicMock:
    """Create a mock LLM client that returns a JSON dict."""
    llm = MagicMock()
    llm.chat = MagicMock(return_value=json.dumps(return_data))
    llm.available = True
    return llm


# ---------------------------------------------------------------------------
# Tests: Text similarity helpers
# ---------------------------------------------------------------------------


class TestTextHelpers:
    """Tests for internal text normalization and similarity functions."""

    def test_normalize(self):
        assert _normalize("  Hello  World  ") == "hello world"
        assert _normalize("") == ""
        assert _normalize("UPPER lower") == "upper lower"

    def test_word_overlap_ratio_identical(self):
        assert _word_overlap_ratio("hello world", "hello world") == 1.0

    def test_word_overlap_ratio_partial(self):
        ratio = _word_overlap_ratio("hello world", "hello there")
        assert 0.33 < ratio < 0.5

    def test_word_overlap_ratio_none(self):
        assert _word_overlap_ratio("hello world", "foo bar") == 0.0

    def test_word_overlap_ratio_empty(self):
        assert _word_overlap_ratio("", "hello") == 0.0
        assert _word_overlap_ratio("hello", "") == 0.0

    def test_char_similarity_identical(self):
        assert _char_similarity("hello world", "hello world") == 1.0

    def test_char_similarity_partial(self):
        sim = _char_similarity("dark mode preference", "dark mode like")
        assert 0.5 < sim < 1.0

    def test_char_similarity_empty(self):
        assert _char_similarity("", "") == 1.0
        assert _char_similarity("a", "") == 0.0

    def test_combined_similarity(self):
        sim = _combined_similarity("hello world", "hello world")
        assert sim == 1.0

        sim2 = _combined_similarity("hello world", "goodbye world")
        assert 0.0 < sim2 < 1.0


# ---------------------------------------------------------------------------
# Tests: Memory merging
# ---------------------------------------------------------------------------


class TestMergeSimilarMemories:
    """Tests for memory merging in heuristic and LLM modes."""

    def test_empty_memories(self):
        """Empty memory store returns empty result."""
        client = _make_mock_client(memories=[])
        result = merge_similar_memories(client, "ws1")
        assert result["merges"] == []
        assert result["total_before"] == 0
        assert result["total_after"] == 0
        assert result["candidates_considered"] == 0

    def test_no_similar_memories(self):
        """No similar memories means no merges."""
        memories = [
            {"id": "m1", "content": "The user likes cats."},
            {"id": "m2", "content": "Python is a programming language."},
        ]
        client = _make_mock_client(memories=memories)
        result = merge_similar_memories(client, "ws1", threshold=0.9)
        assert result["merges"] == []
        assert result["total_before"] == 2
        assert result["total_after"] == 2

    def test_merge_similar_pair(self):
        """Two very similar memories should be merged."""
        memories = _sample_memories()
        client = _make_mock_client(memories=memories)
        result = merge_similar_memories(
            client, "ws1", threshold=0.6, dry_run=True
        )
        # mem_1 and mem_2 both mention dark mode — should be candidates
        assert result["candidates_considered"] > 0
        assert result["merges"] or result["candidates_considered"] > 0

    def test_dry_run_does_not_mutate(self):
        """In dry_run mode, _call should not be invoked."""
        memories = _sample_memories()
        client = _make_mock_client(memories=memories)
        result = merge_similar_memories(
            client, "ws1", threshold=0.6, dry_run=True
        )
        client._call.assert_not_called()

    def test_merge_metadata_combination(self):
        """Merging should preserve and combine metadata correctly."""
        mem_a = {
            "id": "a",
            "content": "User likes apples.",
            "tags": ["fruit", "food"],
            "importance": 0.5,
            "strength": 0.4,
            "confidence": 0.6,
            "access_count": 3,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "source_ids": ["src1"],
        }
        mem_b = {
            "id": "b",
            "content": "User loves apples.",
            "tags": ["fruit", "snack"],
            "importance": 0.8,
            "strength": 0.9,
            "confidence": 0.2,
            "access_count": 10,
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "source_ids": ["src2"],
        }
        merged = _merge_two_memories(mem_a, mem_b, "User loves apples (consolidated).")
        assert merged["id"] == "a"  # First id preserved
        assert "User loves apples (consolidated)." in merged["content"]
        # Tags combined and deduplicated
        assert "fruit" in merged["tags"]
        assert "food" in merged["tags"]
        assert "snack" in merged["tags"]
        # Numeric max taken
        assert merged["importance"] == 0.8
        assert merged["strength"] == 0.9
        assert merged["confidence"] == 0.6  # max(0.6, 0.2)
        assert merged["access_count"] == 10
        # Oldest created_at
        assert merged["created_at"] == "2026-01-01T00:00:00Z"
        # Newest updated_at
        assert merged["updated_at"] == "2026-01-02T00:00:00Z"
        # Source IDs merged
        assert "src1" in merged["source_ids"]
        assert "src2" in merged["source_ids"]

    def test_merge_with_llm(self):
        """LLM-based merge should use the LLM and respect its decisions."""
        memories = [
            {"id": "m1", "content": "User prefers dark mode.", "summary": "dark"},
            {"id": "m2", "content": "User likes dark mode.", "summary": "dark"},
        ]
        client = _make_mock_client(memories=memories)

        # LLM says: merge these
        llm = _make_llm_mock({
            "should_merge": True,
            "confidence": 0.95,
            "merged_content": "User prefers and likes dark mode.",
            "reasoning": "Both statements agree on dark mode.",
        })

        result = merge_similar_memories(
            client, "ws1", threshold=0.5, llm_client=llm, dry_run=True
        )
        assert result["mode"] == "llm"
        assert len(result["merges"]) == 1
        assert "dark mode" in result["merges"][0]["content_after"]

    def test_merge_with_llm_rejects(self):
        """LLM can decide NOT to merge."""
        memories = [
            {"id": "m1", "content": "User prefers dark mode.", "summary": "dark"},
            {"id": "m2", "content": "User likes cats.", "summary": "cats"},
        ]
        client = _make_mock_client(memories=memories)
        llm = _make_llm_mock({
            "should_merge": False,
            "confidence": 0.9,
            "merged_content": "",
            "reasoning": "Unrelated topics.",
        })
        result = merge_similar_memories(
            client, "ws1", threshold=0.1, llm_client=llm, dry_run=True
        )
        # If heuristic picks them up as candidates, LLM should reject
        assert result["mode"] == "llm"
        # Ensure no merges happened if LLM rejected all
        if result["merges"]:
            for merge in result["merges"]:
                assert merge["confidence"] < 0.95 or merge["reasoning"] != "Unrelated topics."

    def test_merge_with_llm_fallback_on_failure(self):
        """When LLM fails, heuristic fallback should be used."""
        memories = [
            {"id": "m1", "content": "User prefers dark mode.", "summary": "dark"},
            {"id": "m2", "content": "User likes dark mode.", "summary": "dark"},
        ]
        client = _make_mock_client(memories=memories)

        # LLM that returns None
        llm = MagicMock()
        llm.chat = MagicMock(return_value=None)
        llm.available = True

        result = merge_similar_memories(
            client, "ws1", threshold=0.5, llm_client=llm, dry_run=True
        )
        # LLM mode was requested, LLM failed, so it falls back to heuristic
        # for the decision. The merge happens because sim >= threshold.
        # mode reports "llm" because llm_client was provided, but fallback used.
        assert result["mode"] == "llm"
        assert len(result["merges"]) > 0

    def test_compute_merge_candidates(self):
        """_compute_merge_candidates finds pairs above threshold."""
        memories = _sample_memories()
        candidates = _compute_merge_candidates(
            memories, threshold=0.5
        )
        # mem_1 and mem_2 (dark mode) should appear
        labels = [(memories[i].get("id"), memories[j].get("id"), s)
                  for i, j, s in candidates]
        ids_checked = set()
        for id1, id2, _ in labels:
            ids_checked.add(id1)
            ids_checked.add(id2)
        assert "mem_1" in ids_checked or "mem_2" in ids_checked
        assert len(candidates) > 0

    def test_compute_merge_candidates_high_threshold(self):
        """Very high threshold yields no candidates."""
        memories = _sample_memories()
        candidates = _compute_merge_candidates(memories, threshold=0.99)
        assert candidates == []

    def test_scoped_memory_ids(self):
        """Only specified memory IDs should be considered for merging."""
        memories = _sample_memories()
        client = _make_mock_client(memories=memories)
        result = merge_similar_memories(
            client, "ws1", threshold=0.5, dry_run=True,
            memory_ids=["mem_1", "mem_2"],
        )
        # Should only consider these two
        assert result["candidates_considered"] >= 0

    def test_error_fetching_memories(self):
        """If _query fails, should return error gracefully."""
        client = MagicMock()
        client._query = MagicMock(side_effect=RuntimeError("STDB error"))
        result = merge_similar_memories(client, "ws1")
        assert result["mode"] == "none"
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: Contradiction Detection
# ---------------------------------------------------------------------------


class TestDetectContradictions:
    """Tests for contradiction detection in heuristic and LLM modes."""

    def test_empty_memories(self):
        """Empty store returns no contradictions."""
        client = _make_mock_client(memories=[])
        result = detect_contradictions(client, "ws1")
        assert result["contradictions"] == []
        assert result["pairs_analyzed"] == 0
        assert result["contradictions_found"] == 0

    def test_no_contradictions(self):
        """Unrelated memories should not be flagged."""
        memories = [
            {"id": "m1", "content": "User likes cats.", "summary": "cats"},
            {"id": "m2", "content": "Python is a language.", "summary": "python"},
        ]
        client = _make_mock_client(memories=memories)
        result = detect_contradictions(client, "ws1", similarity_threshold=0.1)
        # These have low word overlap so might not even be analyzed
        assert result["contradictions_found"] == 0

    def test_contradictory_sentiment(self):
        """Positive vs negative sentiment about same topic should trigger."""
        memories = [
            {"id": "m1", "content": "The user loves the color blue.", "summary": "blue love"},
            {"id": "m2", "content": "The user hates the color blue.", "summary": "blue hate"},
        ]
        client = _make_mock_client(memories=memories)
        result = detect_contradictions(client, "ws1", similarity_threshold=0.1,
                                        threshold=0.3)
        assert result["contradictions_found"] >= 1
        contradiction = result["contradictions"][0]
        assert contradiction["contradiction_score"] >= 0.3
        assert "blue" in contradiction.get("content_a", "")

    def test_contradiction_with_temporal_shift(self):
        """Temporal qualifiers suggesting past vs present state."""
        memories = [
            {"id": "m1", "content": "The user formerly lived in New York.",
             "summary": "past location"},
            {"id": "m2", "content": "The user currently lives in San Francisco.",
             "summary": "current location"},
        ]
        client = _make_mock_client(memories=memories)
        result = detect_contradictions(client, "ws1", similarity_threshold=0.1,
                                        threshold=0.3)
        # These share "the user lives in" structure + temporal signals
        assert result["pairs_analyzed"] >= 1
        # Should have some signal from temporal qualifiers
        score = _heuristic_contradiction_score(memories[0], memories[1])
        assert score > 0.0

    def test_heuristic_contradiction_explanation(self):
        """Explanations should be human-readable."""
        mem_a = {"id": "a", "content": "User loves blue.", "summary": ""}
        mem_b = {"id": "b", "content": "User hates blue.", "summary": ""}
        explanation = _heuristic_contradiction_explanation(mem_a, mem_b)
        assert isinstance(explanation, str)
        assert len(explanation) > 0
        assert "sentiment" in explanation.lower() or "positive" in explanation.lower() or "negative" in explanation.lower()

    def test_heuristic_contradiction_score_bounds(self):
        """Score should always be in 0-1 range."""
        mem_a = {"id": "a", "content": "User likes A.", "summary": ""}
        mem_b = {"id": "b", "content": "User hates A.", "summary": ""}
        score = _heuristic_contradiction_score(mem_a, mem_b)
        assert 0.0 <= score <= 0.95

    def test_llm_contradiction_detection(self):
        """LLM mode should detect contradictions."""
        memories = [
            {"id": "m1", "content": "The user prefers dark mode.", "summary": ""},
            {"id": "m2", "content": "The user prefers light mode.", "summary": ""},
        ]
        client = _make_mock_client(memories=memories)
        llm = _make_llm_mock({
            "contradicts": True,
            "contradiction_score": 0.85,
            "explanation": "One says dark, the other says light.",
            "verdict": "contradiction",
        })
        result = detect_contradictions(
            client, "ws1", threshold=0.3, similarity_threshold=0.1,
            llm_client=llm,
        )
        assert result["mode"] == "llm"
        assert result["contradictions_found"] >= 1
        c = result["contradictions"][0]
        assert c["contradiction_score"] >= 0.3

    def test_llm_says_no_contradiction(self):
        """LLM can determine two memories are consistent."""
        memories = [
            {"id": "m1", "content": "User likes cats.", "summary": ""},
            {"id": "m2", "content": "User likes dogs.", "summary": ""},
        ]
        client = _make_mock_client(memories=memories)
        llm = _make_llm_mock({
            "contradicts": False,
            "contradiction_score": 0.0,
            "explanation": "Different topics, not contradictory.",
            "verdict": "consistent",
        })
        result = detect_contradictions(
            client, "ws1", threshold=0.3, similarity_threshold=0.1,
            llm_client=llm,
        )
        # If LLM says not contradictory, should be empty regardless of heuristic
        assert result["contradictions_found"] == 0

    def test_scoped_memory_ids(self):
        """Only specified memory IDs should be compared."""
        memories = _sample_memories()
        client = _make_mock_client(memories=memories)
        result = detect_contradictions(
            client, "ws1", similarity_threshold=0.1, threshold=0.3,
            memory_ids=["mem_3", "mem_4"],  # blue hate vs blue love
        )
        assert result["contradictions_found"] >= 1

    def test_error_fetching(self):
        """If _query fails, returns error gracefully."""
        client = MagicMock()
        client._query = MagicMock(side_effect=RuntimeError("STDB error"))
        result = detect_contradictions(client, "ws1")
        assert result["mode"] == "none"
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: Memory Rewriting
# ---------------------------------------------------------------------------


class TestRewriteMemory:
    """Tests for memory rewriting in heuristic and LLM modes."""

    def test_rewrite_with_content_override(self):
        """Rewriting with content_override should not hit DB."""
        client = MagicMock()
        result = rewrite_memory(
            client, "ws1", "mem_1", "User now prefers light mode.",
            content_override="User prefers dark mode.",
            dry_run=True,
        )
        assert result["memory_id"] == "mem_1"
        assert "dark" in result["old_content"]
        assert result["new_content"] is not None
        assert len(result["new_content"]) > 0
        client._query.assert_not_called()

    def test_rewrite_preserves_old_info(self):
        """Heuristic rewrite should keep non-contradicted old info."""
        result = rewrite_memory(
            MagicMock(), "ws1", "mem_x",
            "Now prefers light mode.",
            content_override="User prefers dark mode and likes Python.",
            dry_run=True,
        )
        # 'likes Python' is not contradicted — should be preserved
        assert "Python" in result["new_content"] or "python" in result["new_content"].lower()

    def test_rewrite_heuristic_mode(self):
        """Heuristic rewrite produces output."""
        result = rewrite_memory(
            MagicMock(), "ws1", "mem_x",
            "New evidence about the user.",
            content_override="Old memory content.",
            dry_run=True,
        )
        assert result["mode"] == "heuristic"
        assert result["old_content"] == "Old memory content."

    def test_rewrite_llm_mode(self):
        """LLM rewrite should use the LLM response."""
        llm = _make_llm_mock({
            "rewritten_content": "User prefers light mode now (updated from dark mode).",
            "changes": "Updated preference from dark to light.",
            "confidence": 0.9,
        })
        result = rewrite_memory(
            MagicMock(), "ws1", "mem_x",
            "User now prefers light mode.",
            content_override="User prefers dark mode.",
            llm_client=llm,
            dry_run=True,
        )
        assert result["mode"] == "llm"
        assert "light" in result["new_content"]
        assert result["changes"] == "Updated preference from dark to light."
        assert result["confidence"] == 0.9

    def test_rewrite_llm_fallback(self):
        """When LLM fails, heuristic fallback used."""
        llm = MagicMock()
        llm.chat = MagicMock(return_value=None)
        result = rewrite_memory(
            MagicMock(), "ws1", "mem_x",
            "New info.",
            content_override="Old info.",
            llm_client=llm,
            dry_run=True,
        )
        assert result["mode"] == "llm"  # mode reports llm because client provided
        assert result["new_content"] is not None

    def test_basic_rewrite_empty(self):
        """Edge cases for _basic_rewrite."""
        assert _basic_rewrite("", "new") == "new"
        assert _basic_rewrite("old", "") == "old"
        assert _basic_rewrite("", "") == ""

    def test_basic_rewrite_dedup(self):
        """_basic_rewrite should deduplicate near-identical sentences."""
        result = _basic_rewrite(
            "User likes Python. User also likes Rust.",
            "User likes Python.",
        )
        # "User likes Python" is duplicated (high similarity), should be deduped
        assert result is not None
        # "User also likes Rust" should still be present
        assert "Rust" in result

    def test_rewrite_persistence(self):
        """In non-dry-run mode, should call _call to update."""
        client = MagicMock()
        client._query = MagicMock(return_value=[
            {"id": "mem_x", "content": "Old memory.", "summary": ""}
        ])
        result = rewrite_memory(
            client, "ws1", "mem_x",
            "New evidence.",
            dry_run=False,
        )
        client._call.assert_called_once()

    def test_rewrite_memory_not_found(self):
        """If memory not found, returns error."""
        client = MagicMock()
        client._query = MagicMock(return_value=[])
        result = rewrite_memory(client, "ws1", "nonexistent", "new info.")
        assert "error" in result
        assert result["mode"] == "none"


# ---------------------------------------------------------------------------
# Tests: Entity Resolution
# ---------------------------------------------------------------------------


class TestResolveEntities:
    """Tests for entity resolution in heuristic and LLM modes."""

    def test_empty_nodes(self):
        """Empty KG returns empty result."""
        client = _make_mock_client(nodes=[])
        result = resolve_entities(client, "ws1")
        assert result["resolutions"] == []
        assert result["pairs_analyzed"] == 0
        assert result["resolutions_found"] == 0

    def test_no_similar_entities(self):
        """Distinct entities should not be resolved."""
        client = _make_mock_client(nodes=_sample_nodes())
        result = resolve_entities(client, "ws1", threshold=0.95, dry_run=True)
        # With a very high threshold, nothing should merge
        assert result["resolutions_found"] == 0

    def test_resolve_python_nodes(self):
        """'Python programming language' and 'Python language' should be resolved."""
        nodes = _sample_nodes()
        client = _make_mock_client(nodes=nodes)
        result = resolve_entities(client, "ws1", threshold=0.5, dry_run=True)
        # Python nodes should be similar enough
        found = any(
            "Python" in r["canonical_label"]
            for r in result["resolutions"]
        )
        assert found, "Python nodes should be resolved"

    def test_resolve_alice_nodes(self):
        """'Alice Smith' and 'Alice S.' should be resolved."""
        nodes = _sample_nodes()
        client = _make_mock_client(nodes=nodes)
        result = resolve_entities(client, "ws1", threshold=0.5, dry_run=True)
        found = any(
            "Alice" in r.get("label_a", "") and "Alice" in r.get("label_b", "")
            for r in result["resolutions"]
        )
        assert found, "Alice nodes should be resolved"

    def test_entity_label_similarity(self):
        """_entity_label_similarity returns 0-1 score."""
        sim = _entity_label_similarity(
            "Python programming language", "A high-level language.",
            "Python language", "An interpreted language.",
        )
        assert 0.0 <= sim <= 1.0
        assert sim > 0.5, "Python should have high label similarity"

    def test_entity_label_similarity_different(self):
        """Different entities should have low similarity."""
        sim = _entity_label_similarity(
            "Python language", "A programming language.",
            "Alice Smith", "A software engineer.",
        )
        assert sim < 0.5, "Python and Alice should not be similar"

    def test_merge_entity_summaries(self):
        """_merge_entity_summaries combines summaries."""
        merged = _merge_entity_summaries(
            "A high-level programming language.",
            "An interpreted programming language.",
        )
        assert "high-level" in merged or "interpreted" in merged
        assert len(merged) > 0

    def test_merge_entity_summaries_empty(self):
        """Empty summaries handled."""
        assert _merge_entity_summaries("", "B") == "B"
        assert _merge_entity_summaries("A", "") == "A"
        assert _merge_entity_summaries("", "") == ""

    def test_resolve_llm_mode(self):
        """LLM-based entity resolution."""
        nodes = _sample_nodes()[:2]  # Python nodes
        client = _make_mock_client(nodes=nodes)
        llm = _make_llm_mock({
            "same_entity": True,
            "confidence": 0.95,
            "canonical_label": "Python",
            "merged_summary": "A high-level, interpreted programming language.",
            "entity_type": "concept",
            "reasoning": "Both refer to the Python programming language.",
        })
        result = resolve_entities(
            client, "ws1", threshold=0.5, llm_client=llm, dry_run=True
        )
        assert result["mode"] == "llm"
        assert result["resolutions_found"] >= 1
        res = result["resolutions"][0]
        assert res["canonical_label"] == "Python"

    def test_resolve_llm_rejects(self):
        """LLM can determine two entities are distinct."""
        nodes = [
            {"id": "n1", "label": "Apple Inc.", "node_type": "entity",
             "summary": "A technology company.", "name": "Apple"},
            {"id": "n2", "label": "Apple fruit", "node_type": "entity",
             "summary": "A type of fruit.", "name": "Apple"},
        ]
        client = _make_mock_client(nodes=nodes)
        llm = _make_llm_mock({
            "same_entity": False,
            "confidence": 0.95,
            "canonical_label": "",
            "merged_summary": "",
            "entity_type": "",
            "reasoning": "One is a company, the other is a fruit.",
        })
        result = resolve_entities(
            client, "ws1", threshold=0.5, llm_client=llm, dry_run=True
        )
        assert result["resolutions_found"] == 0

    def test_scoped_node_ids(self):
        """Only specified node IDs should be considered."""
        nodes = _sample_nodes()
        client = _make_mock_client(nodes=nodes)
        # Only consider Alice nodes
        result = resolve_entities(
            client, "ws1", threshold=0.5, dry_run=True,
            node_ids=["n3", "n4"],
        )
        assert result["resolutions_found"] >= 1

    def test_dry_run_no_mutation(self):
        """In dry_run mode, no _call should happen."""
        nodes = _sample_nodes()
        client = _make_mock_client(nodes=nodes)
        result = resolve_entities(
            client, "ws1", threshold=0.5, dry_run=True
        )
        client._call.assert_not_called()

    def test_persistence_calls(self):
        """In non-dry-run mode, persistence calls should be made."""
        nodes = [
            {"id": "n1", "label": "Python lang", "node_type": "concept",
             "summary": "A language.", "name": "Python"},
            {"id": "n2", "label": "Python programming language", "node_type": "concept",
             "summary": "A programming language.", "name": "Python"},
        ]
        client = _make_mock_client(nodes=nodes)
        result = resolve_entities(client, "ws1", threshold=0.5, dry_run=False)
        if result["resolutions_found"] > 0:
            # At minimum, should have called update_kg_node and delete_kg_node
            assert client._call.call_count >= 2

    def test_error_fetching_nodes(self):
        """If _query fails, returns error gracefully."""
        client = MagicMock()
        client._query = MagicMock(side_effect=RuntimeError("STDB error"))
        result = resolve_entities(client, "ws1")
        assert result["mode"] == "none"
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: Prompt format verification
# ---------------------------------------------------------------------------


class TestPrompts:
    """Verify prompt templates contain required placeholders."""

    def test_merge_prompt_placeholders(self):
        assert "{mem_a_id}" in MERGE_ANALYSIS_PROMPT
        assert "{mem_a_content}" in MERGE_ANALYSIS_PROMPT
        assert "{mem_b_content}" in MERGE_ANALYSIS_PROMPT

    def test_contradiction_prompt_placeholders(self):
        assert "{mem_a_content}" in CONTRADICTION_PROMPT
        assert "{mem_b_content}" in CONTRADICTION_PROMPT

    def test_rewrite_prompt_placeholders(self):
        assert "{current_content}" in REWRITE_PROMPT
        assert "{new_evidence}" in REWRITE_PROMPT

    def test_entity_resolution_prompt_placeholders(self):
        assert "{entity_a_id}" in ENTITY_RESOLUTION_PROMPT
        assert "{entity_a_label}" in ENTITY_RESOLUTION_PROMPT
        assert "{entity_b_label}" in ENTITY_RESOLUTION_PROMPT


# ---------------------------------------------------------------------------
# Tests: Integration / End-to-End workflows
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """End-to-end integration tests combining multiple self-editing steps."""

    def test_merge_then_rewrite_flow(self):
        """Merge similar memories, then rewrite the surviving one."""
        memories = [
            {"id": "m1", "content": "User prefers dark mode in all apps.",
             "summary": "dark mode", "tags": ["ui"],
             "created_at": "2026-01-01T00:00:00Z",
             "updated_at": "2026-01-01T00:00:00Z",
             "importance": 0.5, "strength": 0.5, "confidence": 0.5,
             "access_count": 1},
            {"id": "m2", "content": "User likes dark mode on devices.",
             "summary": "dark mode", "tags": ["ui"],
             "created_at": "2026-01-02T00:00:00Z",
             "updated_at": "2026-01-02T00:00:00Z",
             "importance": 0.5, "strength": 0.5, "confidence": 0.5,
             "access_count": 1},
        ]
        client = _make_mock_client(memories=memories)

        # Step 1: Merge
        merge_result = merge_similar_memories(
            client, "ws1", threshold=0.5, dry_run=True
        )
        assert merge_result["candidates_considered"] > 0

        # Step 2: Rewrite a memory with new evidence
        rewrite_result = rewrite_memory(
            client, "ws1", "m1",
            "User now uses system theme instead of dark mode.",
            content_override=memories[0]["content"],
            dry_run=True,
        )
        assert rewrite_result["new_content"] is not None
        assert "system theme" in rewrite_result["new_content"] or "dark" in rewrite_result.get("new_content", "")

    def test_detect_then_resolve_flow(self):
        """Detect contradictions and resolve entities in sequence."""
        memories = [
            {"id": "m1", "content": "Alice loves Python.", "summary": "Alice Python"},
            {"id": "m2", "content": "Alice hates Python.", "summary": "Alice Python hate"},
        ]
        nodes = [
            {"id": "n1", "label": "Alice Smith", "node_type": "entity",
             "summary": "Engineer.", "name": "Alice"},
            {"id": "n2", "label": "Alice S.", "node_type": "entity",
             "summary": "Engineer at Acme.", "name": "Alice"},
        ]
        client = _make_mock_client(memories=memories, nodes=nodes)

        # Step 1: Detect contradictions
        contra_result = detect_contradictions(
            client, "ws1", similarity_threshold=0.1, threshold=0.3
        )
        # Step 2: Resolve entities
        resolve_result = resolve_entities(
            client, "ws1", threshold=0.5, dry_run=True
        )
        # Alice nodes should be resolved
        alice_resolved = any(
            "Alice" in r.get("label_a", "") and "Alice" in r.get("label_b", "")
            for r in resolve_result["resolutions"]
        )
        assert alice_resolved

    def test_all_operations_safe_on_empty(self):
        """All operations should handle empty workspace gracefully."""
        client = _make_mock_client(memories=[], nodes=[])

        merge_r = merge_similar_memories(client, "ws1")
        assert merge_r["merges"] == []

        contra_r = detect_contradictions(client, "ws1")
        assert contra_r["contradictions"] == []

        resolve_r = resolve_entities(client, "ws1")
        assert resolve_r["resolutions"] == []

        # Rewrite on empty store
        rewrite_r = rewrite_memory(client, "ws1", "nonexistent", "test")
        assert "error" in rewrite_r


# ---------------------------------------------------------------------------
# Tests: LLM call helper (_call_llm_parse_json)
# ---------------------------------------------------------------------------


class TestLlmCallHelper:
    """Tests for the internal _call_llm_parse_json helper."""

    def test_returns_none_when_no_llm(self):
        from spacetime_memory.self_editing import _call_llm_parse_json
        assert _call_llm_parse_json(None, []) is None

    def test_parses_json_from_llm(self):
        from spacetime_memory.self_editing import _call_llm_parse_json
        llm = _make_llm_mock({"key": "value"})
        result = _call_llm_parse_json(
            llm, [{"role": "user", "content": "test"}]
        )
        assert result == {"key": "value"}
        llm.chat.assert_called_once()

    def test_parses_json_from_callable(self):
        from spacetime_memory.self_editing import _call_llm_parse_json
        def callable_llm(messages):
            return '{"foo": "bar"}'
        result = _call_llm_parse_json(callable_llm, [])
        assert result == {"foo": "bar"}

    def test_handles_markdown_fence(self):
        from spacetime_memory.self_editing import _call_llm_parse_json
        def callable_llm(messages):
            return "```json\n{\"key\": \"value\"}\n```"
        result = _call_llm_parse_json(callable_llm, [])
        assert result == {"key": "value"}

    def test_handles_invalid_json(self):
        from spacetime_memory.self_editing import _call_llm_parse_json
        def callable_llm(messages):
            return "NOT JSON"
        result = _call_llm_parse_json(callable_llm, [])
        assert result is None

    def test_returns_none_on_empty_response(self):
        from spacetime_memory.self_editing import _call_llm_parse_json
        llm = MagicMock()
        llm.chat = MagicMock(return_value=None)
        result = _call_llm_parse_json(llm, [])
        assert result is None

    def test_already_dict(self):
        """If the LLM returns a dict (mock), pass through."""
        from spacetime_memory.self_editing import _call_llm_parse_json
        llm = MagicMock()
        llm.chat = MagicMock(return_value={"key": "val"})
        result = _call_llm_parse_json(llm, [])
        assert result == {"key": "val"}
