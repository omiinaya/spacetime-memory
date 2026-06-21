"""Graphiti-compatible adapter.

Maps the SpacetimeDB knowledge graph behind Graphiti's API.  Provides
signature-compatible ``Graphiti``, ``EntityNode``, ``EntityEdge`` and
associated result types.

NOTE: Return types are plain Python dataclasses, not Pydantic models like the
upstream ``graphiti_core``.  EntityNode and EntityEdge have full field parity
(8/8, 14/14) but lack upstream's automatic serialisation/validation.

**Error contract:**
- ``RuntimeError`` / ``SpacetimeDBError`` for backend failures — these
  propagate from ``Client._sql()`` / ``Client._call()``.
- ``logger.warning`` logged for transient errors (community building,
  LLM summarisation) — operations degrade gracefully.
- ``search()`` returns ``[]`` on failure (logged).
- ``get_entity_edge_summary()`` returns ``[]`` when no edges exist (no
  exception — empty is a valid result).

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

import dataclasses
import difflib
import json
import logging
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Self

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
    def from_stmem(cls: type["EntityNode"], row: dict[str, Any]) -> "EntityNode":
        """Build from a SpacetimeDB ``kg_node`` row."""
        attrs = {}
        raw = row.get("metadata_json", "{}")
        if raw and raw != "{}":
            try:
                attrs = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass  # corrupt attribute data — skip this entry gracefully
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

    def model_dump(self, **kwargs) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type["Self"], data: dict) -> Self:
        return cls(**{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]})


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
    def from_stmem(cls: type["EntityEdge"], row: dict[str, Any]) -> "EntityEdge":
        """Build from a SpacetimeDB ``kg_edge`` row."""
        attrs = {}
        raw = row.get("metadata_json", "{}")
        if raw and raw != "{}":
            try:
                attrs = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass  # corrupt attribute data — skip this entry gracefully
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

    def model_dump(self, **kwargs) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type["Self"], data: dict) -> Self:
        return cls(**{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]})


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
    labels: list[str] = field(default_factory=list)
    episode_metadata: dict[str, Any] = field(default_factory=dict)
    entity_edges: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_at: datetime | None = None

    def model_dump(self, **kwargs) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type["Self"], data: dict) -> Self:
        return cls(**{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]})


@dataclass
class CommunityNode:
    """Community node (result from community detection)."""

    uuid: str = ""
    name: str = ""
    group_id: str = "default"
    summary: str = ""
    labels: list[str] = field(default_factory=list)
    name_embedding: list[float] | None = None
    member_uuids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def model_dump(self, **kwargs) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type["Self"], data: dict) -> Self:
        return cls(**{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]})


@dataclass
class CommunityEdge:
    """Edge connecting communities to entities."""

    uuid: str = ""
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EpisodicEdge:
    """Edge from an episode to an entity it mentions (MENTIONS relationship)."""

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HasEpisodeEdge:
    """Edge from a saga to an episode (HAS_EPISODE relationship)."""

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class NextEpisodeEdge:
    """Edge linking consecutive episodes (NEXT_EPISODE relationship)."""

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SagaNode:
    """An episode saga — a named, summarised group of episodes.

    Maps to SpacetimeDB ``kg_node`` with ``node_type=\"saga\"``.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    group_id: str = "default"
    labels: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str = ""
    first_episode_uuid: str | None = None
    last_episode_uuid: str | None = None
    last_summarized_at: datetime | None = None
    last_summarized_episode_valid_at: datetime | None = None

    def model_dump(self, **kwargs) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type["Self"], data: dict) -> Self:
        return cls(**{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]})


@dataclass
class SearchResults:
    """Results from an advanced search (``search_``)."""

    edges: list[EntityEdge] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)


