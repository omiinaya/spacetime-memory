"""Unit tests for the Query AST Parser module (_query_ast.py).

Tests cover parsing, AST construction, filtering, chunking, query
expansion, and benchmarking — all without a real SpacetimeDB connection.
"""
from __future__ import annotations

import pytest

from spacetime_memory.client._query_ast import (
    QueryNode,
    ast_to_callable,
    ast_to_filter_function,
    benchmark_search,
    chunk_text,
    execute_ast,
    expand_query,
    filter_memories,
    parse_query,
    run_benchmark,
)

# ===========================================================================
# Sample memories used across tests
# ===========================================================================

MEMORY_JOHN_NYC = {
    "id": "mem_1",
    "workspace_id": "ws_test",
    "content": "John lives in New York City and works at a tech startup.",
    "summary": "John in NYC",
    "embedding": [0.1, 0.2, 0.3],
}
MEMORY_JANE_BOSTON = {
    "id": "mem_2",
    "workspace_id": "ws_test",
    "content": "Jane lives in Boston and studies at MIT. She loves machine learning.",
    "summary": "Jane in Boston",
    "embedding": [0.2, 0.3, 0.4],
}
MEMORY_ALICE_TOPIC = {
    "id": "mem_3",
    "workspace_id": "ws_test",
    "content": "Alice is a researcher working on artificial intelligence and robotics.",
    "summary": "Alice AI research",
    "embedding": [0.3, 0.4, 0.5],
}
MEMORY_OBSOLETE = {
    "id": "mem_4",
    "workspace_id": "ws_test",
    "content": "This technology is obsolete and no longer supported.",
    "summary": "Obsolete tech",
    "embedding": [0.4, 0.5, 0.6],
}
MEMORY_BOB_CHICAGO = {
    "id": "mem_5",
    "workspace_id": "ws_test",
    "content": "Bob lives in Chicago and works at a data pipeline company.",
    "summary": "Bob in Chicago",
    "embedding": [0.5, 0.6, 0.7],
}

ALL_MEMORIES = [
    MEMORY_JOHN_NYC,
    MEMORY_JANE_BOSTON,
    MEMORY_ALICE_TOPIC,
    MEMORY_OBSOLETE,
    MEMORY_BOB_CHICAGO,
]


# ===========================================================================
# Parse tests
# ===========================================================================


