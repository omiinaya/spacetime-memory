"""Compounder workflows — search methods."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)




class CompounderWorkflowsSearch:
    """Mixin — search methods."""


    def search_entities(
        self,
        workspace_id: str = "default",
        label: str | None = None,
        node_type: str | None = None,
        semantic_query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search knowledge-graph entities with flexible filters.

        Supports three modes that can be combined:

        * **Label search** — find entities by exact ``label`` match.
        * **Type filter** — find all entities of a given ``node_type``
          (e.g. ``"person"``, ``"concept"``, ``"org"``).
        * **Semantic search** — find entities whose label or summary
          is semantically related to *semantic_query* using the
          hybrid search engine.

        Examples::

            # All person entities
            cp.search_entities(node_type="person")

            # Find entity with specific label
            cp.search_entities(label="RLHF")

            # Semantic search for concept nodes
            cp.search_entities(
                node_type="concept",
                semantic_query="machine learning optimization",
                limit=10,
            )

        Args:
            workspace_id: Target workspace.
            label: Optional exact label to search for.
            node_type: Optional node type filter
                (e.g. ``"person"``, ``"concept"``, ``"org"``,
                 ``"product"``, ``"location"``, ``"event"``, ``"topic"``).
            semantic_query: Optional natural-language query for
                semantic entity search.
            limit: Max results to return (default: 20).

        Returns:
            List of matching ``kg_node`` dicts, each with ``id``,
            ``label``, ``node_type``, ``summary``, ``metadata_json``,
            ``source_memory_id``, and timestamp fields.
        """
        # ── Structured filter query ──
        filter_dict: dict[str, Any] = {}
        if label is not None:
            filter_dict["label"] = label
        if node_type is not None:
            filter_dict["node_type"] = node_type

        filtered_results: list[dict[str, Any]] = []
        if filter_dict:
            filtered_results = self._client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict=filter_dict,
            )

        # ── Semantic search results ──
        # The hybrid_search reducer indexes kg_node content via
        # index_entity with entity_type="node".  Search results with
        # entity_type == "node" carry an entity_id that maps to kg_node.id.
        semantic_node_ids: set[str] = set()
        if semantic_query:
            search_results = self._client.search(
                workspace_id,
                semantic_query,
                limit=limit,
                semantic=True,
                memory_type="",
                tier="",
            )
            for r in search_results:
                if r.get("entity_type") == "node":
                    nid = r.get("entity_id", "")
                    if nid:
                        semantic_node_ids.add(nid)

        # If we have semantic hits, look up the full kg_node records
        semantic_results: list[dict[str, Any]] = []
        if semantic_node_ids:
            all_nodes = self._client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={},
            )
            node_map = {n.get("id", ""): n for n in all_nodes}
            for nid in semantic_node_ids:
                if nid in node_map:
                    semantic_results.append(node_map[nid])

        # ── Merge: semantic results first, then filtered results ──
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for n in semantic_results:
            nid = n.get("id", "")
            if nid and nid not in seen:
                merged.append(n)
                seen.add(nid)
        for n in filtered_results:
            nid = n.get("id", "")
            if nid and nid not in seen:
                merged.append(n)
                seen.add(nid)

        return merged[:limit]



    def find_near_duplicates(
        self,
        content: str,
        workspace_id: str = "default",
        threshold: float = 0.92,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find memories with semantically similar content.

        Uses the existing hybrid search pipeline to find content that
        is nearly identical to *content*.  A threshold of 0.92 (default)
        catches rephrasings of the same fact while letting novel content
        through.

        Args:
            content: The text to check for duplicates.
            workspace_id: Target workspace.
            threshold: Minimum similarity score to consider a duplicate
                (0.0-1.0).  Default 0.92 works well for BGE-M3 embeddings.
            limit: Max candidate duplicates to return.

        Returns:
            List of matching memory/note dicts with keys ``entity_id``,
            ``content``, ``score``, ``entity_type``.  Empty list when
            no near-duplicates are found.
        """
        if not content.strip():
            return []

        results = self._client.search(
            workspace_id,
            query=content,
            limit=limit,
            semantic=True,
            memory_type="",
            tier="",
        )
        duplicates = [r for r in results if r.get("score", 0.0) >= threshold]
        return duplicates