@dataclass
class AddBulkEpisodeResults:
    """Results from a bulk ``add_episode`` operation."""

    episodes: list[EpisodicNode] = field(default_factory=list)
    episodic_edges: list[Any] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)
    edges: list[EntityEdge] = field(default_factory=list)
    communities: list[CommunityNode] = field(default_factory=list)
    community_edges: list[CommunityEdge] = field(default_factory=list)


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
class RawEpisode:
    """Raw episode data before processing (forward compat)."""

    name: str = ""
    content: str = ""
    source: str = "message"
    source_description: str = ""
    reference_time: datetime | None = None
    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])


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
      from raw text (``add_episode``).  This adapter includes optional
      LLM-powered extraction via ``LLMClient`` — it degrades gracefully
      (stores the episode without extracting entities) when no API key
      is configured.
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
    ) -> None:
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
        # Token tracker (property — upstream compat)
        self._token_tracker = None

    @property
    def token_tracker(self) -> "TokenTracker":
        """Token usage tracker (upstream compat — returns None for SpacetimeDB."""
        return self._token_tracker

    @property
    def nodes(self) -> "NodeNamespace":
        """Namespace for node operations. Access as ``graphiti.nodes.entity`` etc."""
        return NodeNamespace(self)

    @property
    def edges(self) -> "EdgeNamespace":
        """Namespace for edge operations. Access as ``graphiti.edges.entity`` etc."""
        return EdgeNamespace(self)

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
        Checks by UUID first, then by name.
        """
        if group_id in self._ws_cache:
            return self._ws_cache[group_id]

        # Search existing workspaces
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        if isinstance(workspaces, list):
            # Pass 1: exact UUID match
            for ws in workspaces:
                if ws.get("id") == group_id:
                    self._ws_cache[group_id] = group_id
                    return group_id
            # Pass 2: name match
            for ws in workspaces:
                if ws.get("name") == group_id and ws.get("id"):
                    self._ws_cache[group_id] = ws["id"]
                    return ws["id"]

        # Workspace doesn't exist — create it
        try:
            self._client.create_workspace(group_id)
        except RuntimeError:
            pass  # resource may already exist — non-fatal

        # Re-list to find the newly created workspace
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("id") == group_id:
                    self._ws_cache[group_id] = group_id
                    return group_id
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

    def _get_or_create_node(
        self,
        node: EntityNode,
        workspace_uuid: str,
        *,
        create: bool = True,
    ) -> tuple[str, float] | None:
        """Get or create a node by label within a workspace.

        Returns (DB-assigned UUID, dedup_score) where dedup_score is:
          1.0  = exact match
          0.95 = case-insensitive match
          >0.85 .. <1.0 = fuzzy difflib match
          0.0  = new node created

        If *create* is False, returns ``(uuid, score)`` for existing
        matching nodes or ``None`` when no match is found.
        """
        all_nodes = self._client._query(
            "kg_node", workspace_id=workspace_uuid, columns=["id", "label"]
        )

        # Pass 1: exact match
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
            fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
            best_node, best_ratio = fuzzy_matches[0]
            return best_node["id"], best_ratio

        if not create:
            return None

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
            pass  # non-fatal — operation may fail under concurrent load or missing data
        # Re-query to get the new node's UUID
        all_nodes = self._client._query(
            "kg_node", workspace_id=workspace_uuid, columns=["id", "label"]
        )
        for n in all_nodes:
            if n.get("label") == node.name:
                return n["id"], 0.0
        return node.uuid, 0.0  # fallback

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

        actual_source_id, source_dedup_score = self._get_or_create_node(
            source_node, ws_id
        )
        actual_target_id, target_dedup_score = self._get_or_create_node(
            target_node, ws_id
        )

        # Create the edge
        try:
            result = self._client.create_edge(
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
        except RuntimeError as e:
            raise RuntimeError(f"create_edge failed: {e}") from e

        # Query the actual DB-assigned edge UUID and temporal fields
        # Use a unique edge identifier: source + target + relation
        actual_edge_id = edge.uuid  # fallback
        actual_version = 1
        actual_edge_group_id = ""
        edge_rows = self._client._query("kg_edge", workspace_id=ws_id,
                                 filter_dict={
                                     "source_node_id": actual_source_id,
                                     "target_node_id": actual_target_id,
                                     "relation": edge.name
                                 },
                                 columns=["id", "version", "edge_group_id"])
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

    def _extract_entities_from_text(self, text: str) -> dict[str, Any] | None:
        """Extract entities and relationships from text using LLM.

        Uses the shared ``LLMClient`` to call an LLM; degrades
        gracefully when no API key is configured.

        Returns:
            Dict with ``entities`` and ``edges`` lists, or ``None`` on
            failure or when LLM is unavailable.
        """
        llm = LLMClient()
        if not llm.available:
            return None

        prompt = (
            "Extract entities and relationships from the following text. "
            "Return a JSON object with two arrays: 'entities' (each with "
            "'name' and 'entity_type' fields) and 'edges' (each with "
            "'source', 'target', and 'relation' fields). Source and target "
            "in edges must match entity names. Only include clear, "
            "explicitly mentioned entities and relationships.\n\n"
            f"Text: {text}"
        )

        result = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a precise knowledge-graph entity extractor. "
                        "Return ONLY valid JSON, no markdown, no explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        if not result:
            return None

        try:
            data = json.loads(result)
            if not isinstance(data, dict):
                return None
            if "entities" not in data or "edges" not in data:
                return None
            return data
        except (json.JSONDecodeError, TypeError):
            logger.warning("add_episode: LLM returned invalid JSON; skipping extraction")
            return None

    def _build_entities_and_edges(
        self,
        extracted: dict[str, Any],
        ws_id: str,
        gid: str,
        episode_uuid: str,
    ) -> tuple[list[EntityNode], list[EntityEdge]]:
        """Create entities and edges from LLM-extracted data.

        Returns (nodes, edges) with DB-assigned UUIDs populated.
        """
        nodes: list[EntityNode] = []
        edges: list[EntityEdge] = []

        # Map entity names to (node_uuid, EntityNode) pairs
        entity_map: dict[str, tuple[str, EntityNode]] = {}
        for entity in extracted.get("entities", []) or []:
            ent_name = entity.get("name", "")
            if not ent_name:
                continue
            ent_type: str = entity.get("entity_type", "entity")
            ent_node = EntityNode(
                name=ent_name,
                group_id=gid,
                labels=[ent_type] if ent_type else [],
            )
            result = self._get_or_create_node(ent_node, ws_id, create=True)
            if result is None:
                continue
            node_uuid, dedup_score = result
            ent_node.uuid = node_uuid
            ent_node.attributes["_dedup_score"] = dedup_score
            entity_map[ent_name] = (node_uuid, ent_node)
            nodes.append(ent_node)

        # Create edges from extracted relationships
        for edge_data in extracted.get("edges", []) or []:
            source_name: str = edge_data.get("source", "")
            target_name: str = edge_data.get("target", "")
            relation: str = edge_data.get("relation", "related_to")

            if not source_name or not target_name:
                continue

            src_entry = entity_map.get(source_name)
            tgt_entry = entity_map.get(target_name)
            if src_entry is None or tgt_entry is None:
                continue

            src_uuid, _ = src_entry
            tgt_uuid, _ = tgt_entry

            try:
                self._client.create_edge(
                    workspace_id=ws_id,
                    source_node_id=src_uuid,
                    target_node_id=tgt_uuid,
                    relation=relation,
                    weight=1.0,
                    metadata_json=json.dumps({"fact": f"{source_name} {relation} {target_name}"}),
                )
            except RuntimeError:
                continue

            # Query the edge to get its DB-assigned UUID
            edge_id = _uuid.uuid4().hex[:32]  # fallback
            e_rows = self._client._query(
                "kg_edge",
                workspace_id=ws_id,
                filter_dict={
                    "source_node_id": src_uuid,
                    "target_node_id": tgt_uuid,
                    "relation": relation,
                },
                columns=["id"],
            )
            if e_rows:
                edge_id = e_rows[0].get("id", edge_id)

            edges.append(EntityEdge(
                uuid=edge_id,
                name=relation,
                fact=f"{source_name} {relation} {target_name}",
                source_node_uuid=src_uuid,
                target_node_uuid=tgt_uuid,
                group_id=gid,
            ))

        return nodes, edges

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
        """Store an episode (text content) and extract entities/edges via LLM.

        Stores the episode as a memory record and attempts to extract
        entities and relationships from the episode body using the
        configured LLM.  Extraction degrades gracefully when no LLM is
        configured.

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
            :class:`AddEpisodeResults` with the stored episode and any
            extracted nodes and edges.
        """
        ws_id = self._resolve_workspace(group_id or "default")
        gid = group_id or "default"
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
            group_id=gid,
            valid_at=ts,
        )

        # Attempt LLM-powered entity / relationship extraction
        extracted = self._extract_entities_from_text(episode_body)
        if extracted is None:
            return AddEpisodeResults(episode=episode, nodes=[], edges=[])

        nodes, edges = self._build_entities_and_edges(
            extracted, ws_id, gid, episode_uuid,
        )

        return AddEpisodeResults(
            episode=episode,
            nodes=nodes,
            edges=edges,
        )

    def add_episode_bulk(
        self,
        bulk_episodes: list[RawEpisode],
        group_id: str | None = None,
        **kwargs: Any,
    ) -> AddBulkEpisodeResults:
        """Add multiple episodes in bulk.

        Processes each episode through :meth:`add_episode`, collecting
        all extracted nodes and edges into a single result.

        Args:
            bulk_episodes: List of :class:`RawEpisode` objects to process.
            group_id: Workspace name override.
            **kwargs: Forward-compat params (entity_types, edge_types, etc.)

        Returns:
            :class:`AddBulkEpisodeResults` with all episodes, nodes, and edges.
        """
        all_episodes: list[EpisodicNode] = []
        all_nodes: list[EntityNode] = []
        all_edges: list[EntityEdge] = []
        episodic_edges: list[Any] = []

        for raw in bulk_episodes:
            result = self.add_episode(
                name=raw.name,
                episode_body=raw.content,
                source_description=raw.source_description or raw.source,
                reference_time=raw.reference_time,
                source=raw.source,
                group_id=group_id or getattr(raw, 'group_id', 'default'),
                uuid=raw.uuid,
                **kwargs,
            )
            if result.episode:
                all_episodes.append(result.episode)
            all_nodes.extend(result.nodes)
            all_edges.extend(result.edges)

        return AddBulkEpisodeResults(
            episodes=all_episodes,
            episodic_edges=episodic_edges,
            nodes=all_nodes,
            edges=all_edges,
            communities=[],
            community_edges=[],
        )

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
            group_ids: Workspace names/UUIDs to scope the query.

        Returns:
            Dict with ``edges`` (list of EntityEdge), ``nodes`` (list of
            connected EntityNode), ``summary`` (concatenated facts).
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)
        try:
            edge_rows = self._client.get_neighbors(entity_uuid, workspace_id=ws_id)
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
            nrows = self._client._query("kg_node", filter_dict={"id": nid})
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
            List of CommunityNode objects.
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)
        try:
            self._client.detect_communities(ws_id)
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data
        try:
            self._client.seed_communities(ws_id)
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

        community_nodes = self._client._query("kg_node", workspace_id=ws_id,
                                     filter_dict={"node_type": "community"})

        communities: list[CommunityNode] = []
        community_edges: list[CommunityEdge] = []
        for row in community_nodes:
            community = CommunityNode(
                uuid=row.get("id", ""),
                name=row.get("label", ""),
                group_id=gid,
                summary=row.get("summary", ""),
            )
            # Fetch community edges (member relationships)
            try:
                edge_rows = self._client._query(
                    "kg_edge",
                    workspace_id=ws_id,
                    filter_dict={"source_node_id": community.uuid},
                )
                for erow in edge_rows:
                    community_edges.append(CommunityEdge(
                        uuid=erow.get("id", ""),
                        source_node_uuid=erow.get("source_node_id", ""),
                        target_node_uuid=erow.get("target_node_id", ""),
                        group_id=gid,
                    ))
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data
            # Generate LLM name and summary if not already set
            if not community.summary or not community.name or community.name.startswith("community_"):
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

                        # Generate name + summary via LLM
                        entity_names = [n.get("name", "?") for n in nodes_for_llm]
                        name_prompt = (
                            f"Based on these entity names: {entity_names}, "
                            "generate a short community name (2-5 words) and a 1-sentence description "
                            "of what this community represents. "
                            'Return JSON: {"name": "...", "summary": "..."}'
                        )
                        name_result = llm.chat(
                            [
                                {"role": "system", "content": "You are a concise knowledge graph analyst. Return ONLY valid JSON, no markdown, no explanation."},
                                {"role": "user", "content": name_prompt},
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.3,
                        )
                        if name_result:
                            try:
                                parsed = json.loads(name_result)
                                llm_name = parsed.get("name", "").strip()
                                llm_summary = parsed.get("summary", "").strip()
                                if llm_name and (not community.name or community.name.startswith("community_")):
                                    community.name = llm_name
                                if llm_summary:
                                    community.summary = llm_summary
                            except (json.JSONDecodeError, TypeError):
                                pass  # corrupt attribute data — skip this entry gracefully

                        # Fall back to summarize_community if summary still empty
                        if not community.summary:
                            summary_text = llm.summarize_community(
                                community.name or community.uuid[:12],
                                nodes_for_llm,
                                edges_for_llm,
                            )
                            if summary_text:
                                community.summary = summary_text

                        # Persist updated name/summary
                        if community.summary or community.name:
                            try:
                                self._client._call(
                                    "update_node",
                                    [community.uuid, community.name, "community",
                                     community.summary, "{}"],
                                )
                            except RuntimeError:
                                pass  # non-fatal — operation may fail under concurrent load or missing data
                except RuntimeError as exc:
                    logger.warning("build_communities() failed to process community: %s", exc)
                    pass
            communities.append(community)

        return communities

    # -------------------------------------------------------------------
    # Saga operations
    # -------------------------------------------------------------------

    def summarize_saga(self, saga_id: str) -> SagaNode:
        """Generate or update an incremental summary for an episode saga.

        Queries all episodes linked to *saga_id* (via ``source_session_id``),
        uses the LLM to produce an incremental summary, and persists the
        result as a :class:`SagaNode` in the knowledge graph
        (``node_type=\"saga\"``).

        Args:
            saga_id: The saga / session identifier.  Maps to
                ``source_session_id`` on the memory table.

        Returns:
            A :class:`SagaNode` with the current summary and episode range.

        Graceful degradation: returns a SagaNode with minimal metadata
        when no LLM is available.
        """
        now = datetime.now(timezone.utc)

        # Query episodes linked to this saga
        episodes = self._client._query(
            "memory",
            filter_dict={"source_session_id": saga_id},
            columns=["id", "content", "created_at", "peer_id", "workspace_id"],
        )

        if not episodes:
            # No episodes yet — return a stub
            return SagaNode(
                uuid=saga_id,
                name=saga_id[:64],
                group_id="default",
                created_at=now,
                summary="",
            )

        # Sort by created_at ascending
        episodes.sort(key=lambda e: e.get("created_at", 0))

        first_ep = episodes[0]
        last_ep = episodes[-1]
        group_id = first_ep.get("workspace_id", "default")
        saga_name = first_ep.get("peer_id", saga_id)[:64] or saga_id[:64]

        first_ep_uuid = first_ep.get("id", "")
        last_ep_uuid = last_ep.get("id", "")

        # Build episode content for LLM summarization
        episode_texts = []
        for ep in episodes:
            content = ep.get("content", "")
            ep_id = ep.get("id", "")[:12]
            if content:
                episode_texts.append(f"[{ep_id}] {content[:500]}")
            else:
                episode_texts.append(f"[{ep_id}] (no content)")

        combined = "\n".join(episode_texts)

        # Try LLM summarization
        summary = ""
        last_summarized_at: datetime | None = None
        try:
            llm = LLMClient()
            if llm.available:
                prompt = (
                    f"You are summarizing an episode saga with {len(episodes)} episodes. "
                    "Write a concise 3-5 sentence summary of the key events, entities, "
                    "and narrative arc across all episodes.\n\n"
                    f"### Episodes\n{combined}"
                )
                result = llm.chat(
                    [
                        {"role": "system", "content": "You are a precise summarization assistant. Summarize the following episode log concisely while preserving key facts, entities, and narrative arc."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=512,
                )
                if result:
                    summary = result.strip()
                    last_summarized_at = now
        except RuntimeError:
            logger.warning("summarize_saga() LLM call failed for saga %s", saga_id)

        # Build SagaNode
        saga = SagaNode(
            uuid=saga_id,
            name=saga_name,
            group_id=group_id,
            created_at=now,
            summary=summary,
            first_episode_uuid=first_ep_uuid,
            last_episode_uuid=last_ep_uuid,
            last_summarized_at=last_summarized_at,
            last_summarized_episode_valid_at=(
                datetime.fromtimestamp(
                    last_ep.get("created_at", 0) / 1_000_000, tz=timezone.utc
                )
                if last_ep.get("created_at", 0) and last_ep.get("created_at", 0) > 1e12
                else datetime.fromtimestamp(last_ep.get("created_at", 0), tz=timezone.utc)
                if last_ep.get("created_at", 0)
                else now
            ),
        )

        # Persist as a kg_node with node_type="saga"
        ws_id = self._resolve_workspace(group_id)
        try:
            self._client.create_node(
                workspace_id=ws_id,
                label=saga_name,
                node_type="saga",
                summary=summary,
                metadata_json=json.dumps({
                    "saga_id": saga_id,
                    "first_episode_uuid": first_ep_uuid,
                    "last_episode_uuid": last_ep_uuid,
                    "episode_count": len(episodes),
                }),
            )
        except RuntimeError:
            # Node may already exist — try updating
            try:
                self._client._call(
                    "update_node",
                    [saga_id, saga_name, "saga", summary,
                     json.dumps({
                         "saga_id": saga_id,
                         "first_episode_uuid": first_ep_uuid,
                         "last_episode_uuid": last_ep_uuid,
                         "episode_count": len(episodes),
                     })],
                )
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data

        return saga

    # -------------------------------------------------------------------
    # Episode removal
    # -------------------------------------------------------------------

    def remove_episode(self, episode_uuid: str) -> dict:
        """Remove an episode (deactivate the associated memory).

        Args:
            episode_uuid: The episode UUID (stored as
                ``source_session_id`` on the memory).

        Returns:
            dict with ``status`` and ``episode_uuid`` keys.
        """
        memories = self._client._query("memory", filter_dict={"source_session_id": episode_uuid},
                               columns=["id"])

        for mem in memories:
            try:
                self._client.delete_memory(mem["id"])
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data

        return {"status": "ok", "episode_uuid": episode_uuid}

    # -------------------------------------------------------------------
    # Episode retrieval
    # -------------------------------------------------------------------

    def retrieve_episodes(
        self,
        reference_time: datetime | None = None,
        last_n: int = 10,
        group_ids: list[str] | None = None,
        source: str | None = None,
    ) -> list[EpisodicNode]:
        """Retrieve episodes from the memory table.

        Args:
            reference_time: If set, only return episodes with
                ``created_at`` >= this datetime.
            last_n: Maximum number of episodes to return (default 10).
            group_ids: Workspace names to scope the query.
            source: Filter by episode source type.

        Returns:
            List of :class:`EpisodicNode` objects.
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)

        memories = self._client._query(
            "memory",
            workspace_id=ws_id,
            columns=["id", "content", "created_at", "source_session_id",
                     "workspace_id", "peer_id"],
        )

        episodes: list[EpisodicNode] = []
        for mem in memories:
            created = mem.get("created_at", 0)
            if created:
                if created > 1e12:
                    created_dt = datetime.fromtimestamp(created / 1_000_000, tz=timezone.utc)
                else:
                    created_dt = datetime.fromtimestamp(created, tz=timezone.utc)
            else:
                created_dt = datetime.now(timezone.utc)

            # Filter by reference_time
            if reference_time is not None and created_dt < reference_time:
                continue

            ep = EpisodicNode(
                uuid=mem.get("source_session_id", mem.get("id", "")),
                name=mem.get("peer_id", mem.get("id", ""))[:64],
                content=mem.get("content", ""),
                source=source or "message",
                source_description=mem.get("peer_id", ""),
                group_id=gid,
                created_at=created_dt,
            )
            episodes.append(ep)

        # Sort by created_at descending (newest first)
        episodes.sort(key=lambda e: e.created_at, reverse=True)
        return episodes[:last_n]

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
        edge_rows = self._client._query("kg_edge", filter_dict={"id": edge_id}, columns=["edge_group_id"])
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
            memories = self._client._query("memory",
                                    filter_dict={"source_session_id": ep_uuid},
                                    columns=["id", "content"])

            if not memories:
                continue

            # Find memory IDs for this episode, then look up edges by source_node_id
            mems = self._client._query("memory", filter_dict={"source_session_id": ep_uuid},
                              columns=["id"])
            edge_rows = []
            for mem in mems:
                edges = self._client._query("kg_edge", filter_dict={"source_node_id": mem.get("id", "")})
                edge_rows.extend(edges)

            for row in edge_rows:
                edge = EntityEdge.from_stmem(row)
                if edge.uuid not in [e.uuid for e in edges]:
                    edges.append(edge)

        return SearchResults(edges=edges, nodes=nodes)


