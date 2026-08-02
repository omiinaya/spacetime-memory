"""Reasoning tiers mixin — Honcho parity.

A formal tier system that constrains agent reasoning depth.
Supports four default tiers: quick, balanced, deep, research.

All data is stored via the ``reasoning_tier`` table using
``create_reasoning_tier``, ``update_reasoning_tier`` reducers etc.
Results are read from ``reasoning_tier_result`` via the generic
``query_table`` reducer.
"""

from __future__ import annotations

import json
from typing import Any

from ._base import _tracing_span

# ---------------------------------------------------------------------------
# Default tiers constant
# ---------------------------------------------------------------------------

DEFAULT_REASONING_TIERS: dict[str, dict[str, Any]] = {
    "quick": {
        "name": "quick",
        "description": "Fast response with minimal context, low tokens, high temperature for speed",
        "max_tokens": 256,
        "temperature": 0.9,
        "top_p": 0.9,
        "max_context_memories": 5,
        "min_confidence": 0.7,
        "requires_reflection": False,
        "requires_graph_traversal": False,
        "priority": 10,
        "is_default": False,
    },
    "balanced": {
        "name": "balanced",
        "description": "Default balanced reasoning tier for most queries",
        "max_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.9,
        "max_context_memories": 15,
        "min_confidence": 0.5,
        "requires_reflection": False,
        "requires_graph_traversal": False,
        "priority": 20,
        "is_default": True,
    },
    "deep": {
        "name": "deep",
        "description": "Thorough analysis with more context and guided reasoning",
        "max_tokens": 4096,
        "temperature": 0.5,
        "top_p": 0.95,
        "max_context_memories": 30,
        "min_confidence": 0.3,
        "requires_reflection": True,
        "requires_graph_traversal": True,
        "priority": 30,
        "is_default": False,
    },
    "research": {
        "name": "research",
        "description": "Maximum depth reasoning using knowledge graph traversal and reflection",
        "max_tokens": 8192,
        "temperature": 0.3,
        "top_p": 0.98,
        "max_context_memories": 50,
        "min_confidence": 0.1,
        "requires_reflection": True,
        "requires_graph_traversal": True,
        "priority": 40,
        "is_default": False,
    },
}


