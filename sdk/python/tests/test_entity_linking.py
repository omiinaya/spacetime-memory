"""Tests for the entity_linking module."""
from __future__ import annotations

from spacetime_memory.entity_linking import (
    extract_entities_heuristic,
    find_entities_in_query,
)


class TestExtractEntitiesHeuristic:
    """Heuristic entity extraction fallback."""

    def test_extracts_quoted_book_title(self):
        entities = extract_entities_heuristic('She read "The Great Gatsby"')
        names = [e["name"] for e in entities]
        assert "The Great Gatsby" in names

    def test_extracts_hashtags(self):
        entities = extract_entities_heuristic("Loving #camping and #painting")
        names = [e["name"] for e in entities]
        assert "camping" in names
        assert "painting" in names

    def test_empty_text_returns_empty(self):
        assert extract_entities_heuristic("") == []
        assert extract_entities_heuristic("   ") == []

    def test_no_entities_returns_empty(self):
        assert extract_entities_heuristic("the cat sat on the mat") == []

    def test_multiple_quotes(self):
        entities = extract_entities_heuristic(
            'Read "Book A" and "Book B"'
        )
        names = [e["name"] for e in entities]
        assert "Book A" in names
        assert "Book B" in names

    def test_deduplicates_entities(self):
        entities = extract_entities_heuristic(
            '"The Great Gatsby" is great. Also "The Great Gatsby" is a classic.'
        )
        names = [e["name"] for e in entities]
        assert len([n for n in names if n == "The Great Gatsby"]) == 1


class FakeClient:
    """Minimal mock client for testing find_entities_in_query."""

    def __init__(self, kg_nodes: list[dict]):
        self._kg_nodes = kg_nodes

    def _query(self, table: str, workspace_id: str = "", filter_dict=None, columns=None):
        if table == "kg_node":
            return self._kg_nodes
        return []


class TestFindEntitiesInQuery:
    """Test KG entity matching against search queries."""

    def make_client(self, nodes: list[tuple[str, str, str, str]]) -> FakeClient:
        """Create a fake client with KG nodes.

        Each tuple: (id, label, node_type, summary)
        """
        return FakeClient([
            {"id": nid, "label": label, "node_type": ntype, "summary": summary}
            for nid, label, ntype, summary in nodes
        ])

    def test_exact_label_match(self):
        client = self.make_client([
            ("n1", "Melanie", "entity", "A person"),
            ("n2", "Caroline", "entity", "A person"),
        ])
        result = find_entities_in_query(client, "ws1", "What is Melanie's pet?")
        assert len(result) == 1
        assert result[0]["label"] == "Melanie"

    def test_word_overlap(self):
        client = self.make_client([
            ("n1", "Pottery Workshop", "entity", "An event"),
        ])
        result = find_entities_in_query(client, "ws1", "pottery class")
        assert len(result) == 1
        assert result[0]["label"] == "Pottery Workshop"

    def test_substring_in_query_word(self):
        client = self.make_client([
            ("n1", "Whiskers", "entity", "A cat"),
        ])
        result = find_entities_in_query(client, "ws1", "Whiskers cat")
        assert len(result) == 1
        assert result[0]["label"] == "Whiskers"

    def test_no_match_returns_empty(self):
        client = self.make_client([
            ("n1", "Pottery", "entity", ""),
        ])
        result = find_entities_in_query(client, "ws1", "Python programming")
        assert len(result) == 0

    def test_multiple_matches(self):
        client = self.make_client([
            ("n1", "Melanie", "entity", ""),
            ("n2", "Whiskers", "entity", ""),
            ("n3", "Camping", "activity", ""),
        ])
        result = find_entities_in_query(client, "ws1", "Melanie and Whiskers go camping")
        assert len(result) == 3
        labels = {r["label"] for r in result}
        assert labels == {"Melanie", "Whiskers", "Camping"}

    def test_empty_query_returns_empty(self):
        client = self.make_client([("n1", "Melanie", "entity", "")])
        assert find_entities_in_query(client, "ws1", "") == []
        assert find_entities_in_query(client, "ws1", "   ") == []

    def test_no_kg_nodes_returns_empty(self):
        client = self.make_client([])
        assert find_entities_in_query(client, "ws1", "Melanie") == []

    def test_deduplicates_by_id(self):
        """"Same node shouldn't appear twice even if it matches multiple ways."""
        client = self.make_client([
            ("n1", "Melanie", "entity", "Melanie is a person"),
        ])
        result = find_entities_in_query(client, "ws1", "Melanie person")
        assert len(result) == 1

    def test_short_words_ignored(self):
        client = self.make_client([
            ("n1", "Artificial Intelligence", "concept", ""),
        ])
        # Short words in query (< 3 chars) are ignored for overlap matching
        result = find_entities_in_query(client, "ws1", "AI and Go")
        assert len(result) == 0

    def test_entity_label_includes_query_word(self):
        """Entity label 'C++' should match when query includes 'C++'."""
        client = self.make_client([
            ("n1", "C++", "concept", "Programming language"),
        ])
        result = find_entities_in_query(client, "ws1", "C++ programming")
        assert len(result) == 1

    def test_possible_strip_before_case_insensitive(self):
        client = self.make_client([
            ("n1", "  Melanie  ", "entity", ""),
        ])
        result = find_entities_in_query(client, "ws1", "Melanie")
        # Label should be stripped internally
        assert len(result) == 1


class TestExtractEntitiesLlm:
    """Basic sanity checks for the LLM entity extraction.

    These tests verify the module-level constants and error handling,
    not the actual LLM call (which requires API keys).
    """

    def test_prompt_has_text_placeholder(self):
        from spacetime_memory.entity_linking import DEFAULT_EXTRACT_PROMPT
        assert "{text}" in DEFAULT_EXTRACT_PROMPT

    def test_prompt_asks_for_json(self):
        from spacetime_memory.entity_linking import DEFAULT_EXTRACT_PROMPT
        assert "JSON" in DEFAULT_EXTRACT_PROMPT

