"""Session search mixin — search across sessions/workspaces.

Extracted from _memories_search.py to keep the search module focused on
memory-specific retrieval.  This module provides the
:class:`SessionSearchMixin` which contributes session-scoped search
methods to the composed :class:`~spacetime_memory.client.Client` class.
"""
from __future__ import annotations

import json
from typing import Any

from ._schemas import _apply_return_schema


class SessionSearchMixin:
    """Session-scoped search methods for the composed Client class.

    Adds the ability to search semantically across all sessions/workspaces
    in a single call.  Inherits from :class:`~spacetime_memory.client._base.ClientBase`
    for connection infrastructure.
    """

    def search_sessions_semantic(
        self,
        query: str,
        limit: int = 10,
        return_schema: str | type | None = None,
    ) -> list[dict[str, Any]]:
        """Semantically search across all sessions/workspaces.

        Embeds the query, calls the ``search_sessions_semantic`` reducer,
        and reads results from ``session_search_result``.

        Args:
            query: The natural-language search query.
            limit: Maximum number of results to return (default 10).
            return_schema: If ``"llm"``, returns ``list[LLMSearchResult]`` with
                compact fields (id, content, relevance, type, snippet, created_at).
                If a ``TypedDict`` subclass, keeps only the annotated fields.
                ``None`` (default) returns raw dicts unchanged.

        Returns:
            List of matching session rows, sorted by relevance score
            descending.
        """
        emb = self._embed(query)
        if not emb:
            return []

        emb_json = json.dumps(emb)
        self._call("search_sessions_semantic", [emb_json, limit])

        qhash = f"sessions:{limit}"
        rows = self._query("session_search_result", filter_dict={"query_hash": qhash})
        rows.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        rows = rows[:limit]
        if return_schema is not None:
            rows = _apply_return_schema(rows, return_schema)
        return rows
