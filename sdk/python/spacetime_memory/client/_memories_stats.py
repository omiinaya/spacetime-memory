"""Memory stats, decay, and recommendations mixin."""
from __future__ import annotations

from typing import Any



class StatsMixin:
    """Spacetime-Memory stats, decay, and recommendations mixin.

    Provides Client methods related to reputation decay configuration,
    memory recommendations, peer reputation, knowledge graph stats,
    bridge node detection, and memory statistics.
    Inherits from ClientBase for connection infrastructure.
    """

    # -----------------------------------------------------------------------
    # Reputation decay configuration (Weibull / Linear)
    # -----------------------------------------------------------------------

    def set_decay_model(
        self,
        workspace_id: str,
        model: str = "linear",
        decay_rate: float = 0.005,
        max_days: int = 90,
        weibull_shape: float = 0.6,
        weibull_scale: float = 30.0,
    ) -> dict[str, Any]:
        """Configure the decay model for a workspace.

        Args:
            workspace_id: Workspace to configure.
            model: ``"linear"`` (default) or ``"weibull"``.
            decay_rate: For linear -- fraction of trust to decay per day (e.g. 0.005 = 0.5%/day).
            max_days: For linear -- max age in days before trust hits floor.
            weibull_shape: For Weibull -- k parameter (< 1 = rapid-then-slow forgetting, default 0.6).
            weibull_scale: For Weibull -- λ parameter (characteristic time in days, default 30.0).

        Returns:
            The reducer response.
        """
        if model not in ("linear", "weibull"):
            raise ValueError(f"Unknown decay model '{model}'. Use 'linear' or 'weibull'.")

        if model == "linear":
            return self._call(
                "apply_reputation_decay",
                [
                    workspace_id,
                    decay_rate,
                    max_days,
                ],
            )
        else:
            return self._call(
                "apply_weibull_decay",
                [
                    workspace_id,
                    weibull_shape,
                    weibull_scale,
                ],
            )

    def get_decay_config(self, workspace_id: str) -> dict[str, Any] | None:
        """Get the current decay configuration for a workspace.

        Returns None if no config has been set yet.
        """
        rows = self._query("workspace_config", filter_dict={"id": workspace_id})
        if rows:
            return rows[0]
        return None

    def recommend_memories(
        self,
        workspace_id: str,
        limit: int = 20,
        min_urgency: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Recommend memories that need attention (review, reinforce, discard).

        Returns memories sorted by urgency -- low-trust, decaying, or
        consistently-poor memories that need human attention.

        Args:
            workspace_id: Target workspace.
            limit: Max recommendations (default 20).
            min_urgency: Minimum urgency threshold 0.0-1.0 (default 0.3).
        """
        self._call(
            "recommend_memories",
            [
                workspace_id,
                limit,
                min_urgency,
            ],
        )
        # Result table — queryable through the query_table reducer
        return self._query(
            "memory_recommendation",
            workspace_id=workspace_id,
            filter_dict={},
        )

    def get_peer_reputation(self, peer_id: str) -> dict[str, Any] | None:
        """Get reputation stats for a peer.

        Calls the get_peer_reputation reducer and reads the result
        from the peer_reputation_result table.
        Returns None if the peer has no feedback history.
        """
        self._call("get_peer_reputation", [peer_id])
        rows = self._query(
            "peer_reputation_result",
            filter_dict={"peer_id": peer_id},
        )
        if rows:
            return rows[0]
        return None

    # -----------------------------------------------------------------------
    # Knowledge graph pattern detection
    # -----------------------------------------------------------------------

    def detect_bridge_nodes(
        self,
        workspace_id: str,
        limit: int = 20,
        min_communities: int = 2,
    ) -> list[dict[str, Any]]:
        """Detect bridge nodes -- concepts that connect multiple communities.

        Returns nodes sorted by bridge score (higher = more integrative).
        """
        self._call(
            "detect_bridge_nodes",
            [
                workspace_id,
                limit,
                min_communities,
            ],
        )
        # Result table — queryable through the query_table reducer
        return self._query(
            "bridge_result",
            workspace_id=workspace_id,
            filter_dict={},
        )

    def compute_kg_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Compute knowledge graph statistics for a workspace.

        Returns a single stats row with node_count, edge_count,
        community_count, orphan_nodes, avg_degree, etc.
        """
        self._call("compute_kg_stats", [workspace_id])
        # Result table — queryable through the query_table reducer
        rows = self._query(
            "kg_stats_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            return rows[0]
        return None

    def get_memory_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Collect per-workspace memory metrics.

        Stats returned:
        - ``total_memories`` -- count of all memories
        - ``active_memories`` -- count of active memories
        - ``by_tier`` -- JSON map of tier → count (L0, L1, L2)
        - ``by_type`` -- JSON map of memory_type → count
        - ``avg_confidence`` -- average confidence score
        - ``avg_age_seconds`` -- average age in seconds
        - ``total_revisions`` -- number of memory revisions
        - ``top_tags`` -- JSON array of top-10 used tags
        - ``total_users`` -- count of distinct user_scope values

        Returns a dict of stat_key → stat_value, or ``None`` if no stats
        were computed.
        """
        self._call("get_memory_stats", [workspace_id])
        # Result table — queryable through the query_table reducer
        rows = self._query(
            "workspace_memory_stats_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            return {r["stat_key"]: r["stat_value"] for r in rows}
        return None
