"""Tests for server/mcp/tools/documents.py — Document tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_get_client():
    """Patch get_client at the module level where documents.py imports it."""
    with patch("server.mcp.tools.documents.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# create_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateDocument:
    """Tests for the create_document MCP tool."""

    def test_create_minimal(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import create_document

        _patch_get_client.create_document.return_value = {
            "id": "doc_abc",
            "status": "created",
        }
        result = create_document(
            workspace_id="ws1",
            title="My Document",
            content="Hello world",
        )
        assert result["status"] == "created"
        _patch_get_client.create_document.assert_called_once_with(
            workspace_id="ws1",
            title="My Document",
            content="Hello world",
            content_type="text",
            file_path="",
            source_url="",
            metadata=None,
        )

    def test_with_metadata(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import create_document

        _patch_get_client.create_document.return_value = {"id": "doc2"}
        create_document(
            workspace_id="ws1",
            title="Doc with meta",
            content="Some content",
            content_type="code",
            file_path="/path/to/file.py",
            source_url="https://example.com",
            metadata_json='{"author": "test"}',
        )
        _patch_get_client.create_document.assert_called_once_with(
            workspace_id="ws1",
            title="Doc with meta",
            content="Some content",
            content_type="code",
            file_path="/path/to/file.py",
            source_url="https://example.com",
            metadata={"author": "test"},
        )

    def test_empty_metadata_json(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import create_document

        _patch_get_client.create_document.return_value = {"id": "doc3"}
        create_document(workspace_id="ws1", content="test")
        _patch_get_client.create_document.assert_called_once_with(
            workspace_id="ws1",
            title="",
            content="test",
            content_type="text",
            file_path="",
            source_url="",
            metadata=None,
        )


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDocument:
    """Tests for the get_document MCP tool."""

    def test_gets(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import get_document

        expected = {"id": "doc_abc", "title": "My Doc", "content": "Hello"}
        _patch_get_client.get_document.return_value = expected

        result = get_document(doc_id="doc_abc")
        assert result == expected
        _patch_get_client.get_document.assert_called_once_with("doc_abc")

    def test_not_found(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import get_document

        _patch_get_client.get_document.return_value = None
        result = get_document(doc_id="nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListDocuments:
    """Tests for the list_documents MCP tool."""

    def test_lists(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import list_documents

        expected = [
            {"id": "doc1", "title": "Doc 1"},
            {"id": "doc2", "title": "Doc 2"},
        ]
        _patch_get_client.list_documents.return_value = expected

        result = list_documents(workspace_id="ws1")
        assert result == expected
        _patch_get_client.list_documents.assert_called_once_with("ws1")

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import list_documents

        _patch_get_client.list_documents.return_value = []
        result = list_documents("ws_empty")
        assert result == []


# ---------------------------------------------------------------------------
# get_document_chunks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDocumentChunks:
    """Tests for the get_document_chunks MCP tool."""

    def test_gets_chunks(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import get_document_chunks

        expected = [
            {"chunk_index": 0, "content": "chunk 1"},
            {"chunk_index": 1, "content": "chunk 2"},
        ]
        _patch_get_client.get_document_chunks.return_value = expected

        result = get_document_chunks(doc_id="doc_abc")
        assert result == expected
        _patch_get_client.get_document_chunks.assert_called_once_with("doc_abc")


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteDocument:
    """Tests for the delete_document MCP tool."""

    def test_deletes(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import delete_document

        expected = {"status": "deleted", "id": "doc_abc"}
        _patch_get_client.delete_document.return_value = expected

        result = delete_document(doc_id="doc_abc")
        assert result == expected
        _patch_get_client.delete_document.assert_called_once_with("doc_abc")


# ---------------------------------------------------------------------------
# reinforce_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReinforceMemory:
    """Tests for the reinforce_memory MCP tool."""

    def test_reinforces(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import reinforce_memory

        expected = {"id": "mem_abc", "access_count": 5}
        _patch_get_client.reinforce.return_value = expected

        result = reinforce_memory(memory_id="mem_abc")
        assert result == expected
        _patch_get_client.reinforce.assert_called_once_with("mem_abc")


# ---------------------------------------------------------------------------
# rate_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRateMemory:
    """Tests for the rate_memory MCP tool."""

    def test_rates(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import rate_memory

        expected = {"id": "mem_abc", "rating": "helpful"}
        _patch_get_client.rate_memory.return_value = expected

        result = rate_memory(memory_id="mem_abc", rating="helpful", peer_id="peer1")
        assert result == expected
        _patch_get_client.rate_memory.assert_called_once_with(
            "mem_abc", "helpful", "peer1"
        )


# ---------------------------------------------------------------------------
# escalate_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEscalateMemories:
    """Tests for the escalate_memories MCP tool."""

    def test_escalates(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import escalate_memories

        result = escalate_memories(workspace_id="ws1", l2_to_l1=10, l1_to_l0=50)
        assert "triggered" in result
        _patch_get_client.escalate_memories.assert_called_once_with("ws1", 10, 50)

    def test_default_params(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import escalate_memories

        escalate_memories(workspace_id="ws1")
        _patch_get_client.escalate_memories.assert_called_once_with("ws1", 5, 20)


# ---------------------------------------------------------------------------
# dedup_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDedupMemories:
    """Tests for the dedup_memories MCP tool."""

    def test_dedups(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import dedup_memories

        result = dedup_memories(workspace_id="ws1")
        assert "Dedup complete" in result
        _patch_get_client.dedup.assert_called_once_with("ws1")


# ---------------------------------------------------------------------------
# consolidate_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConsolidateMemories:
    """Tests for the consolidate_memories MCP tool."""

    def test_consolidates(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import consolidate_memories

        result = consolidate_memories(
            workspace_id="ws1",
            source_ids_json='["mem1", "mem2"]',
            target_content="Consolidated content",
            target_summary="Summary",
        )
        assert "Consolidation complete" in result
        _patch_get_client.consolidate_memories.assert_called_once_with(
            "ws1", ["mem1", "mem2"], "Consolidated content", "Summary"
        )


# ---------------------------------------------------------------------------
# suggest_merges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuggestMerges:
    """Tests for the suggest_merges MCP tool."""

    def test_suggests(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import suggest_merges

        result = suggest_merges(workspace_id="ws1", threshold=0.85)
        assert "Merge suggestion scan" in result
        _patch_get_client.suggest_merges.assert_called_once_with("ws1", 0.85)

    def test_default_threshold(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import suggest_merges

        suggest_merges(workspace_id="ws1")
        _patch_get_client.suggest_merges.assert_called_once_with("ws1", 0.8)


# ---------------------------------------------------------------------------
# approve_merge
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApproveMerge:
    """Tests for the approve_merge MCP tool."""

    def test_approves(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import approve_merge

        result = approve_merge(suggestion_id="sug_abc")
        assert "approved" in result
        _patch_get_client.approve_merge.assert_called_once_with("sug_abc")


# ---------------------------------------------------------------------------
# reject_merge
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRejectMerge:
    """Tests for the reject_merge MCP tool."""

    def test_rejects(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import reject_merge

        result = reject_merge(suggestion_id="sug_abc")
        assert "rejected" in result
        _patch_get_client.reject_merge.assert_called_once_with("sug_abc")


# ---------------------------------------------------------------------------
# set_memory_scope
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetMemoryScope:
    """Tests for the set_memory_scope MCP tool."""

    def test_scopes_to_user(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import set_memory_scope

        result = set_memory_scope(memory_id="mem_abc", user_scope="alice")
        assert "scoped" in result
        assert "alice" in result
        _patch_get_client.set_memory_scope.assert_called_once_with("mem_abc", "alice")

    def test_makes_shared(self, _patch_get_client: MagicMock):
        from server.mcp.tools.documents import set_memory_scope

        result = set_memory_scope(memory_id="mem_abc", user_scope="")
        assert "shared" in result
        _patch_get_client.set_memory_scope.assert_called_once_with("mem_abc", "")