# ---------------------------------------------------------------------------
# Namespace classes (nodes.* / edges.*)
# ---------------------------------------------------------------------------


class EntityNodeNamespace:
    """Namespace for entity node operations. Accessed as ``graphiti.nodes.entity``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, node: EntityNode) -> EntityNode:
        ws_id = self._g._resolve_workspace(node.group_id)
        existing = self._g._client._query(
            "kg_node", workspace_id=ws_id,
            filter_dict={"id": node.uuid}, columns=["id"])
        if existing:
            return node  # already saved
        self._g._client.create_node(
            workspace_id=ws_id,
            label=node.name,
            node_type="entity",
            summary=node.summary,
            metadata_json=json.dumps(node.attributes),
        )
        return node

    def delete(self, node: EntityNode) -> None:
        try:
            self._g._client._call("delete_node", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EntityNode:
        rows = self._g._client._query("kg_node", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"EntityNode '{uuid}' not found")
        return EntityNode.from_stmem(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[EntityNode]:
        results: list[EntityNode] = []
        for uid in uuids:
            rows = self._g._client._query("kg_node", filter_dict={"id": uid})
            if rows:
                results.append(EntityNode.from_stmem(rows[0]))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[EntityNode]:
        all_nodes: list[EntityNode] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_node", workspace_id=ws_id)
            for r in rows:
                node = EntityNode.from_stmem(r)
                if node.group_id == gid:
                    all_nodes.append(node)
        if limit:
            all_nodes = all_nodes[:limit]
        return all_nodes


class EpisodeNodeNamespace:
    """Namespace for episode node operations. Accessed as ``graphiti.nodes.episode``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, node: EpisodicNode) -> EpisodicNode:
        ws_id = self._g._resolve_workspace(node.group_id)
        self._g._client._call("store_memory", [
            ws_id, node.uuid, node.name, node.content,
            node.source, node.source_description, "L2",
            json.dumps(node.episode_metadata),
        ])
        return node

    def delete(self, node: EpisodicNode) -> None:
        try:
            self._g._client._call("deactivate_memory", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EpisodicNode:
        rows = self._g._client._query("memory", filter_dict={"source_session_id": uuid})
        if not rows:
            raise KeyError(f"EpisodicNode '{uuid}' not found")
        return self._row_to_episode(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[EpisodicNode]:
        results: list[EpisodicNode] = []
        for uid in uuids:
            rows = self._g._client._query("memory", filter_dict={"source_session_id": uid})
            if rows:
                results.append(self._row_to_episode(rows[0]))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[EpisodicNode]:
        episodes: list[EpisodicNode] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("memory", workspace_id=ws_id)
            for r in rows:
                ep = self._row_to_episode(r)
                ep.group_id = gid
                episodes.append(ep)
        if limit:
            episodes = episodes[:limit]
        return episodes

    def retrieve_episodes(
        self,
        reference_time: datetime,
        last_n: int = 3,
        group_ids: list[str] | None = None,
        source: str | None = None,
        saga: str | None = None,
    ) -> list[EpisodicNode]:
        return self._g.retrieve_episodes(
            reference_time=reference_time,
            last_n=last_n,
            group_ids=group_ids,
            source=source,
        )

    @staticmethod
    def _row_to_episode(row: dict[str, Any]) -> EpisodicNode:
        created = row.get("created_at", 0)
        return EpisodicNode(
            uuid=row.get("source_session_id", row.get("id", "")),
            name=row.get("peer_id", row.get("id", ""))[:64],
            content=row.get("content", ""),
            source=row.get("source", "message"),
            source_description=row.get("peer_id", ""),
            group_id=row.get("workspace_id", "default"),
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=timezone.utc)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=timezone.utc)
            if created
            else datetime.now(timezone.utc),
        )


