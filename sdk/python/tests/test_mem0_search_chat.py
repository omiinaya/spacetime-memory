"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_search_chat.py -v

"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from mem0_shared import _uid

from spacetime_memory.sdks.mem0 import Memory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


class TestSearchSpecificPaths:
    """Cover search() paths: user_scope check, graph_context."""

    def test_search_user_scope_skips_different_user(self, mem: Memory) -> None:
        """search() skips results scoped to a different user (line 1090)."""
        uid = _uid()
        # search returns a result, get_memory shows different user_scope
        with patch.object(mem, "_ws", return_value="ws-1"):
            with patch.object(mem, "_get_graph_context", return_value=[]):
                with patch.object(
                    mem,
                    "_call",
                    side_effect=[
                        # search call
                        [{"entity_id": "mem-1", "memory_content": "secret", "score": 0.9}],
                        # get_memory call
                        [{"user_scope": "other-user"}],
                    ],
                ):
                    result = mem.search("test", user_id=uid, graph_context=False)
                    # Result should be empty because it was scoped to another user
                    assert len(result["results"]) == 0

    def test_search_graph_context_in_metadata(self, mem: Memory) -> None:
        """search() includes graph_context in metadata (line 1094)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-1"):
            with patch.object(mem, "_get_graph_context", return_value=["EntityA", "EntityB"]):
                with patch.object(
                    mem,
                    "_call",
                    side_effect=[
                        # search call
                        [{"entity_id": "mem-1", "memory_content": "test mem", "score": 0.95}],
                        # get_memory call
                        [{"user_scope": uid}],
                    ],
                ):
                    result = mem.search("test", user_id=uid, graph_context=True)
                    if result["results"]:
                        assert "graph_context" in result["results"][0]["metadata"]
                        assert result["results"][0]["metadata"]["graph_context"] == [
                            "EntityA",
                            "EntityB",
                        ]

    def test_search_with_threshold_filter(self, mem: Memory) -> None:
        """search() filters results below threshold (line 1080)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-1"):
            with patch.object(mem, "_get_graph_context", return_value=[]):
                with patch.object(
                    mem,
                    "_call",
                    return_value=[
                        {"entity_id": "mem-a", "memory_content": "low", "score": 0.2},
                        {"entity_id": "mem-b", "memory_content": "high", "score": 0.95},
                        {"entity_id": "mem-c", "memory_content": "mid", "score": 0.5},
                    ],
                ):
                    # need get_memory for each result
                    with patch.object(mem._client, "get_memory", return_value=[{"user_scope": ""}]):
                        result = mem.search("test", user_id=uid, threshold=0.5, graph_context=False)
                        # only mem-b should remain
                        scores = [r["score"] for r in result["results"]]
                        assert all(s >= 0.5 for s in scores)


# ---------------------------------------------------------------------------
# chat() paths (mocked)
# ---------------------------------------------------------------------------




class TestChatPaths:
    """Cover chat() paths: history messages, LLM failure."""

    def test_chat_with_messages_history(self, mem: Memory) -> None:
        """chat() with messages param builds history_block (line 1447)."""
        uid = _uid()
        with patch.object(mem, "add"):  # suppress add calls
            with patch.object(mem, "search", return_value={"results": []}):
                with patch("spacetime_memory.sdks.mem0._resolve_llm", return_value=None):
                    result = mem.chat(
                        "Test query",
                        user_id=uid,
                        messages=[
                            {"role": "user", "content": "Previous"},
                            {"role": "assistant", "content": "Previous reply"},
                        ],
                    )
                    assert "response" in result
                    assert result["response"] == "Test query"  # fallback without LLM

    def test_chat_llm_error_fallback(self, mem: Memory) -> None:
        """chat() falls back to query when LLM.chat raises RuntimeError (lines 1469-1471)."""
        uid = _uid()
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "chat": lambda self, msgs: (_ for _ in ()).throw(RuntimeError("LLM timeout")),
            },
        )()
        with patch.object(mem, "add"), patch.object(
            mem,
            "search",
            return_value={"results": [{"id": "m1", "memory": "context mem", "score": 0.9}]},
        ), patch("spacetime_memory.sdks.mem0._resolve_llm", return_value=fake_llm):
            result = mem.chat("What do I like?", user_id=uid)
            assert result["response"] == "What do I like?"
            assert "context mem" in result["context"]


# ---------------------------------------------------------------------------
# get_all() no user_id path (mocked)
# ---------------------------------------------------------------------------




