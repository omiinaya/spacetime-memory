"""Node namespace classes for the Graphiti adapter."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ._models import (
    CommunityNode,
    EntityNode,
    EpisodicNode,
    SagaNode,
)

if TYPE_CHECKING:
    from ._client import Graphiti

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class EntityNodeNamespace:
    """Namespace for entity node operations. Accessed as ``graphiti.nodes.entity``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, node: EntityNode) -> EntityNode:
        """Persist the record to SpacetimeDB."""
        ws_id = self._g._resolve_workspace(node.group_id)
        existing = self._g._client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"id": node.uuid}, columns=["id"]
        )
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_node", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EntityNode:
        """Look up a single record by UUID."""
        rows = self._g._client._query("kg_node", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"EntityNode '{uuid}' not found")
        return EntityNode.from_stmem(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[EntityNode]:
        """Look up multiple records by UUIDs."""
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
        """List records filtered by group IDs."""
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

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, node: EpisodicNode) -> EpisodicNode:
        """Persist the record to SpacetimeDB."""
        ws_id = self._g._resolve_workspace(node.group_id)
        self._g._client._call(
            "store_memory",
            [
                ws_id,
                node.uuid,  # peer_id — episode UUID
                node.name,  # observer_id — who observed this
                "episode",  # memory_type — episode type
                node.content,  # content — the episode text
                node.source_description or node.name,  # summary — short description
                json.dumps(node.entity_edges),  # entities_json — entity references
                0.8,  # confidence — default
                node.uuid,  # source_session_id
                "",  # source_message_id
                "",  # images_json — not supported yet in graphiti
            ],
        )
        return node

    def delete(self, node: EpisodicNode) -> None:
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("deactivate_memory", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EpisodicNode:
        """Look up a single record by UUID."""
        rows = self._g._client._query("memory", filter_dict={"source_session_id": uuid})
        if not rows:
            raise KeyError(f"EpisodicNode '{uuid}' not found")
        return self._row_to_episode(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[EpisodicNode]:
        """Look up multiple records by UUIDs."""
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
        """List records filtered by group IDs."""
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
        """Retrieve episode memories for a time window."""
        return self._g.retrieve_episodes(
            reference_time=reference_time,
            last_n=last_n,
            group_ids=group_ids,
            source=source,
        )

    @staticmethod
    def _row_to_episode(row: dict[str, Any]) -> EpisodicNode:
        """Convert a STDB row dict to an Episode dataclass."""
        created = row.get("created_at", 0)
        return EpisodicNode(
            uuid=row.get("source_session_id", row.get("id", "")),
            name=row.get("peer_id", row.get("id", ""))[:64],
            content=row.get("content", ""),
            source=row.get("source", "message"),
            source_description=row.get("peer_id", ""),
            group_id=row.get("workspace_id", "default"),
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=UTC)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=UTC)
            if created
            else datetime.now(UTC),
        )



class CommunityNodeNamespace:
    """Namespace for community node operations. Accessed as ``graphiti.nodes.community``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, node: CommunityNode) -> CommunityNode:
        """Persist the record to SpacetimeDB."""
        ws_id = self._g._resolve_workspace(node.group_id)
        existing = self._g._client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"id": node.uuid}, columns=["id"]
        )
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_node", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> CommunityNode:
        """Look up a single record by UUID."""
        rows = self._g._client._query("kg_node", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"CommunityNode '{uuid}' not found")
        return self._row_to_community(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[CommunityNode]:
        """Look up multiple records by UUIDs."""
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
        """List records filtered by group IDs."""
        communities: list[CommunityNode] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query(
                "kg_node", workspace_id=ws_id, filter_dict={"node_type": "community"}
            )
            for r in rows:
                communities.append(self._row_to_community(r))
        if limit:
            communities = communities[:limit]
        return communities

    @staticmethod
    def _row_to_community(row: dict[str, Any]) -> CommunityNode:
        """Convert a STDB row dict to a Community dataclass."""
        created = row.get("created_at", 0)
        return CommunityNode(
            uuid=row.get("id", ""),
            name=row.get("label", ""),
            group_id=row.get("workspace_id", "default"),
            summary=row.get("summary", ""),
            labels=json.loads(row.get("labels", "[]"))
            if isinstance(row.get("labels"), str)
            else row.get("labels", []),
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=UTC)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=UTC)
            if created
            else datetime.now(UTC),
        )



class SagaNodeNamespace:
    """Namespace for saga node operations. Accessed as ``graphiti.nodes.saga``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, node: SagaNode) -> SagaNode:
        """Persist the record to SpacetimeDB."""
        ws_id = self._g._resolve_workspace(node.group_id)
        existing = self._g._client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"id": node.uuid}, columns=["id"]
        )
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_node", [node.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> SagaNode:
        """Look up a single record by UUID."""
        rows = self._g._client._query("kg_node", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"SagaNode '{uuid}' not found")
        return self._row_to_saga(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[SagaNode]:
        """Look up multiple records by UUIDs."""
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
        """List records filtered by group IDs."""
        sagas: list[SagaNode] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query(
                "kg_node", workspace_id=ws_id, filter_dict={"node_type": "saga"}
            )
            for r in rows:
                sagas.append(self._row_to_saga(r))
        if limit:
            sagas = sagas[:limit]
        return sagas

    @staticmethod
    def _row_to_saga(row: dict[str, Any]) -> SagaNode:
        """Convert a STDB row dict to a Saga dataclass."""
        created = row.get("created_at", 0)
        return SagaNode(
            uuid=row.get("id", ""),
            name=row.get("label", ""),
            group_id=row.get("workspace_id", "default"),
            summary=row.get("summary", ""),
            labels=json.loads(row.get("labels", "[]"))
            if isinstance(row.get("labels"), str)
            else row.get("labels", []),
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=UTC)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=UTC)
            if created
            else datetime.now(UTC),
        )



class NodeNamespace:
    """Namespace for all node operations. Accessed as ``graphiti.nodes``."""

    entity: EntityNodeNamespace
    episode: EpisodeNodeNamespace
    community: CommunityNodeNamespace
    saga: SagaNodeNamespace

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self.entity = EntityNodeNamespace(graphiti)
        self.episode = EpisodeNodeNamespace(graphiti)
        self.community = CommunityNodeNamespace(graphiti)
        self.saga = SagaNodeNamespace(graphiti)


