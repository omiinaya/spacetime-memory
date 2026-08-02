"""Graphiti edges mixin — temporal edge tracking and index maintenance."""

from __future__ import annotations

import json
import logging
from typing import Any

from ._models import (
    EntityEdge,
)
from ._utils import _esc

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class GraphitiEdges:
    """Mixin providing build_indices_and_constraints and related methods."""

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
            raise RuntimeError(f"graphiti.update_edge('{edge_id}') failed: {exc}") from exc


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
        edge_rows = self._client._query(
            "kg_edge", filter_dict={"id": edge_id}, columns=["edge_group_id"]
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
            f"SELECT * FROM edge_history_result WHERE edge_group_id = '{_esc(edge_group_id)}'"
        )
        # Sort in Python
        result_rows.sort(key=lambda r: r.get("valid_at", 0))

        return [EntityEdge.from_stmem(r) for r in result_rows]

    # -------------------------------------------------------------------
    # Nodes and edges by episode
    # -------------------------------------------------------------------