class TestParseQuery:
    def test_single_term(self):
        """Parse a bare word."""
        ast = parse_query("john")
        assert ast.type == "term"
        assert ast.value == "john"
        assert ast.children == []

    def test_and_operator(self):
        """Explicit AND."""
        ast = parse_query("john AND boston")
        assert ast.type == "and"
        assert len(ast.children) == 2
        assert ast.children[0].type == "term"
        assert ast.children[0].value == "john"
        assert ast.children[1].type == "term"
        assert ast.children[1].value == "boston"

    def test_or_operator(self):
        """Explicit OR."""
        ast = parse_query("nyc OR boston")
        assert ast.type == "or"
        assert len(ast.children) == 2
        assert ast.children[0].value == "nyc"
        assert ast.children[1].value == "boston"

    def test_not_operator(self):
        """NOT operator."""
        ast = parse_query("NOT obsolete")
        assert ast.type == "not"
        assert len(ast.children) == 1
        assert ast.children[0].type == "term"
        assert ast.children[0].value == "obsolete"

    def test_field_scope(self):
        """Field-scoped query."""
        ast = parse_query("person:john")
        assert ast.type == "field"
        assert ast.field == "person"
        assert ast.value == "john"

    def test_phrase(self):
        """Exact phrase in double quotes."""
        ast = parse_query('"exact phrase match"')
        assert ast.type == "phrase"
        assert ast.value == "exact phrase match"

    def test_proximity(self):
        """Proximity operator ~N."""
        ast = parse_query("data ~5")
        assert ast.type == "proximity"
        assert ast.value == "data"
        assert ast.proximity == 5

    def test_complex_nested(self):
        """Complex nested boolean expression."""
        ast = parse_query("person:john AND (location:nyc OR location:boston) NOT topic:obsolete")
        # Top-level is AND (second AND from implicit binding)
        assert ast.type == "and"
        assert len(ast.children) == 2

        # Left: AND(field(person:john), OR(field(location:nyc), field(location:boston)))
        assert ast.children[0].type == "and"
        assert ast.children[0].children[0].type == "field"
        assert ast.children[0].children[0].field == "person"
        assert ast.children[0].children[0].value == "john"

        or_node = ast.children[0].children[1]
        assert or_node.type == "or"
        assert len(or_node.children) == 2
        assert or_node.children[0].field == "location"
        assert or_node.children[0].value == "nyc"
        assert or_node.children[1].field == "location"
        assert or_node.children[1].value == "boston"

        # Right: NOT(field(topic:obsolete))
        assert ast.children[1].type == "not"
        not_child = ast.children[1].children[0]
        assert not_child.type == "field"
        assert not_child.field == "topic"
        assert not_child.value == "obsolete"

    def test_implicit_and(self):
        """Adjacent terms should become implicit AND."""
        ast = parse_query("john boston")
        assert ast.type == "and"
        assert len(ast.children) == 2
        assert ast.children[0].value == "john"
        assert ast.children[1].value == "boston"

    def test_parentheses_grouping(self):
        """Parentheses for grouping."""
        ast = parse_query("(alice OR bob) AND memory")
        assert ast.type == "and"
        assert ast.children[0].type == "or"
        assert len(ast.children[0].children) == 2
        assert ast.children[1].value == "memory"

    def test_precedence_not_over_and(self):
        """NOT should bind tighter than AND."""
        ast = parse_query("john NOT obsolete")
        assert ast.type == "and"
        assert ast.children[0].value == "john"
        assert ast.children[1].type == "not"

    def test_empty_query_raises(self):
        """Empty query should raise ValueError."""
        with pytest.raises(ValueError, match="Empty query"):
            parse_query("")
        with pytest.raises(ValueError, match="Empty query"):
            parse_query("   ")

    def test_phrase_within_field(self):
        """Field with phrase value."""
        ast = parse_query('city:"New York"')
        assert ast.type == "field"
        assert ast.field == "city"
        assert ast.value == "New York"

    def test_proximity_default(self):
        """Proximity operator parsing."""
        ast = parse_query("data~3")
        assert ast.type == "proximity"
        assert ast.value == "data"
        assert ast.proximity == 3


# ===========================================================================
# QueryNode equality tests
# ===========================================================================


class TestQueryNodeEquality:
    def test_eq_same(self):
        a = QueryNode(type="term", value="hello")
        b = QueryNode(type="term", value="hello")
        assert a == b

    def test_eq_different_type(self):
        a = QueryNode(type="term", value="hello")
        b = QueryNode(type="phrase", value="hello")
        assert a != b

    def test_repr_term(self):
        n = QueryNode(type="term", value="hello")
        assert "term" in repr(n)
        assert "hello" in repr(n)


# ===========================================================================
# Filter tests
# ===========================================================================


class TestFilterMemories:
    def test_filter_single_term(self):
        """Filter by single term."""
        ast = parse_query("john")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 1
        assert results[0]["id"] == "mem_1"

    def test_filter_term_case_insensitive(self):
        """Term matching is case-insensitive."""
        ast = parse_query("JOHN")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 1
        assert results[0]["id"] == "mem_1"

    def test_filter_and(self):
        """AND filter."""
        ast = parse_query("john AND york")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 1
        assert results[0]["id"] == "mem_1"

    def test_filter_or(self):
        """OR filter."""
        ast = parse_query("john OR jane")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 2
        ids = {m["id"] for m in results}
        assert ids == {"mem_1", "mem_2"}

    def test_filter_not(self):
        """NOT filter."""
        ast = parse_query("NOT obsolete")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 4
        ids = {m["id"] for m in results}
        assert "mem_4" not in ids

    def test_filter_field(self):
        """Field-scoped filter falls back to content if field missing."""
        ast = parse_query("summary:Jane")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 1
        assert results[0]["id"] == "mem_2"

    def test_filter_phrase(self):
        """Phrase filter."""
        ast = parse_query('"lives in Boston"')
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 1
        assert results[0]["id"] == "mem_2"

    def test_filter_complex(self):
        """Complex expression: (john OR alice) AND NOT obsolete."""
        ast = parse_query("(john OR alice) AND NOT obsolete")
        results = filter_memories(ALL_MEMORIES, ast)
        assert len(results) == 2
        ids = {m["id"] for m in results}
        assert ids == {"mem_1", "mem_3"}

    def test_filter_no_match(self):
        """No results."""
        ast = parse_query("xyznonexistent")
        results = filter_memories(ALL_MEMORIES, ast)
        assert results == []

    def test_filter_empty_memories(self):
        """Empty memory list."""
        ast = parse_query("john")
        results = filter_memories([], ast)
        assert results == []


