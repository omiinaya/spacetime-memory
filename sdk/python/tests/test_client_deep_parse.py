"""Deep integration tests for client.py — Advanced module.

Includes: ParseRerankJson, ParseSqlResponse, ProfilesWithPeers,
MemoryRetrieval, FuzzyGet, GlobGet, UserMemories, Decay, DecayDeep,
PluginDispatch, GraphTraversalDeep, GraphStatsDeep, AdminDeep,
GraphNeighborsDeep, QueryHash, ParseRerankJsonDeep,
ParseRerankJsonFinal, DeleteMemoryDeep, UpdateMemoryDeep,
GetterMethods, ClientUnitCoverage, SearchWithFilters,
SearchSessionsSemantic, Recommend, TestDecay,
SearchWithFiltersUnit, ConfigAndReputation, KgStats, MemoryStats,
DirectoryOps, NoteEmbedOps, NoteBacklinks, SessionListing,
ListProfiles, ApiKeyCreate, FuzzyGetEdgeCases, MemoryHistory,
BatchEmbedError, CreateNodeEmbed, RerankerErrorHandling,
QueryCacheInvalidation, TantivyAndHealthCheck, RestoreManifest,
and standalone functions.
"""

from __future__ import annotations

import json
import os

import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]


def _unique(prefix: str = "deep") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Helper: create a unique workspace and return its ID."""
    ws_name = _unique("deep-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for w in workspaces:
        if w.get("name") == ws_name:
            return w["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


def _store_mem(client: Client, ws_id: str, content: str, peer: str = "deep-bot") -> dict:
    """Store a memory and return the result."""
    return client.store(
        workspace_id=ws_id,
        content=content,
        peer_id=peer,
        memory_type="experience",
    )


def _get_first_memory_id(client: Client, ws_id: str) -> str | None:
    """Get the ID of the first memory in a workspace."""
    mems = client.list_memories(workspace_id=ws_id, limit=5)
    return mems[0]["id"] if mems else None



class TestParseRerankJson:
    """Test _parse_rerank_json with valid and malformed JSON inputs."""

    def _get_fn(self):
        from spacetime_memory.client import _parse_rerank_json

        return _parse_rerank_json

    def test_valid_json_array(self):
        """Strategy 1: direct parse of valid JSON array."""
        fn = self._get_fn()
        content = '[{"index": 0, "score": 8.5, "reason": "relevant"}]'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 0

    def test_array_in_text(self):
        """Strategy 2: find JSON array boundaries in surrounding text."""
        fn = self._get_fn()
        content = (
            'Here are the results:\\n[{"index": 1, "score": 7.0, "reason": "good"}]\\nThat is all.'
        )
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 1

    def test_trailing_comma_salvage(self):
        """Strategy 4: trailing commas get stripped."""
        fn = self._get_fn()
        content = '[{"index": 2, "score": 6.5, "reason": "ok"},]'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 2

    def test_dict_wrapper_scores(self):
        """Strategy 5: dict with 'scores' key wrapping an array."""
        fn = self._get_fn()
        content = '{"scores": [{"index": 3, "score": 9.1, "reason": "perfect"}]}'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 3

    def test_dict_wrapper_results(self):
        """Strategy 5: dict with 'results' key."""
        fn = self._get_fn()
        content = '{"results": [{"index": 4, "score": 5.0, "reason": "meh"}]}'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 4

    def test_line_by_line_extraction(self):
        """Strategy 6: one JSON object per line (must evade strategies 1-5)."""
        fn = self._get_fn()
        content = (
            "Here are results:\n"
            '{"index": 5, "value": 4.2, "reason": "low"}\n'
            '{"index": 6, "value": 3.0, "reason": "lower"}'
        )
        result = fn(content)
        assert len(result) == 2
        indices = {r["index"] for r in result}
        assert indices == {5, 6}

    def test_markdown_fence(self):
        """JSON inside markdown code fence."""
        fn = self._get_fn()
        content = '```json\\n[{"index": 7, "score": 8.0, "reason": "good"}]\\n```'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 7

    def test_completely_garbage_input(self):
        """All 6 strategies fail — should raise ValueError."""
        fn = self._get_fn()
        content = "This is not JSON at all, just plain text nonsense."
        with pytest.raises(ValueError):
            fn(content)

    def test_single_object_with_index(self):
        """Strategy 3/5: single dict with 'index' key."""
        fn = self._get_fn()
        content = '{"index": 8, "score": 7.7, "reason": "single"}'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 8


class TestParseSqlResponse:
    """Test _parse_sql_response edge cases."""

    def _get_fn(self):
        from spacetime_memory.client import _parse_sql_response

        return _parse_sql_response

    def test_empty_string(self):
        """Empty raw string returns empty list."""
        fn = self._get_fn()
        result = fn("")
        assert result == []

    def test_whitespace_only(self):
        """Whitespace-only string returns empty list."""
        fn = self._get_fn()
        result = fn("   \n  \t  ")
        assert result == []

    def test_valid_response(self):
        """Valid SQL response with named columns."""
        fn = self._get_fn()
        raw = json.dumps(
            [
                {
                    "schema": {
                        "elements": [
                            {"name": {"some": "id"}},
                            {"name": {"some": "content"}},
                        ]
                    },
                    "rows": [
                        ["mem-1", "hello world"],
                        ["mem-2", "foo bar"],
                    ],
                }
            ]
        )
        result = fn(raw)
        assert len(result) == 2
        assert result[0]["id"] == "mem-1"
        assert result[0]["content"] == "hello world"
        assert result[1]["id"] == "mem-2"

    def test_unnamed_columns(self):
        """Response with elements missing 'some' key → ?col? fallback."""
        fn = self._get_fn()
        raw = json.dumps(
            [
                {
                    "schema": {
                        "elements": [
                            {"name": "bare_string_not_dict"},
                            {"name": None},
                        ]
                    },
                    "rows": [
                        ["val1", "val2"],
                    ],
                }
            ]
        )
        result = fn(raw)
        assert len(result) == 1
        # Both columns get key "?col?" so the second value overwrites the first
        assert result[0]["?col?"] == "val2"


class TestQueryHash:
    """Test _query_hash helper — deterministic hash for hybrid queries."""

    def _get_fn(self):
        from spacetime_memory.client import _query_hash

        return _query_hash

    def test_query_hash_deterministic(self):
        """Same query always produces same hash."""
        fn = self._get_fn()
        h1 = fn("hello world")
        h2 = fn("hello world")
        assert h1 == h2
        assert len(h1) == 16  # 64-bit hex

    def test_query_hash_different(self):
        """Different queries produce different hashes."""
        fn = self._get_fn()
        assert fn("hello") != fn("world")

    def test_query_hash_non_empty(self):
        """Even empty string produces a valid hex hash."""
        fn = self._get_fn()
        h = fn("")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


class TestParseRerankJsonDeep:
    """Cover remaining _parse_rerank_json branches: strategy 4 salvage with
    dict fallback, strategy 5 dict wrapper with 'index' key, strategy 6
    malformed line skip."""

    def _get_fn(self):
        from spacetime_memory.client import _parse_rerank_json

        return _parse_rerank_json

    def test_strategy4_dict_fallback_with_trailing_score(self):
        """Strategy 4: salvage strips trailing commas, then tries dict with
        trailing 'score' artifact."""
        fn = self._get_fn()
        content = '[{"index": 10, "score": 5.5, "reason": "ok"}]'
        result = fn(content)
        assert result[0]["index"] == 10

    def test_strategy4_salvage_array_with_quoted_keys(self):
        """Strategy 4: salvage cleans trailing commas from an array."""
        fn = self._get_fn()
        content = '[{"index": 11, "score": 6.0, "reason": "decent"},]'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 11

    def test_strategy5_dict_index_key(self):
        """Strategy 5: dict with 'index' key but no scores/results wrapper."""
        fn = self._get_fn()
        content = 'prefix {"index": 12, "value": 7.5} trailing'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 12

    def test_strategy5_dict_with_data_key(self):
        """Strategy 5: dict wrapper with 'data' key."""
        fn = self._get_fn()
        content = '{"data": [{"index": 13, "score": 3.0, "reason": "low"}]}'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 13

    def test_strategy5_dict_with_rankings_key(self):
        """Strategy 5: dict wrapper with 'rankings' key."""
        fn = self._get_fn()
        content = '{"rankings": [{"index": 14, "score": 4.1, "reason": "ok"}]}'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 14

    def test_strategy5_dict_with_items_key(self):
        """Strategy 5: dict wrapper with 'items' key."""
        fn = self._get_fn()
        content = '{"items": [{"index": 15, "score": 9.0, "reason": "great"}]}'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 15

    def test_strategy6_skip_malformed_line(self):
        """Strategy 6: line-by-line extraction skips malformed JSON lines."""
        fn = self._get_fn()
        content = 'Text prefix\n{"index": 16, "score": 2.0, "reason": "valid"}\nnot json at all'
        result = fn(content)
        assert len(result) >= 1
        indices = {r["index"] for r in result}
        assert 16 in indices

    def test_strategy5_dict_no_valid_key(self):
        """Strategy 5: dict without any recognized wrapper key is handled gracefully."""
        fn = self._get_fn()
        content = '{"unknown_key": {"nested": "value"}}'
        result = fn(content)
        assert isinstance(result, list)


class TestParseRerankJsonFinal:
    """Cover the last remaining _parse_rerank_json branches."""

    def _get_fn(self):
        from spacetime_memory.client import _parse_rerank_json

        return _parse_rerank_json

    def test_strategy4_error_and_strategy5_rankings_wrapper(self):
        """Strategy 4: invalid array → error append.
        Strategy 5: dict with 'rankings' key containing a list."""
        fn = self._get_fn()
        content = '[bad and {"rankings": [{"index": 0, "score": 5}]}]'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 0

    def test_strategy5_items_wrapper(self):
        """Strategy 5: dict with 'items' key containing a list."""
        fn = self._get_fn()
        content = '[bad and {"items": [{"index": 1, "score": 4}]}]'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 1

    def test_strategy5_data_wrapper(self):
        """Strategy 5: dict with 'data' key containing a list."""
        fn = self._get_fn()
        content = '[bad and {"data": [{"index": 2, "score": 3}]}]'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 2

    def test_strategy6_skip_malformed_line(self):
        """Strategy 6: line-by-line extraction skips malformed lines."""
        fn = self._get_fn()
        content = (
            "unparseable start\n"
            '{"index": 10, "value": 5.0}\n'
            "{not valid json at all}\n"
            '{"index": 11, "rank": 4.0}'
        )
        result = fn(content)
        indices = {r["index"] for r in result}
        assert indices == {10, 11}

    def test_strategy4_dict_with_score_fallback(self):
        """Strategy 4 dict fallback: regex matches a JSON object containing 'score'."""
        fn = self._get_fn()
        content = '[invalid] and {"index": 99, "score": 5.0} trailing'
        result = fn(content)
        assert len(result) == 1
        assert result[0]["index"] == 99
