"""Tests for spacetime_memory.client._schemas — schema resolution and transformation.

Tests ``_resolve_field`` for alias matching and ``_apply_return_schema``
for LLM schema and custom TypedDict transformations.
"""
from __future__ import annotations

from typing import TypedDict


class TestResolveField:
    """Field resolution from raw result dicts with exact match, alias, and
    case-insensitive fallback."""

    def test_exact_match(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"id": "abc-123", "content": "hello"}
        assert _resolve_field(row, "id") == "abc-123"
        assert _resolve_field(row, "content") == "hello"

    def test_alias_lookup(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"entity_id": "eid-1", "memory_content": "some content"}
        # 'id' aliases to entity_id
        assert _resolve_field(row, "id") == "eid-1"
        # 'content' aliases to memory_content
        assert _resolve_field(row, "content") == "some content"

    def test_alias_priority(self):
        from spacetime_memory.client._schemas import _resolve_field

        # First alias in the list should be preferred
        row = {"entity_id": "from-entity", "memory_id": "from-memory", "id": "direct-id"}
        assert _resolve_field(row, "id") == "direct-id"

        row2 = {"entity_id": "eid", "memory_id": "mid"}
        assert _resolve_field(row2, "id") == "eid"

    def test_case_insensitive_fallback(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"Id": "eid-ci", "Content": "val"}
        assert _resolve_field(row, "id") == "eid-ci"
        assert _resolve_field(row, "content") == "val"

    def test_none_value_skipped_direct(self):
        """A field that exists but is None is skipped in direct match."""
        from spacetime_memory.client._schemas import _resolve_field

        row = {"id": None, "entity_id": "real-id"}
        assert _resolve_field(row, "id") == "real-id"

    def test_none_value_skipped_alias(self):
        """An alias that exists but is None is skipped."""
        from spacetime_memory.client._schemas import _resolve_field

        row = {"entity_id": None, "memory_id": "real-mid"}
        assert _resolve_field(row, "id") == "real-mid"

    def test_empty_string_skipped(self):
        """Empty string alias values are skipped."""
        from spacetime_memory.client._schemas import _resolve_field

        row = {"entity_id": "", "memory_id": "real"}
        assert _resolve_field(row, "id") == "real"

    def test_no_match_returns_none(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"some_key": "val"}
        assert _resolve_field(row, "id") is None
        assert _resolve_field(row, "nonexistent") is None

    def test_empty_row(self):
        from spacetime_memory.client._schemas import _resolve_field

        assert _resolve_field({}, "id") is None

    def test_relevance_aliases(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"fused_score": 0.85}
        assert _resolve_field(row, "relevance") == 0.85

        row2 = {"relevance_score": 0.75}
        assert _resolve_field(row2, "relevance") == 0.75

        row3 = {"relevance": 0.65}
        assert _resolve_field(row3, "relevance") == 0.65

    def test_type_aliases(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"entity_type": "memory"}
        assert _resolve_field(row, "type") == "memory"

        row2 = {"memory_type": "experience"}
        assert _resolve_field(row2, "type") == "experience"

    def test_timestamp_aliases(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"created_at": 1712345678.0}
        assert _resolve_field(row, "created_at") == 1712345678.0
        assert _resolve_field(row, "timestamp") == 1712345678.0

        row2 = {"updated_at": 1712349999.0}
        assert _resolve_field(row2, "updated_at") == 1712349999.0
        assert _resolve_field(row2, "created_at") == 1712349999.0

    def test_workspace_aliases(self):
        from spacetime_memory.client._schemas import _resolve_field

        row = {"workspace_id": "ws-1"}
        assert _resolve_field(row, "workspace") == "ws-1"
        assert _resolve_field(row, "workspace_id") == "ws-1"


class TestApplyReturnSchema:
    """Transformation of raw search results into structured schemas."""

    def test_none_schema_returns_unchanged(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [{"id": "1", "content": "hello"}]
        assert _apply_return_schema(results, None) is results

    def test_empty_results_returns_empty(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        assert _apply_return_schema([], "llm") == []
        assert _apply_return_schema([], None) == []

    def test_llm_schema_returns_compact_fields(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [
            {
                "entity_id": "abc-123",
                "memory_content": "RLHF is a technique...",
                "fused_score": 0.87,
                "entity_type": "memory",
                "created_at": 1712345678.0,
                "snippet": "RLHF is a...",
            }
        ]
        transformed = _apply_return_schema(results, "llm")
        assert len(transformed) == 1
        item = transformed[0]
        assert item["id"] == "abc-123"
        assert item["content"] == "RLHF is a technique..."
        assert item["relevance"] == 0.87
        assert item["type"] == "memory"
        assert item["created_at"] == 1712345678.0
        assert item["snippet"] == "RLHF is a..."

    def test_llm_schema_all_fields_present(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [{"id": "1", "content": "x", "score": 0.5, "type": "note", "created_at": 100.0}]
        transformed = _apply_return_schema(results, "llm")
        item = transformed[0]
        expected_keys = {"id", "content", "relevance", "type", "snippet", "created_at"}
        assert set(item.keys()) == expected_keys

    def test_llm_schema_relevance_coercion_to_float(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [{"entity_id": "1", "memory_content": "x", "score": "0.5", "entity_type": "memory", "created_at": 100}]
        transformed = _apply_return_schema(results, "llm")
        assert isinstance(transformed[0]["relevance"], float)
        assert transformed[0]["relevance"] == 0.5

    def test_llm_schema_missing_relevance_defaults_zero(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [{"entity_id": "1", "memory_content": "x", "entity_type": "note", "created_at": 100}]
        transformed = _apply_return_schema(results, "llm")
        assert transformed[0]["relevance"] == 0.0

    def test_custom_typeddict_schema(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        class CustomResult(TypedDict):
            id: str
            title: str

        results = [
            {"entity_id": "e1", "name": "My Title", "content": "ignored"},
        ]
        transformed = _apply_return_schema(results, CustomResult)
        assert len(transformed) == 1
        assert transformed[0]["id"] == "e1"
        assert transformed[0]["title"] == "My Title"
        # 'content' not in schema so not included
        assert "content" not in transformed[0]

    def test_custom_typeddict_with_missing_fields(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        class CustomResult(TypedDict):
            id: str
            missing_field: str

        results = [{"entity_id": "e1"}]
        transformed = _apply_return_schema(results, CustomResult)
        assert transformed[0]["id"] == "e1"
        assert transformed[0]["missing_field"] is None

    def test_unknown_schema_returns_unchanged(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [{"id": "1"}]
        # String that's not "llm" and not a TypedDict → returns unchanged
        assert _apply_return_schema(results, "unknown") is results

    def test_non_typeddict_type(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [{"id": "1"}]
        # A regular class without __annotations__ → returns unchanged
        assert _apply_return_schema(results, int) is results

    def test_multiple_results(self):
        from spacetime_memory.client._schemas import _apply_return_schema

        results = [
            {"entity_id": "1", "memory_content": "a", "score": 0.9, "entity_type": "memory", "created_at": 1.0},
            {"entity_id": "2", "memory_content": "b", "score": 0.5, "entity_type": "note", "created_at": 2.0},
        ]
        transformed = _apply_return_schema(results, "llm")
        assert len(transformed) == 2
        assert transformed[0]["id"] == "1"
        assert transformed[1]["id"] == "2"
