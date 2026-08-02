"""Tests for fuzzy get + glob multi-get (QMD parity)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_client():
    """Client with mocked HTTP layer."""
    from spacetime_memory import Client

    c = Client.__new__(Client)
    c._http = MagicMock()
    c._http.get.return_value = MagicMock(status_code=200)
    c._http.post.return_value = MagicMock(status_code=200, json=list)
    c.database = "test"
    c._identity_token = "test-token"
    c._identity_established = True
    c._call = MagicMock(return_value={"status": "ok"})
    c._sql = MagicMock(return_value=[])
    c._query = MagicMock(return_value=[])
    c._embed = MagicMock(return_value=[0.1] * 384)
    c._circuit_open_until = 0.0
    c._consecutive_failures = 0
    c._circuit_open_until = 0.0
    c._consecutive_failures = 0
    c._circuit_breaker_threshold = 5
    c._circuit_breaker_reset_secs = 30.0
    c._binary_cache = {}
    c._query_cache = None
    c.max_retries = 3
    return c


class TestFuzzyGet:
    """Fuzzy get — typo-tolerant memory lookup by string similarity."""

    def test_exact_match(self, mock_client):
        """Exact content match returns ratio 1.0."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "oauth authentication flow"},
            {"id": "m2", "content": "pizza recipe"},
        ]
        result = mock_client.fuzzy_get("ws-1", "oauth authentication flow")
        assert result is not None
        assert result["id"] == "m1"

    def test_fuzzy_typo(self, mock_client):
        """Fuzzy match corrects minor typos."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "oauth authentication flow"},
            {"id": "m2", "content": "pizza recipe"},
        ]
        result = mock_client.fuzzy_get("ws-1", "oath authenticaton flow")
        assert result is not None
        assert result["id"] == "m1"  # closest match despite typos

    def test_no_match_below_threshold(self, mock_client):
        """Returns None when no memory meets similarity threshold."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "completely different topic"},
        ]
        result = mock_client.fuzzy_get("ws-1", "oauth authentication", threshold=0.6)
        assert result is None

    def test_empty_workspace(self, mock_client):
        """Empty workspace returns None."""
        mock_client._query.return_value = []
        result = mock_client.fuzzy_get("ws-1", "anything")
        assert result is None

    def test_custom_field(self, mock_client):
        """Fuzzy match against custom field (e.g. summary)."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "...", "summary": "auth module setup"},
            {"id": "m2", "content": "...", "summary": "pizza baking tips"},
        ]
        result = mock_client.fuzzy_get("ws-1", "auth module setup", field="summary")
        assert result is not None
        assert result["id"] == "m1"

    def test_threshold_one_exact_only(self, mock_client):
        """threshold=1.0 only matches exact content."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "exact match text"},
            {"id": "m2", "content": "different text"},
        ]
        result = mock_client.fuzzy_get("ws-1", "exact match text", threshold=1.0)
        assert result is not None
        assert result["id"] == "m1"

    def test_very_low_threshold(self, mock_client):
        """threshold=0.1 matches nearly everything."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "completely unrelated"},
        ]
        result = mock_client.fuzzy_get("ws-1", "anything at all", threshold=0.1)
        assert result is not None  # should match anything with low threshold

    def test_empty_query_string(self, mock_client):
        """Empty query returns None."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "something"},
        ]
        result = mock_client.fuzzy_get("ws-1", "")
        assert result is None

    def test_missing_field_custom_field(self, mock_client):
        """Custom field that doesn't exist in memory should not crash."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "content only"},
        ]
        result = mock_client.fuzzy_get("ws-1", "test", field="nonexistent_field")
        assert result is None


class TestGlobGet:
    """Glob multi-get — wildcard pattern matching on memory fields."""

    def test_id_prefix_glob(self, mock_client):
        """glob_get with 'auth-*' matches IDs starting with 'auth-'."""
        mock_client._query.return_value = [
            {"id": "auth-abc123", "content": "oauth flow"},
            {"id": "auth-def456", "content": "sso setup"},
            {"id": "pizza-001", "content": "recipe"},
        ]
        results = mock_client.glob_get("ws-1", "auth-*")
        assert len(results) == 2
        assert all(r["id"].startswith("auth-") for r in results)

    def test_content_glob(self, mock_client):
        """glob_get with '*auth*' on field='content' matches content."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "OAuth2 authentication flow"},
            {"id": "m2", "content": "Basic auth setup"},
            {"id": "m3", "content": "pizza recipe"},
        ]
        results = mock_client.glob_get("ws-1", "*auth*", field="content")
        assert len(results) == 2

    def test_no_match_returns_empty(self, mock_client):
        """No glob match returns empty list."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "pizza"},
        ]
        results = mock_client.glob_get("ws-1", "nonexistent*")
        assert results == []

    def test_question_mark_wildcard(self, mock_client):
        """? wildcard matches exactly one character."""
        mock_client._query.return_value = [
            {"id": "abc", "content": "three"},
            {"id": "ab", "content": "two"},
            {"id": "abcd", "content": "four"},
        ]
        results = mock_client.glob_get("ws-1", "ab?")
        assert len(results) == 1
        assert results[0]["id"] == "abc"

    def test_character_class(self, mock_client):
        """[...] character class glob."""
        mock_client._query.return_value = [
            {"id": "cat", "content": "meow"},
            {"id": "bat", "content": "screech"},
            {"id": "rat", "content": "squeak"},
        ]
        results = mock_client.glob_get("ws-1", "[cb]at")
        assert len(results) == 2

    def test_negated_character_class(self, mock_client):
        """[!...] negated character class."""
        mock_client._query.return_value = [
            {"id": "cat", "content": "meow"},
            {"id": "bat", "content": "screech"},
            {"id": "rat", "content": "squeak"},
        ]
        results = mock_client.glob_get("ws-1", "[!c]at")
        assert len(results) == 2
        assert all(r["id"] == "bat" or r["id"] == "rat" for r in results)

    def test_empty_glob_returns_empty(self, mock_client):
        """Empty glob pattern returns empty list."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "test"},
        ]
        results = mock_client.glob_get("ws-1", "")
        assert results == []

    def test_glob_empty_workspace(self, mock_client):
        """Empty workspace returns empty list."""
        mock_client._query.return_value = []
        results = mock_client.glob_get("ws-1", "test*")
        assert results == []

    def test_missing_custom_field_glob(self, mock_client):
        """Custom field that doesn't exist returns empty."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "has content"},
        ]
        results = mock_client.glob_get("ws-1", "nonexistent*", field="summary")
        assert results == []

    def test_glob_all_match_star(self, mock_client):
        """'*' pattern matches all items."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "first"},
            {"id": "m2", "content": "second"},
            {"id": "m3", "content": "third"},
        ]
        results = mock_client.glob_get("ws-1", "*")
        assert len(results) == 3

    def test_special_chars_in_query(self, mock_client):
        """Characters like brackets in the query shouldn't crash."""
        mock_client._query.return_value = [
            {"id": "m1", "content": "test [data] here"},
        ]
        # This tests that glob doesn't choke on literal brackets
        results = mock_client.glob_get("ws-1", "[d]*")
        # If glob fnmatch treats [d] as character class, it may match "test [data] here"
        # The real test is that it doesn't raise
        assert isinstance(results, list)