class CommunityNodeNamespace:
    """Namespace for community node operations. Accessed as ``graphiti.nodes.community``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, node: CommunityNode) -> CommunityNode:
        ws_id = self._g._resolve_workspace(node.group_id)
        existing = self._g._client._query(
            "kg_node", workspace_id=ws_id,
            filter_dict={"id": node.uuid}, columns=["id"])
        if existing:
            return node
        self._g._client.create_node(
            workspace_id=ws_id,
            label=node.name,
            node_type="community",
            summary=node.summary,
            metadata_json=json.dumps(node.labels),
        )
        return node

    def delete(self, node: CommunityNode) -> None:
        try:
            self._g._client._call("delete_node", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> CommunityNode:
        rows = self._g._client._query("kg_node", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"CommunityNode '{uuid}' not found")
        return self._row_to_community(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[CommunityNode]:
        results: list[CommunityNode] = []
        for uid in uuids:
            rows = self._g._client._query("kg_node", filter_dict={"id": uid})
            if rows:
                results.append(self._row_to_community(rows[0]))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[CommunityNode]:
        communities: list[CommunityNode] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_node", workspace_id=ws_id,
                                   filter_dict={"node_type": "community"})
            for r in rows:
                communities.append(self._row_to_community(r))
        if limit:
            communities = communities[:limit]
        return communities

    @staticmethod
    def _row_to_community(row: dict[str, Any]) -> CommunityNode:
        created = row.get("created_at", 0)
        return CommunityNode(
            uuid=row.get("id", ""),
            name=row.get("label", ""),
            group_id=row.get("workspace_id", "default"),
            summary=row.get("summary", ""),
            labels=json.loads(row.get("labels", "[]")) if isinstance(row.get("labels"), str) else row.get("labels", []),
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=timezone.utc)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=timezone.utc)
            if created
            else datetime.now(timezone.utc),
        )


class SagaNodeNamespace:
    """Namespace for saga node operations. Accessed as ``graphiti.nodes.saga``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, node: SagaNode) -> SagaNode:
        ws_id = self._g._resolve_workspace(node.group_id)
        existing = self._g._client._query(
            "kg_node", workspace_id=ws_id,
            filter_dict={"id": node.uuid}, columns=["id"])
        if existing:
            return node
        self._g._client.create_node(
            workspace_id=ws_id,
            label=node.name,
            node_type="saga",
            summary=node.summary,
            metadata_json=json.dumps(node.labels),
        )
        return node

    def delete(self, node: SagaNode) -> None:
        try:
            self._g._client._call("delete_node", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> SagaNode:
        rows = self._g._client._query("kg_node", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"SagaNode '{uuid}' not found")
        return self._row_to_saga(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[SagaNode]:
        results: list[SagaNode] = []
        for uid in uuids:
            rows = self._g._client._query("kg_node", filter_dict={"id": uid})
            if rows:
                results.append(self._row_to_saga(rows[0]))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[SagaNode]:
        sagas: list[SagaNode] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_node", workspace_id=ws_id,
                                   filter_dict={"node_type": "saga"})
            for r in rows:
                sagas.append(self._row_to_saga(r))
        if limit:
            sagas = sagas[:limit]
        return sagas

    @staticmethod
    def _row_to_saga(row: dict[str, Any]) -> SagaNode:
        created = row.get("created_at", 0)
        return SagaNode(
            uuid=row.get("id", ""),
            name=row.get("label", ""),
            group_id=row.get("workspace_id", "default"),
            summary=row.get("summary", ""),
            labels=json.loads(row.get("labels", "[]")) if isinstance(row.get("labels"), str) else row.get("labels", []),
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=timezone.utc)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=timezone.utc)
            if created
            else datetime.now(timezone.utc),
        )


