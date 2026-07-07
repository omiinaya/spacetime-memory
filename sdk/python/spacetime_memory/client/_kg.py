# flake8: noqa: F811
"""Knowledge graph mixin."""
from __future__ import annotations

from typing import Any

from ._base import ClientBase, logger, _TRACER, _tracing_span, EmbedderUnavailableError, SpacetimeDBError, NotFoundError, ApiError
from ._utils import _esc, _parse_sql_response



class KGMixin:
    """Spacetime-Memory kg mixin.

    Provides Client methods related to kg management.
    Inherits from ClientBase for connection infrastructure.
    """
    pass
    def create_node(
        self,
        workspace_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
        source_memory_id: str = "",
    ) -> dict[str, Any]:
        """Create a knowledge-graph node and auto-index it.

        Args:
            workspace_id: Target workspace.
            label: Node label (used as display name).
            node_type: Type category (default: "concept").
            summary: Optional summary text.
            metadata_json: Optional JSON metadata string.
            source_memory_id: Optional memory record ID that supports this node.
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
            ],
        )
        content = f"{label}: {summary}" if summary else label
        emb = self._embed(content)
        if emb:
            nodes = self._query(
                "kg_node", workspace_id=workspace_id, filter_dict={"label": label}, columns=["id"]
            )
            if nodes:
                self._call(
                    "index_entity",
                    [
                        workspace_id,
                        "node",
                        nodes[-1]["id"],
                        content,
                        json.dumps(emb),
                    ],
                )
        return result

    def update_node(
        self,
        node_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
        source_memory_id: str = "",
    ) -> dict[str, Any]:
        """Update an existing knowledge-graph node's mutable fields.

        Args:
            node_id: The ID of the node to update.
            label: New label (display name).
            node_type: Type category (default: ``"concept"``).
            summary: Updated summary text.
            metadata_json: Updated JSON metadata string.
            source_memory_id: Optional source memory ID.
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
        rows = self._sql(
            "SELECT * FROM edge_history_result WHERE "
            f"edge_group_id = '{_esc(edge_group_id)}' "
            "ORDER BY created_at ASC"
        )
        return rows

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
        rows = self._sql(
            "SELECT * FROM citation_result WHERE "
            f"entity_id = '{_esc(entity_id)}' "
            f"  AND entity_type = '{_esc(entity_type)}' "
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
        rows = self._sql(f"SELECT * FROM profile_context_result WHERE peer_id = '{_esc(peer_id)}'")
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
        rows = self._sql(
            f"SELECT * FROM fact_result WHERE query_hash = '{_esc(query_hash)}' ORDER BY created_at DESC"
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
        rows = self._sql(
            f"SELECT * FROM fact_result WHERE query_hash = '{_esc(query_hash)}' ORDER BY created_at DESC"
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
        return self._sql(f"SELECT * FROM mental_model WHERE id = '{_esc(model_id)}'")

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
        where = f"workspace_id = '{_esc(workspace_id)}'"
        if status:
            where += f" AND status = '{_esc(status)}'"
        return self._sql(
            f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at DESC"
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

