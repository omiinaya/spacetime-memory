"""
Internal graph store module — ``_GraphStore`` and ``_resolve_llm``.

This module is part of the ``spacetime_memory.sdks.mem0`` package.
Import via ``from spacetime_memory.sdks.mem0 import Memory``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ...llm import LLMClient

if TYPE_CHECKING:
    from ._client import Memory

logger = logging.getLogger("spacetime_memory.sdks.mem0")



class _GraphStore:
    """Mem0-compatible graph / entity store.

    Real Mem0 stores entities in a separate vector-store collection.
    We back it with SpacetimeDB's ``entity_link`` table for canonical
    entity resolution with alias support, falling back to ``kg_node``
    when the entity_link table is not available.

    The API shape matches Mem0's ``Memory.graph`` attribute so callers
    can use the same patterns::

        >>> m = Memory()
        >>> m.graph.add("Alice", entity_type="person", user_id="alice")
        >>> results = m.graph.search("Alice", user_id="alice")
        >>> all_nodes = m.graph.get_all(user_id="alice")
    """

    def __init__(self, memory: Memory):
        self._memory = memory

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ws(self, user_id: str | None = None) -> str:
        return self._memory._ws(user_id)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._memory._call(method, *args, **kwargs)

    def _tag(self, user_id: str | None = None) -> str:
        """Build a tag suffix used to scope entities to a user."""
        return f"mem0_user:{user_id}" if user_id else "mem0_global"

    def _tag_filter(self, rows: list[dict[str, Any]], tag: str) -> list[dict[str, Any]]:
        """Filter entity rows by tag, matching both entity_link and kg_node formats.

        For entity_link rows, the tag is stored in the ``description`` field as JSON.
        For kg_node rows, it's in ``metadata_json``.

        Uses proper JSON parsing to avoid fragility of string-based matching.
        """

        def _has_tag(row: dict[str, Any], tag: str) -> bool:
            # Try metadata_json first (kg_node format)
            meta = row.get("metadata_json", "")
            if meta:
                try:
                    parsed = json.loads(meta) if isinstance(meta, str) else meta
                    if isinstance(parsed, dict) and parsed.get("tag") == tag:
                        return True
                except (json.JSONDecodeError, TypeError):
                    pass
            # Try description field (entity_link format)
            desc = row.get("description", "")
            if desc:
                try:
                    parsed = json.loads(desc) if isinstance(desc, str) else desc
                    if isinstance(parsed, dict) and parsed.get("tag") == tag:
                        return True
                except (json.JSONDecodeError, TypeError):
                    pass
            # Empty metadata — allow (global/unscoped entries)
            if not meta and not desc:
                return True
            return False

        return [r for r in rows if _has_tag(r, tag)]

    def _entity_link_to_dict(self, row: dict[str, Any], tag: str) -> dict[str, Any]:
        """Convert an entity_link row to the standard graph entity dict shape."""
        return {
            "id": row.get("id", ""),
            "label": row.get("entity_name", ""),
            "node_type": row.get("entity_type", "concept"),
            "entity_type": row.get("entity_type", "concept"),
            "summary": row.get("entity_name", ""),
            "metadata_json": row.get("description", json.dumps({"tag": tag})),
            "created_at": row.get("created_at", 0),
        }

    # ------------------------------------------------------------------
    # Mem0 graph API
    # ------------------------------------------------------------------

    def add(
        self,
        text: str,
        entity_type: str = "concept",
        user_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Add an entity to the graph with vector-based dedup.

        Embeds the entity name and searches for similar existing entities
        (matching real Mem0's Qdrant-backed dedup).  If a close match is
        found, the existing entity is updated with the new alias.  Falls
        back gracefully when the embedder is unavailable.

        Args:
            text: Entity label / name (e.g. ``\"Alice\"``, ``\"Python\"``).
            entity_type: Semantic type (e.g. ``\"person\"``, ``\"language\"``).
            user_id: Owner user.
            agent_id: Optional agent scope.
            metadata: Optional extra properties.

        Returns:
            Dict with the created or updated entity info.

        Raises:
            ValueError: If ``text`` is empty.
        """
        if not text or not text.strip():
            raise ValueError("graph.add() requires non-empty text")
        cleaned = text.strip()
        ws_id = self._ws(user_id)
        meta = dict(metadata or {})
        if agent_id:
            meta["agent_id"] = agent_id
        tag = self._tag(user_id)
        meta["tag"] = tag

        # Vector-based dedup: search for similar existing entities
        try:
            semantic_rows = self._memory._client.search(
                workspace_id=ws_id,
                query=cleaned,
                limit=5,
                semantic=True,
            )
            node_rows = [r for r in semantic_rows if r.get("entity_type") == "node"]
            for r in node_rows:
                score = r.get("score", 0.0)
                if score < 0.85:
                    continue
                nid = r.get("entity_id", "")
                if not nid:
                    continue
                # Found a close match — resolve existing entity and add alias
                rows = self._memory._client._query(
                    "kg_node",
                    filter_dict={"id": nid},
                )
                if not rows:
                    continue
                existing = rows[0]
                existing_name = existing.get("label", "")
                # Look up entity_link ID for this node
                try:
                    el_rows = self._memory._client._query(
                        "entity_link",
                        workspace_id=ws_id,
                        filter_dict={"entity_name": existing_name},
                    )
                    if el_rows:
                        el_id = el_rows[0]["id"]
                        self._memory._client.add_alias(el_id, cleaned)
                except RuntimeError:
                    pass  # alias already exists or entity_link not available
                logger.debug(
                    "graph.add: merged '%s' into existing '%s' (cos=%.3f)",
                    cleaned,
                    existing_name,
                    score,
                )
                return {
                    "id": nid,
                    "label": existing_name,
                    "entity_type": existing.get("node_type", entity_type),
                    "summary": existing.get("summary", ""),
                    "metadata_json": existing.get("metadata_json", json.dumps(meta)),
                    "created_at": existing.get("created_at", 0),
                    "merged": True,
                }
        except RuntimeError:
            pass  # Embedder down → fall through to exact match

        # No vector match found (or embedder down) — create via exact dedup
        return self._add_exact(cleaned, entity_type, ws_id, meta, tag)

    def _add_exact(
        self,
        text: str,
        entity_type: str,
        ws_id: str,
        meta: dict,
        tag: str,
    ) -> dict[str, Any]:
        """Create entity via entity_link (exact-name dedup) or kg_node fallback."""
        # Try entity_link first — canonical entity resolution with aliases
        try:
            self._memory._client.create_entity_link(
                workspace_id=ws_id,
                canonical_name=text,
                entity_type=entity_type,
                description=json.dumps(meta),
            )
            rows = self._memory._client._query(
                "entity_link",
                workspace_id=ws_id,
                filter_dict={"entity_name": text},
            )
            if rows:
                return self._entity_link_to_dict(rows[0], tag)
            return {"status": "ok", "id": ""}
        except RuntimeError:
            logger.debug("entity_link unavailable for graph.add, falling back to kg_node")

        result = self._call(
            "create_node",
            workspace_id=ws_id,
            label=text,
            node_type=entity_type,
            summary=text,
            metadata_json=json.dumps(meta),
        )
        return result if isinstance(result, dict) else {"status": "ok", "id": str(result)}

    def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search graph entities by label.

        When the embedder sidecar is available, uses vector/semantic search
        via ``hybrid_search`` for relevance-ranked results (matches real
        Mem0's vector-backed entity_store).  Falls back to substring matching
        when the embedder is unavailable.

        Args:
            query: Text to search for.
            user_id: Scope results to this user's workspace.
            limit: Max results (default 10).

        Returns:
            List of matching entity records.
        """
        ws_id = self._ws(user_id)
        tag = self._tag(user_id)

        # Try vector search first (Mem0 entity_store behavior)
        try:
            semantic_rows = self._memory._client.search(
                workspace_id=ws_id,
                query=query,
                limit=limit,
                semantic=True,
            )
            # Filter to node-type results only
            node_rows = [r for r in semantic_rows if r.get("entity_type") == "node"]
            if node_rows:
                results = []
                for r in node_rows[:limit]:
                    nid = r.get("entity_id", "")
                    if not nid:
                        continue
                    rows = self._memory._client._query(
                        "kg_node",
                        filter_dict={"id": nid},
                    )
                    if rows:
                        n = rows[0]
                        results.append(
                            {
                                "id": n.get("id", ""),
                                "label": n.get("label", ""),
                                "node_type": n.get("node_type", "entity"),
                                "entity_type": n.get("node_type", "entity"),
                                "summary": n.get("summary", ""),
                                "metadata_json": n.get("metadata_json", "{}"),
                                "created_at": n.get("created_at", 0),
                                "score": r.get("score", 0.0),
                            }
                        )
                if results:
                    return self._tag_filter(results, tag)[:limit]
        except RuntimeError:
            pass  # Embedder down or hybrid_search fails → fallback

        # ── Tantivy BM25 search fallback (better than substring) ──
        try:
            tantivy_hits = self._memory._client._tantivy_search(
                workspace_id=ws_id,
                query=query,
                limit=limit,
            )
            if tantivy_hits:
                results = []
                for th in tantivy_hits[:limit]:
                    nid = th.get("entity_id", "")
                    etype = th.get("entity_type", "node")
                    if not nid:
                        continue
                    if etype == "node":
                        rows = self._memory._client._query(
                            "kg_node",
                            filter_dict={"id": nid},
                        )
                        if rows:
                            n = rows[0]
                            results.append(
                                {
                                    "id": n.get("id", ""),
                                    "label": n.get("label", ""),
                                    "node_type": n.get("node_type", "entity"),
                                    "entity_type": n.get("node_type", "entity"),
                                    "summary": n.get("summary", ""),
                                    "metadata_json": n.get("metadata_json", "{}"),
                                    "created_at": n.get("created_at", 0),
                                    "score": th.get("score", 0.0),
                                }
                            )
                    elif etype == "memory":
                        rows = self._memory._client._query(
                            "memory",
                            filter_dict={"id": nid},
                        )
                        if rows:
                            m = rows[0]
                            results.append(
                                {
                                    "id": m.get("id", ""),
                                    "label": m.get("content", "")[:80],
                                    "node_type": "memory",
                                    "entity_type": "memory",
                                    "summary": m.get("summary", ""),
                                    "metadata_json": "{}",
                                    "created_at": m.get("created_at", 0),
                                    "score": th.get("score", 0.0),
                                }
                            )
                if results:
                    return self._tag_filter(results, tag)[:limit]
        except RuntimeError:
            pass

        # Fallback: substring match on entity_link or kg_node
        # Try entity_link path
        try:
            try:
                self._memory._client.resolve_entity(ws_id, query)
            except RuntimeError:
                pass

            rows = self._memory._client._query("entity_link", workspace_id=ws_id)
            q = query.lower()
            matched = [r for r in rows if q in r.get("entity_name", "").lower()]
            filtered = self._tag_filter(matched, tag)
            return [self._entity_link_to_dict(r, tag) for r in filtered[:limit]]
        except RuntimeError:
            logger.debug("entity_link unavailable for graph.search, falling back to kg_node")

        rows = self._call("query_graph", workspace_id=ws_id, query=query)
        filtered = self._tag_filter(rows, tag)
        return filtered[:limit]

    def get_all(
        self,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List all graph entities for a user.

        Queries the ``entity_link`` table.  Falls back to ``query_graph``
        (kg_node) if entity_link is not available.

        Args:
            user_id: Owner user.
            limit: Max results (default 100).

        Returns:
            List of entity records.
        """
        ws_id = self._ws(user_id)
        tag = self._tag(user_id)

        # Try entity_link first
        try:
            rows = self._memory._client._query("entity_link", workspace_id=ws_id)
            filtered = self._tag_filter(rows, tag)
            return [self._entity_link_to_dict(r, tag) for r in filtered[:limit]]
        except RuntimeError:
            # Graceful fallback to kg_node
            logger.debug("entity_link unavailable for graph.get_all, falling back to kg_node")

        rows = self._call("query_graph", workspace_id=ws_id, query="")
        filtered = self._tag_filter(rows, tag)
        return filtered[:limit]

    def delete(self, entity_id: str) -> dict[str, Any]:
        """Delete a graph entity by node ID.

        Deletes via ``delete_node`` (kg_node).  Entity link deletion is
        not yet supported by the server-side reducer; entity_link rows
        are left in place for now.

        Args:
            entity_id: The UUID to remove.

        Returns:
            Operation status dict.
        """
        # Soft-delete: set is_active=False via the delete_node reducer
        self._call("delete_node", entity_id)
        return {"status": "ok", "deleted": entity_id}


def _resolve_llm(
    llm_config: dict[str, Any] | None = None,
) -> LLMClient | None:
    """Resolve an ``LLMClient``, optionally with custom per-user config.

    ``llm_config`` can contain:
        - ``model`` (default ``"gpt-4o-mini"``)
        - ``api_key`` (per-user override)
        - ``base_url`` (custom endpoint)

    Returns ``None`` if no ``OPENAI_API_KEY`` is available.
    """
    if not llm_config:
        return LLMClient()
    return LLMClient(
        model=llm_config.get("model", "gpt-4o-mini"),
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("base_url"),
    )