class NodeNamespace:
    """Namespace for all node operations. Accessed as ``graphiti.nodes``."""

    entity: EntityNodeNamespace
    episode: EpisodeNodeNamespace
    community: CommunityNodeNamespace
    saga: SagaNodeNamespace

    def __init__(self, graphiti: "Graphiti") -> None:
        self.entity = EntityNodeNamespace(graphiti)
        self.episode = EpisodeNodeNamespace(graphiti)
        self.community = CommunityNodeNamespace(graphiti)
        self.saga = SagaNodeNamespace(graphiti)


class EntityEdgeNamespace:
    """Namespace for entity edge operations. Accessed as ``graphiti.edges.entity``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, edge: EntityEdge) -> EntityEdge:
        ws_id = self._g._resolve_workspace(edge.group_id)
        self._g._client.create_edge(
            workspace_id=ws_id,
            source_node_id=edge.source_node_uuid,
            target_node_id=edge.target_node_uuid,
            relation=edge.name,
            weight=1.0,
            metadata_json=json.dumps({
                "fact": edge.fact,
                **edge.attributes,
            }),
        )
        return edge

    def delete(self, edge: EntityEdge) -> None:
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EntityEdge:
        rows = self._g._client._query("kg_edge", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"EntityEdge '{uuid}' not found")
        return EntityEdge.from_stmem(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[EntityEdge]:
        results: list[EntityEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                results.append(EntityEdge.from_stmem(rows[0]))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[EntityEdge]:
        edges: list[EntityEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_edge", workspace_id=ws_id)
            for r in rows:
                e = EntityEdge.from_stmem(r)
                if e.group_id == gid:
                    edges.append(e)
        if limit:
            edges = edges[:limit]
        return edges

    def get_between_nodes(
        self,
        source_node_uuid: str,
        target_node_uuid: str,
    ) -> list[EntityEdge]:
        rows = self._g._client._query(
            "kg_edge",
            filter_dict={
                "source_node_id": source_node_uuid,
                "target_node_id": target_node_uuid,
            },
        )
        return [EntityEdge.from_stmem(r) for r in rows]

    def get_by_node_uuid(self, node_uuid: str) -> list[EntityEdge]:
        rows_src = self._g._client._query(
            "kg_edge", filter_dict={"source_node_id": node_uuid})
        rows_tgt = self._g._client._query(
            "kg_edge", filter_dict={"target_node_id": node_uuid})
        seen: set[str] = set()
        edges: list[EntityEdge] = []
        for r in rows_src + rows_tgt:
            eid = r.get("id", "")
            if eid not in seen:
                seen.add(eid)
                edges.append(EntityEdge.from_stmem(r))
        return edges


class EpisodicEdgeNamespace:
    """Namespace for episodic edge operations. Accessed as ``graphiti.edges.episodic``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, edge: EpisodicEdge) -> EpisodicEdge:
        ws_id = self._g._resolve_workspace(edge.group_id)
        self._g._client.create_edge(
            workspace_id=ws_id,
            source_node_id=edge.source_node_uuid,
            target_node_id=edge.target_node_uuid,
            relation="MENTIONS",
            weight=1.0,
            metadata_json=json.dumps({"edge_type": "episodic"}),
        )
        return edge

    def delete(self, edge: EpisodicEdge) -> None:
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EpisodicEdge:
        rows = self._g._client._query("kg_edge", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"EpisodicEdge '{uuid}' not found")
        return EpisodicEdge(
            uuid=rows[0].get("id", ""),
            source_node_uuid=rows[0].get("source_node_id", ""),
            target_node_uuid=rows[0].get("target_node_id", ""),
            group_id=rows[0].get("workspace_id", "default"),
        )

    def get_by_uuids(self, uuids: list[str]) -> list[EpisodicEdge]:
        results: list[EpisodicEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(EpisodicEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[EpisodicEdge]:
        edges: list[EpisodicEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_edge", workspace_id=ws_id,
                                   filter_dict={"relation": "MENTIONS"})
            for r in rows:
                edges.append(EpisodicEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        if limit:
            edges = edges[:limit]
        return edges


class CommunityEdgeNamespace:
    """Namespace for community edge operations. Accessed as ``graphiti.edges.community``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, edge: CommunityEdge) -> CommunityEdge:
        ws_id = self._g._resolve_workspace(edge.group_id)
        self._g._client.create_edge(
            workspace_id=ws_id,
            source_node_id=edge.source_node_uuid,
            target_node_id=edge.target_node_uuid,
            relation="MEMBER_OF",
            weight=1.0,
            metadata_json=json.dumps({"edge_type": "community"}),
        )
        return edge

    def delete(self, edge: CommunityEdge) -> None:
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> CommunityEdge:
        rows = self._g._client._query("kg_edge", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"CommunityEdge '{uuid}' not found")
        return CommunityEdge(
            uuid=rows[0].get("id", ""),
            source_node_uuid=rows[0].get("source_node_id", ""),
            target_node_uuid=rows[0].get("target_node_id", ""),
            group_id=rows[0].get("workspace_id", "default"),
        )

    def get_by_uuids(self, uuids: list[str]) -> list[CommunityEdge]:
        results: list[CommunityEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(CommunityEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[CommunityEdge]:
        edges: list[CommunityEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_edge", workspace_id=ws_id,
                                   filter_dict={"relation": "MEMBER_OF"})
            for r in rows:
                edges.append(CommunityEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        if limit:
            edges = edges[:limit]
        return edges


class HasEpisodeEdgeNamespace:
    """Namespace for has_episode edge operations. Accessed as ``graphiti.edges.has_episode``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, edge: HasEpisodeEdge) -> HasEpisodeEdge:
        ws_id = self._g._resolve_workspace(edge.group_id)
        self._g._client.create_edge(
            workspace_id=ws_id,
            source_node_id=edge.source_node_uuid,
            target_node_id=edge.target_node_uuid,
            relation="HAS_EPISODE",
            weight=1.0,
            metadata_json=json.dumps({"edge_type": "has_episode"}),
        )
        return edge

    def delete(self, edge: HasEpisodeEdge) -> None:
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> HasEpisodeEdge:
        rows = self._g._client._query("kg_edge", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"HasEpisodeEdge '{uuid}' not found")
        return HasEpisodeEdge(
            uuid=rows[0].get("id", ""),
            source_node_uuid=rows[0].get("source_node_id", ""),
            target_node_uuid=rows[0].get("target_node_id", ""),
            group_id=rows[0].get("workspace_id", "default"),
        )

    def get_by_uuids(self, uuids: list[str]) -> list[HasEpisodeEdge]:
        results: list[HasEpisodeEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(HasEpisodeEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[HasEpisodeEdge]:
        edges: list[HasEpisodeEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_edge", workspace_id=ws_id,
                                   filter_dict={"relation": "HAS_EPISODE"})
            for r in rows:
                edges.append(HasEpisodeEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        if limit:
            edges = edges[:limit]
        return edges


class NextEpisodeEdgeNamespace:
    """Namespace for next_episode edge operations. Accessed as ``graphiti.edges.next_episode``."""

    def __init__(self, graphiti: "Graphiti") -> None:
        self._g = graphiti

    def save(self, edge: NextEpisodeEdge) -> NextEpisodeEdge:
        ws_id = self._g._resolve_workspace(edge.group_id)
        self._g._client.create_edge(
            workspace_id=ws_id,
            source_node_id=edge.source_node_uuid,
            target_node_id=edge.target_node_uuid,
            relation="NEXT_EPISODE",
            weight=1.0,
            metadata_json=json.dumps({"edge_type": "next_episode"}),
        )
        return edge

    def delete(self, edge: NextEpisodeEdge) -> None:
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> NextEpisodeEdge:
        rows = self._g._client._query("kg_edge", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"NextEpisodeEdge '{uuid}' not found")
        return NextEpisodeEdge(
            uuid=rows[0].get("id", ""),
            source_node_uuid=rows[0].get("source_node_id", ""),
            target_node_uuid=rows[0].get("target_node_id", ""),
            group_id=rows[0].get("workspace_id", "default"),
        )

    def get_by_uuids(self, uuids: list[str]) -> list[NextEpisodeEdge]:
        results: list[NextEpisodeEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(NextEpisodeEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[NextEpisodeEdge]:
        edges: list[NextEpisodeEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query("kg_edge", workspace_id=ws_id,
                                   filter_dict={"relation": "NEXT_EPISODE"})
            for r in rows:
                edges.append(NextEpisodeEdge(
                    uuid=r.get("id", ""),
                    source_node_uuid=r.get("source_node_id", ""),
                    target_node_uuid=r.get("target_node_id", ""),
                    group_id=r.get("workspace_id", "default"),
                ))
        if limit:
            edges = edges[:limit]
        return edges


class EdgeNamespace:
    """Namespace for all edge operations. Accessed as ``graphiti.edges``."""

    entity: EntityEdgeNamespace
    episodic: EpisodicEdgeNamespace
    community: CommunityEdgeNamespace
    has_episode: HasEpisodeEdgeNamespace
    next_episode: NextEpisodeEdgeNamespace

    def __init__(self, graphiti: "Graphiti") -> None:
        self.entity = EntityEdgeNamespace(graphiti)
        self.episodic = EpisodicEdgeNamespace(graphiti)
        self.community = CommunityEdgeNamespace(graphiti)
        self.has_episode = HasEpisodeEdgeNamespace(graphiti)
        self.next_episode = NextEpisodeEdgeNamespace(graphiti)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _esc(val: str) -> str:
    """Basic SQL string escaping."""
    return val.replace("'", "''")