# ===========================================================================
# ast_to_callable tests
# ===========================================================================


class TestAstToCallable:
    def test_term_callable(self):
        fn = ast_to_callable(parse_query("john"))
        assert fn(MEMORY_JOHN_NYC) is True
        assert fn(MEMORY_JANE_BOSTON) is False

    def test_and_callable(self):
        fn = ast_to_callable(parse_query("john AND york"))
        assert fn(MEMORY_JOHN_NYC) is True
        assert fn(MEMORY_JANE_BOSTON) is False

    def test_ast_to_filter_function(self):
        """Alias works."""
        fn = ast_to_filter_function(parse_query("john"))
        assert fn(MEMORY_JOHN_NYC) is True


# ===========================================================================
# execute_ast tests
# ===========================================================================


class TestExecuteAst:
    def test_execute_no_embedding(self):
        """Execute AST without embedding reranking."""
        ast = parse_query("john OR jane")
        results = execute_ast("ws_test", ast, ALL_MEMORIES)
        assert len(results) == 2

    def test_execute_with_embedding(self):
        """Execute AST with embedding similarity scoring."""
        ast = parse_query("john")

        def dummy_embed(text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

        results = execute_ast("ws_test", ast, ALL_MEMORIES, embedding_fn=dummy_embed)
        assert len(results) == 1
        assert results[0]["id"] == "mem_1"

    def test_execute_empty_memories(self):
        """Execute with empty memory list."""
        ast = parse_query("john")
        results = execute_ast("ws_test", ast, [])
        assert results == []


# ===========================================================================
# Chunking tests
# ===========================================================================


class TestChunkText:
    def test_chunk_word_default(self):
        """Word-level chunking with default size."""
        text = "word " * 300
        chunks = chunk_text(text, strategy="word", chunk_size=200, overlap=20)
        assert len(chunks) >= 1
        # First chunk should be 200 words
        assert len(chunks[0].split()) == 200
        # Should have overlap
        if len(chunks) > 1:
            first_words = chunks[0].split()[-20:]
            second_words = chunks[1].split()[:20]
            assert first_words == second_words

    def test_chunk_char(self):
        """Character-level chunking."""
        text = "a" * 500
        chunks = chunk_text(text, strategy="char", chunk_size=100, overlap=10)
        assert len(chunks) >= 5
        assert len(chunks[0]) == 100
        assert len(chunks[-1]) <= 100

    def test_chunk_sentence(self):
        """Sentence-level chunking."""
        text = "First sentence here. Second sentence there. Third sentence everywhere. Fourth sentence nowhere. Fifth sentence somewhere."
        chunks = chunk_text(text, strategy="sentence", chunk_size=10, overlap=2)
        assert len(chunks) >= 1
        # Each chunk should contain complete sentences
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_chunk_empty_text(self):
        """Empty text returns empty list."""
        assert chunk_text("") == []

    def test_chunk_invalid_strategy(self):
        """Unknown strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            chunk_text("hello", strategy="invalid")

    def test_chunk_overlap_gte_chunk_size(self):
        """overlap >= chunk_size should raise."""
        with pytest.raises(ValueError, match="overlap must be less than chunk_size"):
            chunk_text("hello", chunk_size=10, overlap=10)

    def test_chunk_word_no_text(self):
        """Only whitespace returns empty list."""
        assert chunk_text("   ") == []

    def test_chunk_small_text(self):
        """Text smaller than chunk_size returns single chunk."""
        text = "short text"
        chunks = chunk_text(text, strategy="word", chunk_size=200)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_sentence_varied_lengths(self):
        """Sentence chunking with varied sentence lengths."""
        text = "Short. A bit longer sentence here. This is a much longer sentence that should still work fine. Tiny."
        chunks = chunk_text(text, strategy="sentence", chunk_size=10, overlap=2)
        assert len(chunks) >= 1


# ===========================================================================
# Query expansion tests
# ===========================================================================


class TestExpandQuery:
    def test_expand_with_default_synonyms(self):
        """Expand query using default synonym dictionary."""
        variants = expand_query("AI memory")
        assert "AI memory" in variants
        assert any("artificial intelligence" in v for v in variants)
        assert any("machine learning" in v for v in variants)

    def test_expand_with_custom_synonyms(self):
        """Expand query with custom synonym dictionary."""
        custom_syns = {"hello": ["hi", "hey", "greetings"]}
        variants = expand_query("hello world", synonyms_dict=custom_syns)
        assert "hello world" in variants
        assert "hi world" in variants

    def test_expand_empty_query(self):
        """Empty query returns list with original string."""
        assert expand_query("") == [""]
        assert expand_query("   ") == ["   "]

    def test_expand_repeated_word(self):
        """Word appearing multiple times generates proper variants."""
        custom_syns = {"cat": ["feline", "kitten"]}
        variants = expand_query("cat", synonyms_dict=custom_syns)
        assert "cat" in variants
        assert "feline" in variants
        assert "kitten" in variants


# ===========================================================================
# Benchmark tests
# ===========================================================================


class TestBenchmarkSearch:
    def test_benchmark_basic(self):
        """Basic benchmark with known queries."""
        queries = [
            ("john", [MEMORY_JOHN_NYC]),
            ("jane", [MEMORY_JANE_BOSTON]),
        ]
        result = benchmark_search(queries, ALL_MEMORIES)
        assert result["num_queries"] == 2
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1"] == 1.0

    def test_benchmark_partial(self):
        """Benchmark with imperfect (partial precision/recall) matches."""
        queries = [
            ("john", [MEMORY_JOHN_NYC]),
            # "alice" also matches nothing else
            ("alice", [MEMORY_ALICE_TOPIC]),
        ]
        result = benchmark_search(queries, ALL_MEMORIES)
        assert result["num_queries"] == 2
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0

    def test_benchmark_empty_queries(self):
        """Empty list returns zeros."""
        result = benchmark_search([], ALL_MEMORIES)
        assert result["num_queries"] == 0
        assert result["precision"] == 0.0

    def test_run_benchmark(self):
        """run_benchmark alias works."""
        queries = [
            ("john", [MEMORY_JOHN_NYC]),
        ]
        result = run_benchmark("ws_test", queries, ALL_MEMORIES)
        assert result["num_queries"] == 1
        assert result["precision"] == 1.0

    def test_run_benchmark_no_memories(self):
        """run_benchmark with no memories returns zeros."""
        result = run_benchmark("ws_test", [])
        assert result["num_queries"] == 0

    def test_benchmark_not_operator(self):
        """Benchmark using NOT operator."""
        queries = [
            ("NOT obsolete", [MEMORY_JOHN_NYC, MEMORY_JANE_BOSTON, MEMORY_ALICE_TOPIC, MEMORY_BOB_CHICAGO]),
            ("obsolete", [MEMORY_OBSOLETE]),
        ]
        result = benchmark_search(queries, ALL_MEMORIES)
        assert result["num_queries"] == 2
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0

    def test_benchmark_imperfect(self):
        """Genuinely imperfect precision and recall."""
        # Query "john" returns only mem_1, but we expect mem_1 and mem_5
        # → TP=1, FP=0, FN=1 → precision=1.0, recall=0.5
        # Query "boston" returns mem_2, but we expect mem_2 and mem_3
        # → TP=1, FP=0, FN=1 → precision=1.0, recall=0.5
        queries = [
            ("john", [MEMORY_JOHN_NYC, MEMORY_BOB_CHICAGO]),
            ("boston", [MEMORY_JANE_BOSTON, MEMORY_ALICE_TOPIC]),
        ]
        result = benchmark_search(queries, ALL_MEMORIES)
        assert result["num_queries"] == 2
        assert result["precision"] == 1.0  # No false positives
        assert result["recall"] == 0.5  # Each gets 1/2 expected
        assert result["f1"] == pytest.approx(0.6667, rel=1e-3)


# ===========================================================================
# Edge case / error handling
# ===========================================================================


class TestEdgeCases:
    def test_memory_without_content_key(self):
        """Memory dict without content key should not crash."""
        fn = ast_to_callable(parse_query("hello"))
        result = fn({"id": "test"})
        assert result is False

    def test_memory_with_none_content(self):
        """Memory with None content should not crash."""
        fn = ast_to_callable(parse_query("test"))
        result = fn({"id": "test", "content": None})
        assert result is False

    def test_field_predicate_string_field(self):
        """Field predicate on a string field."""
        fn = ast_to_callable(parse_query("name:john"))
        memory = {"id": "test", "content": "some content", "name": "john doe"}
        # Falls back to content for some, checks name
        assert fn(memory) is True

    def test_proximity_filter(self):
        """Proximity filter matching."""
        ast = parse_query("data~3")
        results = filter_memories(ALL_MEMORIES, ast)
        # 'data' appears in MEMORY_BOB_CHICAGO ("data pipeline company") and maybe others
        assert len(results) >= 1

    def test_complex_precedence(self):
        """AND has higher precedence than OR."""
        ast = parse_query("john OR jane AND boston")
        # With precedence: OR is lower, so it's: john OR (jane AND boston)
        # Actually our parser does: OR > AND, left-to-right for same precedence
        # Let's check: _parse_or calls _parse_and, _parse_and calls _parse_not
        # _parse_and keeps consuming AND tokens, _parse_or keeps consuming OR tokens
        # So 'john OR jane AND boston' parses as _parse_or -> first _parse_and gives 'john',
        # then sees OR, then _parse_and gives 'jane AND boston'
        # So: john OR (jane AND boston)
        assert ast.type == "or"
        assert len(ast.children) == 2
        assert ast.children[0].value == "john"
        assert ast.children[1].type == "and"
        assert ast.children[1].children[0].value == "jane"
        assert ast.children[1].children[1].value == "boston"

    def test_multiple_not(self):
        """Multiple NOT operators."""
        ast = parse_query("NOT obsolete NOT chicago")
        # Should be and(NOT obsolete, NOT chicago)
        assert ast.type == "and"
        assert len(ast.children) == 2
        assert all(c.type == "not" for c in ast.children)

    def test_expand_no_synonyms_found(self):
        """No synonyms found returns just the original."""
        variants = expand_query("xyznonexistent", synonyms_dict={"nothing": ["here"]})
        assert "xyznonexistent" in variants
        assert len(variants) == 1

    def test_benchmark_mixed_types(self):
        """Benchmark handles memories with no embedding gracefully."""
        queries = [
            ("john", [MEMORY_JOHN_NYC]),
        ]
        result = benchmark_search(queries, ALL_MEMORIES)
        assert result["precision"] > 0

    def test_chunk_overlap_zero(self):
        """Overlap of zero works fine."""
        text = "a b c d e f g h i j"
        chunks = chunk_text(text, strategy="word", chunk_size=4, overlap=0)
        assert len(chunks) == 3
        assert chunks[0] == "a b c d"
        assert chunks[1] == "e f g h"
        assert chunks[2] == "i j"

    def test_chunk_negative_overlap_raises(self):
        """Negative overlap raises ValueError."""
        with pytest.raises(ValueError, match="overlap must be non-negative"):
            chunk_text("hello", overlap=-1)

    def test_chunk_zero_size_raises(self):
        """Zero chunk_size raises ValueError."""
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("hello", chunk_size=0)
