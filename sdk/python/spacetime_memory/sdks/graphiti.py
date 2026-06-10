"""Graphiti-compatible adapter.

Maps the Graphiti knowledge graph API (https://github.com/getzep/graphiti)
to SpacetimeDB tables. Provides signature-compatible ``Graphiti``,
``EntityNode``, and ``EntityEdge`` classes.

NOTE: Return types are plain Python classes, not Pydantic models like the
upstream ``graphiti_core``. EntityNode and EntityEdge are missing some
upstream fields (``uuid``, ``labels``, ``created_at``, ``attributes``,
``episodes``, ``reference_time``). See ROADMAP.md for planned parity work.

Maps::

    Graphiti Neo4j graph   → SpacetimeDB kg_node / kg_edge tables
    Graphiti episode       → SpacetimeDB memory record
    Graphiti entity node   → SpacetimeDB kg_node
    Graphiti entity edge   → SpacetimeDB kg_edge

Usage::

    from spacetime_memory.sdks.graphiti import Graphiti

    g = Graphiti(host="localhost", port=3001)

    # Add a triplet (subject → relation → object)
    result = g.add_triplet(
        source_node=EntityNode(name="Alice", group_id="default"),
        edge=EntityEdge(name="likes", fact="Alice likes pizza", group_id="default"),
        target_node=EntityNode(name="Pizza", group_id="default"),
    )

    # Search the knowledge graph
    results = g.search("Alice food preferences", group_ids=["default"])

    # Search with advanced config (returns SearchResults)
    results = g.search_("Alice food preferences", group_ids=["default"])

    # Get edges for a node
    edges = g.get_entity_edge_summary(entity_uuid="abc123")

    # Close when done
    g.close()
"""

from __future__ import annotations

import difflib
import json
import logging
import time
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..client import Client
from ..llm import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types matching Graphiti's core models
# ---------------------------------------------------------------------------


@dataclass
class EntityNode:
    """Knowledge graph entity node.

    Maps to SpacetimeDB ``kg_node`` table.  ``name`` is indexed
    for semantic search via the embedder.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    name_embedding: list[float] | None = None
    summary: str = ""
    group_id: str = "default"
    labels: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_stmem(cls, row: dict[str, Any]) -> "EntityNode":
        """Build from a SpacetimeDB ``kg_node`` row."""
        attrs = {}
        raw = row.get("metadata_json", "{}")
        if raw and raw != "{}":
            try:
                attrs = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass
        labels_raw = row.get("labels", "")
        labels = json.loads(labels_raw) if isinstance(labels_raw, str) and labels_raw else []
        created = row.get("created_at", 0)
        return cls(
            uuid=row.get("id", ""),
            name=row.get("label", ""),
            summary=row.get("summary", ""),
            group_id=row.get("workspace_id", "default"),
            labels=labels,
            attributes=attrs,
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=timezone.utc)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=timezone.utc)
            if created
            else datetime.now(timezone.utc),
        )


@dataclass
class EntityEdge:
    """Knowledge graph directed edge between two entity nodes.

    Maps to SpacetimeDB ``kg_edge`` table.  ``fact`` contains the
    natural-language description of the relationship.

    Supports temporal versioning (Graphiti parity): when an edge is
    updated, the old version is invalidated (``invalid_at`` set) and
    a new version is created with incremented ``version`` and the
    same ``edge_group_id``.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    fact: str = ""
    fact_embedding: list[float] | None = None
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    episodes: list[str] = field(default_factory=list)
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Temporal versioning (Graphiti parity)
    version: int = 1
    edge_group_id: str = ""
    reference_time: datetime | None = None

    @classmethod
    def from_stmem(cls, row: dict[str, Any]) -> "EntityEdge":
        """Build from a SpacetimeDB ``kg_edge`` row."""
        attrs = {}
        raw = row.get("metadata_json", "{}")
        if raw and raw != "{}":
            try:
                attrs = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass
        created = row.get("created_at", 0)
        valid = row.get("valid_at", 0)
        invalid = row.get("invalid_at", 0)
        return cls(
            uuid=row.get("id", ""),
            name=row.get("relation", ""),
            fact=row.get("fact", row.get("relation", "")),
            source_node_uuid=row.get("source_node_id", ""),
            target_node_uuid=row.get("target_node_id", ""),
            group_id=row.get("workspace_id", "default"),
            attributes=attrs,
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=timezone.utc)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=timezone.utc)
            if created
            else datetime.now(timezone.utc),
            valid_at=datetime.fromtimestamp(valid / 1_000_000, tz=timezone.utc)
            if valid and valid > 1e12
            else datetime.fromtimestamp(valid, tz=timezone.utc)
            if valid
            else None,
            invalid_at=datetime.fromtimestamp(invalid / 1_000_000, tz=timezone.utc)
            if invalid and invalid > 1e12
            else datetime.fromtimestamp(invalid, tz=timezone.utc)
            if invalid
            else None,
            version=row.get("version", 1),
            edge_group_id=row.get("edge_group_id", ""),
        )


