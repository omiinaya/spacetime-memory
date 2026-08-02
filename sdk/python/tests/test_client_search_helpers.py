"""Unit tests for search helper functions — embedding parsing, BM25, tokenization, context formatting.

These are pure functions tested with dict inputs — no fixtures needed.
"""

from __future__ import annotations

import json


class TestParseEmbeddingJson:
    """parse_embedding_json edge cases."""

    def test_valid_array(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json("[0.1, 0.2, 0.3]")
        assert result == [0.1, 0.2, 0.3]

    def test_empty_string(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json("")
        assert result == []

    def test_empty_brackets(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json("[]")
        assert result == []

    def test_null_string(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json("null")
        assert result == []

    def test_invalid_json(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json("not json")
        assert result == []

    def test_not_a_list(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json('{"a": 1}')
        assert result == []

    def test_mixed_types(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json('[0.1, "a"]')
        assert result == []

    def test_int_list(self):
        from spacetime_memory.client._search_helpers import parse_embedding_json
        result = parse_embedding_json("[1, 2, 3]")
        assert result == [1.0, 2.0, 3.0]


class TestCosineSimilarity:
    """cosine_similarity edge cases."""

    def test_identical_vectors(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert result == 1.0

    def test_orthogonal_vectors(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert result == 0.0

    def test_opposite_vectors_clamped(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert result == 0.0  # clamped from -1.0

    def test_empty_first_vector(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([], [1.0, 0.0])
        assert result == 0.0

    def test_empty_second_vector(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([1.0, 0.0], [])
        assert result == 0.0

    def test_different_lengths(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0])
        assert result == 0.0

    def test_zero_vector(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([0.0, 0.0], [1.0, 0.0])
        assert result == 0.0

    def test_partial_match(self):
        from spacetime_memory.client._search_helpers import cosine_similarity
        result = cosine_similarity([1.0, 0.5, 0.0], [0.8, 0.3, 0.1])
        assert 0.9 < result < 1.0


class TestBm25Idf:
    """bm25_idf edge cases."""

    def test_normal_case(self):
        from spacetime_memory.client._search_helpers import bm25_idf
        result = bm25_idf(100, 10)
        assert result > 0

    def test_zero_term_freq(self):
        from spacetime_memory.client._search_helpers import bm25_idf
        result = bm25_idf(100, 0)
        assert result == 0.0

    def test_zero_doc_count(self):
        from spacetime_memory.client._search_helpers import bm25_idf
        result = bm25_idf(0, 5)
        assert result == 0.0

    def test_term_in_all_docs(self):
        from spacetime_memory.client._search_helpers import bm25_idf
        result = bm25_idf(10, 10)
        assert result > 0
        assert result < 0.7  # N = n => log(1 + 0.5/10.5) ≈ 0.046

    def test_rare_term_high_idf(self):
        from spacetime_memory.client._search_helpers import bm25_idf
        result = bm25_idf(1000, 1)
        assert result > 5.0  # log(1 + 999.5/1.5) ≈ 6.6


class TestBm25Score:
    """bm25_score edge cases."""

    def test_normal_case(self):
        from spacetime_memory.client._search_helpers import bm25_score
        result = bm25_score(term_freq=3, doc_len=100, avg_doc_len=150, idf=2.0)
        assert result > 0

    def test_zero_doc_len(self):
        from spacetime_memory.client._search_helpers import bm25_score
        result = bm25_score(term_freq=1, doc_len=0, avg_doc_len=150, idf=2.0)
        assert result == 0.0

    def test_zero_avg_doc_len(self):
        from spacetime_memory.client._search_helpers import bm25_score
        result = bm25_score(term_freq=1, doc_len=100, avg_doc_len=0, idf=2.0)
        assert result == 0.0

    def test_zero_idf(self):
        from spacetime_memory.client._search_helpers import bm25_score
        result = bm25_score(term_freq=1, doc_len=100, avg_doc_len=150, idf=0.0)
        assert result == 0.0

    def test_custom_params(self):
        from spacetime_memory.client._search_helpers import bm25_score
        result = bm25_score(term_freq=5, doc_len=200, avg_doc_len=150, idf=1.5, k1=2.0, b=0.5)
        assert result > 0


class TestTokenizeQuery:
    """tokenize_query edge cases."""

    def test_empty_query(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("")
        assert result == []

    def test_basic_query(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("Python programming language")
        assert "python" in result
        assert "programming" in result
        assert "language" in result

    def test_stopwords_removed(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("the is a")
        assert result == []

    def test_punctuation_stripped(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("hello, world!")
        assert "hello" in result
        assert "world" in result

    def test_single_char_removed(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("a b c python")
        assert result == ["python"]

    def test_custom_stopwords(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("python language", stopwords={"python"})
        assert "language" in result
        assert "python" not in result

    def test_case_normalization(self):
        from spacetime_memory.client._search_helpers import tokenize_query
        result = tokenize_query("PYTHON Language")
        assert result == ["python", "language"]


class TestMakeContextJson:
    """make_context_json edge cases."""

    def test_empty_rows(self):
        from spacetime_memory.client._search_helpers import make_context_json
        result = make_context_json([])
        assert json.loads(result) == []

    def test_rows_with_content(self):
        from spacetime_memory.client._search_helpers import make_context_json
        rows = [
            {"memory_content": "Python is great", "content": "", "snippet": "", "entity_type": "memory"},
            {"content": "Another result", "memory_content": "", "snippet": "", "entity_type": "note"},
        ]
        result = make_context_json(rows)
        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_max_chars_truncation(self):
        from spacetime_memory.client._search_helpers import make_context_json
        rows = [
            {"memory_content": "A" * 3000},
            {"memory_content": "B" * 3000},
        ]
        result = make_context_json(rows, max_chars=500)
        assert len(result) == 503  # 500 + "..."
        assert result.endswith("...")

    def test_custom_include_fields(self):
        from spacetime_memory.client._search_helpers import make_context_json
        rows = [
            {"id": "1", "memory_content": "hello", "custom_field": "world"},
        ]
        result = make_context_json(rows, include_fields=("custom_field",))
        parsed = json.loads(result)
        assert "custom_field" in parsed[0]
        assert "memory_content" not in parsed[0]
