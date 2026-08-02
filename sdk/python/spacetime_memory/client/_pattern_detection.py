"""Server-side pattern detection mixin.

Wraps the SpacetimeDB server-side pattern detection reducers:
- detect_temporal_clusters
- detect_entity_cooccurrences
- detect_topic_clusters

Each reducer reads from the memory table server-side and writes results to
a result table (compute-and-store pattern). This mixin calls the reducer,
then reads from the result table.
"""

from __future__ import annotations

from typing import Any


class PatternDetectionMixin:
    """Mixin providing server-side pattern detection methods."""

    # ------------------------------------------------------------------
    # Temporal Clusters
    # ------------------------------------------------------------------

    def detect_temporal_clusters(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Detect temporal clusters — groups of memories stored close together in time.

        Uses 30-minute buckets server-side. Requires admin auth.

        Args:
            workspace_id: The workspace to analyse.

        Returns:
            List of cluster dicts with keys: id, workspace_id, start_time,
            end_time, count, memory_ids (JSON string), summary_terms (JSON string),
            created_at. Sorted by start_time descending.
        """
        self._call("detect_temporal_clusters", [workspace_id])
        return self._query("temporal_cluster_result", workspace_id=workspace_id)

    # ------------------------------------------------------------------
    # Entity Co‑occurrences
    # ------------------------------------------------------------------

    def detect_entity_cooccurrences(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Detect entity co‑occurrence patterns.

        Pairs of entities (from ``entities_json``) that frequently appear
        together in the same memory. Requires admin auth.

        Args:
            workspace_id: The workspace to analyse.

        Returns:
            List of co‑occurrence dicts with keys: id, workspace_id,
            entity_a, entity_b, count, strength, created_at.
            Sorted by count descending.
        """
        self._call("detect_entity_cooccurrences", [workspace_id])
        return self._query("entity_cooccurrence_result", workspace_id=workspace_id)

    # ------------------------------------------------------------------
    # Topic Clusters
    # ------------------------------------------------------------------

    def detect_topic_clusters(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Detect topic clusters — groups of memories organised by shared term frequency.

        Identifies top frequent terms across memories, then groups memories
        that share each top term. Requires admin auth.

        Args:
            workspace_id: The workspace to analyse.

        Returns:
            List of topic cluster dicts with keys: id, workspace_id,
            topic, count, memory_ids (JSON string), top_terms (JSON string),
            avg_confidence, created_at. Sorted by count descending.
        """
        self._call("detect_topic_clusters", [workspace_id])
        return self._query("topic_cluster_result", workspace_id=workspace_id)
