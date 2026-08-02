"""Tests for structured output schemas — ``search(return_schema=...)``.

Covers:
- ``_apply_return_schema`` with ``None`` (passthrough)
- ``_apply_return_schema`` with ``"llm"`` (compact LLMSearchResult)
- ``_apply_return_schema`` with a custom TypedDict
- ``_resolve_field``: exact match, alias fallback, case-insensitive match
- Edge cases: empty results, missing fields, partial fields
"""

from __future__ import annotations

from typing import Any, TypedDict

import pytest

from spacetime_memory.client._schemas import (
    _apply_return_schema,
    _resolve_field,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def raw_memory_rows() -> list[dict[str, Any]]:
    return [
        {
            "entity_id": "00000001-0001-0001-0001-000000000001",
            "memory_content": "Reinforcement learning from human feedback (RLHF) is a technique...",
            "fused_score": 0.87,
            "entity_type": "memory",
            "created_at": 1712345678.0,
        },
        {
            "entity_id": "00000001-0001-0001-0001-000000000002",
            "memory_content": "SpacetimeDB is a relational database with temporal features...",
            "fused_score": 0.72,
            "entity_type": "memory",
            "created_at": 1712345680.0,
        },
    ]


@pytest.fixture
def raw_note_rows() -> list[dict[str, Any]]:
    return [
        {
            "note_id": "note-0001",
            "content": "Attention is all you need introduced transformer architecture.",
            "score": 0.91,
            "doc_type": "note",
            "created_at": 1712345600.0,
        },
    ]


@pytest.fixture
def raw_node_rows() -> list[dict[str, Any]]:
    return [
        {
            "node_id": "node-0001",
            "summary": "A type of neural network architecture without recurrence.",
            "relevance": 0.84,
            "node_type": "concept",
            "timestamp_": 1712345500.0,
        },
    ]


@pytest.fixture
def mixed_rows(
    raw_memory_rows: list[dict[str, Any]],
    raw_note_rows: list[dict[str, Any]],
    raw_node_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return raw_memory_rows + raw_note_rows + raw_node_rows


# ---------------------------------------------------------------------------
# _resolve_field
# ---------------------------------------------------------------------------


class TestResolveField:
    def test_exact_match(self) -> None:
        row = {"id": "abc", "score": 0.5}
        assert _resolve_field(row, "id") == "abc"

    def test_alias_fallback(self) -> None:
        row = {"entity_id": "abc", "fused_score": 0.87}
        assert _resolve_field(row, "id") == "abc"
        assert _resolve_field(row, "relevance") == 0.87

    def test_case_insensitive_fallback(self) -> None:
        row = {"TITLE": "My Document"}
        assert _resolve_field(row, "title") == "My Document"

    def test_none_when_missing(self) -> None:
        row = {"name": "bob"}
        assert _resolve_field(row, "id") is None

    def test_skip_none_values(self) -> None:
        row = {"entity_id": None, "fused_score": None}
        assert _resolve_field(row, "id") is None
        assert _resolve_field(row, "relevance") is None


# ---------------------------------------------------------------------------
# _apply_return_schema — passthrough
# ---------------------------------------------------------------------------


class TestApplyReturnSchemaPassthrough:
    def test_none_returns_unchanged(self, mixed_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(mixed_rows, None)
        assert result is mixed_rows  # same identity when None

    def test_empty_list(self) -> None:
        result = _apply_return_schema([], "llm")
        assert result == []


# ---------------------------------------------------------------------------
# _apply_return_schema — "llm" mode
# ---------------------------------------------------------------------------


class TestApplyReturnSchemaLlm:
    def test_returns_correct_fields(self, raw_memory_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(raw_memory_rows, "llm")
        assert len(result) == 2
        for row in result:
            assert set(row.keys()) == {"id", "content", "relevance", "type", "snippet", "created_at"}

    def test_field_mapping(self, raw_memory_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(raw_memory_rows, "llm")
        r0 = result[0]
        assert r0["id"] == "00000001-0001-0001-0001-000000000001"
        assert r0["content"] == "Reinforcement learning from human feedback (RLHF) is a technique..."
        assert r0["relevance"] == 0.87
        assert r0["type"] == "memory"
        assert r0["created_at"] == 1712345678.0

    def test_note_mapping(self, raw_note_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(raw_note_rows, "llm")
        r0 = result[0]
        assert r0["id"] == "note-0001"
        assert r0["type"] == "note"

    def test_node_mapping(self, raw_node_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(raw_node_rows, "llm")
        r0 = result[0]
        assert r0["id"] == "node-0001"
        assert r0["type"] == "concept"

    def test_relevance_coerced_to_float(self) -> None:
        rows = [{"entity_id": "x", "memory_content": "test", "fused_score": "0.5", "entity_type": "memory"}]
        result = _apply_return_schema(rows, "llm")
        assert isinstance(result[0]["relevance"], float)
        assert result[0]["relevance"] == 0.5

    def test_relevance_defaults_to_zero(self) -> None:
        rows = [{"entity_id": "x", "memory_content": "test", "entity_type": "memory"}]
        result = _apply_return_schema(rows, "llm")
        assert result[0]["relevance"] == 0.0


# ---------------------------------------------------------------------------
# _apply_return_schema — custom TypedDict
# ---------------------------------------------------------------------------


class TestApplyReturnSchemaCustom:
    def test_custom_typed_dict(self, mixed_rows: list[dict[str, Any]]) -> None:
        class MyResult(TypedDict):
            id: str
            title: str

        result = _apply_return_schema(mixed_rows, MyResult)
        for row in result:
            assert set(row.keys()) == {"id", "title"}
            assert row["id"] is not None or "title" not in row

    def test_partial_fields(self) -> None:
        class Brief(TypedDict):
            content: str
            score: float

        rows = [{"memory_content": "hello world", "score": 0.9}]
        result = _apply_return_schema(rows, Brief)
        assert result == [{"content": "hello world", "score": 0.9}]

    def test_missing_fields_default_to_none(self) -> None:
        class OptionalResult(TypedDict):
            id: str
            missing_field: str  # not present in source

        rows = [{"entity_id": "abc"}]
        result = _apply_return_schema(rows, OptionalResult)
        assert result[0]["id"] == "abc"
        assert result[0]["missing_field"] is None


# ---------------------------------------------------------------------------
# _apply_return_schema — edge cases / resilience
# ---------------------------------------------------------------------------


class TestApplyReturnSchemaEdgeCases:
    def test_unknown_schema_type_returns_as_is(self, raw_memory_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(raw_memory_rows, "unknown_string")
        assert result is raw_memory_rows

    def test_snippet_generation(self) -> None:
        """LLM schema should include a snippet field."""
        long_text = "A" * 500
        rows = [{"entity_id": "x", "memory_content": long_text, "content": long_text, "fused_score": 0.5, "entity_type": "memory"}]
        result = _apply_return_schema(rows, "llm")
        assert isinstance(result[0]["snippet"], str)
        assert len(result[0]["snippet"]) <= len(long_text)

    def test_mixed_types_preserved(self, mixed_rows: list[dict[str, Any]]) -> None:
        result = _apply_return_schema(mixed_rows, "llm")
        types = {r["type"] for r in result}
        assert types == {"memory", "note", "concept"}


# ---------------------------------------------------------------------------
# Integration: search(return_schema="llm") signature
# ---------------------------------------------------------------------------


class TestSearchReturnSchemaSignature:
    def test_search_accepts_return_schema_keyword(self) -> None:
        """Verify the search() method accepts ``return_schema`` as a keyword argument.
        This test checks the signature exists — doesn't run the actual search.
        """
        import inspect

        from spacetime_memory.client._memories_search import SearchMixin

        sig = inspect.signature(SearchMixin.search)
        assert "return_schema" in sig.parameters
        param = sig.parameters["return_schema"]
        assert param.default is None
        # Accept: str, type, or None
        annotation_str = str(param.annotation)
        assert "str" in annotation_str or "type" in annotation_str or "None" in annotation_str
