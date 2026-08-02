"""Edge namespace classes for the Graphiti adapter."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ._models import (
    CommunityEdge,
    EntityEdge,
    EpisodicEdge,
    HasEpisodeEdge,
    NextEpisodeEdge,
)

if TYPE_CHECKING:
    from ._client import Graphiti

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class EntityEdgeNamespace:
    """Namespace for entity edge operations. Accessed as ``graphiti.edges.entity``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, edge: EntityEdge) -> EntityEdge:
        """Persist the record to SpacetimeDB."""
        ws_id = self._g._resolve_workspace(edge.group_id)
        self._g._client.create_edge(
            workspace_id=ws_id,
            source_node_id=edge.source_node_uuid,
            target_node_id=edge.target_node_uuid,
            relation=edge.name,
            weight=1.0,
            metadata_json=json.dumps(
                {
                    "fact": edge.fact,
                    **edge.attributes,
                }
            ),
        )
        return edge

    def delete(self, edge: EntityEdge) -> None:
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EntityEdge:
        """Look up a single record by UUID."""
        rows = self._g._client._query("kg_edge", filter_dict={"id": uuid})
        if not rows:
            raise KeyError(f"EntityEdge '{uuid}' not found")
        return EntityEdge.from_stmem(rows[0])

    def get_by_uuids(self, uuids: list[str]) -> list[EntityEdge]:
        """Look up multiple records by UUIDs."""
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
        """List records filtered by group IDs."""
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
        """Get edges between two nodes by their UUIDs."""
        rows = self._g._client._query(
            "kg_edge",
            filter_dict={
                "source_node_id": source_node_uuid,
                "target_node_id": target_node_uuid,
            },
        )
        return [EntityEdge.from_stmem(r) for r in rows]

    def get_by_node_uuid(self, node_uuid: str) -> list[EntityEdge]:
        """Get all edges connected to a node."""
        rows_src = self._g._client._query("kg_edge", filter_dict={"source_node_id": node_uuid})
        rows_tgt = self._g._client._query("kg_edge", filter_dict={"target_node_id": node_uuid})
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

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, edge: EpisodicEdge) -> EpisodicEdge:
        """Persist the record to SpacetimeDB."""
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> EpisodicEdge:
        """Look up a single record by UUID."""
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
        """Look up multiple records by UUIDs."""
        results: list[EpisodicEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(
                    EpisodicEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[EpisodicEdge]:
        """List records filtered by group IDs."""
        edges: list[EpisodicEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query(
                "kg_edge", workspace_id=ws_id, filter_dict={"relation": "MENTIONS"}
            )
            for r in rows:
                edges.append(
                    EpisodicEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        if limit:
            edges = edges[:limit]
        return edges



class CommunityEdgeNamespace:
    """Namespace for community edge operations. Accessed as ``graphiti.edges.community``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, edge: CommunityEdge) -> CommunityEdge:
        """Persist the record to SpacetimeDB."""
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> CommunityEdge:
        """Look up a single record by UUID."""
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
        """Look up multiple records by UUIDs."""
        results: list[CommunityEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(
                    CommunityEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[CommunityEdge]:
        """List records filtered by group IDs."""
        edges: list[CommunityEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query(
                "kg_edge", workspace_id=ws_id, filter_dict={"relation": "MEMBER_OF"}
            )
            for r in rows:
                edges.append(
                    CommunityEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        if limit:
            edges = edges[:limit]
        return edges



class HasEpisodeEdgeNamespace:
    """Namespace for has_episode edge operations. Accessed as ``graphiti.edges.has_episode``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, edge: HasEpisodeEdge) -> HasEpisodeEdge:
        """Persist the record to SpacetimeDB."""
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> HasEpisodeEdge:
        """Look up a single record by UUID."""
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
        """Look up multiple records by UUIDs."""
        results: list[HasEpisodeEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(
                    HasEpisodeEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[HasEpisodeEdge]:
        """List records filtered by group IDs."""
        edges: list[HasEpisodeEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query(
                "kg_edge", workspace_id=ws_id, filter_dict={"relation": "HAS_EPISODE"}
            )
            for r in rows:
                edges.append(
                    HasEpisodeEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        if limit:
            edges = edges[:limit]
        return edges



class NextEpisodeEdgeNamespace:
    """Namespace for next_episode edge operations. Accessed as ``graphiti.edges.next_episode``."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
        self._g = graphiti

    def save(self, edge: NextEpisodeEdge) -> NextEpisodeEdge:
        """Persist the record to SpacetimeDB."""
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
        """Remove the record from SpacetimeDB."""
        try:
            self._g._client._call("delete_edge", [edge.uuid])
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

    def get_by_uuid(self, uuid: str) -> NextEpisodeEdge:
        """Look up a single record by UUID."""
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
        """Look up multiple records by UUIDs."""
        results: list[NextEpisodeEdge] = []
        for uid in uuids:
            rows = self._g._client._query("kg_edge", filter_dict={"id": uid})
            if rows:
                r = rows[0]
                results.append(
                    NextEpisodeEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
        return results

    def get_by_group_ids(
        self,
        group_ids: list[str],
        limit: int | None = None,
        uuid_cursor: str | None = None,
    ) -> list[NextEpisodeEdge]:
        """List records filtered by group IDs."""
        edges: list[NextEpisodeEdge] = []
        for gid in group_ids:
            ws_id = self._g._resolve_workspace(gid)
            rows = self._g._client._query(
                "kg_edge", workspace_id=ws_id, filter_dict={"relation": "NEXT_EPISODE"}
            )
            for r in rows:
                edges.append(
                    NextEpisodeEdge(
                        uuid=r.get("id", ""),
                        source_node_uuid=r.get("source_node_id", ""),
                        target_node_uuid=r.get("target_node_id", ""),
                        group_id=r.get("workspace_id", "default"),
                    )
                )
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

    def __init__(self, graphiti: Graphiti) -> None:
        """Initialize the store with a reference to the parent Graphiti instance."""
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