@dataclass
class EpisodicNode:
    """An episode (text input that generated graph entities).

    Maps to SpacetimeDB ``memory`` table.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    content: str = ""
    source: str = "message"
    source_description: str = ""
    group_id: str = "default"
    entity_edges: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_at: datetime | None = None


@dataclass
class CommunityNode:
    """Community node (result from community detection)."""

    uuid: str = ""
    name: str = ""
    group_id: str = "default"
    summary: str = ""
    member_uuids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CommunityEdge:
    """Edge connecting communities to entities."""

    uuid: str = ""
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SearchResults:
    """Results from an advanced search (``search_``)."""

    edges: list[EntityEdge] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)


@dataclass
class AddEpisodeResults:
    """Results from ``add_episode``."""

    episode: EpisodicNode | None = None
    episodic_edges: list[Any] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)
    edges: list[EntityEdge] = field(default_factory=list)
    communities: list[CommunityNode] = field(default_factory=list)
    community_edges: list[CommunityEdge] = field(default_factory=list)


@dataclass
class AddTripletResults:
    """Results from ``add_triplet``."""

    nodes: list[EntityNode] = field(default_factory=list)
    edges: list[EntityEdge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Graphiti adapter
# ---------------------------------------------------------------------------


class Graphiti:
    """Drop-in replacement for ``graphiti_core.graphiti.Graphiti``.

    Wraps Spacetime-Memory's knowledge graph operations (kg_node,
    kg_edge) behind Graphiti's API.

    **Important differences from the real Graphiti:**

    * Our adapter is **synchronous** (Graphiti uses ``asyncio``).  All
      ``async def`` methods in the real API are ``def`` here.
    * The real Graphiti uses an **LLM** to extract entities and edges
      from raw text (``add_episode``).  This adapter does NOT include
      an LLM — you must provide pre-extracted nodes and edges via
      ``add_triplet``, or use ``add_episode`` which stores the content
      as a memory (without automatic entity extraction).
    * ``group_id`` maps to a SpacetimeDB workspace **name**.  The
      adapter resolves group_id strings to actual workspace UUIDs via
      the ``_resolve_workspace`` cache.
    * ``build_communities`` delegates to the SpacetimeDB
      ``detect_communities`` reducer.
    * ``search`` returns ``EntityEdge`` objects (fact edges), matching
      the real Graphiti behaviour.
    * ``search_`` returns ``SearchResults`` with both nodes and edges,
      matching the real advanced search.

    Example::

        from spacetime_memory.sdks.graphiti import (
            Graphiti, EntityNode, EntityEdge,
        )

        g = Graphiti()
        result = g.add_triplet(
            source_node=EntityNode(name="Alice", group_id="ws1"),
            edge=EntityEdge(name="likes", fact="Alice likes pizza",
                            group_id="ws1"),
            target_node=EntityNode(name="Pizza", group_id="ws1"),
        )
        print(f"Created nodes: {[n.name for n in result.nodes]}")
        print(f"Created edges: {[e.name for e in result.edges]}")

        # Search for relevant facts
        edges = g.search("Alice food", group_ids=["ws1"])
        for e in edges:
            print(f"  {e.name}: {e.fact}")

        g.close()
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        token: str | None = None,
        embedder_url: str | None = None,
        embedder_type: str | None = None,
        client: Client | None = None,
    ):
        """
        Args:
            host: SpacetimeDB host (default: localhost).
            port: SpacetimeDB port (default: 3001).
            database: SpacetimeDB database identity.
            token: JWT token for authenticated requests.
            embedder_url: Embedder sidecar URL (default: http://localhost:9090).
            embedder_type: Embedder type (local, openai, auto).
            client: An existing Client instance (overrides other params).
        """
        if client is not None:
            self._client = client
        else:
            self._client = Client(
                host=host,
                port=port,
                database=database,
                token=token,
                embedder_url=embedder_url,
                embedder_type=embedder_type,
            )
        self.clients = self._client
        # Cache: group_id (str) -> workspace_id (str)
        self._ws_cache: dict[str, str] = {}

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if hasattr(self._client, "_http") and self._client._http:
            self._client._http.close()

    # -------------------------------------------------------------------
    # Workspace resolution
    # -------------------------------------------------------------------

    def _resolve_workspace(self, group_id: str) -> str:
        """Resolve a group_id string to an actual workspace UUID.

        Caches the mapping.  Creates the workspace if it doesn't exist.
        """
        if group_id in self._ws_cache:
            return self._ws_cache[group_id]

        # Search existing workspaces by name
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == group_id and ws.get("id"):
                    self._ws_cache[group_id] = ws["id"]
                    return ws["id"]

        # Workspace doesn't exist — create it
        try:
            self._client.create_workspace(group_id)
        except RuntimeError:
            pass

        # Re-list to find the newly created workspace
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == group_id and ws.get("id"):
                    self._ws_cache[group_id] = ws["id"]
                    return ws["id"]

        # Last resort: use the group_id itself as the workspace UUID
        self._ws_cache[group_id] = group_id
        return group_id

    def _sql_query(self, query: str) -> list[dict[str, Any]]:
        """Run a SQL query, with safe error handling."""
        try:
            return self._client._sql(query)
        except RuntimeError:
            return []

    def _filter_by_valid_at(
        self,
        edges: list[EntityEdge],
        valid_at_after: datetime | None = None,
        valid_at_before: datetime | None = None,
    ) -> list[EntityEdge]:
        """Filter a list of edges by ``valid_at`` timestamp.

        Args:
            edges: List of :class:`EntityEdge` objects to filter.
            valid_at_after: If set, only return edges whose ``valid_at``
                is greater than or equal to this datetime.
            valid_at_before: If set, only return edges whose ``valid_at``
                is less than or equal to this datetime.

        Returns:
            Filtered list of edges.  Edges without a ``valid_at`` are
            excluded when any filter is active.
        """
        if valid_at_after is None and valid_at_before is None:
            return edges

        filtered: list[EntityEdge] = []
        for edge in edges:
            if edge.valid_at is None:
                continue  # no timestamp to compare against
            if valid_at_after is not None and edge.valid_at < valid_at_after:
                continue
            if valid_at_before is not None and edge.valid_at > valid_at_before:
                continue
            filtered.append(edge)

        return filtered

    # -------------------------------------------------------------------
    # Triplet operations (primary API for direct KG manipulation)
    # -------------------------------------------------------------------

    def add_triplet(
        self,
        source_node: EntityNode,
        edge: EntityEdge,
        target_node: EntityNode,
        *,
        group_id: str | None = None,
    ) -> AddTripletResults:
        """Add a source -[edge]-> target triplet to the knowledge graph.

        Creates both entity nodes (if they don't exist by label within
        the workspace) and the directed edge between them.

        Args:
            source_node: The source entity node.
            edge: The relationship edge.
            target_node: The target entity node.
            group_id: Workspace name (overrides node/edge group_ids if set).

        Returns:
            :class:`AddTripletResults` with the created nodes and edges.
        """
        gid = group_id or source_node.group_id or edge.group_id or target_node.group_id
        ws_id = self._resolve_workspace(gid)

        # Helper: get or create a node by label within a workspace.
        # Returns (DB-assigned UUID, dedup_score) where dedup_score is:
        #   1.0  = exact match
        #   0.95 = case-insensitive match
        #   >0.85 .. <1.0 = fuzzy difflib match
        #   0.0  = new node created
        def _get_or_create_node(
            node: EntityNode, workspace_uuid: str
        ) -> tuple[str, float]:
            all_nodes = self._sql_query(
                "SELECT id, label FROM kg_node WHERE "
                f"workspace_id = '{_esc(workspace_uuid)}' "
            )

            # Pass 1: exact match (current behavior)
            for n in all_nodes:
                if n.get("label") == node.name:
                    return n["id"], 1.0

            name_lower = node.name.lower()

            # Pass 2: case-insensitive matching
            for n in all_nodes:
                if n.get("label", "").lower() == name_lower:
                    return n["id"], 0.95

            # Pass 3: fuzzy matching via difflib.SequenceMatcher
            fuzzy_matches: list[tuple[dict[str, Any], float]] = []
            for n in all_nodes:
                label = n.get("label", "")
                ratio = difflib.SequenceMatcher(
                    None, name_lower, label.lower()
                ).ratio()
                if ratio > 0.85:
                    fuzzy_matches.append((n, ratio))

            if fuzzy_matches:
                # Prefer the closest match
                fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
                best_node, best_ratio = fuzzy_matches[0]
                return best_node["id"], best_ratio

            # Node doesn't exist — create it
            try:
                self._client.create_node(
                    workspace_id=workspace_uuid,
                    label=node.name,
                    node_type="entity",
                    summary=node.summary,
                    metadata_json=json.dumps(node.attributes),
                )
            except RuntimeError:
                pass
            # Re-query to get the new node's UUID
            all_nodes = self._sql_query(
                "SELECT id, label FROM kg_node WHERE "
                f"workspace_id = '{_esc(workspace_uuid)}' "
            )
            for n in all_nodes:
                if n.get("label") == node.name:
                    return n["id"], 0.0
            return node.uuid, 0.0  # fallback

        actual_source_id, source_dedup_score = _get_or_create_node(source_node, ws_id)
        actual_target_id, target_dedup_score = _get_or_create_node(target_node, ws_id)

        # Create the edge
        try:
            self._client.create_edge(
                workspace_id=ws_id,
                source_node_id=actual_source_id,
                target_node_id=actual_target_id,
                relation=edge.name,
                weight=1.0,
                metadata_json=json.dumps({
                    "fact": edge.fact,
                    **edge.attributes,
                }),
            )
        except RuntimeError:
            pass

        # Query the actual DB-assigned edge UUID and temporal fields
        # Use a unique edge identifier: source + target + relation
        actual_edge_id = edge.uuid  # fallback
        actual_version = 1
        actual_edge_group_id = ""
        edge_rows = self._sql_query(
            "SELECT id, version, edge_group_id FROM kg_edge WHERE "
            f"source_node_id = '{_esc(actual_source_id)}' AND "
            f"target_node_id = '{_esc(actual_target_id)}' AND "
            f"relation = '{_esc(edge.name)}' AND "
            f"workspace_id = '{_esc(ws_id)}'"
        )
        if edge_rows:
            r = edge_rows[0]
            actual_edge_id = r.get("id", edge.uuid)
            actual_version = r.get("version", 1)
            actual_edge_group_id = r.get("edge_group_id", "")

        resolved_source = EntityNode(
            uuid=actual_source_id,
            name=source_node.name,
            summary=source_node.summary,
            group_id=gid,
            attributes={
                **source_node.attributes,
                "_dedup_score": source_dedup_score,
            },
        )
        resolved_target = EntityNode(
            uuid=actual_target_id,
            name=target_node.name,
            summary=target_node.summary,
            group_id=gid,
            attributes={
                **target_node.attributes,
                "_dedup_score": target_dedup_score,
            },
        )
        resolved_edge = EntityEdge(
            uuid=actual_edge_id,
            name=edge.name,
            fact=edge.fact,
            source_node_uuid=actual_source_id,
            target_node_uuid=actual_target_id,
            group_id=gid,
            attributes=edge.attributes,
            version=actual_version,
            edge_group_id=actual_edge_group_id,
        )

        return AddTripletResults(
            nodes=[resolved_source, resolved_target],
            edges=[resolved_edge],
        )

    # -------------------------------------------------------------------
    # Episode operations
    # -------------------------------------------------------------------

    def add_episode(
        self,
        name: str,
        episode_body: str,
        source_description: str,
        reference_time: datetime | None = None,
        source: str = "message",
        group_id: str | None = None,
        uuid: str | None = None,
        **kwargs: Any,
    ) -> AddEpisodeResults:
        """Store an episode (text content) as a memory in the workspace.

        **Important:** The real Graphiti uses an LLM to automatically
        extract entities and edges from the episode body.  This adapter
        does NOT include an LLM — it stores the episode as a memory
        record and returns it.  Use ``add_triplet`` to manually add
        extracted nodes and edges.

        Args:
            name: Episode name.
            episode_body: The text content.
            source_description: Description of the source.
            reference_time: Timestamp for the episode.
            source: Episode type (message, text, json, fact_triple).
            group_id: Workspace name (maps to Graphiti's group_id).
            uuid: Optional episode UUID.
            **kwargs: Additional Graphiti parameters (accepted for
                compatibility, ignored).

        Returns:
            :class:`AddEpisodeResults` with the stored episode.
        """
        ws_id = self._resolve_workspace(group_id or "default")
        ts = reference_time or datetime.now(timezone.utc)
        episode_uuid = uuid or _uuid.uuid4().hex[:32]

        try:
            self._client.store(
                workspace_id=ws_id,
                content=episode_body,
                memory_type="episode",
                peer_id=source_description or name,
                source_session_id=episode_uuid,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"graphiti.add_episode('{name}') failed: {exc}"
            ) from exc

        episode = EpisodicNode(
            uuid=episode_uuid,
            name=name,
            content=episode_body,
            source=source,
            source_description=source_description,
            group_id=group_id or "default",
            valid_at=ts,
        )

        return AddEpisodeResults(episode=episode)

    # -------------------------------------------------------------------
    # Search operations
    # -------------------------------------------------------------------

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
                neighbor_rows = self._client.get_neighbors(nid)
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
                edge_rows = self._sql_query(
                    f"SELECT * FROM kg_edge WHERE id = '{_esc(eid)}'"
                )
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
                            neighbor_rows = self._client.get_neighbors(nid)
                        except RuntimeError:
                            continue
                        for row in neighbor_rows:
                            eid = row.get("id", "")
                            if eid and eid not in seen_edge_ids:
                                seen_edge_ids.add(eid)
                                edges.append(EntityEdge.from_stmem(row))
            except RuntimeError:
                pass

        # Apply time-range filter on valid_at (if provided)
        valid_at_after = kwargs.get("valid_at_after")
        valid_at_before = kwargs.get("valid_at_before")
        if valid_at_after is not None or valid_at_before is not None:
            edges = self._filter_by_valid_at(
                edges, valid_at_after, valid_at_before
            )

        # Sort by score if available, then by name
        def _sort_key(e: EntityEdge) -> tuple[float, str]:
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
        search_filter: Any = None,
        **kwargs: Any,
    ) -> SearchResults:
        """Advanced search returning nodes and edges.

        Searches the knowledge graph and returns structured results
        with both ``EntityNode`` and ``EntityEdge`` objects.

        Args:
            query: The search query string.
            config: Search config (accepted for compat, not used).
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

        results = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=20,
            semantic=True,
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
                node_rows = self._sql_query(
                    f"SELECT * FROM kg_node WHERE id = '{_esc(entity_id)}'"
                )
                if node_rows:
                    nodes.append(EntityNode.from_stmem(node_rows[0]))

            elif entity_type == "edge" and entity_id and entity_id not in seen_edge_ids:
                seen_edge_ids.add(entity_id)
                edge_rows = self._sql_query(
                    f"SELECT * FROM kg_edge WHERE id = '{_esc(entity_id)}'"
                )
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
                pass

        # Apply time-range filter on edges (if provided)
        valid_at_after = kwargs.get("valid_at_after")
        valid_at_before = kwargs.get("valid_at_before")
        if valid_at_after is not None or valid_at_before is not None:
            edges = self._filter_by_valid_at(
                edges, valid_at_after, valid_at_before
            )

        return SearchResults(edges=edges, nodes=nodes)

    def get_entity_edge_summary(
        self,
        entity_uuid: str,
        group_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get all edges connected to an entity node.

        Args:
            entity_uuid: The UUID of the entity node.
            group_ids: Not used (accepted for compat).

        Returns:
            Dict with ``edges`` (list of EntityEdge), ``nodes`` (list of
            connected EntityNode), ``summary`` (concatenated facts).
        """
        try:
            edge_rows = self._client.get_neighbors(entity_uuid)
        except RuntimeError:
            return {"edges": [], "nodes": [], "summary": ""}

        edges: list[EntityEdge] = []
        node_ids: set[str] = set()

        for row in edge_rows:
            edge = EntityEdge.from_stmem(row)
            edges.append(edge)
            src = row.get("source_node_id", "")
            tgt = row.get("target_node_id", "")
            if src:
                node_ids.add(src)
            if tgt:
                node_ids.add(tgt)

        node_ids.discard(entity_uuid)
        node_ids.discard("")

        nodes: list[EntityNode] = []
        for nid in node_ids:
            nrows = self._sql_query(
                f"SELECT * FROM kg_node WHERE id = '{_esc(nid)}'"
            )
            if nrows:
                nodes.append(EntityNode.from_stmem(nrows[0]))

        facts = [e.fact for e in edges if e.fact]
        summary = "; ".join(facts) if facts else ""

        return {"edges": edges, "nodes": nodes, "summary": summary}

    # -------------------------------------------------------------------
    # Community detection
    # -------------------------------------------------------------------

    def build_communities(
        self, group_ids: list[str] | None = None
    ) -> list[CommunityNode]:
        """Run community detection on the knowledge graph.

        Delegates to SpacetimeDB's ``detect_communities`` reducer.

        Args:
            group_ids: List of workspace names.  Uses first if multiple.

        Returns:
            List of :class:`CommunityNode` objects.
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)
        try:
            self._client.detect_communities(ws_id)
        except RuntimeError:
            pass
        try:
            self._client.seed_communities(ws_id)
        except RuntimeError:
            pass

        community_nodes = self._sql_query(
            "SELECT * FROM kg_node WHERE "
            f"workspace_id = '{_esc(ws_id)}' AND "
            "node_type = 'community'"
        )

        communities = []
        for row in community_nodes:
            community = CommunityNode(
                uuid=row.get("id", ""),
                name=row.get("label", ""),
                group_id=gid,
                summary=row.get("summary", ""),
            )
            # Generate LLM summary if one isn't already set
            if not community.summary:
                try:
                    llm = LLMClient()
                    if llm.available:
                        # Fetch member nodes and edges for this community
                        member_rows = self._sql_query(
                            "SELECT n.* FROM community_edge ce "
                            "JOIN kg_node n ON ce.target_node_uuid = n.id "
                            f"WHERE ce.source_node_uuid = '{_esc(community.uuid)}'"
                        )
                        edge_rows = self._sql_query(
                            "SELECT e.* FROM community_edge ce "
                            "JOIN kg_edge e ON ce.target_node_uuid = e.id "
                            f"WHERE ce.source_node_uuid = '{_esc(community.uuid)}'"
                        )
                        nodes_for_llm = [
                            {"name": r.get("label", r.get("id", "")[:12]),
                             "summary": r.get("summary", "")}
                            for r in member_rows
                        ]
                        edges_for_llm = [
                            {"source_node": r.get("source_node_id", "")[:12],
                             "target_node": r.get("target_node_id", "")[:12],
                             "relation": r.get("relation", ""),
                             "fact": r.get("fact", "")}
                            for r in edge_rows
                        ]
                        summary_text = llm.summarize_community(
                            community.name or community.uuid[:12],
                            nodes_for_llm,
                            edges_for_llm,
                        )
                        if summary_text:
                            community.summary = summary_text
                            try:
                                self._client._call(
                                    "update_node",
                                    [community.uuid, community.name, "community",
                                     summary_text, "{}"],
                                )
                            except RuntimeError:
                                pass
                except Exception as exc:
                    logger.warning("build_communities() failed to process community: %s", exc)
                    pass
            communities.append(community)

        return communities

    # -------------------------------------------------------------------
    # Episode removal
    # -------------------------------------------------------------------

    def remove_episode(self, episode_uuid: str) -> dict[str, Any]:
        """Remove an episode (deactivate the associated memory).

        Args:
            episode_uuid: The episode UUID (stored as
                ``source_session_id`` on the memory).

        Returns:
            Dict with operation status.
        """
        memories = self._sql_query(
            "SELECT id FROM memory WHERE "
            f"source_session_id = '{_esc(episode_uuid)}'"
        )

        count = 0
        for mem in memories:
            try:
                self._client.delete_memory(mem["id"])
                count += 1
            except RuntimeError:
                pass

        return {"status": "ok", "deleted_count": count, "episode_uuid": episode_uuid}

    # -------------------------------------------------------------------
    # Index maintenance
    # -------------------------------------------------------------------

    def build_indices_and_constraints(self, delete_existing: bool = False) -> dict[str, Any]:
        """No-op: SpacetimeDB manages indices automatically.

        Args:
            delete_existing: Ignored (accepted for compat).

        Returns:
            Dict with status.
        """
        return {"status": "ok", "note": "SpacetimeDB manages indices automatically"}

    # -------------------------------------------------------------------
    # Temporal edge tracking
    # -------------------------------------------------------------------

    def update_edge(
        self,
        edge_id: str,
        relation: str | None = None,
        weight: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an edge, creating a new temporal version.

        Invalidates the current edge version (sets ``invalid_at``) and
        creates a new edge with incremented ``version``.  Both share
        the same ``edge_group_id`` for history tracking.

        Args:
            edge_id: The UUID of the current edge version to update.
            relation: New relation name (or None to keep current).
            weight: New weight (or None to keep current).
            metadata: New metadata dict (or None to keep current).

        Returns:
            Dict with operation status.
        """
        try:
            result = self._client._call(
                "update_edge",
                [
                    edge_id,
                    relation or "",
                    weight if weight is not None else 1.0,
                    json.dumps(metadata) if metadata else "{}",
                ],
            )
            return result
        except RuntimeError as exc:
            raise RuntimeError(
                f"graphiti.update_edge('{edge_id}') failed: {exc}"
            ) from exc

    def get_edge_history(
        self,
        edge_id: str,
    ) -> list[EntityEdge]:
        """Get all versions of an edge (temporal history).

        Retrieves every version of the edge identified by its current
        UUID, ordered from oldest to newest by ``valid_at``.

        Args:
            edge_id: The UUID of any version of the edge.

        Returns:
            List of :class:`EntityEdge` objects, one per version.
        """
        # First find the edge_group_id from this edge
        edge_rows = self._sql_query(
            f"SELECT edge_group_id FROM kg_edge WHERE id = '{_esc(edge_id)}'"
        )
        if not edge_rows:
            return []
        edge_group_id = edge_rows[0].get("edge_group_id", "")
        if not edge_group_id:
            return []

        try:
            self._client._call("get_edge_history", [edge_group_id])
        except RuntimeError:
            return []

        # Read from the result table
        result_rows = self._sql_query(
            "SELECT * FROM edge_history_result WHERE "
            f"edge_group_id = '{_esc(edge_group_id)}'"
        )
        # Sort in Python
        result_rows.sort(key=lambda r: r.get("valid_at", 0))

        return [EntityEdge.from_stmem(r) for r in result_rows]

    # -------------------------------------------------------------------
    # Nodes and edges by episode
    # -------------------------------------------------------------------

    def get_nodes_and_edges_by_episode(
        self, episode_uuids: list[str]
    ) -> SearchResults:
        """Get nodes and edges associated with episodes.

        Args:
            episode_uuids: List of episode UUIDs.

        Returns:
            :class:`SearchResults` with matching nodes and edges.
        """
        nodes: list[EntityNode] = []
        edges: list[EntityEdge] = []

        for ep_uuid in episode_uuids:
            memories = self._sql_query(
                "SELECT id, content FROM memory WHERE "
                f"source_session_id = '{_esc(ep_uuid)}'"
            )

            if not memories:
                continue

            edge_rows = self._sql_query(
                "SELECT e.* FROM kg_edge e, memory m WHERE "
                f"m.source_session_id = '{_esc(ep_uuid)}' AND "
                "e.source_node_id = m.id"
            )

            for row in edge_rows:
                edge = EntityEdge.from_stmem(row)
                if edge.uuid not in [e.uuid for e in edges]:
                    edges.append(edge)

        return SearchResults(edges=edges, nodes=nodes)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _esc(val: str) -> str:
    """Basic SQL string escaping."""
    return val.replace("'", "''")
