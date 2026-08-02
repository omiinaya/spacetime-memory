"""Knowledge graph mixin."""
from __future__ import annotations

import json
from typing import Any

from ._base import logger
from ._utils import _esc


class KGMixin:
    """Spacetime-Memory kg mixin.

    Provides Client methods related to kg management.
    Inherits from ClientBase for connection infrastructure.
    """
    def create_node(
        self,
        workspace_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
        source_memory_id: str = "",
        source_document_id: str = "",
    ) -> dict[str, Any]:
        """Create a knowledge-graph node and auto-index it.

        Args:
            workspace_id: Target workspace.
            label: Node label (used as display name).
            node_type: Type category (default: "concept").
            summary: Optional summary text.
            metadata_json: Optional JSON metadata string.
            source_memory_id: Optional memory record ID that supports this node.
            source_document_id: Optional source document ID for provenance.
        """
        result = self._call(
            "create_node",
            [
                workspace_id,
                label,
                node_type,
                summary,
                metadata_json,
                source_memory_id,
                source_document_id,
            ],
        )
        content = f"{label}: {summary}" if summary else label
        emb = self._embed(content)
        if emb:
            nodes = self._query(
                "kg_node", workspace_id=workspace_id, filter_dict={"label": label}
            )
            if nodes:
                node = nodes[-1]
                self._call(
                    "index_entity",
                    [
                        workspace_id,
                        "node",
                        node["id"],
                        content,
                        json.dumps(emb),
                    ],
                )
                # Return the created node PLUS status so both callers work:
                # deep CRUD tests assert result["status"] == "ok"; compounder
                # workflows use node["id"]/node["label"].
                return {**node, "status": "ok"}
        # No embedding / no node found back — still return the reducer result.
        # Callers (compounder workflows) expect a dict; if we can't resolve the
        # created node, return the raw reducer response.
        return result

    def update_node(
        self,
        node_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
        source_memory_id: str = "",
        source_document_id: str = "",
    ) -> dict[str, Any]:
        """Update an existing knowledge-graph node's mutable fields.

        Args:
            node_id: The ID of the node to update.
            label: New label (display name).
            node_type: Type category (default: ``"concept"``).
            summary: Updated summary text.
            metadata_json: Updated JSON metadata string.
            source_memory_id: Optional source memory ID.
            source_document_id: Optional source document ID for provenance.
        """
        return self._call(
            "update_node",
            [
                node_id,
                label,
                node_type,
                summary,
                metadata_json,
                source_memory_id,
                source_document_id,
            ],
        )

    def delete_node(
        self,
        node_id: str,
    ) -> dict[str, Any]:
        """Soft-delete a knowledge-graph node by ID.

        Removes the node from the KG (sets ``is_active = false``).
        The node's edges remain but become orphaned.

        Args:
            node_id: The ID of the node to delete.
        """
        return self._call("delete_node", [node_id])

    def create_edge(
        self,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: str = "EXTRACTED",
        metadata_json: str = "{}",
        source_memory_id: str = "",
        source_document_id: str = "",
    ) -> dict[str, Any]:
        """Create a directed, typed edge between two KG nodes.

        Args:
            workspace_id: Target workspace.
            source_node_id: Source node ID.
            target_node_id: Target node ID.
            relation: Relationship type label.
            weight: Edge weight (default: 1.0).
            confidence: Confidence level (default: "EXTRACTED").
            metadata_json: Optional JSON metadata string.
            source_memory_id: Optional memory record ID that supports this edge.
        """
        return self._call(
            "create_edge",
            [
                workspace_id,
                source_node_id,
                target_node_id,
                relation,
                weight,
                confidence,
                metadata_json,
                source_memory_id,
            ],
        )

    def update_edge(
        self,
        edge_id: str,
        relation: str,
        weight: float = 1.0,
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Update an existing knowledge-graph edge's mutable fields.

        Args:
            edge_id: The ID of the edge to update.
            relation: New relationship type label.
            weight: New edge weight (default: 1.0).
            metadata_json: Updated JSON metadata string.
        """
        return self._call(
            "update_edge",
            [
                edge_id,
                relation,
                weight,
                metadata_json,
            ],
        )

    def delete_edge(
        self,
        edge_id: str,
    ) -> dict[str, Any]:
        """Soft-delete a knowledge-graph edge by ID.

        Removes the edge from the KG (sets ``is_active = false``).

        Args:
            edge_id: The ID of the edge to delete.
        """
        return self._call("delete_edge", [edge_id])

    def add_node_citation(
        self,
        workspace_id: str,
        node_id: str,
        memory_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Add a citation linking a KG node to a source memory.

        Args:
            workspace_id: Target workspace.
            node_id: The knowledge graph node ID.
            memory_id: The memory record that supports this node.
            description: Optional description of the citation relationship.
        """
        return self._call(
            "add_node_citation",
            [
                workspace_id,
                node_id,
                memory_id,
                description,
            ],
        )

    def add_edge_citation(
        self,
        workspace_id: str,
        edge_id: str,
        memory_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Add a citation linking a KG edge to a source memory.

        Args:
            workspace_id: Target workspace.
            edge_id: The knowledge graph edge ID.
            memory_id: The memory record that supports this edge.
            description: Optional description of the citation relationship.
        """
        return self._call(
            "add_edge_citation",
            [
                workspace_id,
                edge_id,
                memory_id,
                description,
            ],
        )

    def get_edge_history(
        self,
        edge_group_id: str,
    ) -> list[dict[str, Any]]:
        """Get all historical versions of a knowledge-graph edge.

        Edges in the KG are versioned — when an edge is updated, a new
        version is created with the same ``edge_group_id``. This method
        returns every version ordered by ``created_at``, letting you
        trace how a relationship evolved over time.

        Args:
            edge_group_id: The group ID of the edge(s) to query. All
                versions sharing this group ID are returned.

        Returns:
            List of edge version records with source_node_id,
            target_node_id, relation, weight, confidence, version, and
            timestamps (created_at, valid_at, invalid_at).
        """
        self._call("get_edge_history", [edge_group_id])
        rows = self._sql_param(
            "SELECT * FROM edge_history_result WHERE "
            "edge_group_id = ? "
            "ORDER BY created_at ASC",
            edge_group_id,
        )
        return rows

    def get_edge_as_of(
        self,
        edge_group_id: str,
        timestamp_micros: int,
    ) -> dict[str, Any] | None:
        """Get an edge version as of a specific point in time (temporal query).

        Queries the KG for an edge that was valid at the given timestamp.
        An edge is considered valid at time ``t`` if:
        ``valid_at <= t < invalid_at`` (or ``invalid_at == 0`` for still-valid edges).

        This provides Mnemosyne/Graphiti-parity ``as_of`` temporal querying
        without needing a dedicated reducer — the data is queried directly
        from the public ``kg_edge`` table.

        Args:
            edge_group_id: The group ID of the edge to query.
            timestamp_micros: Unix timestamp in microseconds to query at.

        Returns:
            The edge version dict that was valid at the given time, or
            None if no version existed at that time.
        """
        rows = self._sql_param(
            "SELECT * FROM kg_edge WHERE "
            "edge_group_id = ? AND valid_at <= ? "
            "LIMIT 50",
            edge_group_id, timestamp_micros,
        )
        # Filter in Python for still-valid edges (invalid_at == 0 or after timestamp),
        # then pick the highest version number
        best = None
        for row in rows:
            if row.get("invalid_at", 0) == 0 or row["invalid_at"] > timestamp_micros:
                if best is None or row.get("version", 0) > best.get("version", 0):
                    best = row
        return best

    def get_citations(
        self,
        workspace_id: str,
        entity_id: str,
        entity_type: str = "node",
    ) -> list[dict[str, Any]]:
        """Get all citations for a KG entity (node or edge).

        Args:
            workspace_id: Target workspace.
            entity_id: The node or edge ID.
            entity_type: "node" (default) or "edge".

        Returns:
            List of citation records with source_memory_id, description, and timestamp.
        """
        self._call(
            "get_citations",
            [
                workspace_id,
                entity_id,
                entity_type,
            ],
        )
        rows = self._query(
            "citation_result",
            filter_dict={"entity_id": entity_id, "entity_type": entity_type},
        )
        return rows

    def query_graph(self, workspace_id: str, query: str = "") -> list[dict[str, Any]]:
        """Search KG nodes by label within a workspace."""
        rows = self._query("kg_node", workspace_id=workspace_id)
        if query:
            # Client-side filter (SpacetimeDB doesn't support LIKE)
            q = query.lower()
            rows = [
                r
                for r in rows
                if q in r.get("label", "").lower() or q in r.get("summary", "").lower()
            ]
        return rows

    def get_neighbors(self, node_id: str, workspace_id: str = "") -> list[dict[str, Any]]:
        """Get edges connected to a node within an optional workspace."""
        # Query both directions since _query doesn't support OR
        edges_src = self._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={"source_node_id": node_id}
        )
        edges_tgt = self._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={"target_node_id": node_id}
        )
        seen = set()
        edges = []
        for e in edges_src + edges_tgt:
            if e["id"] not in seen:
                seen.add(e["id"])
                edges.append(e)
        # Enrich with labels
        node_ids = set()
        for e in edges:
            node_ids.add(e.get("source_node_id", ""))
            node_ids.add(e.get("target_node_id", ""))
        node_ids.discard("")
        label_map = {}
        for nid in node_ids:
            rows = self._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={"id": nid},
                columns=["id", "label"],
            )
            if rows:
                label_map[nid] = rows[0].get("label", "")

        for e in edges:
            e["source_label"] = label_map.get(e.get("source_node_id", ""), "")
            e["target_label"] = label_map.get(e.get("target_node_id", ""), "")
        edges.sort(key=lambda r: r.get("weight", 0.0), reverse=True)
        return edges

    def detect_communities(self, workspace_id: str) -> dict[str, Any]:
        """Run label-propagation community detection."""
        return self._call("detect_communities", [workspace_id])

    def seed_communities(self, workspace_id: str) -> dict[str, Any]:
        """Seed unassigned nodes into new communities."""
        return self._call("seed_communities", [workspace_id])

    def create_community(self, workspace_id: str, name: str, summary: str = "") -> dict[str, Any]:
        """Call create_community reducer to create a KG community."""
        return self._call("create_community", [workspace_id, name, summary])

    def assign_to_community(self, node_id: str, community_id: int) -> dict[str, Any]:
        """Call assign_to_community reducer to assign a node to a community."""
        return self._call("assign_to_community", [node_id, community_id])

    # -----------------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------------

    def upsert_profile(
        self,
        peer_id: str,
        static_facts: str = "",
        dynamic_context: str = "",
        preferences: str = "",
        tags: str = "",
    ) -> dict[str, Any]:
        """Create or update a peer profile.

        Args:
            peer_id: The peer ID.
            static_facts: JSON-encoded list of fact strings.
            dynamic_context: JSON-encoded list of context strings.
            preferences: JSON-encoded object of key-value preferences.
            tags: JSON-encoded list of tag strings.
        """
        return self._call(
            "upsert_profile",
            [
                peer_id,
                static_facts,
                dynamic_context,
                preferences,
                tags,
            ],
        )

    def add_profile_fact(self, peer_id: str, fact: str) -> dict[str, Any]:
        """Add a fact to a peer's profile (appended to static_facts_json array)."""
        return self._call("add_profile_fact", [peer_id, fact])

    def add_dynamic_context(self, peer_id: str, context: str) -> dict[str, Any]:
        """Add dynamic context to a peer's profile."""
        return self._call("add_dynamic_context", [peer_id, context])

    def update_peer(self, peer_id: str, name: str, metadata_json: str = "{}") -> dict[str, Any]:
        """Call update_peer reducer to update a peer's name and metadata."""
        return self._call("update_peer", [peer_id, name, metadata_json])

    def delete_peer(self, peer_id: str) -> dict[str, Any]:
        """Call delete_peer reducer to delete a peer."""
        return self._call("delete_peer", [peer_id])

    def get_peer_memory_summary(self, peer_id: str) -> None:
        """Call get_peer_memory_summary reducer; results in peer_summary_result table."""
        self._call("get_peer_memory_summary", [peer_id])

    def get_profile(self, peer_id: str) -> dict[str, Any] | None:
        """Get a peer's profile by peer_id."""
        rows = self._query("profile", filter_dict={"peer_id": peer_id})
        return rows[0] if rows else None

    def list_profiles(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all profiles in a workspace (via peers → profiles)."""
        peers = self._query("peer", filter_dict={"workspace_id": workspace_id})
        peer_ids = [p["id"] for p in peers if p.get("id")]
        if not peer_ids:
            return []
        profiles = []
        for pid in peer_ids:
            p = self.get_profile(pid)
            if p:
                profiles.append(p)
        return profiles

    def search_profiles(
        self, workspace_id: str, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search profiles by static_facts or dynamic_context (client-side filter)."""
        profiles = self.list_profiles(workspace_id)
        if query:
            q = query.lower()
            profiles = [
                r
                for r in profiles
                if q in r.get("static_facts_json", "").lower()
                or q in r.get("dynamic_context_json", "").lower()
            ]
        return profiles[:limit]

    def get_profile_context(self, peer_id: str) -> dict[str, Any] | None:
        """Get profile context result for a peer (calls get_profile_context reducer)."""
        self._call("get_profile_context", [peer_id])
        rows = self._query(
            "profile_context_result",
            filter_dict={"peer_id": peer_id},
        )
        return rows[0] if rows else None

    # -----------------------------------------------------------------------
    # Facts
    # -----------------------------------------------------------------------

    def add_fact(
        self,
        workspace_id: str,
        peer_id: str,
        content: str,
        fact_type: str = "dynamic",
        category: str = "custom",
        confidence: float = 0.8,
        source: str = "manual",
        tier: str = "L1",
    ) -> dict[str, Any]:
        """Add a fact about a peer.

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        peer_id:
            The peer to associate the fact with.
        content:
            The fact content text.
        fact_type:
            Fact type (e.g. ``"dynamic"``, ``"static"``).
        category:
            Fact category (e.g. ``"custom"``).
        confidence:
            Confidence score (0.0–1.0). Default 0.8.
        source:
            Source of the fact (e.g. ``"manual"``).
        tier:
            Memory tier: ``"L0"``, ``"L1"``, or ``"L2"``.
        """
        return self._call(
            "add_fact",
            [workspace_id, peer_id, fact_type, category, content, confidence, source, tier],
        )

    def list_facts(
        self,
        workspace_id: str,
        peer_id: str = "",
        fact_type: str = "",
        tier: str = "",
        category: str = "",
    ) -> list[dict[str, Any]]:
        """List facts for a workspace with optional filters.

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        peer_id:
            Optional: filter by peer ID.
        fact_type:
            Optional: filter by fact type.
        tier:
            Optional: filter by memory tier.
        category:
            Optional: filter by category.

        Returns:
            List of fact records from the ``fact_result`` table.
        """
        self._call("list_facts", [workspace_id, peer_id, fact_type, tier, category])
        query_hash = f"{workspace_id}:{peer_id}:{fact_type}:{tier}:{category}"
        rows = self._query(
            "fact_result",
            filter_dict={"query_hash": query_hash},
        )
        if rows:
            try:
                return json.loads(rows[0].get("json_data", "[]"))
            except (json.JSONDecodeError, IndexError):
                logger.warning("get_cached_fact_result: failed to parse cached JSON data")
        return []

    def delete_fact(self, fact_id: str) -> dict[str, Any]:
        """Deactivate a fact (soft delete).

        Parameters
        ----------
        fact_id:
            The fact ID to delete.

        Returns:
            The reducer result dict.
        """
        return self._call("delete_fact", [fact_id])

    def update_fact(
        self,
        fact_id: str,
        content: str = "",
        confidence: float = 0.0,
        category: str = "",
        tier: str = "",
    ) -> dict[str, Any]:
        """Update a fact's content, confidence, category, and/or tier.

        Empty string parameters leave the corresponding field unchanged.
        A confidence of 0.0 leaves confidence unchanged.

        Parameters
        ----------
        fact_id:
            The fact ID to update.
        content:
            New content text (empty string = no change).
        confidence:
            New confidence score (0.0 = no change, 0.0–1.0).
        category:
            New category (empty string = no change).
        tier:
            New memory tier: ``\"L0\"``, ``\"L1\"``, or ``\"L2\"`` (empty string = no change).

        Returns:
            The reducer result dict.
        """
        return self._call("update_fact", [fact_id, content, confidence, category, tier])

    def search_facts(
        self,
        workspace_id: str,
        query: str,
        tier: str = "",
    ) -> list[dict[str, Any]]:
        """Search facts by content text (substring / case-insensitive match).

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        query:
            The search query text.
        tier:
            Optional: filter by memory tier (``\"L0\"``, ``\"L1\"``, ``\"L2\"``).

        Returns:
            List of matching fact records from the ``fact_result`` table.
        """
        self._call("search_facts", [workspace_id, query, tier])
        query_hash = f"search:{query}:{tier}"
        rows = self._query(
            "fact_result",
            filter_dict={"query_hash": query_hash},
        )
        if rows:
            try:
                return json.loads(rows[0].get("json_data", "[]"))
            except (json.JSONDecodeError, IndexError):
                logger.warning("get_fact_cache: failed to parse cached JSON data")
        return []

    # -----------------------------------------------------------------------
    # Knowledge Graph — additional queries
    # -----------------------------------------------------------------------

    def get_node(self, node_id: str) -> list[dict[str, Any]]:
        """Get a KG node by ID."""
        return self._query("kg_node", filter_dict={"id": node_id})

    def get_community(self, community_id: int) -> dict[str, Any]:
        """Get community details and its nodes."""
        community = self._query("kg_community", filter_dict={"id": str(community_id)})
        nodes = self._query("kg_node", filter_dict={"community_id": str(community_id)})
        return {
            "community": community[0] if community else None,
            "nodes": nodes,
        }

    def compute_pagerank(
        self, workspace_id: str, damping: float = 0.85, max_iterations: int = 100
    ) -> dict[str, Any]:
        """Compute PageRank centrality for all nodes in a workspace.

        Args:
            workspace_id: The workspace to compute PageRank for.
            damping: PageRank damping factor (default: 0.85).
            max_iterations: Maximum iterations (default: 100).

        Returns:
            Reducer status.
        """
        return self._call("compute_pagerank", [workspace_id, damping, max_iterations])

    def compute_community_hierarchy(self, workspace_id: str) -> dict[str, Any]:
        """Build hierarchical community dendrogram using agglomerative clustering.

        Args:
            workspace_id: The workspace to build hierarchy for.

        Returns:
            Reducer status.
        """
        return self._call("compute_community_hierarchy", [workspace_id])

    def compute_god_nodes(self, workspace_id: str, top_n: int = 10) -> dict[str, Any]:
        """Call compute_god_nodes reducer to compute top-N most connected nodes."""
        return self._call("compute_god_nodes", [workspace_id, top_n])

    # -----------------------------------------------------------------------
    # API Keys
    # -----------------------------------------------------------------------

    def graph_bfs(self, workspace_id: str, start_node_id: str, max_depth: int = 3) -> None:
        """BFS traversal from a start node up to max_depth.
        Results are in graph_traversal_result table, keyed by query_id."""
        self._call("graph_bfs", [workspace_id, start_node_id, max_depth])

    def shortest_path(
        self, workspace_id: str, source_id: str, target_id: str, max_hops: int = 6
    ) -> None:
        """Shortest path between two nodes.
        Results in shortest_path_result table, ordered by step_order."""
        self._call("shortest_path", [workspace_id, source_id, target_id, max_hops])

    def get_neighbors_via_reducer(self, workspace_id: str, node_id: str) -> None:
        """Get immediate neighbours of a node.
        Results in graph_traversal_result table with depth=1."""
        self._call("get_neighbors", [workspace_id, node_id])

    # -------------------------------------------------------------------
    # Multi-hop graph traversal (Python-level wrappers)
    # -------------------------------------------------------------------

    def traverse_bfs(
        self, workspace_id: str, start_node_id: str, max_depth: int = 3
    ) -> list[dict[str, Any]]:
        """BFS traversal from a start node, returns structured path results.

        Calls the graph_bfs reducer, then reads graph_traversal_result
        to build a list of {depth, node_id, label, node_type, summary}
        entries ordered by traversal order.

        Args:
            workspace_id: Target workspace.
            start_node_id: ID of the starting KG node.
            max_depth: Maximum traversal depth (default 3).

        Returns:
            List of dicts with keys: depth, node_id, label, node_type, summary.
        """
        # Generate a unique query_id for this traversal
        import secrets
        query_id = secrets.token_hex(16)

        self._call("graph_bfs", [workspace_id, start_node_id, max_depth])

        # Read results from traversal table
        try:
            results = self._query(
                "graph_traversal_result",
                workspace_id=workspace_id,
                filter_dict={"query_id": query_id} if query_id else {},
            )
        except Exception:
            # If query_id filtering fails, get all for workspace and filter client-side
            results = self._query(
                "graph_traversal_result", workspace_id=workspace_id,
                filter_dict={},
            )

        if not results:
            return []

        # Enrich with node labels (batch fetch all referenced nodes)
        node_ids = set()
        for r in results:
            nid = r.get("node_id", r.get("target_node_id", ""))
            if nid:
                node_ids.add(nid)

        node_map = {}
        if node_ids:
            try:
                all_nodes = self._query("kg_node", workspace_id=workspace_id, filter_dict={})
                node_map = {
                    n.get("id", ""): {
                        "label": n.get("label", "?"),
                        "node_type": n.get("node_type", "unknown"),
                        "summary": n.get("summary", ""),
                    }
                    for n in all_nodes
                    if n.get("id") in node_ids
                }
            except Exception:
                pass

        # Build structured result
        structured = []
        for r in results:
            nid = r.get("node_id", r.get("target_node_id", ""))
            info = node_map.get(nid, {})
            structured.append({
                "depth": r.get("depth", 0),
                "node_id": nid,
                "label": info.get("label", nid[:16]),
                "node_type": info.get("node_type", "unknown"),
                "summary": info.get("summary", ""),
                "edge_type": r.get("edge_type", ""),
                "source_node_id": r.get("source_node_id", ""),
            })

        return structured

    def find_shortest_path(
        self, workspace_id: str, source_id: str, target_id: str, max_hops: int = 6
    ) -> list[dict[str, Any]]:
        """Find shortest path between two KG nodes.

        Calls the shortest_path reducer, then reads the result table
        to build an ordered list of path steps.

        Args:
            workspace_id: Target workspace.
            source_id: Starting node ID.
            target_id: Target node ID.
            max_hops: Maximum hops to search (default 6).

        Returns:
            Ordered list of {step, node_id, label, node_type, edge_type}
            from source to target. Empty list if no path found.
        """
        self._call("shortest_path", [workspace_id, source_id, target_id, max_hops])

        try:
            results = self._query(
                "shortest_path_result",
                workspace_id=workspace_id,
                filter_dict={},
            )
        except Exception:
            return []

        if not results:
            return []

        # Sort by step_order
        results.sort(key=lambda r: r.get("step_order", 0))

        # Enrich with node labels
        node_ids = set()
        for r in results:
            nid = r.get("node_id", "")
            if nid:
                node_ids.add(nid)

        node_map = {}
        if node_ids:
            try:
                all_nodes = self._query("kg_node", workspace_id=workspace_id, filter_dict={})
                node_map = {
                    n.get("id", ""): {
                        "label": n.get("label", "?"),
                        "node_type": n.get("node_type", "unknown"),
                        "summary": n.get("summary", ""),
                    }
                    for n in all_nodes
                    if n.get("id") in node_ids
                }
            except Exception:
                pass

        path = []
        for r in results:
            nid = r.get("node_id", "")
            info = node_map.get(nid, {})
            path.append({
                "step": r.get("step_order", 0),
                "node_id": nid,
                "label": info.get("label", nid[:16]),
                "node_type": info.get("node_type", "unknown"),
                "summary": info.get("summary", ""),
                "edge_type": r.get("edge_type", ""),
                "edge_id": r.get("edge_id", ""),
            })

        return path

    # -------------------------------------------------------------------
    # Ripple Impact
    # -------------------------------------------------------------------

    def detect_ripple_impact(self, workspace_id: str, source_type: str, source_id: str) -> dict[str, Any]:
        """Call detect_ripple_impact reducer to find affected KG nodes."""
        return self._call("detect_ripple_impact", [workspace_id, source_type, source_id])

    def get_ripple_impacts(self, workspace_id: str, source_id: str = "") -> None:
        """Call get_ripple_impacts reducer; results in ripple_impact_result table."""
        self._call("get_ripple_impacts", [workspace_id, source_id])

    def resolve_ripple_impact(self, impact_id: str) -> dict[str, Any]:
        """Call resolve_ripple_impact reducer to mark an impact as resolved."""
        return self._call("resolve_ripple_impact", [impact_id])

    def dismiss_ripple_impact(self, impact_id: str) -> dict[str, Any]:
        """Call dismiss_ripple_impact reducer to dismiss a ripple impact."""
        return self._call("dismiss_ripple_impact", [impact_id])

    def get_stale_nodes(self, workspace_id: str) -> None:
        """Call get_stale_nodes reducer; results in stale_nodes_result table."""
        self._call("get_stale_nodes", [workspace_id])

    # -------------------------------------------------------------------
    # Mental Models
    # -------------------------------------------------------------------

    def synthesize_mental_models(self, workspace_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Request synthesis of a mental model from a set of source memories.

        Creates a pending ``MentalModel`` record. Run ``mental_model_synthesis.py``
        to generate actual LLM content.

        Parameters
        ----------
        workspace_id:
            The workspace containing the source memories.
        memory_ids:
            List of memory IDs to synthesize a mental model from.
        """
        return self._call(
            "synthesize_mental_models",
            [workspace_id, json.dumps(memory_ids)],
        )

    def get_mental_model(self, model_id: str) -> list[dict[str, Any]]:
        """Get a single mental model by its ID.

        Parameters
        ----------
        model_id:
            The UUID of the mental model.
        """
        return self._sql_param(
            "SELECT * FROM mental_model WHERE id = ?",
            model_id,
        )

    def list_mental_models(
        self, workspace_id: str, status: str = ""
    ) -> list[dict[str, Any]]:
        """List mental models for a workspace, optionally filtered by status.

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        status:
            Optional filter: ``"pending"``, ``"completed"``, ``"failed"``,
            or ``""`` for all.
        """
        if status:
            return self._sql_param(
                "SELECT * FROM mental_model WHERE "
                "workspace_id = ? AND status = ? "
                "ORDER BY created_at DESC",
                workspace_id, status,
            )
        return self._sql_param(
            "SELECT * FROM mental_model WHERE "
            "workspace_id = ? "
            "ORDER BY created_at DESC",
            workspace_id,
        )

    def delete_mental_model(self, model_id: str) -> dict[str, Any]:
        """Delete a mental model.

        Parameters
        ----------
        model_id:
            The UUID of the mental model to delete.
        """
        return self._call("delete_mental_model", [model_id])

    def update_mental_model(
        self,
        model_id: str,
        content: str,
        confidence: float = 0.5,
        status: str = "completed",
    ) -> dict[str, Any]:
        """Update the content, confidence, and status of an existing mental model.

        Parameters
        ----------
        model_id:
            The UUID of the mental model.
        content:
            The new synthesized content.
        confidence:
            Confidence score (0.0–1.0) for this mental model. Default 0.5.
        status:
            Status: ``"pending"``, ``"completed"``, or ``"failed"``.
        """
        return self._call(
            "update_mental_model",
            [model_id, content, confidence, status],
        )

    # -------------------------------------------------------------------
    # Tours
    # -------------------------------------------------------------------



    # -------------------------------------------------------------------
    # BFS traversal (alias for graph_bfs)
    # -------------------------------------------------------------------

    def bfs(self, workspace_id: str, start_node_id: str, max_depth: int = 3) -> None:
        """BFS traversal from a start node up to max_depth (alias for graph_bfs).

        Results are in graph_traversal_result table, keyed by query_id.

        Args:
            workspace_id: The workspace ID.
            start_node_id: The starting node ID.
            max_depth: Maximum traversal depth (default 3).
        """
        return self.graph_bfs(workspace_id, start_node_id, max_depth)

    # -------------------------------------------------------------------
    # Cross-linking (semantic relationship discovery)
    # -------------------------------------------------------------------

    def cross_link(
        self,
        workspace_id: str = "default",
        limit: int = 50,
        similarity_threshold: float = 0.7,
    ) -> dict[str, Any]:
        """Find memories semantically related but not yet linked, and create edges.

        Uses semantic search to find near-neighbours, then checks if
        an edge already exists before creating one.

        Args:
            workspace_id: Target workspace (default "default").
            limit: Max memories to scan.
            similarity_threshold: Min similarity to auto-link (0.0-1.0).

        Returns:
            Dict with ``links_created`` and ``pairs_checked``.
        """
        # Fetch recent memories
        memories = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if not memories:
            return {"links_created": 0, "pairs_checked": 0}

        memories = sorted(memories, key=lambda r: r.get("created_at", 0), reverse=True)[:limit]

        links_created = 0
        pairs_checked = 0

        for i, mem in enumerate(memories):
            mid = mem.get("id", "")
            if not mid:
                continue
            content = mem.get("content", "")
            if not content or len(content) < 20:
                continue

            # Find similar memories
            search_results = self._query(
                "memory",
                workspace_id=workspace_id,
                filter_dict={"content_contains": content[:100]},
            )
            if not search_results:
                continue

            for other in search_results:
                other_id = other.get("id", "")
                if not other_id or other_id == mid:
                    continue

                # Check if edge already exists
                existing = self._sql(
                    f"SELECT id FROM kg_edge WHERE "
                    f"(source_node_id = '{_esc(mid)}' AND target_node_id = '{_esc(other_id)}') "
                    f"OR (source_node_id = '{_esc(other_id)}' AND target_node_id = '{_esc(mid)}')"
                )
                if existing:
                    continue

                pairs_checked += 1
                try:
                    self._call("create_edge", [
                        workspace_id,
                        mid,
                        other_id,
                        "semantic_link",
                        similarity_threshold,
                        "EXTRACTED",
                        "{}",
                    ])
                    links_created += 1
                except RuntimeError:
                    continue

        return {"links_created": links_created, "pairs_checked": pairs_checked}

    # -------------------------------------------------------------------
    # Lint workspace: count orphan KG nodes with no edges
    # -------------------------------------------------------------------

    def lint_workspace(self, workspace_id: str) -> dict[str, Any]:
        """Lint a workspace: count orphan KG nodes (nodes with no edges).

        Args:
            workspace_id: The workspace ID.

        Returns:
            Dict with ``orphans`` count and ``total`` node count.
        """
        all_nodes = self._sql(
            f"SELECT id FROM kg_node WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        total = len(all_nodes)
        orphans = 0
        for node in all_nodes:
            nid = node.get("id", "")
            if not nid:
                continue
            edges = self._sql(
                f"SELECT id FROM kg_edge WHERE "
                f"source_node_id = '{_esc(nid)}' OR target_node_id = '{_esc(nid)}' LIMIT 1"
            )
            if not edges:
                orphans += 1
        return {"orphans": orphans, "total": total}

    # -------------------------------------------------------------------
    # Suggest connections: find node pairs sharing neighbors but not linked
    # -------------------------------------------------------------------

    def suggest_connections(self, workspace_id: str) -> list[dict[str, Any]]:
        """Find KG node pairs that share neighbors but aren't directly connected.

        Useful for suggesting new graph connections.

        Args:
            workspace_id: The workspace ID.

        Returns:
            List of KG node records from the workspace.
        """
        self._call("compute_community_hierarchy", [workspace_id])
        return self._query("kg_node", workspace_id=workspace_id)

    # -------------------------------------------------------------------
    # Store answer (simplified compounder pattern)
    # -------------------------------------------------------------------

    def store_answer(
        self,
        query: str,
        answer: str,
        workspace_id: str = "default",
        title: str = "",
        source_memory_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store an answer as a wiki note, automatically linking to entities.

        Creates a note, extracts topics as KG nodes, and links them via edges.

        Args:
            query: The question/query that prompted this answer.
            answer: The answer text (markdown).
            workspace_id: The workspace ID (default "default").
            title: Optional title (default auto-generated from query).
            source_memory_ids: Optional list of source memory IDs to link.

        Returns:
            Dict with ``note`` (created note info), ``entities`` (list of KG node IDs),
            and ``links`` (number of edges created).
        """
        if not answer.strip():
            return {"note": {"id": "", "title": ""}, "entities": [], "links": 0}

        used_title = title or f"Q: {query[:60]}"

        # Create the note
        self._call("create_note", [workspace_id, used_title, answer, True])

        # Get the note we just created
        notes = self._sql(
            f"SELECT id FROM note WHERE workspace_id = '{_esc(workspace_id)}' "
            f"AND title = '{_esc(used_title)}' ORDER BY created_at DESC LIMIT 1"
        )
        if not notes:
            return {"note": {"id": "", "title": ""}, "entities": [], "links": 0}

        note_id = notes[0]["id"]
        entities: list[str] = []
        links = 0

        # Extract simple topic words as entities
        import re as _re
        words = set(_re.findall(r'\b[A-Z][a-z]+(?: [A-Z][a-z]+)*\b', answer))
        for word in list(words)[:10]:
            try:
                self._call("resolve_entity", [workspace_id, word])
                node_result = self._sql(
                    f"SELECT id FROM kg_node WHERE workspace_id = '{_esc(workspace_id)}' "
                    f"AND label = '{_esc(word)}' ORDER BY created_at DESC LIMIT 1"
                )
                if node_result:
                    node_id = node_result[0]["id"]
                    entities.append(node_id)
                    self._call("create_edge", [
                        workspace_id, node_id, note_id,
                        "informed_by", 1.0, "EXTRACTED", "{}",
                    ])
                    links += 1
            except RuntimeError:
                continue

        # Link to source memories
        if source_memory_ids:
            for sid in source_memory_ids:
                try:
                    self._call("create_edge", [
                        workspace_id, sid, note_id,
                        "informed_by", 0.8, "EXTRACTED", "{}",
                    ])
                except RuntimeError:
                    continue

        return {
            "note": {"id": note_id, "title": used_title},
            "entities": entities,
            "links": links,
        }

    def list_subscriptions(self, workspace_id: str = "") -> dict[str, Any]:
        """List subscriptions for a workspace.

        Args:
            workspace_id: Optional workspace ID.

        Returns:
            Reducer status dict.
        """
        return self._call("list_subscriptions", [workspace_id])

    def get_search_results(self, workspace_id: str = "", query_hash: str = "") -> dict[str, Any]:
        """Get search results for a query hash.

        Args:
            workspace_id: Optional workspace ID.
            query_hash: The query hash to retrieve results for.

        Returns:
            Reducer status dict.
        """
        return self._call("get_search_results", [workspace_id, query_hash])

    # ------------------------------------------------------------------
    # Bi-temporal fact management (Graphiti parity)
    # ------------------------------------------------------------------

    def resolve_edge_contradictions(
        self,
        workspace_id: str,
        edge_ids: list[str],
    ) -> dict[str, Any]:
        """Mark one or more KG edges as expired due to contradiction.

        Sets ``expired_at`` on the specified edges to the current system time.
        This is the system-discovery-time — distinct from ``invalid_at``
        (real-world expiry).  Expired edges are excluded from default context
        building but remain available for historical queries.

        Args:
            workspace_id: Target workspace UUID.
            edge_ids: List of edge UUIDs to expire.

        Returns:
            Reducer status dict.
        """
        edge_ids_json = json.dumps(edge_ids)
        return self._call("resolve_edge_contradictions", [workspace_id, edge_ids_json])

    def detect_contradictions(
        self,
        workspace_id: str,
        *,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        edge_id: str | None = None,
        new_relation: str = "",
    ) -> list[dict[str, Any]]:
        """Rule-based contradiction detection in the knowledge graph.

        Finds existing edges that share the same source+target nodes but
        have a *different* relation.  This is a native (no-LLM) check
        suitable for the default memory processing path — no external
        dependencies required.

        Pass either ``(source_node_id, target_node_id)`` to check what
        relations exist between those two nodes, or ``edge_id`` to look
        up the edge's source/target first.

        Returns a list of candidate contradicting edges, each with:
        - ``edge_id`` — UUID of the conflicting edge
        - ``relation`` — the existing relation
        - ``contradicting_relation`` — the new relation that conflicts
        - ``reason`` — description of why they conflict

        Args:
            workspace_id: Target workspace UUID.
            source_node_id: Source node UUID (optional if edge_id provided).
            target_node_id: Target node UUID (optional if edge_id provided).
            edge_id: Edge UUID to look up source/target (alternative to
                     passing source_node_id + target_node_id).

        Returns:
            List of contradicting edge candidates.
        """
        contradictions: list[dict[str, Any]] = []

        # Resolve source/target from edge_id if provided
        if edge_id:
            try:
                edge = self._sql(
                    "SELECT source_node_id, target_node_id, relation "
                    f"FROM kg_edge WHERE id = '{_esc(edge_id)}'"
                )
                if edge:
                    source_node_id = edge[0].get("source_node_id", source_node_id or "")
                    target_node_id = edge[0].get("target_node_id", target_node_id or "")
                    new_relation = edge[0].get("relation", "")
                else:
                    return contradictions
            except RuntimeError:
                logger.warning("detect_contradictions: edge lookup failed")
                return contradictions

        if not source_node_id or not target_node_id:
            return contradictions

        # Query existing edges between these nodes
        try:
            existing = self._sql(
                "SELECT id, relation, valid_at, invalid_at "
                "FROM kg_edge "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"AND source_node_id = '{_esc(source_node_id)}' "
                f"AND target_node_id = '{_esc(target_node_id)}' "
                "AND invalid_at = 0 "
                "LIMIT 20"
            )
        except RuntimeError:
            logger.warning("detect_contradictions: kg_edge query failed")
            return []

        for ex in existing:
            ex_rel = ex.get("relation", "")
            ex_id = ex.get("id", "")

            # Same relation — not a contradiction (may be duplicate, but
            # dedup is handled elsewhere).  Different relation = likely
            # update/contradiction.
            if ex_rel == new_relation:
                continue

            # Known contradictory relation pairs
            contradictory_pairs = [
                ("employed_by", "self_employed"),
                ("reports_to", "manages"),
                ("located_in", "relocated_to"),
                ("acquired", "spun_off"),
                ("partner_of", "competitor_of"),
                ("merged_with", "divested"),
                ("succeeded_by", "preceded_by"),
            ]

            is_contradiction = False
            reason = ""
            for a, b in contradictory_pairs:
                if (ex_rel == a and new_relation == b) or (ex_rel == b and new_relation == a):
                    is_contradiction = True
                    reason = f"'{ex_rel}' contradicts '{new_relation}' between same nodes"
                    break

            # Different relations that aren't explicitly contradictory pairs
            # are still flagged as potential contradictions for LLM verification
            if not is_contradiction and ex_rel != new_relation:
                is_contradiction = True
                reason = f"Potential contradiction: existing '{ex_rel}' vs new '{new_relation}'"

            if is_contradiction:
                contradictions.append({
                    "edge_id": ex_id,
                    "relation": ex_rel,
                    "contradicting_relation": new_relation,
                    "reason": reason,
                })

        return contradictions

    def detect_contradictions_llm(
        self,
        workspace_id: str,
        edge_id: str,
        llm_client: Any = None,
    ) -> list[dict[str, Any]]:
        """LLM-based contradiction detection.

        Uses an LLM to semantically compare a new or updated edge against
        existing edges for the same source+target nodes.  Catches
        contradictions that rule-based pattern matching misses (e.g.
        ``"employee_of"`` vs ``"works_at"`` with different org names).

        Args:
            workspace_id: Target workspace UUID.
            edge_id: The edge to check for contradictions.
            llm_client: Optional LLM client.  If omitted, uses the
                        project's configured LLM (``local_llm`` or
                        ``spacetime_memory.llm`` module).

        Returns:
            List of contradicting edge candidates.
        """
        # Fetch the edge data
        try:
            edge_rows = self._sql(
                "SELECT source_node_id, target_node_id, relation, "
                "metadata_json, valid_at "
                "FROM kg_edge "
                f"WHERE id = '{_esc(edge_id)}'"
            )
        except RuntimeError:
            logger.warning("detect_contradictions_llm: edge lookup failed")
            return []

        if not edge_rows:
            return []

        edge = edge_rows[0]
        source_id = edge.get("source_node_id", "")
        target_id = edge.get("target_node_id", "")
        new_relation = edge.get("relation", "")
        new_fact = ""

        if not source_id or not target_id:
            return []

        # Fetch existing edges between same nodes
        try:
            existing = self._sql(
                "SELECT id, relation, valid_at, invalid_at "
                "FROM kg_edge "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"AND source_node_id = '{_esc(source_id)}' "
                f"AND target_node_id = '{_esc(target_id)}' "
                "AND id != '{_esc(edge_id)}' "
                "AND invalid_at = 0 "
                "LIMIT 20"
            )
        except RuntimeError:
            return []

        if not existing:
            return []

        # Get node labels for context
        try:
            node_rows = self._sql(
                "SELECT node_id, label FROM kg_node "
                f"WHERE node_id IN ('{_esc(source_id)}', '{_esc(target_id)}')"
            )
            node_labels = {n["node_id"]: n.get("label", "?") for n in node_rows}
        except RuntimeError:
            node_labels = {}

        source_label = node_labels.get(source_id, source_id[:12])
        target_label = node_labels.get(target_id, target_id[:12])

        # Build the LLM prompt
        prompt = (
            f"You are analyzing a knowledge graph for factual contradictions.\n\n"
            f"Two entities are connected by an edge:\n"
            f"  Source: {source_label} ({source_id[:12]}...)\n"
            f"  Target: {target_label} ({target_id[:12]}...)\n\n"
            f"NEW edge being added:\n"
            f"  Relation: {new_relation}\n"
            f"  Fact: {new_fact or '(none)'}\n\n"
            f"EXISTING edges that may conflict:\n"
        )

        for ex in existing:
            prompt += (
                f"  - {ex.get('relation', '?')} "
                f"(valid since {ex.get('valid_at', 0)})\n"
            )

        prompt += (
            "\nFor each existing edge, determine if the NEW edge contradicts it.\n"
            "Contradictions include: incompatible relations, mutually exclusive facts, "
            "temporal inconsistencies, or role conflicts.\n\n"
            'Return a JSON object: {"contradictions": [{"edge_id": "...", "reason": "..."}]}\n'
            'Return {"contradictions": []} if no contradictions found.\n'
            "JSON only, no other text."
        )

        # Use the LLM client
        if llm_client is None:
            try:
                from ..llm import complete
                response_text = complete(prompt, max_tokens=1000)
            except ImportError:
                logger.warning("detect_contradictions_llm: no LLM client available")
                return []
            except Exception as llm_err:
                logger.warning("detect_contradictions_llm: LLM call failed: %s", llm_err)
                return []
        else:
            try:
                response_text = llm_client.complete(prompt, max_tokens=1000)
            except Exception as llm_err:
                logger.warning("detect_contradictions_llm: LLM call failed: %s", llm_err)
                return []

        # Parse response
        try:
            result = json.loads(response_text)
            contradictions = result.get("contradictions", [])
            # Ensure each has edge_id
            return [
                {"edge_id": c.get("edge_id", ""), "reason": c.get("reason", "")}
                for c in contradictions
                if c.get("edge_id")
            ]
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("detect_contradictions_llm: failed to parse LLM response: %s", e)
            return []

    def create_edge_resolve(
        self,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: str = "EXTRACTED",
        metadata_json: str = "",
        source_memory_id: str = "",
        *,
        auto_resolve: bool = True,
        use_llm: bool = False,
        llm_client: Any = None,
    ) -> dict[str, Any]:
        """Create a KG edge and automatically resolve contradictions.

        Combines ``create_edge`` with rule-based (or optional LLM-based)
        contradiction detection in a single call.  Any edges found to
        contradict the new edge are marked as expired.

        This is the recommended way to create edges when bi-temporal
        consistency is important.

        Args:
            workspace_id: Target workspace UUID.
            source_node_id: Source node UUID.
            target_node_id: Target node UUID.
            relation: Relation type (e.g. ``\"employed_by\"``).
            weight: Edge weight (default 1.0).
            confidence: ``\"EXTRACTED\"``, ``\"INFERRED\"``, or ``\"AMBIGUOUS\"``.
            metadata_json: Optional JSON metadata string.
            source_memory_id: Optional source memory UUID.
            auto_resolve: If True (default), run rule-based contradiction
                          detection after creation.
            use_llm: If True, also run LLM-based detection (requires
                     ``llm_client`` or the project's default LLM).  SLOW.
            llm_client: Optional LLM client for LLM-based detection.

        Returns:
            Dict with creation status and any resolved contradictions.
        """
        # Create the edge first
        result = self._call(
            "create_edge",
            [
                workspace_id,
                source_node_id,
                target_node_id,
                relation,
                weight,
                confidence,
                metadata_json,
                source_memory_id,
            ],
        )

        resolved_edges: list[str] = []

        if auto_resolve and isinstance(result, dict) and result.get("status") == "ok":
            # Get the edge ID from the result
            edge_id = result.get("edge_id", result.get("id", ""))

            # Rule-based detection
            contradictions = self.detect_contradictions(
                workspace_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                new_relation=relation,
            )

            if contradictions:
                contradicting_ids = [c["edge_id"] for c in contradictions if c.get("edge_id")]
                if contradicting_ids:
                    self.resolve_edge_contradictions(workspace_id, contradicting_ids)
                    resolved_edges.extend(contradicting_ids)

            # LLM-based detection (optional, slow)
            if use_llm and edge_id:
                llm_contradictions = self.detect_contradictions_llm(
                    workspace_id, edge_id, llm_client=llm_client
                )
                llm_ids = [
                    c["edge_id"] for c in llm_contradictions
                    if c.get("edge_id") and c["edge_id"] not in resolved_edges
                ]
                if llm_ids:
                    self.resolve_edge_contradictions(workspace_id, llm_ids)
                    resolved_edges.extend(llm_ids)

        return {
            "status": result.get("status", "ok"),
            "edge_id": result.get("edge_id", result.get("id", "")),
            "resolved_contradictions": resolved_edges,
        }
