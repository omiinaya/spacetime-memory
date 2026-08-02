"""Tests for server/mcp/tools/context.py - Context MCP tools."""
import pytest
from server.mcp.tools.context import (
    get_context_chain, detect_patterns, fuzzy_get, glob_get,
    list_context_packs, list_context_entries, list_context_deltas,
)


class TestContextModule:
    """Test suite for context.py - verify all expected exports exist."""

    def test_get_context_chain_exists(self):
        assert callable(get_context_chain)

    def test_detect_patterns_exists(self):
        assert callable(detect_patterns)

    def test_fuzzy_get_exists(self):
        assert callable(fuzzy_get)

    def test_glob_get_exists(self):
        assert callable(glob_get)

    def test_list_context_packs_exists(self):
        assert callable(list_context_packs)

    def test_list_context_entries_exists(self):
        assert callable(list_context_entries)

    def test_list_context_deltas_exists(self):
        assert callable(list_context_deltas)