class TestInjectEntityContext:
    """Test the inject_entity_context function."""

    def test_extract_entities_llm_no_key_returns_none(self):
        import os

        from spacetime_memory.entity_linking import extract_entities_llm
        old_key = os.environ.pop("LLM_RERANK_API_KEY", None)
        try:
            result = extract_entities_llm("test text")
            assert result is None
        finally:
            if old_key:
                os.environ["LLM_RERANK_API_KEY"] = old_key

    def make_mock_client(self, kg_nodes: list[dict], edges: list[dict], memories: list[dict]):
        """Create a mock client for testing inject_entity_context."""
        class MockClient:
            def _query(self, table, workspace_id="", filter_dict=None, columns=None):
                if table == "kg_node":
                    return kg_nodes
                if table == "kg_edge":
                    return edges
                if table == "memory":
                    return memories
                return []
        return MockClient()

    def test_inject_new_memories(self):
        """Should inject memories connected to entities found in query."""
        from spacetime_memory.entity_linking import inject_entity_context

        client = self.make_mock_client(
            kg_nodes=[{"id": "n1", "label": "Melanie", "node_type": "entity", "summary": ""}],
            edges=[],
            memories=[],
        )
        results = [{"entity_id": "existing1", "content": "Hello", "fused_score": 0.5}]
        output = inject_entity_context(client, "ws1", "What is Melanie's pet?", results)
        # Should return at least the original result
        assert len(output) >= 1
        assert output[0]["entity_id"] == "existing1"

    def test_empty_query_no_change(self):
        from spacetime_memory.entity_linking import inject_entity_context
        client = self.make_mock_client([], [], [])
        results = [{"entity_id": "m1", "content": "test", "fused_score": 0.5}]
        output = inject_entity_context(client, "ws1", "", results)
        assert output == results

    def test_no_entities_found_no_change(self):
        from spacetime_memory.entity_linking import inject_entity_context
        client = self.make_mock_client([], [], [])
        results = [{"entity_id": "m1", "content": "test", "fused_score": 0.5}]
        output = inject_entity_context(client, "ws1", "random query with no entities", results)
        assert output == results


# ── _query_or_sql fallback (ACL-tolerant public-table reads) ─────────


class _AclRejectingClient:
    """Fake client whose reducer path rejects (non-member identity), but
    whose public tables are readable via raw SQL — mirrors the benchmark
    evaluation identity against a private workspace."""

    def __init__(self, kg_rows: list[dict], memory_rows: list[dict]):
        self._kg_rows = kg_rows
        self._memory_rows = memory_rows
        self._sql_calls: list[str] = []

    def _query(self, table, workspace_id="", filter_dict=None, columns=None):
        raise RuntimeError("Access denied: peer has no permission for workspace")

    def _sql(self, query: str):
        self._sql_calls.append(query)
        if "FROM kg_node" in query:
            return self._kg_rows
        if "FROM kg_edge" in query:
            return []
        if "FROM memory" in query:
            return self._memory_rows
        return []


class TestQueryOrSqlFallback:
    """The reducer path enforces workspace ACL; public tables must be
    readable via SQL fallback so non-member identities (e.g. benchmark
    evaluators) still get entity-linked retrieval."""

    def test_find_entities_falls_back_to_sql(self):
        from spacetime_memory.entity_linking import find_entities_in_query
        client = _AclRejectingClient(
            kg_rows=[{"id": "n1", "label": "Melanie", "node_type": "entity", "summary": "person"}],
            memory_rows=[],
        )
        result = find_entities_in_query(client, "ws1", "What is Melanie's pet?")
        assert len(result) == 1
        assert result[0]["label"] == "Melanie"
        assert any("FROM kg_node" in q for q in client._sql_calls)

    def test_get_memories_for_entities_sql_fallback(self):
        from spacetime_memory.entity_linking import get_memories_for_entities
        client = _AclRejectingClient(
            kg_rows=[],
            memory_rows=[{"id": "m1", "content": "Melanie has a cat", "summary": "pet", "created_at": 1}],
        )
        result = get_memories_for_entities(client, "ws1", ["n1"])
        # kg_edge returns [] via SQL fallback, so no memories are linked —
        # verifies the path is exercised without crashing.
        assert result == []
        assert any("FROM kg_edge" in q for q in client._sql_calls)

    def test_inject_entity_context_sql_fallback(self):
        from spacetime_memory.entity_linking import inject_entity_context
        client = _AclRejectingClient(
            kg_rows=[{"id": "n1", "label": "Melanie", "node_type": "entity", "summary": "person"}],
            memory_rows=[{"id": "m1", "content": "Melanie has a cat", "summary": "pet", "created_at": 1}],
        )
        results = [{"entity_id": "m0", "content": "base", "fused_score": 0.4}]
        output = inject_entity_context(client, "ws1", "What is Melanie's pet?", results)
        assert len(output) >= 1
        assert any("FROM kg_node" in q for q in client._sql_calls)
        assert any("FROM kg_edge" in q for q in client._sql_calls)

    def test_private_table_reducer_error_still_returns_empty(self):
        """If even the SQL fallback raises, callers degrade gracefully."""
        from spacetime_memory.entity_linking import find_entities_in_query

        class _FullyBlocked:
            def _query(self, *a, **k):
                raise RuntimeError("Access denied")

            def _sql(self, q):
                raise RuntimeError("no such table")

        assert find_entities_in_query(_FullyBlocked(), "ws1", "Melanie") == []