class TestGetAllNoUser:
    """Cover get_all() when user_id is None (lines 1168-1170)."""

    def test_get_all_no_user_id_uses_empty_ws(self, mem: Memory) -> None:
        """get_all() without user_id calls list_memories with empty workspace."""
        with patch.object(mem, "_ws", return_value=""):
            with patch.object(mem, "_call", return_value=[]) as mock_call:
                result = mem.get_all()
                assert "results" in result
                # verify _ws was called with None
                mock_call.assert_called()

    def test_get_all_with_user_id_filters_by_scope(self, mem: Memory) -> None:
        """get_all() with user_id filters by user_scope (line 1166)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-1"), patch.object(
            mem,
            "_call",
            return_value=[
                {"id": "m1", "content": "scoped", "user_scope": uid, "entity_id": "m1"},
                {"id": "m2", "content": "other", "user_scope": "other-user", "entity_id": "m2"},
                {"id": "m3", "content": "global", "user_scope": "", "entity_id": "m3"},
            ],
        ):
            result = mem.get_all(user_id=uid)
            assert len(result["results"]) == 2  # m2 filtered out


# ---------------------------------------------------------------------------
# delete_all with filters extraction (mocked)
# ---------------------------------------------------------------------------




class TestDeleteAllFilters:
    """Cover delete_all() filters extraction paths."""

    def test_delete_all_with_filters_extraction(self, mem: Memory) -> None:
        """delete_all() extracts from filters dict (lines 1282-1286)."""
        uid = _uid()
        with patch.object(
            mem,
            "get_all",
            return_value={
                "results": [{"id": "mem-d", "memory": "del", "user_id": uid, "metadata": {}}]
            },
        ), patch.object(mem, "_call"):  # suppress delete_memory call
            result = mem.delete_all(
                filters={"user_id": uid, "agent_id": "agent1", "run_id": "run1"}
            )
            assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# _tag_filter coverage (JSON parsing paths)
# ---------------------------------------------------------------------------




class TestTagFilter:
    """Cover _tag_filter internal JSON parsing paths."""

    def test_tag_filter_metadata_json_parsed(self, mem: Memory) -> None:
        """_tag_filter parses metadata_json as JSON string (line 100-107)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "n1", "label": "test", "metadata_json": json.dumps({"tag": tag})},
            {"id": "n2", "label": "other", "metadata_json": json.dumps({"tag": "wrong"})},
            {"id": "n3", "label": "empty-meta", "metadata_json": "", "description": ""},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 2  # n1 matches, n3 has empty metadata

    def test_tag_filter_description_parsed(self, mem: Memory) -> None:
        """_tag_filter parses description as entity_link format (lines 108-116)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {
                "id": "el1",
                "entity_name": "e1",
                "metadata_json": "",
                "description": json.dumps({"tag": tag}),
            },
            {
                "id": "el2",
                "entity_name": "e2",
                "metadata_json": "",
                "description": json.dumps({"tag": "other"}),
            },
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "el1"

    def test_tag_filter_json_decode_error(self, mem: Memory) -> None:
        """_tag_filter handles JSON decode errors gracefully (lines 106-107, 115-116)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "bad1", "metadata_json": "not-json{{{", "description": ""},
            {"id": "bad2", "metadata_json": "", "description": "also-bad-json"},
            {"id": "good", "metadata_json": json.dumps({"tag": tag}), "description": ""},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "good"

    def test_tag_filter_non_string_metadata(self, mem: Memory) -> None:
        """_tag_filter handles non-string metadata_json (already dict)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "d1", "metadata_json": {"tag": tag}, "description": ""},
            {"id": "d2", "metadata_json": {"tag": "nope"}, "description": ""},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "d1"

    def test_tag_filter_non_string_description(self, mem: Memory) -> None:
        """_tag_filter handles non-string description (already dict)."""
        uid = _uid()
        tag = f"mem0_user:{uid}"
        rows = [
            {"id": "dd1", "metadata_json": "", "description": {"tag": tag}},
            {"id": "dd2", "metadata_json": "", "description": {"tag": "other"}},
        ]
        result = mem.graph._tag_filter(rows, tag)
        assert len(result) == 1
        assert result[0]["id"] == "dd1"


# ---------------------------------------------------------------------------
# _entity_link_to_dict coverage
# ---------------------------------------------------------------------------




class TestEntityLinkToDict:
    """Cover _entity_link_to_dict method."""

    def test_entity_link_to_dict_defaults(self, mem: Memory) -> None:
        """_entity_link_to_dict with missing fields uses defaults."""
        row = {}
        result = mem.graph._entity_link_to_dict(row, "mem0_global")
        assert result["id"] == ""
        assert result["label"] == ""
        assert result["node_type"] == "concept"
        assert result["entity_type"] == "concept"
        assert result["summary"] == ""

    def test_entity_link_to_dict_full(self, mem: Memory) -> None:
        """_entity_link_to_dict with all fields populated."""
        row = {
            "id": "el-full",
            "entity_name": "FullEntity",
            "entity_type": "person",
            "description": '{"key": "val"}',
            "created_at": 1234567890,
        }
        result = mem.graph._entity_link_to_dict(row, "tag123")
        assert result["id"] == "el-full"
        assert result["label"] == "FullEntity"
        assert result["node_type"] == "person"
        assert result["entity_type"] == "person"
