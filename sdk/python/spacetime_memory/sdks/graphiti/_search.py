"""Graphiti search mixin — hybrid search, entity edge summary, episode lookup."""

from __future__ import annotations

import logging
from typing import Any

from ._models import (
    EntityEdge,
    EntityNode,
    SearchResults,
)

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class GraphitiSearch:
    """Mixin providing search and related methods."""

    DEFAULT_SEARCH_LIMIT = 10

    def search(
        self,
        query: str,
        center_node_uuid: str | None = None,
        group_ids: list[str] | None = None,
        num_results: int = DEFAULT_SEARCH_LIMIT,
        search_filter: Any | None = None,
        driver: Any | None = None,
        **kwargs: Any,
    ) -> list[EntityEdge]:
        """Perform hybrid search over the knowledge graph.

        Searches by semantic similarity and returns the most relevant
        entity edges (facts).

        Args:
            query: The search query string.
            center_node_uuid: Not supported (accepted for compat).
            group_ids: List of workspace names to search.
            num_results: Max results to return (default 10).
            search_filter: Not supported (accepted for compat with graphiti-core).
            driver: Not supported (accepted for compat with graphiti-core).
            **kwargs: Additional parameters:
                valid_at_after (datetime | None): If set, only return
                    edges whose ``valid_at`` is >= this datetime.
                valid_at_before (datetime | None): If set, only return
                    edges whose ``valid_at`` is <= this datetime.
                Other kwargs are accepted for compat and ignored.

        Returns:
            List of :class:`EntityEdge` objects sorted by relevance.
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)
        limit = num_results or self.DEFAULT_SEARCH_LIMIT

        rows = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=limit,
            semantic=True,
        )

        # Collect all node IDs referenced in hybrid results, then fetch
        # the actual edges connected to those nodes (Graphiti returns
        # EntityEdge objects, not raw rows).
        node_ids_to_lookup: set[str] = set()
        edge_ids_to_lookup: set[str] = set()
        for row in rows:
            eid = row.get("entity_id", "")
            etype = row.get("entity_type", "")
            if etype == "node" and eid:
                node_ids_to_lookup.add(eid)
            elif etype == "edge" and eid:
                edge_ids_to_lookup.add(eid)

        # Look up edges connected to found nodes
        edges: list[EntityEdge] = []
        seen_edge_ids: set[str] = set()
        for nid in node_ids_to_lookup:
            try:
                neighbor_rows = self._client.get_neighbors(nid, workspace_id=ws_id)
            except RuntimeError:
                neighbor_rows = []
            for row in neighbor_rows:
                eid = row.get("id", "")
                if eid and eid not in seen_edge_ids:
                    seen_edge_ids.add(eid)
                    edges.append(EntityEdge.from_stmem(row))

        # Look up edges by ID
        for eid in edge_ids_to_lookup:
            if eid not in seen_edge_ids:
                seen_edge_ids.add(eid)
                edge_rows = self._client._query("kg_edge", filter_dict={"id": eid})
                if edge_rows:
                    edges.append(EntityEdge.from_stmem(edge_rows[0]))

        # If no edges found via hybrid result IDs, try a direct KG query
        # as a fallback
        if not edges:
            try:
                all_nodes = self._client.query_graph(workspace_id=ws_id, query=query)
                for n in all_nodes:
                    nid = n.get("id", "")
                    if nid:
                        try:
                            neighbor_rows = self._client.get_neighbors(nid, workspace_id=ws_id)
                        except RuntimeError:
                            continue
                        for row in neighbor_rows:
                            eid = row.get("id", "")
                            if eid and eid not in seen_edge_ids:
                                seen_edge_ids.add(eid)
                                edges.append(EntityEdge.from_stmem(row))
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data

        # Apply time-range filter on valid_at (if provided)
        valid_at_after = kwargs.get("valid_at_after")
        valid_at_before = kwargs.get("valid_at_before")
        if valid_at_after is not None or valid_at_before is not None:
            edges = self._filter_by_valid_at(edges, valid_at_after, valid_at_before)

        # Sort by score if available, then by name
        def _sort_key(e: EntityEdge) -> tuple[float, str]:
            """Sort key for ordering entities."""
            score = getattr(e, "_score", None)
            try:
                return (0 - float(score)) if score is not None else (1, e.name)
            except (TypeError, ValueError):
                return (1, e.name)

        edges.sort(key=_sort_key)
        return edges[:limit]


    def search_(
        self,
        query: str,
        config: Any = None,
        group_ids: list[str] | None = None,
        center_node_uuid: str | None = None,
        bfs_origin_node_uuids: list[str] | None = None,
        search_filter: Any | None = None,
        **kwargs: Any,
    ) -> SearchResults:
        """Advanced search returning nodes and edges.

        Searches the knowledge graph and returns structured results
        with both ``EntityNode`` and ``EntityEdge`` objects.

        Args:
            query: The search query string.
            config: Search config — supports Graphiti's ``SearchConfig``
                shape (``search_strategy``, ``hybrid_mode``,
                ``cross_encoder``, ``mmr_strength``) plus plain dicts.
                Recognised fields:
                  - ``search_strategy``: "semantic" | "keyword" |
                    "hybrid" (default hybrid)
                  - ``hybrid_mode``: ``"fusion"`` (default) or
                    ``"relaxed"`` — fusion keeps the weighted min-max
                    blend; relaxed is a simple union fallback.
                  - ``cross_encoder``: bool — run the local ONNX
                    cross-encoder rerank (default False).
                  - ``mmr_strength``: float 0–1 — MMR diversity rerank
                    strength (default 0.0 = disabled).
            group_ids: List of workspace names.
            center_node_uuid: Not supported (accepted for compat).
            bfs_origin_node_uuids: Not supported (accepted for compat).
            search_filter: Not supported (accepted for compat).
            **kwargs: Additional parameters (accepted for compat).

        Returns:
            :class:`SearchResults` with ``edges`` and ``nodes``.
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)

        # ── Recipe resolution from config ──
        strategy = "hybrid"
        hybrid_mode = "fusion"
        cross_encoder = False
        mmr_strength = 0.0
        if config is not None:
            if hasattr(config, "model_dump"):  # pydantic SearchConfig
                cfg = config.model_dump()
            elif isinstance(config, dict):
                cfg = config
            else:
                cfg = getattr(config, "__dict__", {})
            strategy = (
                cfg.get("search_strategy")
                or cfg.get("strategy")
                or strategy
            )
            hybrid_mode = cfg.get("hybrid_mode") or hybrid_mode
            cross_encoder = bool(cfg.get("cross_encoder", False))
            mmr_strength = float(cfg.get("mmr_strength", cfg.get("mmr", 0.0)) or 0.0)

        semantic = strategy != "keyword"
        mmr_lambda = mmr_strength if mmr_strength > 0 else 0.0

        results = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=20,
            semantic=semantic,
            cross_encoder=cross_encoder,
            mmr_lambda=mmr_lambda,
        )
        if hybrid_mode == "relaxed" and not results:
            # Relaxed mode: pure keyword fallback when fusion found nothing
            results = self._client.search(
                workspace_id=ws_id,
                query=query,
                limit=20,
                semantic=False,
            )

        edges: list[EntityEdge] = []
        nodes: list[EntityNode] = []
        seen_node_ids: set[str] = set()
        seen_edge_ids: set[str] = set()

        for row in results:
            entity_id = row.get("entity_id", "")
            entity_type = row.get("entity_type", "")

            if entity_type == "node" and entity_id and entity_id not in seen_node_ids:
                seen_node_ids.add(entity_id)
                node_rows = self._client._query("kg_node", filter_dict={"id": entity_id})
                if node_rows:
                    nodes.append(EntityNode.from_stmem(node_rows[0]))

            elif entity_type == "edge" and entity_id and entity_id not in seen_edge_ids:
                seen_edge_ids.add(entity_id)
                edge_rows = self._client._query("kg_edge", filter_dict={"id": entity_id})
                if edge_rows:
                    edges.append(EntityEdge.from_stmem(edge_rows[0]))

        # Also fetch all nodes in the workspace for context
        if not nodes:
            try:
                all_nodes = self._client.query_graph(workspace_id=ws_id)
                for n in all_nodes:
                    nid = n.get("id", "")
                    if nid not in seen_node_ids:
                        seen_node_ids.add(nid)
                        nodes.append(EntityNode.from_stmem(n))
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data

        # Apply time-range filter on edges (if provided)
        valid_at_after = kwargs.get("valid_at_after")
        valid_at_before = kwargs.get("valid_at_before")
        if valid_at_after is not None or valid_at_before is not None:
            edges = self._filter_by_valid_at(edges, valid_at_after, valid_at_before)

        return SearchResults(edges=edges, nodes=nodes)


    def get_entity_edge_summary(
        self,
        entity_names: list[str],
        group_ids: list[str],
    ) -> dict[str, Any]:
        """Get all edges connected to an entity node (Graphiti-parity).

        Args:
            entity_names: Names of the entity nodes to summarize. Graphiti
                resolves names → node UUIDs internally; we do the same via
                search before fetching neighbours.
            group_ids: Workspace names/UUIDs to scope the query.

        Returns:
            Dict with ``edges`` (list of EntityEdge), ``nodes`` (list of
            connected EntityNode), ``summary`` (concatenated facts).
        """
        # Accept both upstream list args and a single string convenience
        names = [entity_names] if isinstance(entity_names, str) else list(entity_names or [])
        groups = [group_ids] if isinstance(group_ids, str) else list(group_ids or [])
        gid = groups[0] if groups else "default"
        ws_id = self._resolve_workspace(gid)

        edge_rows: list[dict[str, Any]] = []
        node_ids: set[str] = set()
        for name in names:
            resolved = self._resolve_entity_uuid(name, ws_id)
            if resolved is None:
                continue
            try:
                rows = self._client.get_neighbors(resolved, workspace_id=ws_id)
            except RuntimeError:
                continue
            edge_rows.extend(rows)
            node_ids.add(resolved)

        edges: list[EntityEdge] = []
        for row in edge_rows:
            edges.append(EntityEdge.from_stmem(row))
            src = row.get("source_node_id", "")
            tgt = row.get("target_node_id", "")
            if src:
                node_ids.add(src)
            if tgt:
                node_ids.add(tgt)

        nodes: list[EntityNode] = []
        for nid in list(node_ids):
            nrows = self._client.get_node(nid)
            if nrows:
                nodes.append(EntityNode.from_stmem(nrows[0]))

        summary = " ".join(e.fact for e in edges if getattr(e, "fact", None))
        return {"edges": edges, "nodes": nodes, "summary": summary}

    def _resolve_entity_uuid(self, name: str, ws_id: str) -> str | None:
        """Resolve an entity NAME to its node UUID by querying kg_node."""
        try:
            rows = self._client._query("kg_node", workspace_id=ws_id, filter_dict={"label": name})
        except (RuntimeError, TypeError):
            rows = []
        if not rows:
            try:
                rows = self._client._query("kg_node", workspace_id=ws_id)
            except (RuntimeError, TypeError):
                rows = []
            rows = [r for r in rows
                    if str(r.get("label", "")).lower() == name.lower()]
        else:
            # _query may or may not apply the filter server-side; keep exact
            rows = [r for r in rows
                    if str(r.get("label", "")).lower() == name.lower()] or rows
        for n in rows:
            nid = n.get("id", "") if isinstance(n, dict) else getattr(n, "id", "")
            if nid:
                return nid
        return None

    # -------------------------------------------------------------------
    # Community detection
    # -------------------------------------------------------------------


    def get_nodes_and_edges_by_episode(self, episode_uuids: list[str]) -> SearchResults:
        """Get nodes and edges associated with episodes.

        Args:
            episode_uuids: List of episode UUIDs.

        Returns:
            :class:`SearchResults` with matching nodes and edges.
        """
        nodes: list[EntityNode] = []
        edges: list[EntityEdge] = []

        for ep_uuid in episode_uuids:
            memories = self._client._query(
                "memory", filter_dict={"source_session_id": ep_uuid}, columns=["id", "content"]
            )

            if not memories:
                continue

            # Find memory IDs for this episode, then look up edges by source_node_id
            mems = self._client._query(
                "memory", filter_dict={"source_session_id": ep_uuid}, columns=["id"]
            )
            edge_rows = []
            for mem in mems:
                edges = self._client._query(
                    "kg_edge", filter_dict={"source_node_id": mem.get("id", "")}
                )
                edge_rows.extend(edges)

            for row in edge_rows:
                edge = EntityEdge.from_stmem(row)
                if edge.uuid not in [e.uuid for e in edges]:
                    edges.append(edge)

        return SearchResults(edges=edges, nodes=nodes)


# ---------------------------------------------------------------------------
# Namespace classes (nodes.* / edges.*)
# ---------------------------------------------------------------------------


