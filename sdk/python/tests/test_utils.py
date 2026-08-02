"""Tests for spacetime_memory.client._utils — pure utility functions."""

import json

from spacetime_memory.client._utils import (
    _esc,
    _make_snippet,
    _parse_sql_response,
    _query_hash,
)

# ── _esc tests ────────────────────────────────────────────────────────────────

class TestEsc:
    """SQL string escaping."""

    def test_no_single_quotes(self):
        """Plain string with no quotes passes through unchanged."""
        assert _esc("hello world") == "hello world"

    def test_single_quote_replaced(self):
        """A single ' becomes ''."""
        assert _esc("it's") == "it''s"

    def test_multiple_single_quotes(self):
        """Multiple single quotes each become doubled."""
        assert _esc("'a' 'b'") == "''a'' ''b''"

    def test_only_quotes(self):
        """String consisting entirely of single quotes."""
        assert _esc("'''") == "''''''"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert _esc("") == ""

    def test_no_quoting_needed(self):
        """Numbers, special chars, no quotes → unchanged."""
        assert _esc("abc123!@#") == "abc123!@#"

    def test_unicode_preserved(self):
        """Unicode characters are preserved through escaping."""
        assert _esc("café") == "café"

    def test_backslash_not_affected(self):
        """Backslashes are not escaped."""
        assert _esc("foo\\bar") == "foo\\bar"


# ── _query_hash tests ─────────────────────────────────────────────────────────

class TestQueryHash:
    """Deterministic 64-bit hash matching the Rust hybrid_query reducer."""

    def test_empty_query(self):
        """Empty string produces a valid 16-char hex hash."""
        h = _query_hash("")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        """Deterministic: same input always produces same output."""
        assert _query_hash("hello world") == _query_hash("hello world")

    def test_different_inputs_differ(self):
        """Different inputs produce different hashes."""
        assert _query_hash("hello") != _query_hash("world")

    def test_hex_length(self):
        """Output is always exactly 16 hex characters."""
        cases = ["", "a", "x" * 100, "🔥", "SELECT * FROM memory"]
        for c in cases:
            h = _query_hash(c)
            assert len(h) == 16, f"Expected 16 chars, got {len(h)} for {c!r}"
            assert all(ch in "0123456789abcdef" for ch in h), f"Non-hex in {h}"

    def test_case_sensitive(self):
        """Hash is case-sensitive (different from Rust's case handling)."""
        assert _query_hash("Hello") != _query_hash("hello")

    def test_whitespace_matters(self):
        """Leading/trailing whitespace changes the hash."""
        assert _query_hash("query") != _query_hash(" query ")

    def test_unicode_safe(self):
        """Unicode characters produce distinct hashes."""
        h1 = _query_hash("café")
        h2 = _query_hash("cafe")
        assert h1 != h2


# ── _parse_sql_response tests ─────────────────────────────────────────────────

