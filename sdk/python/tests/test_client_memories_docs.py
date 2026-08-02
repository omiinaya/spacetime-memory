"""Unit tests for DocumentMixin — document CRUD, search, chunks.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch


class TestDocumentMixin:
    """DocumentMixin methods (documents, chunks, search)."""

    def test_create_document(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "doc-1", "title": "My Doc", "created_at": 100}
             ]), \
             patch.object(mock_http_client, "_embed", return_value=[0.1, 0.2]):
            result = mock_http_client.create_document("ws-1", "My Doc", "Some content")
        assert result["status"] == "ok"
        assert result["id"] == "doc-1"

    def test_create_document_no_embedding(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "doc-1", "title": "My Doc", "created_at": 100}
             ]), \
             patch.object(mock_http_client, "_embed", return_value=[]):
            result = mock_http_client.create_document("ws-1", "My Doc", "Content")
        assert result["status"] == "ok"

    def test_create_document_id_resolution_fails(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]), \
             patch.object(mock_http_client, "_embed", return_value=[0.1]):
            result = mock_http_client.create_document("ws-1", "My Doc", "Content")
        assert result["status"] == "ok"
        assert result.get("id") is None

    def test_get_document(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"id": "doc-1", "title": "My Doc", "content": "Content"}]):
            result = mock_http_client.get_document("doc-1")
        assert result["id"] == "doc-1"

    def test_get_document_not_found(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_document("nonexistent")
        assert result is None

    def test_update_document(self, mock_http_client):
        result = mock_http_client.update_document("doc-1", "New Title", "New content", {"key": "val"})
        assert result == {"status": "ok"}

    def test_delete_document(self, mock_http_client):
        result = mock_http_client.delete_document("doc-1")
        assert result == {"status": "ok"}

    def test_list_documents(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "doc-1", "workspace_id": "ws-1", "created_at": 200},
            {"id": "doc-2", "workspace_id": "ws-1", "created_at": 100},
        ]):
            result = mock_http_client.list_documents("ws-1")
        assert len(result) == 2
        # Sorted by created_at DESC
        assert result[0]["id"] == "doc-1"

    def test_list_documents_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_documents("ws-1")
        assert result == []

    def test_search_documents(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"query_hash": "hash:docsearch", "document_id": "doc-1", "rank": 1, "score": 0.9}
             ]):
            result = mock_http_client.search_documents("ws-1", "test query", limit=10)
        assert len(result) == 1
        assert result[0]["document_id"] == "doc-1"

    def test_search_documents_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.search_documents("ws-1", "nothing")
        assert result == []

    def test_get_document_chunks(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"query_hash": "doc_chunks:doc-1", "chunk_index": 0, "content": "chunk1"},
                 {"query_hash": "doc_chunks:doc-1", "chunk_index": 1, "content": "chunk2"},
             ]):
            result = mock_http_client.get_document_chunks("doc-1")
        assert len(result) == 2
        assert result[0]["chunk_index"] == 0

    def test_get_document_chunks_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_document_chunks("doc-1")
        assert result == []

    def test_add_chunk(self, mock_http_client):
        result = mock_http_client.add_chunk("doc-1", "chunk content", chunk_index=1, metadata_json='{"page": 5}')
        assert result == {"status": "ok"}
