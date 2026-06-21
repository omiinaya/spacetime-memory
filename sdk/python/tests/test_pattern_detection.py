"""Tests for pattern detection (pattern_detection.py)."""

import pytest
from datetime import datetime, timezone
from spacetime_memory.pattern_detection import (
    _tokenize,
    detect_temporal_clusters,
    detect_frequent_terms,
    detect_co_occurrences,
    _extract_common_terms,
    detect_patterns,
)


# ── _tokenize ───────────────────────────────────────────────────────────────


class TestTokenize:
    """Tokenization and filtering of text to meaningful terms."""

    def test_basic_tokenization(self):
        assert _tokenize("hello world") == ["hello", "world"]

    def test_filter_short_tokens(self):
        # "a", "an", "to" are < 3 chars, should be filtered
        tokens = _tokenize("a an to the big cat")
        assert "a" not in tokens
        assert "an" not in tokens
        assert "to" not in tokens
        assert "big" in tokens
        assert "cat" in tokens

    def test_min_len_parameter(self):
        assert _tokenize("ab cd efgh ij", min_len=3) == ["efgh"]

    def test_punctuation_removed(self):
        tokens = _tokenize("hello, world! how's it going?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "how" in tokens
        assert any("," not in t for t in tokens)

    def test_numbers_and_underscores(self):
        tokens = _tokenize("var_123 test abc")
        assert "var_123" in tokens
        assert "test" in tokens

    def test_lowercase_output(self):
        tokens = _tokenize("Hello WORLD PyThOn")
        assert all(t == t.lower() for t in tokens)

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_all_short_tokens(self):
        assert _tokenize("a b c d", min_len=3) == []

    def test_min_len_one(self):
        tokens = _tokenize("a bc def", min_len=1)
        assert "a" in tokens
        assert "bc" in tokens
        assert "def" in tokens


# ── detect_temporal_clusters ────────────────────────────────────────────────


class TestDetectTemporalClusters:
    """Temporal clustering of memories by creation time."""

    def test_empty_memories(self):
        assert detect_temporal_clusters([]) == []

    def test_no_memories(self):
        assert detect_temporal_clusters([]) == []

    def test_single_memory_below_min_cluster(self):
        memories = [{"id": "m1", "content": "test", "created_at": 1000}]
        result = detect_temporal_clusters(memories, min_cluster_size=2)
        assert result == []

    def test_two_memories_same_bucket(self):
        memories = [
            {"id": "m1", "content": "hello world", "created_at": 1000},
            {"id": "m2", "content": "foo bar baz", "created_at": 1010},
        ]
        result = detect_temporal_clusters(memories, bucket_minutes=30, min_cluster_size=2)
        assert len(result) == 1
        cluster = result[0]
        assert cluster["count"] == 2
        assert set(cluster["ids"]) == {"m1", "m2"}
        assert "start_time" in cluster
        assert "end_time" in cluster
        assert "summary_terms" in cluster

    def test_microsecond_timestamps(self):
        """Timestamps > 1e12 are treated as microseconds and converted to seconds."""
        # 1,700,000,000,000,000 microseconds = 1,700,000,000 seconds
        memories = [
            {"id": "m1", "content": "alpha beta", "created_at": 1_700_000_000_000_000},
            {"id": "m2", "content": "gamma delta", "created_at": 1_700_000_000_000_050},
        ]
        result = detect_temporal_clusters(memories, bucket_minutes=30, min_cluster_size=2)
        assert len(result) == 1

    def test_multiple_clusters(self):
        base = 1_000_000  # seconds
        memories = [
            {"id": "m1", "content": "cluster one alpha", "created_at": base},
            {"id": "m2", "content": "cluster one beta", "created_at": base + 60},
            # Different bucket (bucket_minutes=30 → 1800s per bucket)
            {"id": "m3", "content": "cluster two gamma", "created_at": base + 3600},
            {"id": "m4", "content": "cluster two delta", "created_at": base + 3660},
        ]
        result = detect_temporal_clusters(memories, bucket_minutes=30, min_cluster_size=2)
        assert len(result) == 2

    def test_clusters_sorted_by_time_desc(self):
        base = 1_000_000
        memories = [
            {"id": "m1", "content": "old", "created_at": base},
            {"id": "m2", "content": "old2", "created_at": base + 60},
            {"id": "m3", "content": "new", "created_at": base + 10000},
            {"id": "m4", "content": "new2", "created_at": base + 10060},
        ]
        result = detect_temporal_clusters(memories, bucket_minutes=30, min_cluster_size=2)
        assert len(result) == 2
        # Most recent cluster first
        assert result[0]["start_time"] > result[1]["start_time"]

    def test_min_cluster_size_enforced(self):
        memories = [
            {"id": "m1", "content": "solo memory", "created_at": 1000},
        ]
        result = detect_temporal_clusters(memories, min_cluster_size=2)
        assert result == []

    def test_missing_created_at_defaults_to_zero(self):
        memories = [
            {"id": "m1", "content": "a"},
            {"id": "m2", "content": "b"},
        ]
        result = detect_temporal_clusters(memories, bucket_minutes=30, min_cluster_size=2)
        assert len(result) == 1  # both default to ts=0, same bucket

    def test_summary_terms_in_output(self):
        memories = [
            {"id": "m1", "content": "deploy production server alpha", "created_at": 1000},
            {"id": "m2", "content": "deploy staging server beta", "created_at": 1010},
        ]
        result = detect_temporal_clusters(memories, bucket_minutes=30, min_cluster_size=2)
        assert len(result) == 1
        assert len(result[0]["summary_terms"]) <= 5
        assert "deploy" in result[0]["summary_terms"]
        assert "server" in result[0]["summary_terms"]

    def test_custom_bucket_minutes(self):
        memories = [
            {"id": "m1", "content": "test", "created_at": 0},
            {"id": "m2", "content": "test", "created_at": 600},  # 10 min later
        ]
        # With 5-min buckets: different buckets → no cluster
        result = detect_temporal_clusters(memories, bucket_minutes=5, min_cluster_size=2)
        assert result == []
        # With 15-min buckets: same bucket → cluster
        result2 = detect_temporal_clusters(memories, bucket_minutes=15, min_cluster_size=2)
        assert len(result2) == 1


# ── detect_frequent_terms ───────────────────────────────────────────────────


class TestDetectFrequentTerms:
    """Extract most frequent meaningful terms."""

    def test_empty_memories(self):
        assert detect_frequent_terms([]) == []

    def test_single_memory(self):
        # detect_frequent_terms has default min_df=2, so with 1 memory no term
        # appears in ≥2 docs. Use min_df=1 to get results from a single doc.
        memories = [{"content": "hello world hello"}]
        result = detect_frequent_terms(memories, min_df=1)
        assert len(result) >= 1
        # "hello" appears twice in the doc
        term_names = [t["term"] for t in result]
        assert "hello" in term_names

    def test_multiple_memories(self):
        memories = [
            {"content": "python programming language"},
            {"content": "python web framework"},
            {"content": "python data science"},
        ]
        result = detect_frequent_terms(memories)
        term_names = [t["term"] for t in result]
        assert "python" in term_names

    def test_min_df_filter(self):
        memories = [
            {"content": "common term here"},
            {"content": "common term there"},
            {"content": "rare unique word"},
        ]
        # With min_df=2, only terms appearing in ≥2 docs survive
        result = detect_frequent_terms(memories, min_df=2)
        term_names = [t["term"] for t in result]
        assert "common" in term_names
        assert "term" in term_names
        assert "rare" not in term_names

    def test_top_n_limit(self):
        memories = [
            {"content": "a b c d e f g h i j k l m n o p q r s t u v w x y z"},
        ] * 3
        result = detect_frequent_terms(memories, top_n=5)
        assert len(result) <= 5

    def test_doc_count_field(self):
        memories = [
            {"content": "python code"},
            {"content": "python test"},
            {"content": "rust code"},
        ]
        result = detect_frequent_terms(memories)
        for term in result:
            assert "doc_count" in term
            assert "frequency" in term
            assert isinstance(term["doc_count"], int)

    def test_missing_content_defaults_empty(self):
        memories = [
            {"id": "m1"},
            {"id": "m2", "content": "something"},
        ]
        result = detect_frequent_terms(memories, min_df=2)
        # Only terms from m2, but m1 has no content → doc_freq for any term is 1
        assert len(result) <= 1

    def test_all_memories_missing_content(self):
        memories = [{"id": "m1"}, {"id": "m2"}]
        result = detect_frequent_terms(memories)
        assert result == []


# ── detect_co_occurrences ───────────────────────────────────────────────────


class TestDetectCoOccurrences:
    """Term co-occurrence pair detection."""

    def test_empty_memories(self):
        assert detect_co_occurrences([]) == []

    def test_single_memory(self):
        # detect_co_occurrences returns [] when len(memories) < 2
        memories = [{"content": "python java"}]
        result = detect_co_occurrences(memories)
        assert result == []  # need at least 2 memories

    def test_two_memories_single_pair(self):
        memories = [
            {"content": "python java"},
            {"content": "python go"},
        ]
        result = detect_co_occurrences(memories)
        assert len(result) >= 1

    def test_two_memories_shared_pair(self):
        memories = [
            {"content": "python django web"},
            {"content": "python django rest"},
        ]
        result = detect_co_occurrences(memories)
        # Pairs: python-django (2 docs), python-web (1), python-rest (1), django-web (1), django-rest (1), web-rest (0)
        pairs = {(r["term_a"], r["term_b"]): r["count"] for r in result}
        pair_key1 = ("django", "python")
        pair_key2 = ("python", "django")
        if pair_key1 in pairs:
            assert pairs[pair_key1] == 2
        elif pair_key2 in pairs:
            assert pairs[pair_key2] == 2

    def test_strength_calculation(self):
        memories = [
            {"content": "alpha beta"},
            {"content": "alpha gamma"},
        ]
        result = detect_co_occurrences(memories)
        for r in result:
            assert 0.0 <= r["strength"] <= 1.0
            if {r["term_a"], r["term_b"]} == {"alpha", "beta"}:
                assert r["strength"] == 0.5

    def test_single_token_docs_skipped(self):
        memories = [
            {"content": "singleterm"},
            {"content": "alpha beta"},
        ]
        result = detect_co_occurrences(memories)
        # Only the second doc contributes
        for r in result:
            assert r["count"] >= 1

    def test_top_n_limit(self):
        memories = [
            {"content": f"term_{i} term_{j}"}
            for i in range(10)
            for j in range(i + 1, 10)
        ]
        result = detect_co_occurrences(memories, top_n=5)
        assert len(result) <= 5

    def test_missing_content(self):
        memories = [{"id": "m1"}, {"id": "m2", "content": "hello world"}]
        result = detect_co_occurrences(memories)
        # Only m2 contributes, but has 2 tokens → 1 pair
        assert len(result) == 1

    def test_all_empty_content(self):
        memories = [{"id": "m1"}, {"id": "m2"}]
        result = detect_co_occurrences(memories)
        assert result == []


# ── _extract_common_terms ───────────────────────────────────────────────────


class TestExtractCommonTerms:
    """Helper to extract common terms across memory groups."""

    def test_basic(self):
        items = [
            {"content": "deploy server alpha"},
            {"content": "deploy server beta"},
            {"content": "deploy database gamma"},
        ]
        result = _extract_common_terms(items, top_n=3)
        assert "deploy" in result

    def test_top_n_limit(self):
        items = [{"content": f"term{i} unique{i}"} for i in range(20)]
        result = _extract_common_terms(items, top_n=5)
        assert len(result) <= 5

    def test_empty_items(self):
        assert _extract_common_terms([]) == []

    def test_missing_content(self):
        items = [{"id": "m1"}, {"content": "hello world"}]
        result = _extract_common_terms(items, top_n=5)
        assert "hello" in result or "world" in result


# ── detect_patterns (orchestrator) ──────────────────────────────────────────


class TestDetectPatterns:
    """Orchestrator function — runs all analyses."""

    def _sample_memories(self):
        return [
            {"id": "m1", "content": "python programming language", "created_at": 1000},
            {"id": "m2", "content": "python web development", "created_at": 1010},
            {"id": "m3", "content": "rust systems programming", "created_at": 5000},
            {"id": "m4", "content": "rust web server", "created_at": 5020},
        ]

    def test_all_analyses(self):
        result = detect_patterns(self._sample_memories())
        assert result["total_memories"] == 4
        assert "temporal_clusters" in result
        assert "frequent_terms" in result
        assert "co_occurrences" in result
        assert "summary" in result
        assert len(result["summary"]) > 0

    def test_clusters_only(self):
        result = detect_patterns(
            self._sample_memories(),
            include_clusters=True,
            include_terms=False,
            include_co_occur=False,
        )
        assert "temporal_clusters" in result
        assert "frequent_terms" not in result
        assert "co_occurrences" not in result

    def test_terms_only(self):
        result = detect_patterns(
            self._sample_memories(),
            include_clusters=False,
            include_terms=True,
            include_co_occur=False,
        )
        assert "temporal_clusters" not in result
        assert "frequent_terms" in result
        assert "co_occurrences" not in result

    def test_co_occur_only(self):
        result = detect_patterns(
            self._sample_memories(),
            include_clusters=False,
            include_terms=False,
            include_co_occur=True,
        )
        assert "temporal_clusters" not in result
        assert "frequent_terms" not in result
        assert "co_occurrences" in result

    def test_none_enabled(self):
        result = detect_patterns(
            self._sample_memories(),
            include_clusters=False,
            include_terms=False,
            include_co_occur=False,
        )
        assert result["total_memories"] == 4
        assert "temporal_clusters" not in result
        assert "frequent_terms" not in result
        assert "co_occurrences" not in result
        assert result["summary"] == "no significant patterns detected"

    def test_empty_memories(self):
        result = detect_patterns([])
        assert result["total_memories"] == 0
        assert result["summary"] == "no significant patterns detected"

    def test_single_memory_minimal_patterns(self):
        result = detect_patterns(
            [{"id": "m1", "content": "hello world", "created_at": 1000}]
        )
        assert result["total_memories"] == 1
        # temporal_clusters: min_cluster_size=2 → empty
        assert result["temporal_clusters"] == []
        # frequent_terms: min_df=2, one doc → empty or limited
        # co_occurrences: len(memories) < 2 → empty
        assert result["co_occurrences"] == []

    def test_summary_with_clusters(self):
        result = detect_patterns(self._sample_memories())
        assert "temporal clusters detected" in result["summary"].lower()

    def test_summary_with_terms(self):
        result = detect_patterns(self._sample_memories())
        assert "top terms" in result["summary"].lower()

    def test_summary_with_co_occurrences(self):
        result = detect_patterns(self._sample_memories())
        assert "co-occurrence" in result["summary"].lower()