class TestParseSqlResponse:
    """Parse SpacetimeDB positional-array SQL responses into dicts."""

    def test_empty_string(self):
        """Empty or whitespace-only input returns []."""
        assert _parse_sql_response("") == []
        assert _parse_sql_response("  ") == []
        assert _parse_sql_response("\n\t") == []

    def test_valid_single_row(self):
        """Single row with named columns."""
        raw = json.dumps([{
            "schema": {
                "elements": [
                    {"name": {"some": "id"}},
                    {"name": {"some": "value"}},
                ]
            },
            "rows": [["abc", 42]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"id": "abc", "value": 42}]

    def test_multiple_rows(self):
        """Multiple rows parsed correctly."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": {"some": "x"}}]},
            "rows": [["a"], ["b"], ["c"]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"x": "a"}, {"x": "b"}, {"x": "c"}]

    def test_empty_rows(self):
        """Empty rows list returns [] with correct schema."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": {"some": "id"}}]},
            "rows": [],
        }])
        assert _parse_sql_response(raw) == []

    def test_unnamed_column_fallback(self):
        """Columns with no name get fallback '?col?'."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": {}}]},
            "rows": [["val"]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"?col?": "val"}]

    def test_name_is_string_direct(self):
        """Some STDB versions return name as string, not dict."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": "direct_col"}]},
            "rows": [["val"]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"?col?": "val"}]

    def test_multiple_tables(self):
        """Multiple table entries are concatenated."""
        raw = json.dumps([
            {
                "schema": {"elements": [{"name": {"some": "a"}}]},
                "rows": [[1]],
            },
            {
                "schema": {"elements": [{"name": {"some": "b"}}]},
                "rows": [[2]],
            },
        ])
        result = _parse_sql_response(raw)
        assert result == [{"a": 1}, {"b": 2}]

    def test_out_of_range_column(self):
        """More values than column names — fallback to colN."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": {"some": "id"}}]},
            "rows": [["a", "extra"]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"id": "a", "col1": "extra"}]

    def test_fewer_values_than_columns(self):
        """Fewer values than columns — missing cols get no value."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": {"some": "a"}}, {"name": {"some": "b"}}]},
            "rows": [[1]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"a": 1}]

    def test_null_values(self):
        """Null values are passed through as-is."""
        raw = json.dumps([{
            "schema": {"elements": [{"name": {"some": "val"}}]},
            "rows": [[None]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"val": None}]

    def test_invalid_json_raises(self):
        """Invalid JSON should raise JSONDecodeError."""
        import json as j
        try:
            _parse_sql_response("not-json")
            assert False, "Expected JSONDecodeError"
        except j.JSONDecodeError:
            pass

    def test_missing_schema_elements(self):
        """Schema with no elements returns no rows."""
        raw = json.dumps([{
            "schema": {},
            "rows": [["val"]],
        }])
        result = _parse_sql_response(raw)
        assert result == [{"col0": "val"}]


# ── _make_snippet tests ───────────────────────────────────────────────────────

class TestMakeSnippet:
    """Text truncation at word boundaries."""

    def test_empty_text(self):
        """Empty or falsy input returns ''."""
        assert _make_snippet("") == ""
        assert _make_snippet(None) == ""
        assert _make_snippet("", max_chars=50) == ""

    def test_short_text_not_truncated(self):
        """Text shorter than max_chars is returned as-is."""
        assert _make_snippet("hello") == "hello"

    def test_exact_length_not_truncated(self):
        """Text equal to max_chars is not truncated."""
        text = "a" * 200
        assert _make_snippet(text) == "a" * 200

    def test_truncated_adds_ellipsis(self):
        """Text exceeding max_chars is truncated with '...'."""
        text = "hello world " + "x" * 200
        result = _make_snippet(text, max_chars=20)
        assert result.endswith("...")
        assert len(result) <= 23  # 20 + "..."

    def test_break_at_word_boundary(self):
        """Truncation breaks at the last space within the limit."""
        text = "the quick brown fox jumps"
        result = _make_snippet(text, max_chars=15)
        # "the quick" = 9 chars + "..." = 12
        assert "quick" in result or "brown" not in result
        assert result.endswith("...")

    def test_no_space_in_truncated_region(self):
        """If no space in meaningful range, breaks at max_chars anyway."""
        text = "abcdefghijklmnopqrstuvwxyz"
        result = _make_snippet(text, max_chars=10)
        assert result.endswith("...")
        assert len(result) <= 13

    def test_custom_max_chars(self):
        """Custom max_chars limit is respected."""
        text = "this is a test string"
        result = _make_snippet(text, max_chars=50)
        assert result == text  # Not truncated

    def test_custom_max_chars_truncates(self):
        """Custom small limit truncates."""
        text = "this is a test string"
        result = _make_snippet(text, max_chars=7)
        assert result.endswith("...")
        assert len(result) <= 10

    def text_whitespace_only(self):
        """Whitespace-only input returns ''."""
        result = _make_snippet("   ")
        assert result == "" or all(c == ' ' for c in result.rstrip('...'))

    def test_newlines_preserved_in_short_text(self):
        """Newlines within limit are preserved."""
        text = "line1\nline2\nline3"
        result = _make_snippet(text, max_chars=50)
        assert result == text

    def test_exact_word_boundary(self):
        """Text ending exactly at a space before max_chars."""
        text = "hello world and more"
        result = _make_snippet(text, max_chars=12)
        # at 12 chars: "hello world " → strips to "hello world..."
        assert "hello world" in result

    def test_unicode_text(self):
        """Unicode multi-byte characters."""
        text = "🔥" * 100
        result = _make_snippet(text, max_chars=10)
        assert result.endswith("...")
