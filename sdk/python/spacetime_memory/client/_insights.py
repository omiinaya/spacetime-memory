"""Insight management mixin — create and delete insights."""

from __future__ import annotations

from typing import Any


class InsightMixin:
    """Mixin providing typed insight creation and deletion."""

    def create_insight(
        self,
        workspace_id: str,
        peer_id: str,
        content: str,
        insight_type: str,
        source_memory_ids_json: str,
        confidence: float,
    ) -> dict[str, Any]:
        """Create a new insight derived from source memories.

        Args:
            workspace_id: The workspace that owns the insight.
            peer_id: The peer / agent that created the insight.
            content: The insight body text.
            insight_type: Type of insight (e.g. "conclusion", "observation",
                          "connection", "question").
            source_memory_ids_json: JSON array of source memory IDs.
            confidence: Confidence score between 0.0 and 1.0.

        Returns:
            Reducer status.
        """
        return self._call(
            "create_insight",
            [workspace_id, peer_id, content, insight_type, source_memory_ids_json, confidence],
        )

    def delete_insight(self, insight_id: str) -> dict[str, Any]:
        """Delete an insight by its unique identifier.

        Args:
            insight_id: The ID of the insight to delete.

        Returns:
            Reducer status.
        """
        return self._call("delete_insight", [insight_id])
