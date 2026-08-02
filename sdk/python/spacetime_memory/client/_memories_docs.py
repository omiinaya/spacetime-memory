"""Document management mixin."""
from __future__ import annotations

import json
from typing import Any

from ._base import logger
from ._schemas import _apply_return_schema
from ._utils import _query_hash


class DocumentMixin:
    """Spacetime-Memory document management mixin.

    Provides Client methods related to workspace documents.
    Inherits from ClientBase for connection infrastructure.
    """

    def create_document(
        self, workspace_id: str, title: str, content: str = "", metadata: dict | None = None
    ) -> dict[str, Any]:
        """Create a new document in the workspace."""
        return self._register_document_with_embedding(
            workspace_id, title, content, metadata or {}
        )

    def _register_document_with_embedding(
        self, workspace_id: str, title: str, content: str, metadata: dict
    ) -> dict[str, Any]:
        """Create document via the real create_document reducer, resolve the
        generated id, and index a title embedding for semantic search."""
        result = self._call(
            "create_document",
            [workspace_id, title, content, "text", "", "", json.dumps(metadata)],
        )
        # Resolve the new document id (most recent with this title in the workspace)
        doc_id = ""
        try:
            rows = self._query("document", workspace_id=workspace_id, filter_dict={"title": title})
            if rows:
                rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
                doc_id = rows[0].get("id", "")
        except Exception:
            logger.debug("create_document: id resolution failed for %r", title)
        # Index title embedding for semantic search (best-effort)
        try:
            emb = self._embed(title)
        except Exception:
            emb = []
        if emb and doc_id:
            try:
                self._call("index_entity", [workspace_id, "document", doc_id, title, json.dumps(emb)])
            except Exception:
                logger.warning("create_document: index_entity failed for %s", doc_id)
        if isinstance(result, dict):
            if doc_id and not result.get("id"):
                result["id"] = doc_id
            return result
        return {"status": "ok", "id": doc_id or None}

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        """Get a single document by ID. Returns None if not found."""
        rows = self._query("document", filter_dict={"id": document_id})
        return rows[0] if rows else None

    def update_document(
        self, document_id: str, title: str, content: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        """Update document content and re-embed if title changed."""
        return self._call("update_document", [document_id, title, content, metadata or {}])

    def delete_document(self, document_id: str) -> dict[str, Any]:
        """Delete a document by ID."""
        return self._call("delete_document", [document_id])

    def list_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all documents in a workspace, ordered by created_at DESC."""
        rows = self._query("document", filter_dict={"workspace_id": workspace_id})
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return rows

    def search_documents(self, workspace_id: str, query: str, limit: int = 10,
                         return_schema: str | type | None = None) -> list[dict[str, Any]]:
        """Semantic search over documents.

        Args:
            workspace_id: Target workspace.
            query: Search query text.
            limit: Max results to return (default 10).
            return_schema: If ``"llm"``, returns ``list[LLMSearchResult]`` with compact
                    fields. If a ``TypedDict`` subclass, keeps only the annotated fields.
                    ``None`` (default) returns raw dicts unchanged.
        """
        self._call("search_documents", [workspace_id, query, limit])
        query_hash = _query_hash(f"{workspace_id}:{query}") + ":docsearch"
        rows = self._query("document_search_result", filter_dict={"query_hash": query_hash})
        rows.sort(key=lambda r: r.get("rank", 0))
        if return_schema is not None:
            rows = _apply_return_schema(rows, return_schema)
        return rows


    def get_document_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Retrieve all chunks for a document.

        Args:
            doc_id: The document ID to retrieve chunks for.

        Returns:
            A list of chunk dicts, each with keys:
            id, document_id, chunk_index, content, embedding, created_at.
        """
        self._call("get_document_chunks", [doc_id])
        query_hash = f"doc_chunks:{doc_id}"
        rows = self._query("document_chunk", filter_dict={"query_hash": query_hash})
        rows.sort(key=lambda r: r.get("chunk_index", 0))
        return rows

    def add_chunk(self, document_id: str, content: str, chunk_index: int = 0, metadata_json: str = "{}") -> dict[str, Any]:
        """Add a chunk to a document.

        Args:
            document_id: The document ID.
            content: Chunk content text.
            chunk_index: Optional chunk index (default: 0).
            metadata_json: Optional JSON metadata string (default: "{}").

        Returns:
            Reducer status dict.
        """
        return self._call("add_chunk", [document_id, content, chunk_index, metadata_json])
