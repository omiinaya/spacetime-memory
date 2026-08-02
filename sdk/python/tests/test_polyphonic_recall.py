"""Comprehensive unit tests for Polyphonic Recall (Gap #8: Mnemosyne parity).

Tests cover standalone functions:
- classify_query_intent with various query types
- compress_memories with different strategies
- extract_persona with memories and messages
- detect_content_patterns

And PolyphonicRecallMixin methods:
- search_with_intent
- compress_workspace_memories
- extract_user_persona
- detect_advanced_patterns

All tests are pure unit tests — no STDB connection needed.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from spacetime_memory.client._polyphonic_recall import (
    QUERY_INTENTS,
    PolyphonicRecallMixin,
    _compress_diverse,
    _compress_llm,
    _recency_weight,
    classify_query_intent,
    compress_memories,
    detect_content_patterns,
    extract_persona,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_memories():
    """A diverse set of memory dicts for compression/persona tests."""
    return [
        {
            "content": "User prefers dark mode for all applications",
            "importance": 0.9,
            "memory_type": "preference",
            "created_at": time.time() * 1_000_000,
        },
        {
            "content": "User lives in San Francisco, California",
            "importance": 0.7,
            "memory_type": "fact",
            "created_at": (time.time() - 86400 * 7) * 1_000_000,
        },
        {
            "content": "User is a software engineer at a startup",
            "importance": 0.8,
            "memory_type": "fact",
            "created_at": (time.time() - 86400 * 30) * 1_000_000,
        },
        {
            "content": "User enjoys hiking and outdoor activities",
            "importance": 0.6,
            "memory_type": "activity",
            "created_at": (time.time() - 86400 * 14) * 1_000_000,
        },
        {
            "content": "User likes Python and Rust programming languages",
            "importance": 0.85,
            "memory_type": "preference",
            "created_at": (time.time() - 86400 * 3) * 1_000_000,
        },
    ]


@pytest.fixture
def sample_messages():
    """Sample message dicts for persona extraction."""
    return [
        {"sender_id": "user", "content": "Hi, can you help me with Python?"},
        {"sender_id": "user", "content": "I really enjoy coding in Rust too."},
        {"sender_id": "user", "content": "What's the best way to learn dark mode UI?"},
        {"sender_id": "user", "content": "Thanks for your help!"},
    ]


@pytest.fixture
def mock_llm():
    """A mock LLM completion function."""
    return MagicMock(return_value="mock response")


# ===================================================================
# 1. classify_query_intent
# ===================================================================


class TestClassifyQueryIntent:
    """Test query intent classification."""

    def test_empty_query(self):
        """Test empty query returns 'unknown' with 0 confidence."""
        result = classify_query_intent("")
        assert result["intent"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["secondary_intents"] == []

    def test_factual_query(self):
        """Test factual query detection."""
        result = classify_query_intent("What is the capital of France?")
        assert result["intent"] == "factual"
        assert result["confidence"] > 0

    def test_temporal_query(self):
        """Test temporal query detection."""
        result = classify_query_intent("When did the project start?")
        assert result["intent"] == "temporal"
        assert result["confidence"] > 0

    def test_procedural_query(self):
        """Test procedural query detection."""
        result = classify_query_intent("How do I install Python?")
        assert result["intent"] == "procedural"
        assert result["confidence"] > 0

    def test_comparison_query(self):
        """Test comparison query detection."""
        result = classify_query_intent("Compare Python vs Rust performance")
        assert result["intent"] == "comparison"
        assert result["confidence"] > 0

    def test_causal_query(self):
        """Test causal query detection."""
        result = classify_query_intent("Why does the sky appear blue?")
        assert result["intent"] == "causal"
        assert result["confidence"] > 0

    def test_social_query(self):
        """Test social query detection (must avoid factual/causal keywords)."""
        result = classify_query_intent("Who is the most popular person in the group?")
        assert result["intent"] == "social"
        assert result["confidence"] > 0

    def test_summarization_query(self):
        """Test summarization query detection."""
        result = classify_query_intent("Summarize the key findings")
        assert result["intent"] == "summarization"
        assert result["confidence"] > 0

    def test_exploratory_short_query(self):
        """Test short queries default to exploratory."""
        result = classify_query_intent("ideas")
        assert result["intent"] == "exploratory"
        # Short queries (<=3 words) get 0.6
        assert result["confidence"] == 0.6

    def test_exploratory_longer_query(self):
        """Test unrecognized longer queries get exploratory with 0.3."""
        result = classify_query_intent("something completely random with no keywords")
        assert result["intent"] == "exploratory"
        assert result["confidence"] == 0.3

    def test_secondary_intents(self):
        """Test secondary intents when query matches multiple categories."""
        # 'when did' is temporal, 'explain' is factual
        result = classify_query_intent("When did it happen and explain why")
        assert result["intent"] in ("temporal", "factual", "causal")
        assert isinstance(result["secondary_intents"], list)

    def test_llm_mode_returns_llm_result(self, mock_llm):
        """Test LLM mode returns LLM classification."""
        mock_llm.return_value = json.dumps(
            {"intent": "temporal", "confidence": 0.95}
        )
        result = classify_query_intent(
            "When did the event occur?",
            use_llm=True,
            llm_complete_fn=mock_llm,
        )
        assert result["intent"] == "temporal"
        assert result["confidence"] == 0.95

    def test_llm_mode_fallback(self, mock_llm):
        """Test LLM mode falls back to heuristic on failure."""
        mock_llm.side_effect = RuntimeError("LLM down")
        result = classify_query_intent(
            "What is Python?",
            use_llm=True,
            llm_complete_fn=mock_llm,
        )
        # Should fall back to heuristic
        assert result["intent"] != "unknown"

    def test_llm_invalid_json_fallback(self, mock_llm):
        """Test LLM mode falls back when LLM returns invalid JSON."""
        mock_llm.return_value = "not valid json"
        result = classify_query_intent(
            "What is Rust?",
            use_llm=True,
            llm_complete_fn=mock_llm,
        )
        assert result["intent"] != "unknown"

    def test_llm_confidence_clamped(self, mock_llm):
        """Test LLM confidence is clamped to [0.0, 1.0]."""
        mock_llm.return_value = json.dumps(
            {"intent": "factual", "confidence": 1.5}
        )
        result = classify_query_intent(
            "test", use_llm=True, llm_complete_fn=mock_llm
        )
        assert result["confidence"] <= 1.0

    def test_query_intents_dict_structure(self):
        """Test QUERY_INTENTS has expected categories."""
        expected = {
            "factual", "temporal", "procedural",
            "exploratory", "social", "summarization",
            "comparison", "causal",
        }
        assert set(QUERY_INTENTS.keys()) == expected


# ===================================================================
# 2. compress_memories
# ===================================================================


class TestCompressMemories:
    """Test memory compression with different strategies."""

    def test_empty_memories(self):
        """Test compress_memories with empty list."""
        result = compress_memories([])
        assert result == []

    def test_importance_strategy(self, sample_memories):
        """Test importance strategy keeps highest importance memories."""
        result = compress_memories(
            sample_memories,
            max_tokens=2000,
            strategy="importance",
        )
        assert len(result) <= len(sample_memories)
        if len(result) >= 2:
            # First result should have highest importance
            assert result[0]["importance"] >= result[1]["importance"]

    def test_importance_strategy_keeps_top(self, sample_memories):
        """Test importance strategy with limited max_tokens."""
        result = compress_memories(
            sample_memories,
            max_tokens=200,  # Very small — should keep only 1 or 2
            strategy="importance",
        )
        assert len(result) > 0
        # Should keep the highest importance ones
        assert result[0]["importance"] >= 0.85

    def test_recency_strategy(self, sample_memories):
        """Test recency strategy keeps most recent memories."""
        result = compress_memories(
            sample_memories,
            max_tokens=2000,
            strategy="recency",
        )
        assert len(result) <= len(sample_memories)
        if len(result) >= 2:
            recent_ts = float(result[0].get("created_at", 0))
            older_ts = float(result[1].get("created_at", 0))
            assert recent_ts >= older_ts

    def test_diverse_strategy(self, sample_memories):
        """Test diverse strategy keeps diverse set."""
        result = compress_memories(
            sample_memories,
            max_tokens=2000,
            strategy="diverse",
        )
        assert len(result) > 0
        # Diverse strategy should pick from different clusters
        assert len(result) <= len(sample_memories)

    def test_diverse_strategy_few_memories(self):
        """Test diverse strategy returns all if <= 3 memories."""
        memories = [
            {"content": "A", "importance": 0.5},
            {"content": "B", "importance": 0.5},
            {"content": "C", "importance": 0.5},
        ]
        result = compress_memories(memories, strategy="diverse")
        assert len(result) == 3

    def test_hybrid_strategy(self, sample_memories):
        """Test hybrid strategy combines importance and recency."""
        result = compress_memories(
            sample_memories,
            max_tokens=2000,
            strategy="hybrid",
        )
        assert len(result) > 0

    def test_llm_strategy(self, mock_llm, sample_memories):
        """Test LLM strategy uses LLM for compression."""
        mock_llm.return_value = json.dumps(
            ["Memory 1", "Memory 2", "Memory 3"]
        )
        result = compress_memories(
            sample_memories,
            max_tokens=2000,
            strategy="llm",
            llm_complete_fn=mock_llm,
        )
        assert len(result) == 3
        assert result[0]["memory_type"] == "compressed"

    def test_llm_strategy_fallback(self, mock_llm, sample_memories):
        """Test LLM strategy falls back to importance sorting on failure."""
        mock_llm.side_effect = RuntimeError("LLM unavailable")
        result = compress_memories(
            sample_memories,
            max_tokens=2000,
            strategy="llm",
            llm_complete_fn=mock_llm,
        )
        # Should fallback to top 5 by importance
        assert len(result) <= 5

    def test_unknown_strategy_falls_to_hybrid(self, sample_memories):
        """Test unknown strategy falls through to hybrid."""
        result = compress_memories(
            sample_memories,
            strategy="nonexistent_strategy",
        )
        assert len(result) > 0

    def test_recency_weight_positive(self):
        """Test _recency_weight returns positive values."""
        now = time.time() * 1_000_000
        weight = _recency_weight(now - 86400 * 1_000_000, now)
        assert weight > 0
        assert weight <= 1.0

    def test_recency_weight_recent_is_higher(self):
        """Test more recent events have higher recency weight."""
        now = time.time() * 1_000_000
        recent = _recency_weight(now - 3600 * 1_000_000, now)  # 1 hour ago
        old = _recency_weight(now - 86400 * 30 * 1_000_000, now)  # 30 days ago
        assert recent > old

    def test_recency_weight_zero_or_negative(self):
        """Test _recency_weight returns 0.5 for non-positive timestamps."""
        assert _recency_weight(0, 100) == 0.5
        assert _recency_weight(-1, 100) == 0.5

    def test_recency_weight_just_now(self):
        """Test _recency_weight returns 1.0 for very recent."""
        now = time.time() * 1_000_000
        # Very recent — less than 1 second
        weight = _recency_weight(now - 100_000, now)
        assert weight > 0.999


# ===================================================================
# 3. extract_persona
# ===================================================================


class TestExtractPersona:
    """Test persona extraction from memories and messages."""

    def test_no_memories(self):
        """Test with empty memories returns default persona."""
        result = extract_persona([])
        assert result["preferences"] == []
        assert result["traits"] == []
        assert result["interests"] == []
        assert result["communication_style"] == ""
        assert result["confidence"] == 0.0

    def test_extracts_preferences(self, sample_memories):
        """Test preference extraction from memory content."""
        result = extract_persona(sample_memories)
        assert len(result["preferences"]) > 0
        # Should find "prefer" in the first memory
        assert any("prefers" in p.lower() for p in result["preferences"])

    def test_memory_profile(self, sample_memories):
        """Test memory profile counts by type."""
        result = extract_persona(sample_memories)
        assert "memory_profile" in result
        assert len(result["memory_profile"]) > 0

    def test_communication_style_from_messages(self, sample_memories, sample_messages):
        """Test communication style is determined from messages."""
        result = extract_persona(sample_memories, messages=sample_messages)
        # Average message length should be moderate
        assert result["communication_style"] in ("concise", "moderate", "verbose")
        assert result["message_count"] == 4
        assert result["avg_message_length"] > 0

    def test_communication_style_concise(self, sample_memories):
        """Test very short messages result in 'concise' style."""
        short_msgs = [
            {"sender_id": "u", "content": "Hi"},
            {"sender_id": "u", "content": "Ok"},
            {"sender_id": "u", "content": "Yes"},
        ]
        result = extract_persona(sample_memories, messages=short_msgs)
        assert result["communication_style"] == "concise"

    def test_communication_style_verbose(self, sample_memories):
        """Test very long messages result in 'verbose' style."""
        long_msgs = [
            {"sender_id": "u", "content": "A" * 300},
            {"sender_id": "u", "content": "B" * 300},
        ]
        result = extract_persona(sample_memories, messages=long_msgs)
        assert result["communication_style"] == "verbose"

    def test_confidence_calculation(self, sample_memories):
        """Test confidence is calculated from data quantity."""
        # 5 memories * 0.05 = 0.25
        result = extract_persona(sample_memories)
        assert result["confidence"] == 0.25  # 5 * 0.05

        # With messages: 5 * 0.05 + 4 * 0.01 = 0.29
        messages = [{"sender_id": "u", "content": "test"} for _ in range(4)]
        result2 = extract_persona(sample_memories, messages=messages)
        assert result2["confidence"] == 0.29

    def test_llm_enrichment(self, mock_llm, sample_memories, sample_messages):
        """Test LLM enrichment provides richer traits/interests."""
        mock_llm.return_value = json.dumps({
            "traits": ["curious", "analytical", "creative"],
            "interests": ["programming", "AI", "hiking"],
            "communication_style": "Direct and technical",
        })
        result = extract_persona(
            sample_memories,
            messages=sample_messages,
            llm_complete_fn=mock_llm,
        )
        assert result["traits"] == ["curious", "analytical", "creative"]
        assert result["interests"] == ["programming", "AI", "hiking"]
        assert result["communication_style"] == "Direct and technical"

    def test_llm_enrichment_parse_error(self, mock_llm, sample_memories):
        """Test LLM enrichment handles JSON parse errors gracefully."""
        mock_llm.return_value = "not valid json"
        result = extract_persona(
            sample_memories,
            llm_complete_fn=mock_llm,
        )
        # Should still have preferences from keyword extraction
        assert len(result["preferences"]) > 0

    def test_llm_runtime_error_fallback(self, mock_llm, sample_memories):
        """Test LLM enrichment handles runtime errors gracefully."""
        mock_llm.side_effect = RuntimeError("API error")
        result = extract_persona(
            sample_memories,
            llm_complete_fn=mock_llm,
        )
        assert len(result["preferences"]) > 0

    def test_preference_keyword_search(self):
        """Test preference keywords are found in content."""
        memories = [
            {"content": "User likes ice cream and enjoys coding"},
            {"content": "User prefers dark mode"},
            {"content": "User loves hiking on weekends"},
        ]
        result = extract_persona(memories)
        assert len(result["preferences"]) >= 2

    def test_preferences_limited_to_10(self):
        """Test preferences list is capped at 10 items."""
        memories = [
            {"content": f"User likes item {i}"} for i in range(20)
        ]
        result = extract_persona(memories)
        assert len(result["preferences"]) <= 10


# ===================================================================
# 4. detect_content_patterns
# ===================================================================


class TestDetectContentPatterns:
    """Test advanced pattern detection in memories."""

    def test_empty_memories(self):
        """Test with empty memories returns empty patterns."""
        result = detect_content_patterns([])
        assert result == []

    def test_few_memories(self):
        """Test with fewer than min_frequency memories."""
        result = detect_content_patterns(
            [{"content": "test"}],
            min_frequency=2,
        )
        assert result == []

    def test_recurring_topics(self):
        """Test recurring topic detection."""
        memories = [
            {"content": "Python is great for data science and machine learning"},
            {"content": "Python has many libraries like NumPy and Pandas"},
            {"content": "Python programming is fun and productive"},
            {"content": "Rust is great for systems programming"},
        ]
        result = detect_content_patterns(memories)
        types = {p["type"] for p in result}
        assert "recurring_topics" in types
        # Find the topic pattern
        topic_pattern = next(p for p in result if p["type"] == "recurring_topics")
        assert len(topic_pattern["terms"]) > 0
        assert "strength" in topic_pattern

    def test_temporal_pattern(self):
        """Test temporal pattern detection."""
        base = time.time()
        memories = [
            {"content": "Morning routine", "created_at": base},
            {"content": "Morning coffee", "created_at": base + 3600},
            {"content": "Morning standup", "created_at": base + 7200},
        ]
        result = detect_content_patterns(memories, min_frequency=2)
        types = {p["type"] for p in result}
        assert "temporal_pattern" in types

    def test_temporal_with_microsecond_timestamps(self):
        """Test temporal pattern detection with microsecond timestamps."""
        base = time.time() * 1_000_000
        memories = [
            {"content": "Morning meeting discussion", "created_at": base - 7200_000_000},
            {"content": "Afternoon standup notes", "created_at": base},
            {"content": "Evening planning session", "created_at": base + 43200_000_000},
        ]
        result = detect_content_patterns(memories, min_frequency=2)
        assert isinstance(result, list)

    def test_temporal_without_timestamps(self):
        """Test with memories without timestamps."""
        memories = [
            {"content": "Only content"},
            {"content": "No timestamps"},
        ]
        result = detect_content_patterns(memories, min_frequency=2)
        types = {p["type"] for p in result}
        assert "temporal_pattern" not in types

    def test_sequence_pattern(self):
        """Test sequence pattern detection."""
        memories = [
            {"content": "Python programming for data science and machine learning projects"},
            {"content": "Python machine learning with scikit-learn and numpy arrays"},
            {"content": "Python deep learning with TensorFlow for data science tasks"},
            {"content": "Unrelated topic about cars and vehicles"},
        ]
        result = detect_content_patterns(memories, min_frequency=2)
        types = {p["type"] for p in result}
        assert "sequence_pattern" in types, f"Patterns: {types}"

    def test_all_pattern_types(self):
        """Test multiple pattern types are returned together."""
        base = time.time()
        memories = [
            {"content": "Python programming for data science", "created_at": base},
            {"content": "Python machine learning with scikit-learn", "created_at": base + 3600},
            {"content": "Python deep learning frameworks", "created_at": base + 7200},
            {"content": "Related python data pipeline", "created_at": base + 10800},
        ]
        result = detect_content_patterns(memories, min_frequency=2)
        types = {p["type"] for p in result}
        # Should have at least recurring_topics
        assert "recurring_topics" in types


# ===================================================================
# 5. PolyphonicRecallMixin methods
# ===================================================================


class _TestableMixin(PolyphonicRecallMixin):
    """A mixin without full Client — just mocked deps."""


@pytest.fixture
def poly_mixin():
    """Create a PolyphonicRecallMixin with mocked dependencies."""
    mixin = _TestableMixin()
    mixin._query = MagicMock(return_value=[])
    mixin.search = MagicMock(return_value=[])
    mixin._llm_complete = MagicMock(return_value="Mock answer")
    return mixin


class TestPolyphonicRecallMixin:
    """Test the PolyphonicRecallMixin methods."""

    # --- search_with_intent ---

    def test_search_with_intent_basic(self, poly_mixin):
        """Test basic search with intent classification."""
        poly_mixin.search.return_value = [
            {"id": "1", "content": "Python is a programming language", "score": 0.95},
        ]
        result = poly_mixin.search_with_intent(
            workspace_id="ws-1",
            query="What is Python?",
            top_k=5,
        )
        assert len(result["results"]) == 1
        assert result["query_intent"]["intent"] == "factual"
        assert "strategy_used" in result
        assert "reranker_used" in result

    def test_search_with_intent_fallback_to_query(self, poly_mixin):
        """Test search_with_intent falls back to _query when no search attr."""
        del poly_mixin.search
        result = poly_mixin.search_with_intent(
            workspace_id="ws-1",
            query="How to code?",
        )
        assert "results" in result
        assert "query_intent" in result

    def test_search_with_intent_llm_mode(self, poly_mixin):
        """Test search with LLM intent classification."""
        poly_mixin.search.return_value = []
        result = poly_mixin.search_with_intent(
            workspace_id="ws-1",
            query="How to install Python?",
            use_llm_intent=True,
        )
        assert result["query_intent"]["intent"] is not None

    def test_search_with_intent_extra_kwargs(self, poly_mixin):
        """Test search_with_intent passes extra kwargs to search."""
        poly_mixin.search.return_value = [{"id": "1", "content": "test"}]
        _ = poly_mixin.search_with_intent(
            workspace_id="ws-1",
            query="test query",
            top_k=10,
            custom_param="value",
        )
        poly_mixin.search.assert_called_once()
        kwargs = poly_mixin.search.call_args[1]
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["query"] == "test query"
        assert kwargs["top_k"] == 10
        assert kwargs["custom_param"] == "value"
        assert kwargs["polyphonic"] is True

    def test_search_with_intent_strategy_map(self, poly_mixin):
        """Test different intent types map to different strategies."""
        test_cases = [
            ("What is X?", "factual"),
            ("When did X happen?", "temporal"),
            ("How do I do X?", "procedural"),
            ("Compare X and Y", "comparison"),
            ("Summarize the results", "summarization"),
        ]
        for query, expected_intent in test_cases:
            poly_mixin.search.return_value = []
            result = poly_mixin.search_with_intent(
                workspace_id="ws-1", query=query,
            )
            assert result["query_intent"]["intent"] == expected_intent

    # --- compress_workspace_memories ---

    def test_compress_workspace_memories_basic(self, poly_mixin):
        """Test workspace memory compression."""
        poly_mixin._query.return_value = [
            {"content": "Important memory", "importance": 0.9},
            {"content": "Less important", "importance": 0.3},
        ]
        result = poly_mixin.compress_workspace_memories(
            workspace_id="ws-1",
            max_tokens=2000,
            strategy="importance",
        )
        assert len(result) > 0
        poly_mixin._query.assert_called_once_with(
            "memory",
            workspace_id="ws-1",
            filter_dict={"workspace_id": "ws-1"},
        )

    def test_compress_workspace_memories_empty(self, poly_mixin):
        """Test compression with no memories returns empty."""
        poly_mixin._query.return_value = []
        result = poly_mixin.compress_workspace_memories(
            workspace_id="ws-1",
        )
        assert result == []

    def test_compress_workspace_memories_with_strategies(self, poly_mixin):
        """Test compression with different strategies."""
        memories = [
            {"content": "A" * 100, "importance": 0.9, "created_at": time.time() * 1_000_000},
            {"content": "B" * 100, "importance": 0.5, "created_at": 0},
        ]
        for strategy in ("importance", "recency", "diverse", "hybrid"):
            poly_mixin._query.return_value = memories
            result = poly_mixin.compress_workspace_memories(
                workspace_id="ws-1",
                strategy=strategy,
            )
            # Should not crash for any strategy
            assert isinstance(result, list)

    # --- extract_user_persona ---

    def test_extract_user_persona_with_session(self, poly_mixin):
        """Test persona extraction with a specific session."""
        poly_mixin._query.side_effect = [
            [  # First call: memories
                {"content": "User prefers dark mode", "memory_type": "preference"},
            ],
            [  # Second call: messages
                {"sender_id": "user", "content": "I like Python"},
            ],
        ]
        result = poly_mixin.extract_user_persona(
            workspace_id="ws-1",
            session_id="session-123",
        )
        assert "preferences" in result
        assert "traits" in result
        assert "interests" in result
        assert "communication_style" in result
        # Should have called _query twice
        assert poly_mixin._query.call_count == 2

    def test_extract_user_persona_without_session(self, poly_mixin):
        """Test persona extraction without session (memories only)."""
        poly_mixin._query.return_value = [
            {"content": "User loves programming", "memory_type": "preference"},
        ]
        result = poly_mixin.extract_user_persona(
            workspace_id="ws-1",
        )
        assert "preferences" in result
        # _query called only once for memories
        assert poly_mixin._query.call_count == 1

    def test_extract_user_persona_llm_enrichment(self, poly_mixin):
        """Test persona extraction uses LLM enrichment when available."""
        poly_mixin._query.return_value = [
            {"content": "User prefers dark mode", "memory_type": "preference"},
        ]
        result = poly_mixin.extract_user_persona(
            workspace_id="ws-1",
            session_id="session-123",
        )
        # With mock messages and LLM available, enrichment is attempted
        assert "preferences" in result

    # --- detect_advanced_patterns ---

    def test_detect_advanced_patterns_basic(self, poly_mixin):
        """Test advanced pattern detection."""
        poly_mixin._query.return_value = [
            {"content": "Python programming is fun", "created_at": time.time()},
            {"content": "Python has many libraries", "created_at": time.time() + 3600},
            {"content": "Python is great for ML", "created_at": time.time() + 7200},
        ]
        result = poly_mixin.detect_advanced_patterns(
            workspace_id="ws-1",
            min_frequency=2,
        )
        assert len(result) > 0
        types = {p["type"] for p in result}
        assert "recurring_topics" in types

    def test_detect_advanced_patterns_empty(self, poly_mixin):
        """Test pattern detection with no memories."""
        poly_mixin._query.return_value = []
        result = poly_mixin.detect_advanced_patterns(
            workspace_id="ws-1",
        )
        assert result == []

    def test_detect_advanced_patterns_few_memories(self, poly_mixin):
        """Test pattern detection with fewer than min_frequency memories."""
        poly_mixin._query.return_value = [
            {"content": "Only one memory"},
        ]
        result = poly_mixin.detect_advanced_patterns(
            workspace_id="ws-1",
            min_frequency=3,
        )
        assert result == []


# ===================================================================
# 6. Integration / Edge cases for standalone functions
# ===================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_classify_query_intent_all_punctuation(self):
        """Test query with only punctuation."""
        result = classify_query_intent("!@#$%")
        # Short (<=3 words) with no keywords → exploratory with 0.6
        # Actually "!@#$%" isn't really words... let's check
        assert result["intent"] in ("exploratory", "unknown")

    def test_compress_memories_no_importance_field(self):
        """Test compression with memories missing importance field."""
        memories = [
            {"content": "Memory without importance"},
            {"content": "Another without importance"},
        ]
        result = compress_memories(memories, strategy="importance")
        assert len(result) > 0
        # Should default to 0.5
        assert result[0]["content"] is not None

    def test_compress_memories_max_tokens_exact(self):
        """Test compression when content exactly fills max_tokens."""
        memories = [
            {"content": "A" * 100, "importance": 0.9},
            {"content": "B" * 100, "importance": 0.8},
            {"content": "C" * 100, "importance": 0.7},
        ]
        # max_tokens = 100 + 100 overhead = 200 for first item
        # That means first item fits, second should be cut
        result = compress_memories(memories, max_tokens=200, strategy="importance")
        assert len(result) == 1

    def test_extract_persona_only_messages_no_memories(self):
        """Test persona extraction with only messages (no memories)."""
        messages = [
            {"sender_id": "user", "content": "Hi there"},
        ]
        result = extract_persona([], messages=messages)
        # Empty memories should return default persona
        assert result["preferences"] == []

    def test_detect_content_patterns_string_timestamps(self):
        """Test pattern detection ignores non-numeric timestamps."""
        memories = [
            {"content": "test", "created_at": "not-a-number"},
        ]
        result = detect_content_patterns(memories, min_frequency=1)
        assert isinstance(result, list)

    def test_compress_diverse_clustering(self):
        """Test _compress_diverse internal function."""
        memories = [
            {"content": "Python programming", "importance": 0.9},
            {"content": "Python coding", "importance": 0.8},
            {"content": "Rust systems programming", "importance": 0.7},
            {"content": "Rust memory safety", "importance": 0.6},
            {"content": "Hiking mountains", "importance": 0.5},
        ]
        result = _compress_diverse(memories, max_tokens=2000)
        assert len(result) >= 1
        # Should have at most one from each cluster
        assert len(result) <= 5

    def test_compress_llm_internal(self, mock_llm):
        """Test _compress_llm internal function."""
        mock_llm.return_value = json.dumps(["Summary 1", "Summary 2"])
        memories = [
            {"content": "Test memory 1"},
            {"content": "Test memory 2"},
        ]
        result = _compress_llm(memories, 2000, mock_llm)
        assert len(result) == 2
        assert result[0]["memory_type"] == "compressed"

    def test_compress_llm_empty_memories(self, mock_llm):
        """Test _compress_llm with empty memories."""
        result = _compress_llm([], 2000, mock_llm)
        assert result == []

    def test_compress_llm_parse_fallback(self, mock_llm):
        """Test _compress_llm fallback when LLM returns invalid data."""
        mock_llm.return_value = "not json"
        memories = [
            {"content": "A", "importance": 0.9},
            {"content": "B", "importance": 0.5},
            {"content": "C", "importance": 0.3},
            {"content": "D", "importance": 0.2},
            {"content": "E", "importance": 0.1},
            {"content": "F", "importance": 0.05},
        ]
        result = _compress_llm(memories, 2000, mock_llm)
        assert len(result) == 5  # fallback: top 5 by importance