class ReasoningTierMixin:
    """Mixin for reasoning tier management — Honcho parity.

    Provides a formal tier system that constrains agent reasoning depth.
    """

    # -----------------------------------------------------------------------
    # CRUD operations
    # -----------------------------------------------------------------------

    def create_reasoning_tier(
        self,
        workspace_id: str,
        name: str,
        description: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_context_memories: int = 15,
        min_confidence: float = 0.5,
        requires_reflection: bool = False,
        requires_graph_traversal: bool = False,
        priority: int = 20,
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Create a new reasoning tier.

        Args:
            workspace_id: Workspace to create the tier in.
            name: Tier name (e.g. "quick", "balanced", "deep", "research").
            description: Human-readable description.
            max_tokens: Maximum tokens for this tier.
            temperature: LLM temperature (0.0–2.0).
            top_p: Nucleus sampling parameter (0.0–1.0).
            max_context_memories: How many memories to retrieve.
            min_confidence: Minimum confidence for included memories (0.0–1.0).
            requires_reflection: Whether reflection is required.
            requires_graph_traversal: Whether knowledge graph traversal is used.
            priority: Priority (lower = more important).
            is_default: Whether this is the default tier.

        Returns:
            The reducer result.
        """
        with _tracing_span("create_reasoning_tier"):
            return self._call("create_reasoning_tier", [
                workspace_id, "", name, description,
                max_tokens, temperature, top_p,
                max_context_memories, min_confidence,
                requires_reflection, requires_graph_traversal,
                priority, is_default,
            ])

    def update_reasoning_tier(
        self,
        workspace_id: str,
        tier_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update fields of an existing reasoning tier.

        Args:
            workspace_id: Workspace containing the tier.
            tier_id: ID of the tier to update.
            **kwargs: Fields to update. Valid keys: name, description,
                max_tokens, temperature, top_p, max_context_memories,
                min_confidence, requires_reflection, requires_graph_traversal,
                priority, is_default.

        Returns:
            The reducer result.
        """
        with _tracing_span("update_reasoning_tier"):
            name = kwargs.get("name", "")
            description = kwargs.get("description", "")
            max_tokens = kwargs.get("max_tokens", 1024)
            temperature = kwargs.get("temperature", 0.7)
            top_p = kwargs.get("top_p", 0.9)
            max_context_memories = kwargs.get("max_context_memories", 15)
            min_confidence = kwargs.get("min_confidence", 0.5)
            requires_reflection = kwargs.get("requires_reflection", False)
            requires_graph_traversal = kwargs.get("requires_graph_traversal", False)
            priority = kwargs.get("priority", 20)
            is_default = kwargs.get("is_default", False)

            return self._call("update_reasoning_tier", [
                workspace_id, tier_id, name, description,
                max_tokens, temperature, top_p,
                max_context_memories, min_confidence,
                requires_reflection, requires_graph_traversal,
                priority, is_default,
            ])

    def delete_reasoning_tier(
        self,
        workspace_id: str,
        tier_id: str,
    ) -> dict[str, Any]:
        """Delete a reasoning tier.

        Args:
            workspace_id: Workspace containing the tier.
            tier_id: ID of the tier to delete.

        Returns:
            The reducer result.
        """
        with _tracing_span("delete_reasoning_tier"):
            return self._call("delete_reasoning_tier", [workspace_id, tier_id])

    def get_reasoning_tiers(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Get all reasoning tiers for a workspace.

        Args:
            workspace_id: Workspace to get tiers for.

        Returns:
            List of reasoning tier dicts, sorted by priority.
        """
        with _tracing_span("get_reasoning_tiers"):
            self._call("get_reasoning_tiers", [workspace_id])
            # Read from the most recent reasoning_tier_result entry
            rows = self._query(
                "reasoning_tier_result",
                workspace_id=workspace_id,
            )
            if rows and len(rows) > 0:
                # Get the latest result (largest created_at)
                latest = max(rows, key=lambda r: r.get("created_at", 0))
                data = latest.get("data", "[]")
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        pass
            return []

    def get_default_reasoning_tier(
        self,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        """Get the default reasoning tier for a workspace.

        Args:
            workspace_id: Workspace to get the default tier for.

        Returns:
            The default tier dict, or None if none is set.
        """
        with _tracing_span("get_default_reasoning_tier"):
            self._call("get_default_reasoning_tier", [workspace_id])
            rows = self._query(
                "reasoning_tier_result",
                workspace_id=workspace_id,
            )
            if rows and len(rows) > 0:
                latest = max(rows, key=lambda r: r.get("created_at", 0))
                data = latest.get("data", "{}")
                if isinstance(data, str):
                    try:
                        result = json.loads(data)
                        return result if result else None
                    except (json.JSONDecodeError, TypeError):
                        pass
            return None

    def set_default_tier(
        self,
        workspace_id: str,
        tier_id: str,
    ) -> dict[str, Any]:
        """Set which tier is the default for a workspace.

        Args:
            workspace_id: Workspace containing the tier.
            tier_id: ID of the tier to set as default.

        Returns:
            The reducer result.
        """
        with _tracing_span("set_default_tier"):
            return self._call("set_default_tier", [workspace_id, tier_id])

    def apply_reasoning_tier_to_memory(
        self,
        workspace_id: str,
        memory_id: str,
        tier_id: str,
    ) -> dict[str, Any]:
        """Tag a memory with a reasoning tier.

        Args:
            workspace_id: Workspace containing the tier and memory.
            memory_id: ID of the memory to tag.
            tier_id: ID of the tier to apply.

        Returns:
            The reducer result.
        """
        with _tracing_span("apply_reasoning_tier_to_memory"):
            return self._call("apply_reasoning_tier_to_memory", [workspace_id, memory_id, tier_id])

    # -----------------------------------------------------------------------
    # Convenience methods
    # -----------------------------------------------------------------------

    def get_reasoning_tier_config(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Get all reasoning tiers as a config dict keyed by tier name.

        Args:
            workspace_id: Workspace to get config for.

        Returns:
            Dict mapping tier name -> tier config.
        """
        tiers = self.get_reasoning_tiers(workspace_id)
        return {t["name"]: t for t in tiers if "name" in t}

    def select_tier_for_query(
        self,
        workspace_id: str,
        query_complexity: str = "balanced",
    ) -> dict[str, Any] | None:
        """Automatically select a tier based on query complexity.

        Args:
            workspace_id: Workspace to select from.
            query_complexity: One of "quick", "balanced", "deep", "research".

        Returns:
            The selected tier dict, or the default tier if not found.
        """
        config = self.get_reasoning_tier_config(workspace_id)
        if query_complexity in config:
            return config[query_complexity]
        # Fall back to default
        return self.get_default_reasoning_tier(workspace_id)
