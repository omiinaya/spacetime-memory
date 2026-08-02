"""Tests for client/_session_search.py — SessionSearchMixin.

All tests use mocked client — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestSessionSearchMixin:
    """SessionSearchMixin methods."""

    @pytest.fixture
    def mixin(self):
        from spacetime_memory.client._session_search import SessionSearchMixin

        m = SessionSearchMixin()
        m._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        m._call = MagicMock()
        m._query = MagicMock(return_value=[])
        return m

    # ── Existing tests (preserved) ──────────────────────────────

    def test_search_sessions_semantic_empty_query(self, mixin):
        """Empty query returns empty list."""
        mixin._embed = MagicMock(return_value=[])
        result = mixin.search_sessions_semantic(query="")
        assert result == []

    def test_search_sessions_semantic_no_embed(self, mixin):
        """When embedding returns falsy, return empty list."""
        mixin._embed = MagicMock(return_value=None)
        result = mixin.search_sessions_semantic(query="test")
        assert result == []

    def test_search_sessions_semantic_empty_results(self, mixin):
        """No matching sessions returns empty list."""
        mixin._query = MagicMock(return_value=[])
        result = mixin.search_sessions_semantic(query="test", limit=10)
        assert result == []

    def test_search_sessions_semantic_with_results(self, mixin):
        """Returns sorted results when sessions match."""
        mixin._query = MagicMock(return_value=[
            {"query_hash": "sessions:10", "score": 0.9, "content": "match 1"},
            {"query_hash": "sessions:10", "score": 0.5, "content": "match 2"},
        ])
        result = mixin.search_sessions_semantic(query="test", limit=10)
        assert len(result) == 2
        assert result[0]["content"] == "match 1"
        assert result[1]["content"] == "match 2"

    def test_search_sessions_semantic_truncates_to_limit(self, mixin):
        """Results are truncated to the specified limit."""
        mixin._query = MagicMock(return_value=[
            {"query_hash": "sessions:3", "score": s, "content": f"match {s}"}
            for s in [0.9, 0.7, 0.5, 0.3, 0.1]
        ])
        result = mixin.search_sessions_semantic(query="test", limit=3)
        assert len(result) == 3

    def test_search_sessions_semantic_calls_embed(self, mixin):
        """Verify _embed is called with the query."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        mixin._query = MagicMock(return_value=[])
        mixin.search_sessions_semantic(query="hello world", limit=5)
        mixin._embed.assert_called_once_with("hello world")

    def test_search_sessions_semantic_calls_reducer(self, mixin):
        """Verify _call is invoked with the correct reducer name and args."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[])
        mixin.search_sessions_semantic(query="test", limit=5)
        mixin._call.assert_called_once()
        args = mixin._call.call_args[0]
        assert args[0] == "search_sessions_semantic"
        assert args[1][1] == 5

    def test_search_sessions_semantic_uses_query_hash(self, mixin):
        """Verify the query hash filter is based on session prefix."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[])
        mixin.search_sessions_semantic(query="test", limit=20)
        filter_dict = mixin._query.call_args[1].get("filter_dict", {})
        assert "sessions:20" in filter_dict["query_hash"]

    def test_search_sessions_semantic_with_return_schema(self, mixin):
        """When return_schema is provided, _apply_return_schema is called."""

        rows = [
            {"query_hash": "sessions:5", "score": 0.8, "content": "hello"},
        ]
        mixin._query = MagicMock(return_value=rows)

        with patch(
            "spacetime_memory.client._session_search._apply_return_schema"
        ) as mock_schema:
            mock_schema.return_value = [{"content": "hello"}]
            result = mixin.search_sessions_semantic(
                query="test", limit=5, return_schema="llm"
            )
            mock_schema.assert_called_once()
            assert result == [{"content": "hello"}]

    # ── NEW: Error-case tests ───────────────────────────────────

    def test_search_sessions_semantic_call_raises_runtime_error(self, mixin):
        """A server error from _call propagates as RuntimeError."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._call = MagicMock(side_effect=RuntimeError("STDB reducer error"))
        with pytest.raises(RuntimeError, match="STDB reducer error"):
            mixin.search_sessions_semantic(query="test", limit=5)

    def test_search_sessions_semantic_call_raises_connection_error(self, mixin):
        """A network-level error from _call propagates."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._call = MagicMock(side_effect=ConnectionError("connection refused"))
        with pytest.raises(ConnectionError, match="connection refused"):
            mixin.search_sessions_semantic(query="test", limit=5)

    def test_search_sessions_semantic_query_raises_runtime_error(self, mixin):
        """A server error from _query propagates as RuntimeError."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._call = MagicMock()
        mixin._query = MagicMock(side_effect=RuntimeError("query failed"))
        with pytest.raises(RuntimeError, match="query failed"):
            mixin.search_sessions_semantic(query="test", limit=5)

    def test_search_sessions_semantic_embed_raises_error(self, mixin):
        """If _embed itself raises an exception, it propagates."""
        mixin._embed = MagicMock(side_effect=RuntimeError("embedder offline"))
        with pytest.raises(RuntimeError, match="embedder offline"):
            mixin.search_sessions_semantic(query="test", limit=5)

    # ── NEW: Edge-case queries ──────────────────────────────────

    def test_search_sessions_semantic_very_long_query(self, mixin):
        """Very long query strings are handled without error."""
        long_query = "a" * 10_000
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[])
        result = mixin.search_sessions_semantic(query=long_query, limit=5)
        assert result == []
        mixin._embed.assert_called_once_with(long_query)

    def test_search_sessions_semantic_unicode_query(self, mixin):
        """Unicode / multi-byte query strings are handled."""
        unicode_query = "Hello 世界 café 🚀 emoji —测试"
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[])
        result = mixin.search_sessions_semantic(query=unicode_query, limit=5)
        assert result == []
        mixin._embed.assert_called_once_with(unicode_query)

    def test_search_sessions_semantic_query_with_special_chars(self, mixin):
        """Query with special characters that could break JSON/embedding."""
        special_query = "test 'quote' \"double\" \n newline \t tab \\ backslash"
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[])
        result = mixin.search_sessions_semantic(query=special_query, limit=5)
        assert result == []
        mixin._embed.assert_called_once_with(special_query)

    # ── NEW: Limit edge cases ───────────────────────────────────

    def test_search_sessions_semantic_zero_limit(self, mixin):
        """Zero limit should still call the reducer but filter to 0 results."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[
            {"query_hash": "sessions:0", "score": 0.9, "content": "match"},
        ])
        result = mixin.search_sessions_semantic(query="test", limit=0)
        # _query uses f"sessions:{limit}" for the hash, and then [:limit] slices to 0
        assert result == []

    def test_search_sessions_semantic_negative_limit(self, mixin):
        """Negative limit should not crash — slicing with negative might behave oddly."""
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=[
            {"query_hash": "sessions:-1", "score": 0.9, "content": "match"},
        ])
        result = mixin.search_sessions_semantic(query="test", limit=-1)
        # Python list[:-1] excludes the last element, so with 1 result it would be empty
        assert result == []

    def test_search_sessions_semantic_large_limit(self, mixin):
        """Large limit is passed through correctly."""
        large_limit = 10_000
        mock_rows = [
            {"query_hash": f"sessions:{large_limit}", "score": 0.9, "content": "a"},
            {"query_hash": f"sessions:{large_limit}", "score": 0.8, "content": "b"},
        ]
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=mock_rows)
        result = mixin.search_sessions_semantic(query="test", limit=large_limit)
        assert len(result) == 2
        # Verify the limit was passed to _call
        mixin._call.assert_called_once()
        assert mixin._call.call_args[0][1][1] == large_limit

    # ── NEW: Result sorting and filtering ───────────────────────

    def test_search_sessions_semantic_results_sorted_descending(self, mixin):
        """Results are sorted by score descending regardless of input order."""
        unsorted = [
            {"query_hash": "sessions:10", "score": 0.3, "content": "low"},
            {"query_hash": "sessions:10", "score": 0.9, "content": "high"},
            {"query_hash": "sessions:10", "score": 0.5, "content": "mid"},
        ]
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=unsorted)
        result = mixin.search_sessions_semantic(query="test", limit=10)
        assert len(result) == 3
        assert result[0]["content"] == "high"
        assert result[1]["content"] == "mid"
        assert result[2]["content"] == "low"

    def test_search_sessions_semantic_missing_score_field(self, mixin):
        """Rows without a score field are handled (sorted with default 0)."""
        rows = [
            {"query_hash": "sessions:10", "content": "no score"},
            {"query_hash": "sessions:10", "score": 0.8, "content": "has score"},
        ]
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=rows)
        result = mixin.search_sessions_semantic(query="test", limit=10)
        assert len(result) == 2
        # Row with score goes first (0.8 > 0.0)
        assert result[0]["content"] == "has score"

    def test_search_sessions_semantic_extra_fields_preserved(self, mixin):
        """Extra fields in returned rows are preserved (not stripped)."""
        rows = [
            {
                "query_hash": "sessions:5",
                "score": 0.9,
                "content": "test",
                "workspace_id": "ws-1",
                "session_id": "sess-1",
                "extra_field": "should persist",
            },
        ]
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=rows)
        result = mixin.search_sessions_semantic(query="test", limit=5)
        assert result[0]["workspace_id"] == "ws-1"
        assert result[0]["session_id"] == "sess-1"
        assert result[0]["extra_field"] == "should persist"

    # ── NEW: return_schema edge cases ───────────────────────────

    def test_search_sessions_semantic_return_schema_none(self, mixin):
        """return_schema=None returns raw results unchanged."""
        rows = [
            {"query_hash": "sessions:5", "score": 0.8, "content": "hello"},
        ]
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=rows)
        result = mixin.search_sessions_semantic(query="test", limit=5, return_schema=None)
        assert result == rows

    def test_search_sessions_semantic_return_schema_custom_typeddict(self, mixin):
        """Custom TypedDict return_schema filters fields correctly."""
        from typing import TypedDict

        class MySchema(TypedDict):
            content: str
            score: float

        rows = [
            {"query_hash": "sessions:5", "score": 0.8, "content": "hello", "extra": "x"},
        ]
        mixin._embed = MagicMock(return_value=[0.1, 0.2])
        mixin._query = MagicMock(return_value=rows)
        result = mixin.search_sessions_semantic(
            query="test", limit=5, return_schema=MySchema
        )
        assert len(result) == 1
        assert list(result[0].keys()) == ["content", "score"]
        assert result[0]["content"] == "hello"
        assert result[0]["score"] == 0.8
        assert "extra" not in result[0]

    # ── NEW: Embed edge cases ───────────────────────────────────

    def test_search_sessions_semantic_embed_returns_empty_list(self, mixin):
        """Empty list from _embed means no embedding — empty result."""
        mixin._embed = MagicMock(return_value=[])
        mixin._call = MagicMock()
        mixin._query = MagicMock(return_value=[{"content": "should not appear"}])
        result = mixin.search_sessions_semantic(query="test")
        assert result == []
        mixin._call.assert_not_called()
        mixin._query.assert_not_called()
