"""Graphiti core mixin — init, lifecycle, and helper methods."""

from __future__ import annotations

import difflib
import json
import logging
from datetime import datetime
from typing import Any

from ...client import Client
from ._edge_namespaces import EdgeNamespace
from ._models import (
    EntityEdge,
    EntityNode,
)
from ._node_namespaces import NodeNamespace

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class GraphitiCore:
    """Mixin providing __init__ and related methods."""

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        token: str | None = None,
        embedder_url: str | None = None,
        client: Client | None = None,
    ) -> None:
        """
        Args:
            host: SpacetimeDB host (default: 127.0.0.1).
            port: SpacetimeDB port (default: 3001).
            database: SpacetimeDB database identity.
            token: JWT token for authenticated requests.
            embedder_url: Embedder sidecar URL (default: http://127.0.0.1:9090).
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
            )
        self.clients = self._client
        # Cache: group_id (str) -> workspace_id (str)
        self._ws_cache: dict[str, str] = {}
        # Token tracker (property — upstream compat)
        self._token_tracker = None

    @property

    def token_tracker(self) -> None:
        """Token usage tracker (upstream compat — returns None for SpacetimeDB."""
        return self._token_tracker

    @property

    def nodes(self) -> NodeNamespace:
        """Namespace for node operations. Access as ``graphiti.nodes.entity`` etc."""
        return NodeNamespace(self)

    @property

    def edges(self) -> EdgeNamespace:
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


    def _sql_param(self, query_template: str, *args: Any) -> list[dict[str, Any]]:
        """Run a SQL query with parameterized placeholders, with safe error handling."""
        try:
            return self._client._sql_param(query_template, *args)
        except RuntimeError:
            return []


    def _filter_by_valid_at(
        self,
        edges: list[EntityEdge],
        valid_at_after: datetime | None = None,
        valid_at_before: datetime | None = None,
        invalid_at_after: datetime | None = None,
        invalid_at_before: datetime | None = None,
    ) -> list[EntityEdge]:
        """Filter a list of edges by bi-temporal validity (Graphiti parity).

        Mirrors Graphiti's ``SearchFilters`` date filters: ``valid_at`` and
        ``invalid_at`` are separate, independently combinable field
        comparisons (``ComparisonOperator >= / <=``) on the edge's validity
        window ``[valid_at, invalid_at)``.

        - ``valid_at_after``  → keep edges with ``valid_at >= date``
        - ``valid_at_before`` → keep edges with ``valid_at <= date``
        - ``invalid_at_after``  → keep edges with ``invalid_at >= date``
        - ``invalid_at_before`` → keep edges with ``invalid_at <= date``

        ``invalid_at`` of 0/None means *currently valid* (never invalidated).
        For ``invalid_at`` comparisons it is treated as ``+inf`` for the
        ``after`` bound and as an unmatched NULL for the ``before`` bound —
        i.e. an edge invalidated ``<= date`` matches ``invalid_at_before``,
        and a never-invalidated edge does not.

        When **no bounds are supplied** the original edge list is returned
        unchanged (matching Graphiti, which returns all versions and lets the
        caller compose date filters).

        Args:
            edges: List of :class:`EntityEdge` objects to filter.
            valid_at_after: Only return edges whose ``valid_at >=`` this date.
            valid_at_before: Only return edges whose ``valid_at <=`` this date.
            invalid_at_after: Only return edges whose ``invalid_at >=`` this
                date (never-invalidated edges always match).
            invalid_at_before: Only return edges whose ``invalid_at <=`` this
                date (never-invalidated edges never match).

        Returns:
            Filtered list of edges.
        """
        if (
            valid_at_after is None
            and valid_at_before is None
            and invalid_at_after is None
            and invalid_at_before is None
        ):
            return edges

        def _ts(dt: datetime | None) -> int | None:
            if dt is None:
                return None
            return int(dt.timestamp() * 1_000_000)

        def _edge_times(edge: EntityEdge) -> tuple[int | None, int | None, bool]:
            """(valid_at_us, invalid_at_us_or_None, never_invalidated)"""
            start = _ts(edge.valid_at)
            invalid_raw = _ts(edge.invalid_at)
            never = invalid_raw is None or invalid_raw == 0
            return start, invalid_raw, never

        after_us = _ts(valid_at_after)
        before_us = _ts(valid_at_before)
        invalid_after_us = _ts(invalid_at_after)
        invalid_before_us = _ts(invalid_at_before)

        filtered: list[EntityEdge] = []
        for edge in edges:
            start, invalid_raw, never = _edge_times(edge)

            if after_us is not None:
                if start is None or start < after_us:
                    continue  # valid_at < date
            if before_us is not None:
                if start is None or start > before_us:
                    continue  # valid_at > date

            if invalid_after_us is not None:
                # Never-invalidated edges are still valid, so they satisfy
                # "invalid_at >= date". Otherwise require invalid_at >= date.
                if not never and (invalid_raw is None or invalid_raw < invalid_after_us):
                    continue
            if invalid_before_us is not None:
                # Only edges actually invalidated by this date match.
                if never or invalid_raw is None or invalid_raw > invalid_before_us:
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
            ratio = difflib.SequenceMatcher(None, name_lower, label.lower()).ratio()
            if ratio > 0.85:
                fuzzy_matches.append((n, ratio))

        if fuzzy_matches:
            fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
            best_node, best_ratio = fuzzy_matches[0]
            return best_node["id"], best_ratio

        # Pass 4: semantic similarity via the embedder (vector-backed
        # entity dedup — mirrors upstream Graphiti's embedding-based
        # node resolution).  Uses the same hybrid search the adapter's
        # graph store relies on; no extra dependencies.
        try:
            semantic_rows = self._client.search(
                workspace_id=workspace_uuid,
                query=node.name,
                limit=5,
                semantic=True,
            )
            best_sem: tuple[dict[str, Any], float] | None = None
            for r in semantic_rows:
                if r.get("entity_type") != "node":
                    continue
                nid = r.get("entity_id", "")
                if not nid:
                    continue
                score = float(r.get("score", 0.0))
                if score >= 0.55:
                    if best_sem is None or score > best_sem[1]:
                        rows = self._client._query(
                            "kg_node", workspace_id=workspace_uuid,
                            filter_dict={"id": nid},
                        )
                        if rows:
                            best_sem = (rows[0], score)
            if best_sem is not None:
                return best_sem[0]["id"], best_sem[1]
        except RuntimeError:
            pass  # embedder unavailable — fall through to create

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

