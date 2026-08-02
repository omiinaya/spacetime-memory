"""Tests for server/mcp/tools/context.py — Context tools (QMD-style context chains)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_get_client():
    """Patch get_client at the module level where context.py imports it."""
    with patch("server.mcp.tools.context.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# set_workspace_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetWorkspaceContext:
    """Tests for the set_workspace_context MCP tool."""

    def test_sets_context(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import set_workspace_context

        _patch_get_client.set_workspace_context.return_value = {"status": "ok"}
        result = set_workspace_context(workspace_id="ws1", context="Project context")
        assert result == {"status": "ok"}
        _patch_get_client.set_workspace_context.assert_called_once_with(
            "ws1", "Project context"
        )

    def test_returns_dict(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import set_workspace_context

        _patch_get_client.set_workspace_context.return_value = {"status": "ok"}
        result = set_workspace_context("ws2", "another context")
        assert isinstance(result, dict)

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import set_workspace_context

        _patch_get_client.set_workspace_context.side_effect = RuntimeError("nope")
        with pytest.raises(RuntimeError, match="nope"):
            set_workspace_context(workspace_id="ws1", context="boom")

    def test_empty_context(self, _patch_get_client: MagicMock):
        """An empty context string is allowed."""
        from server.mcp.tools.context import set_workspace_context

        _patch_get_client.set_workspace_context.return_value = {"status": "ok"}
        result = set_workspace_context(workspace_id="ws1", context="")
        assert result == {"status": "ok"}
        _patch_get_client.set_workspace_context.assert_called_once_with(
            "ws1", ""
        )


# ---------------------------------------------------------------------------
# set_memory_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetMemoryContext:
    """Tests for the set_memory_context MCP tool."""

    def test_sets_memory_context(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import set_memory_context

        _patch_get_client.set_memory_context.return_value = {"status": "ok"}
        result = set_memory_context(memory_id="mem1", context="Memory ctx")
        assert result == {"status": "ok"}
        _patch_get_client.set_memory_context.assert_called_once_with(
            "mem1", "Memory ctx"
        )

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import set_memory_context

        _patch_get_client.set_memory_context.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            set_memory_context(memory_id="mem1", context="x")

    def test_empty_context(self, _patch_get_client: MagicMock):
        """An empty context string is passed through."""
        from server.mcp.tools.context import set_memory_context

        _patch_get_client.set_memory_context.return_value = {"status": "ok"}
        result = set_memory_context(memory_id="mem1", context="")
        assert result == {"status": "ok"}
        _patch_get_client.set_memory_context.assert_called_once_with("mem1", "")


# ---------------------------------------------------------------------------
# get_context_chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetContextChain:
    """Tests for the get_context_chain MCP tool."""

    def test_gets_chain(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import get_context_chain

        expected = {
            "workspace_context": "Project ctx",
            "memory_context": "Memory ctx",
        }
        _patch_get_client.get_context_chain.return_value = expected
        result = get_context_chain(memory_id="mem1")
        assert result == expected
        _patch_get_client.get_context_chain.assert_called_once_with("mem1")

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import get_context_chain

        _patch_get_client.get_context_chain.side_effect = RuntimeError("bad")
        with pytest.raises(RuntimeError, match="bad"):
            get_context_chain(memory_id="mem1")

    def test_empty_memory_id(self, _patch_get_client: MagicMock):
        """An empty memory_id is passed to the client as-is."""
        from server.mcp.tools.context import get_context_chain

        _patch_get_client.get_context_chain.return_value = {}
        result = get_context_chain(memory_id="")
        assert result == {}
        _patch_get_client.get_context_chain.assert_called_once_with("")


# ---------------------------------------------------------------------------
# list_context_packs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListContextPacks:
    """Tests for the list_context_packs MCP tool."""

    def test_lists_packs(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import list_context_packs

        expected = [{"id": "pack1", "name": "Pack 1"}]
        _patch_get_client.list_context_packs.return_value = expected
        result = list_context_packs(workspace_id="ws1")
        assert result == expected
        _patch_get_client.list_context_packs.assert_called_once_with("ws1")

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import list_context_packs

        _patch_get_client.list_context_packs.return_value = []
        result = list_context_packs("ws1")
        assert result == []

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import list_context_packs

        _patch_get_client.list_context_packs.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            list_context_packs(workspace_id="ws1")


# ---------------------------------------------------------------------------
# list_context_entries
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListContextEntries:
    """Tests for the list_context_entries MCP tool."""

    def test_lists_entries(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import list_context_entries

        expected = [{"id": "entry1", "data": "some data"}]
        _patch_get_client.list_context_entries.return_value = expected
        result = list_context_entries(pack_id="pack1")
        assert result == expected
        _patch_get_client.list_context_entries.assert_called_once_with("pack1")

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import list_context_entries

        _patch_get_client.list_context_entries.side_effect = RuntimeError("oops")
        with pytest.raises(RuntimeError, match="oops"):
            list_context_entries(pack_id="pack1")

    def test_empty_pack_id(self, _patch_get_client: MagicMock):
        """An empty pack_id is passed through to the client."""
        from server.mcp.tools.context import list_context_entries

        _patch_get_client.list_context_entries.return_value = []
        result = list_context_entries(pack_id="")
        assert result == []
        _patch_get_client.list_context_entries.assert_called_once_with("")


# ---------------------------------------------------------------------------
# list_context_deltas
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListContextDeltas:
    """Tests for the list_context_deltas MCP tool."""

    def test_lists_deltas(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import list_context_deltas

        expected = [{"field": "context", "old": "a", "new": "b"}]
        _patch_get_client.list_context_deltas.return_value = expected
        result = list_context_deltas(previous_pack_id="pack1")
        assert result == expected
        _patch_get_client.list_context_deltas.assert_called_once_with("pack1")

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import list_context_deltas

        _patch_get_client.list_context_deltas.side_effect = RuntimeError("delta err")
        with pytest.raises(RuntimeError, match="delta err"):
            list_context_deltas(previous_pack_id="pack1")


# ---------------------------------------------------------------------------
# fuzzy_get
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFuzzyGet:
    """Tests for the fuzzy_get MCP tool."""

    def test_finds_match(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import fuzzy_get

        expected = {"id": "mem1", "content": "hello world"}
        _patch_get_client.fuzzy_get.return_value = expected
        result = fuzzy_get(workspace_id="ws1", name="hello")
        assert json.loads(result) == expected
        _patch_get_client.fuzzy_get.assert_called_once_with(
            workspace_id="ws1",
            name="hello",
            field="content",
            threshold=0.5,
            limit=50,
        )

    def test_no_match(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import fuzzy_get

        _patch_get_client.fuzzy_get.return_value = None
        result = fuzzy_get(workspace_id="ws1", name="xyz")
        assert "No memory found" in result
        assert "xyz" in result

    def test_with_custom_params(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import fuzzy_get

        _patch_get_client.fuzzy_get.return_value = {"id": "m1"}
        fuzzy_get(
            workspace_id="ws1",
            name="test",
            field="summary",
            threshold=0.8,
            limit=10,
        )
        _patch_get_client.fuzzy_get.assert_called_once_with(
            workspace_id="ws1",
            name="test",
            field="summary",
            threshold=0.8,
            limit=10,
        )

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import fuzzy_get

        _patch_get_client.fuzzy_get.side_effect = RuntimeError("fuzzy fail")
        with pytest.raises(RuntimeError, match="fuzzy fail"):
            fuzzy_get(workspace_id="ws1", name="test")

    def test_threshold_zero(self, _patch_get_client: MagicMock):
        """threshold=0.0 matches anything the client returns."""
        from server.mcp.tools.context import fuzzy_get

        expected = {"id": "m1", "content": "anything"}
        _patch_get_client.fuzzy_get.return_value = expected
        result = fuzzy_get(
            workspace_id="ws1", name="whatever", threshold=0.0
        )
        assert json.loads(result) == expected
        _patch_get_client.fuzzy_get.assert_called_once_with(
            workspace_id="ws1",
            name="whatever",
            field="content",
            threshold=0.0,
            limit=50,
        )

    def test_empty_name(self, _patch_get_client: MagicMock):
        """Empty name is forwarded to the client."""
        from server.mcp.tools.context import fuzzy_get

        _patch_get_client.fuzzy_get.return_value = {"id": "m1"}
        result = fuzzy_get(workspace_id="ws1", name="")
        assert json.loads(result) == {"id": "m1"}
        _patch_get_client.fuzzy_get.assert_called_once_with(
            workspace_id="ws1", name="", field="content", threshold=0.5, limit=50
        )


# ---------------------------------------------------------------------------
# glob_get
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGlobGet:
    """Tests for the glob_get MCP tool."""

    def test_finds_matches(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import glob_get

        expected = [{"id": "auth-key-1"}, {"id": "auth-key-2"}]
        _patch_get_client.glob_get.return_value = expected
        result = glob_get(workspace_id="ws1", pattern="auth-*")
        assert json.loads(result) == expected
        _patch_get_client.glob_get.assert_called_once_with(
            workspace_id="ws1",
            pattern="auth-*",
            field="id",
            limit=200,
        )

    def test_no_match(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import glob_get

        _patch_get_client.glob_get.return_value = []
        result = glob_get(workspace_id="ws1", pattern="nonexistent-*")
        assert "No memories matching pattern" in result

    def test_with_custom_field(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import glob_get

        _patch_get_client.glob_get.return_value = [{"content": "match"}]
        glob_get(workspace_id="ws1", pattern="*agent*", field="content", limit=10)
        _patch_get_client.glob_get.assert_called_once_with(
            workspace_id="ws1",
            pattern="*agent*",
            field="content",
            limit=10,
        )

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import glob_get

        _patch_get_client.glob_get.side_effect = RuntimeError("glob fail")
        with pytest.raises(RuntimeError, match="glob fail"):
            glob_get(workspace_id="ws1", pattern="*")

    def test_empty_pattern(self, _patch_get_client: MagicMock):
        """Empty pattern is forwarded to the client."""
        from server.mcp.tools.context import glob_get

        _patch_get_client.glob_get.return_value = [{"id": "match"}]
        result = glob_get(workspace_id="ws1", pattern="")
        assert json.loads(result) == [{"id": "match"}]
        _patch_get_client.glob_get.assert_called_once_with(
            workspace_id="ws1", pattern="", field="id", limit=200
        )


# ---------------------------------------------------------------------------
# detect_patterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectPatterns:
    """Tests for the detect_patterns MCP tool."""

    def test_detects_patterns(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import detect_patterns

        expected = {
            "temporal_clusters": [],
            "frequent_terms": ["ml", "ai"],
            "co_occurrences": [["ml", "ai"]],
            "total_memories": 10,
            "summary": "Patterns found.",
        }
        _patch_get_client.detect_patterns.return_value = expected
        result = detect_patterns(workspace_id="ws1")
        assert json.loads(result) == expected
        _patch_get_client.detect_patterns.assert_called_once_with(
            workspace_id="ws1",
            limit=200,
            include_clusters=True,
            include_terms=True,
            include_co_occur=True,
        )

    def test_with_options(self, _patch_get_client: MagicMock):
        from server.mcp.tools.context import detect_patterns

        _patch_get_client.detect_patterns.return_value = {"summary": ""}
        detect_patterns(
            workspace_id="ws1",
            limit=50,
            include_clusters=False,
            include_terms=True,
            include_co_occur=False,
        )
        _patch_get_client.detect_patterns.assert_called_once_with(
            workspace_id="ws1",
            limit=50,
            include_clusters=False,
            include_terms=True,
            include_co_occur=False,
        )

    def test_error_propagation(self, _patch_get_client: MagicMock):
        """Client error propagates through the MCP tool."""
        from server.mcp.tools.context import detect_patterns

        _patch_get_client.detect_patterns.side_effect = RuntimeError("pattern fail")
        with pytest.raises(RuntimeError, match="pattern fail"):
            detect_patterns(workspace_id="ws1")

    def test_all_flags_false(self, _patch_get_client: MagicMock):
        """All analysis flags can be disabled."""
        from server.mcp.tools.context import detect_patterns

        _patch_get_client.detect_patterns.return_value = {"summary": "no analysis"}
        result = detect_patterns(
            workspace_id="ws1",
            include_clusters=False,
            include_terms=False,
            include_co_occur=False,
        )
        assert json.loads(result) == {"summary": "no analysis"}
        _patch_get_client.detect_patterns.assert_called_once_with(
            workspace_id="ws1",
            limit=200,
            include_clusters=False,
            include_terms=False,
            include_co_occur=False,
        )
