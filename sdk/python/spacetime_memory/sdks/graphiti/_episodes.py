"""Graphiti episodes mixin — triplet, episode, and retrieval methods."""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from ...llm import LLMClient
from ._models import (
    AddBulkEpisodeResults,
    AddEpisodeResults,
    AddTripletResults,
    EntityEdge,
    EntityNode,
    EpisodicNode,
    RawEpisode,
)

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class GraphitiEpisodes:
    """Mixin providing add_triplet and related methods."""

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

        actual_source_id, source_dedup_score = self._get_or_create_node(source_node, ws_id)
        actual_target_id, target_dedup_score = self._get_or_create_node(target_node, ws_id)

        # Create the edge
        try:
            self._client.create_edge(
                workspace_id=ws_id,
                source_node_id=actual_source_id,
                target_node_id=actual_target_id,
                relation=edge.name,
                weight=1.0,
                metadata_json=json.dumps(
                    {
                        "fact": edge.fact,
                        **edge.attributes,
                    }
                ),
            )
        except RuntimeError as e:
            raise RuntimeError(f"create_edge failed: {e}") from e

        # Query the actual DB-assigned edge UUID and temporal fields
        # Use a unique edge identifier: source + target + relation
        actual_edge_id = edge.uuid  # fallback
        actual_version = 1
        actual_edge_group_id = ""
        edge_rows = self._client._query(
            "kg_edge",
            workspace_id=ws_id,
            filter_dict={
                "source_node_id": actual_source_id,
                "target_node_id": actual_target_id,
                "relation": edge.name,
            },
            columns=["id", "version", "edge_group_id"],
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

            edges.append(
                EntityEdge(
                    uuid=edge_id,
                    name=relation,
                    fact=f"{source_name} {relation} {target_name}",
                    source_node_uuid=src_uuid,
                    target_node_uuid=tgt_uuid,
                    group_id=gid,
                )
            )

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
        ts = reference_time or datetime.now(UTC)
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
            raise RuntimeError(f"graphiti.add_episode('{name}') failed: {exc}") from exc

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
            extracted,
            ws_id,
            gid,
            episode_uuid,
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
                group_id=group_id or getattr(raw, "group_id", "default"),
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


    def remove_episode(self, episode_uuid: str) -> dict:
        """Remove an episode (deactivate the associated memory).

        Args:
            episode_uuid: The episode UUID (stored as
                ``source_session_id`` on the memory).

        Returns:
            dict with ``status`` and ``episode_uuid`` keys.
        """
        memories = self._client._query(
            "memory", filter_dict={"source_session_id": episode_uuid}, columns=["id"]
        )

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
            columns=["id", "content", "created_at", "source_session_id", "workspace_id", "peer_id"],
        )

        episodes: list[EpisodicNode] = []
        for mem in memories:
            created = mem.get("created_at", 0)
            if created:
                if created > 1e12:
                    created_dt = datetime.fromtimestamp(created / 1_000_000, tz=UTC)
                else:
                    created_dt = datetime.fromtimestamp(created, tz=UTC)
            else:
                created_dt = datetime.now(UTC)

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

