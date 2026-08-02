"""Tests for server/mcp/tools/documents.py - Document MCP tools."""
import pytest
from server.mcp.tools.documents import (
    create_document, get_document, delete_document,
    consolidate_memories, dedup_memories, escalate_memories,
    approve_merge,
)


class TestDocumentsModule:
    """Test suite for documents.py - verify all expected exports exist."""

    def test_create_document_exists(self):
        assert callable(create_document)

    def test_get_document_exists(self):
        assert callable(get_document)

    def test_delete_document_exists(self):
        assert callable(delete_document)

    def test_consolidate_memories_exists(self):
        assert callable(consolidate_memories)

    def test_dedup_memories_exists(self):
        assert callable(dedup_memories)

    def test_escalate_memories_exists(self):
        assert callable(escalate_memories)

    def test_approve_merge_exists(self):
        assert callable(approve_merge)
