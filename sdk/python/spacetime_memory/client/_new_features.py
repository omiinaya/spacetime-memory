"""New features mixin: MemoryMeta, Webhook, Observation, ContextTree, Review.

Wraps the corresponding SpacetimeDB reducers for each domain.
"""
from __future__ import annotations

import json
from typing import Any

from ._base import logger


class NewFeaturesMixin:
    """Spacetime-Memory new-features mixin.

    Provides Client methods for:
      - MemoryMeta — extensible metadata on memories
      - Webhook — registered callback URLs for workspace events
      - Observation — discrete knowledge-claim records (facts, inferences, beliefs)
      - ContextTree — hierarchical path-based context entries
      - Review — SM-2 spaced-repetition review scheduler

    Inherits from ClientBase for connection infrastructure.
    """

    # -------------------------------------------------------------------
    # MemoryMeta
    # -------------------------------------------------------------------

    def set_memory_meta(
        self,
        workspace_id: str,
        memory_id: str,
        category: str = "",
        immutable: bool = False,
        extra_json: str = "{}",
    ) -> dict[str, Any]:
        """Set or update metadata on a memory (upsert).

        Args:
            workspace_id: Target workspace.
            memory_id: The memory to attach metadata to.
            category: User-defined category label (e.g. ``"preferences"``, ``"facts"``).
            immutable: If ``True``, the memory cannot be modified or deleted.
            extra_json: JSON blob for future extensions.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "set_memory_meta",
            [workspace_id, memory_id, category, immutable, extra_json],
        )

    def get_memory_meta(self, memory_id: str) -> dict[str, Any] | None:
        """Get metadata for a single memory by its ID.

        Calls the ``get_memory_meta`` reducer (auth check) then queries
        the ``memory_meta`` content table.

        Args:
            memory_id: The memory ID to look up.

        Returns:
            The metadata dict, or ``None`` if no metadata exists for this
            memory.
        """
        self._call("get_memory_meta", [memory_id])
        rows = self._query("memory_meta", filter_dict={"memory_id": memory_id})
        return rows[0] if rows else None

    def batch_set_memory_meta(
        self,
        workspace_id: str,
        ids_json: str,
        category: str = "",
        immutable: bool = False,
    ) -> dict[str, Any]:
        """Batch-set metadata on multiple memories at once.

        Args:
            workspace_id: Target workspace.
            ids_json: JSON array of memory ID strings, e.g. ``'["mem_1","mem_2"]'``.
            category: Category label to apply (empty string preserves existing).
            immutable: Immutable flag to apply to all.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "batch_set_memory_meta",
            [workspace_id, ids_json, category, immutable],
        )

    def list_memory_meta(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all memory-metadata entries for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of metadata dicts.
        """
        return self._query("memory_meta", workspace_id=workspace_id)

    # -------------------------------------------------------------------
    # Webhook
    # -------------------------------------------------------------------

    def create_webhook(
        self,
        workspace_id: str,
        name: str,
        url: str,
        event_types: str = "[]",
        secret: str = "",
    ) -> dict[str, Any]:
        """Register a new webhook for workspace events.

        Args:
            workspace_id: Target workspace.
            name: Human-friendly label.
            url: Target URL that receives POST requests.
            event_types: JSON array of event type strings, e.g.
                ``'["message.created", "memory.created"]'``.
                An empty array ``[]`` matches all events.
            secret: HMAC-SHA256 signing secret.

        Returns:
            Reducer status dict.
        """
        return self._call("create_webhook", [workspace_id, name, url, event_types, secret])

    def update_webhook(
        self,
        webhook_id: str,
        name: str = "",
        url: str = "",
        event_types: str = "",
        is_active: bool = True,
    ) -> dict[str, Any]:
        """Update an existing webhook's mutable fields.

        Args:
            webhook_id: The webhook ID to update.
            name: New label (empty = keep current).
            url: New target URL (empty = keep current).
            event_types: New event-types JSON array (empty = keep current).
            is_active: Whether the webhook is actively delivering.

        Returns:
            Reducer status dict.
        """
        return self._call("update_webhook", [webhook_id, name, url, event_types, is_active])

    def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
        """Delete a webhook and its pending deliveries.

        Args:
            webhook_id: The webhook ID to delete.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_webhook", [webhook_id])

    def list_webhooks(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all webhooks registered in a workspace.

        Calls the ``list_webhooks`` reducer which populates the
        ``webhook_list_result`` table, then reads it directly via SQL.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of webhook result dicts with keys: webhook_id, name, url,
            event_types, is_active, created_at, updated_at, created_by.
        """
        self._call("list_webhooks", [workspace_id])
        rows = self._query(
            "webhook_list_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0)
        return rows

    def fire_webhook_event(
        self,
        workspace_id: str,
        event_type: str,
        payload: str = "{}",
    ) -> dict[str, Any]:
        """Manually fire a webhook event (creates pending deliveries).

        Args:
            workspace_id: Target workspace.
            event_type: Event type string, e.g. ``"memory.created"``.
            payload: JSON payload to send in the POST body.

        Returns:
            Reducer status dict.
        """
        return self._call("fire_webhook_event", [workspace_id, event_type, payload])

    # -------------------------------------------------------------------
    # Observation
    # -------------------------------------------------------------------

    def create_observation(
        self,
        workspace_id: str,
        content: str,
        summary: str = "",
        evidence_json: str = "[]",
        observation_type: str = "fact",
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        """Create a discrete knowledge-claim observation.

        Args:
            workspace_id: Target workspace.
            content: The observation text content.
            summary: A short summary / description.
            evidence_json: JSON array of memory IDs serving as evidence.
            observation_type: ``"fact"`` | ``"inference"`` | ``"belief"``.
            confidence: Confidence score 0.0–1.0.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "create_observation",
            [workspace_id, content, summary, evidence_json, observation_type, confidence],
        )

    def update_observation(
        self,
        id: str,
        content: str = "",
        summary: str = "",
        confidence: float = 0.0,
    ) -> dict[str, Any]:
        """Update an existing observation's mutable fields.

        Args:
            id: The observation ID.
            content: New content (empty = keep current).
            summary: New summary (empty = keep current).
            confidence: New confidence (0.0 = keep current).

        Returns:
            Reducer status dict.
        """
        return self._call("update_observation", [id, content, summary, confidence])

    def delete_observation(self, id: str) -> dict[str, Any]:
        """Delete an observation by ID.

        Args:
            id: The observation ID.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_observation", [id])

    def list_observations(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all observations for a workspace.

        Calls the ``list_observations`` reducer which populates the
        ``observation_list_result`` table with a ``json_data`` field
        containing a JSON-serialised array of observation records.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of observation dicts.
        """
        self._call("list_observations", [workspace_id])
        rows = self._query(
            "observation_list_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("json_data"):
            try:
                return json.loads(rows[0]["json_data"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("list_observations: failed to parse json_data")
        return []

    # -------------------------------------------------------------------
    # ContextTree
    # -------------------------------------------------------------------

    def set_context(
        self,
        workspace_id: str,
        path: str,
        content: str,
        priority: float = 0.0,
        is_global: bool = False,
    ) -> dict[str, Any]:
        """Create or update a hierarchical context entry (upsert by path).

        Args:
            workspace_id: Target workspace.
            path: Hierarchical path, e.g. ``"/api/v2"`` or ``"/user/preferences"``.
            content: Context text content / guidance for this path.
            priority: Priority score (higher = more relevant).
            is_global: If ``True``, this context matches all paths.

        Returns:
            Reducer status dict.
        """
        return self._call("set_context", [workspace_id, path, content, priority, is_global])

    def delete_context(self, context_id: str) -> dict[str, Any]:
        """Delete a context entry by its primary key id.

        Args:
            context_id: The context entry ID.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_context", [context_id])

    def list_contexts(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all context entries for a workspace.

        Calls the ``list_contexts`` reducer which populates the
        ``context_tree_result`` table (query_id = ``"list"``) with a
        ``results_json`` field containing the matched entries.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of context entry dicts.
        """
        self._call("list_contexts", [workspace_id])
        rows = self._query(
            "context_tree_result",
            workspace_id=workspace_id,
            filter_dict={"query_id": "list"},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("results_json"):
            try:
                return json.loads(rows[0]["results_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("list_contexts: failed to parse results_json")
        return []

    def resolve_context(self, workspace_id: str, path: str) -> list[dict[str, Any]]:
        """Resolve the most specific context entries for a given path.

        Uses hierarchical prefix matching: given ``"/api/v2/users/123"``,
        finds all contexts whose path is a prefix of the input (including
        the exact match and root ``"/"``), ranked by specificity then
        priority.

        Args:
            workspace_id: Target workspace.
            path: The path to resolve context for.

        Returns:
            List of matched context entry dicts, sorted by specificity
            (longest path first) then priority (highest first).
        """
        self._call("resolve_context", [workspace_id, path])
        rows = self._query(
            "context_tree_result",
            workspace_id=workspace_id,
            filter_dict={"query_id": path},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("results_json"):
            try:
                return json.loads(rows[0]["results_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("resolve_context: failed to parse results_json")
        return []

    # -------------------------------------------------------------------
    # Review (SM-2 spaced repetition)
    # -------------------------------------------------------------------

    def schedule_review(
        self,
        workspace_id: str,
        memory_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Schedule a memory for review using SM-2 spaced repetition.

        Creates or resets a ``ReviewItem`` for the given memory and user,
        setting it as due immediately with default easiness factor (2.5).

        Args:
            workspace_id: Target workspace.
            memory_id: The memory to review.
            user_id: The user performing the review.

        Returns:
            Reducer status dict.
        """
        return self._call("schedule_review", [workspace_id, memory_id, user_id])

    def perform_review(
        self,
        review_id: str,
        grade: int,
    ) -> dict[str, Any]:
        """Perform a review on an existing ReviewItem with a grade (0–6).

        Implements the SM-2 algorithm to update easiness factor, interval,
        and next review date.

        Args:
            review_id: The ReviewItem ID.
            grade: Grade 0–6 (0 = complete blackout, 5 = perfect, 6 = perfect
                with extra ease). Grades 0–1 reset the item; grades 2+
                advance the interval.

        Returns:
            Reducer status dict.
        """
        return self._call("perform_review", [review_id, grade])

    def get_due_reviews(
        self,
        workspace_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """Get all review items due now for a workspace/user.

        Calls the ``get_due_reviews`` reducer which populates the
        ``review_result`` table.

        Args:
            workspace_id: Target workspace.
            user_id: The user to get due reviews for.

        Returns:
            List of ReviewItem dicts that are due for review.
        """
        self._call("get_due_reviews", [workspace_id, user_id])
        rows = self._query(
            "review_result",
            workspace_id=workspace_id,
            filter_dict={"user_id": user_id},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("items_json"):
            try:
                return json.loads(rows[0]["items_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("get_due_reviews: failed to parse items_json")
        return []

    def get_review_stats(
        self,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Get review statistics for a workspace/user.

        Calls the ``get_review_stats`` reducer which populates the
        ``review_result`` table with aggregate statistics.

        Args:
            workspace_id: Target workspace.
            user_id: The user to get stats for.

        Returns:
            Dict with keys: ``total_review_items``, ``active_items``,
            ``due_now``, ``average_grade``, ``average_easiness_factor``,
            ``user_id``. Returns ``None`` if no stats available.
        """
        self._call("get_review_stats", [workspace_id, user_id])
        rows = self._query(
            "review_result",
            workspace_id=workspace_id,
            filter_dict={"user_id": user_id},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("items_json"):
            try:
                return json.loads(rows[0]["items_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("get_review_stats: failed to parse items_json")
        return None

    # -------------------------------------------------------------------
    # Veracity (Bayesian confidence scoring)
    # -------------------------------------------------------------------

    def update_memory_veracity(
        self,
        workspace_id: str,
        memory_id: str,
        outcome: bool = True,
        weight: float = 0.25,
    ) -> dict[str, Any]:
        """Update Bayesian veracity for a single memory.

        Args:
            workspace_id: Target workspace.
            memory_id: The memory to update.
            outcome: ``True`` = positive/confirmatory evidence,
                ``False`` = negative/contradictory evidence.
            weight: Evidence weight (default 0.25 for explicit feedback).

        Returns:
            Reducer status dict.
        """
        return self._call(
            "update_memory_veracity",
            [workspace_id, memory_id, outcome, weight],
        )

    def batch_update_veracity(
        self,
        workspace_id: str,
        items: list[dict],
    ) -> dict[str, Any]:
        """Batch update veracity for multiple memories.

        Each item in ``items`` should be a dict with keys:
        ``memory_id``, ``outcome`` (optional, default ``True``),
        ``weight`` (optional, default ``0.05``).

        Args:
            workspace_id: Target workspace.
            items: List of veracity update items.

        Returns:
            Reducer status dict.
        """
        return self._call(
            "batch_update_veracity",
            [workspace_id, json.dumps(items)],
        )

    def get_memory_veracity(
        self,
        workspace_id: str,
        memory_id: str,
    ) -> dict[str, Any] | None:
        """Get the Bayesian veracity evidence for a memory.

        Args:
            workspace_id: Target workspace.
            memory_id: The memory ID to look up.

        Returns:
            Dict with keys: memory_id, alpha, beta, confidence, tier,
            evidence_count, confirmatory_count, contradictory_count,
            total_evidence, last_updated. Returns ``None`` if not found.
        """
        self._call("get_memory_veracity", [workspace_id, memory_id])
        rows = self._query(
            "veracity_evidence_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("result_json"):
            try:
                return json.loads(rows[0]["result_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("get_memory_veracity: failed to parse result_json")
        return None

    def list_workspace_veracity(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List all veracity evidence entries for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of veracity summary dicts (memory_id, confidence, tier,
            evidence_count, total_evidence).
        """
        self._call("list_workspace_veracity", [workspace_id])
        rows = self._query(
            "veracity_evidence_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows and rows[0].get("result_json"):
            try:
                return json.loads(rows[0]["result_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("list_workspace_veracity: failed to parse result_json")
        return []

    # -------------------------------------------------------------------
    # Anomaly Detection
    # -------------------------------------------------------------------

    def detect_anomalies(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Detect statistical anomalies among memories in a workspace.

        Identifies memories with unusually high/low confidence, content
        length, or entity counts (>3σ z-score outliers).

        Args:
            workspace_id: Target workspace.

        Returns:
            List of anomaly dicts (memory_id, anomaly_type, metric_value,
            z_score, description).
        """
        self._call("detect_anomalies", [workspace_id])
        rows = self._query(
            "anomaly_result",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if rows:
            rows.sort(key=lambda r: r.get("z_score", 0) or 0, reverse=True)
        return rows
