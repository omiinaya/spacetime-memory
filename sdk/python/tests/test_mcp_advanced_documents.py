"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestCreateDocument:
    """Tests for the create_document MCP tool."""

    def test_creates_document(self, mock_mcp_client):
        from server.mcp.main import create_document

        mock_mcp_client.create_document.return_value = {"id": "doc1", "title": "Doc"}
        result = create_document(
            workspace_id="ws1",
            title="Doc",
            content="Content here",
        )
        assert result["id"] == "doc1"
        mock_mcp_client.create_document.assert_called_once()

    def test_with_metadata(self, mock_mcp_client):
        from server.mcp.main import create_document

        mock_mcp_client.create_document.return_value = {"id": "doc2"}
        create_document(
            workspace_id="ws1",
            title="Meta",
            content="Doc content",
            metadata_json='{"source": "web"}',
        )
        call_kw = mock_mcp_client.create_document.call_args[1]
        assert call_kw["metadata"] == {"source": "web"}



# ── TestGetDocument ────────────────────────────────────────────────────────

class TestGetDocument:
    """Tests for the get_document MCP tool."""

    def test_gets(self, mock_mcp_client):
        from server.mcp.main import get_document

        mock_mcp_client.get_document.return_value = {"id": "doc1", "title": "Doc"}
        result = get_document(doc_id="doc1")
        assert result["title"] == "Doc"
        mock_mcp_client.get_document.assert_called_once_with("doc1")

    def test_not_found(self, mock_mcp_client):
        from server.mcp.main import get_document

        mock_mcp_client.get_document.return_value = None
        result = get_document(doc_id="nonexistent")
        assert result is None



# ── TestListDocuments ────────────────────────────────────────────────────────

class TestListDocuments:
    """Tests for the list_documents MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_documents

        mock_mcp_client.list_documents.return_value = [
            {"id": "d1", "title": "Doc 1"},
        ]
        result = list_documents(workspace_id="ws1")
        assert len(result) == 1
        mock_mcp_client.list_documents.assert_called_once_with("ws1")



# ── TestGetDocumentChunks ────────────────────────────────────────────────────────

class TestGetDocumentChunks:
    """Tests for the get_document_chunks MCP tool."""

    def test_gets_chunks(self, mock_mcp_client):
        from server.mcp.main import get_document_chunks

        mock_mcp_client.get_document_chunks.return_value = [
            {"index": 0, "content": "chunk1"},
            {"index": 1, "content": "chunk2"},
        ]
        result = get_document_chunks(doc_id="doc1")
        assert len(result) == 2
        mock_mcp_client.get_document_chunks.assert_called_once_with("doc1")



# ── TestDeleteDocument ────────────────────────────────────────────────────────

class TestDeleteDocument:
    """Tests for the delete_document MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_document

        mock_mcp_client.delete_document.return_value = {"status": "ok"}
        result = delete_document(doc_id="doc1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_document.assert_called_once_with("doc1")


# ── Memory lifecycle / maintenance tools ─────────────────────────────────



# ── TestReinforceMemory ────────────────────────────────────────────────────────

class TestReinforceMemory:
    """Tests for the reinforce_memory MCP tool."""

    def test_reinforces(self, mock_mcp_client):
        from server.mcp.main import reinforce_memory

        mock_mcp_client.reinforce.return_value = {"status": "ok"}
        result = reinforce_memory(memory_id="m1")
        assert result["status"] == "ok"
        mock_mcp_client.reinforce.assert_called_once_with("m1")



# ── TestRateMemory ────────────────────────────────────────────────────────

class TestRateMemory:
    """Tests for the rate_memory MCP tool."""

    def test_rates_helpful(self, mock_mcp_client):
        from server.mcp.main import rate_memory

        mock_mcp_client.rate_memory.return_value = {"status": "ok"}
        result = rate_memory(memory_id="m1", rating="helpful", peer_id="p1")
        assert result["status"] == "ok"
        mock_mcp_client.rate_memory.assert_called_once_with("m1", "helpful", "p1")



# ── TestEscalateMemories ────────────────────────────────────────────────────────

class TestEscalateMemories:
    """Tests for the escalate_memories MCP tool."""

    def test_escalates(self, mock_mcp_client):
        from server.mcp.main import escalate_memories

        result = escalate_memories(workspace_id="ws1", l2_to_l1=5, l1_to_l0=20)
        assert "escalation triggered" in result.lower()
        mock_mcp_client.escalate_memories.assert_called_once_with("ws1", 5, 20)



# ── TestDedupMemories ────────────────────────────────────────────────────────

class TestDedupMemories:
    """Tests for the dedup_memories MCP tool."""

    def test_dedups(self, mock_mcp_client):
        from server.mcp.main import dedup_memories

        result = dedup_memories(workspace_id="ws1")
        assert "Dedup complete" in result
        mock_mcp_client.dedup.assert_called_once_with("ws1")



# ── TestConsolidateMemories ────────────────────────────────────────────────────────

class TestConsolidateMemories:
    """Tests for the consolidate_memories MCP tool."""

    def test_consolidates(self, mock_mcp_client):
        from server.mcp.main import consolidate_memories

        result = consolidate_memories(
            workspace_id="ws1",
            source_ids_json='["m1", "m2"]',
            target_content="Consolidated content",
            target_summary="Consolidated summary",
        )
        assert "Consolidation complete" in result
        mock_mcp_client.consolidate_memories.assert_called_once_with(
            "ws1", ["m1", "m2"], "Consolidated content", "Consolidated summary"
        )



# ── TestSuggestMerges ────────────────────────────────────────────────────────

class TestSuggestMerges:
    """Tests for the suggest_merges MCP tool."""

    def test_suggests(self, mock_mcp_client):
        from server.mcp.main import suggest_merges

        result = suggest_merges(workspace_id="ws1", threshold=0.85)
        assert "Merge suggestion scan complete" in result
        mock_mcp_client.suggest_merges.assert_called_once_with("ws1", 0.85)



# ── TestApproveMerge ────────────────────────────────────────────────────────

class TestApproveMerge:
    """Tests for the approve_merge MCP tool."""

    def test_approves(self, mock_mcp_client):
        from server.mcp.main import approve_merge

        result = approve_merge(suggestion_id="sg-1")
        assert "approved" in result
        mock_mcp_client.approve_merge.assert_called_once_with("sg-1")



# ── TestRejectMerge ────────────────────────────────────────────────────────

class TestRejectMerge:
    """Tests for the reject_merge MCP tool."""

    def test_rejects(self, mock_mcp_client):
        from server.mcp.main import reject_merge

        result = reject_merge(suggestion_id="sg-1")
        assert "rejected" in result
        mock_mcp_client.reject_merge.assert_called_once_with("sg-1")
