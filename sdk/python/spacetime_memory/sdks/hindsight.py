"""Hindsight-compatible drop-in adapter.

Usage::

    from spacetime_memory.sdks.hindsight import Hindsight

    h = Hindsight()  # reads env vars for host/port/db
    h.retain("I like pizza", source="chat")
    results = h.recall("food preferences")
    insights = h.reflect("What themes emerge?")
"""

from __future__ import annotations

from typing import Any

from ..client import Client


class Hindsight:
    """Drop-in replacement for ``hindsight.Hindsight``.

    Maps:

    * ``retain(content, source)`` → ``store_memory``
    * ``recall(query, limit)`` → ``hybrid_search``
    * ``reflect(prompt)`` → ``create_insight`` via LLM
    * ``forget(memory_id)`` → ``delete_memory``
    """

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._client = Client(
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("db", config.get("database")),
            embedder_url=config.get("embedder_url"),
        )
        self._workspace_id: str = config.get("workspace_id", "")
        if not self._workspace_id:
            # Use or create a default workspace
            ws_list = self._client.list_workspaces()
            if ws_list:
                self._workspace_id = ws_list[0]["id"]
            else:
                self._client.create_workspace("default", "Hindsight default workspace")
                ws_list = self._client.list_workspaces()
                if ws_list:
                    self._workspace_id = ws_list[0]["id"]

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _ws(self) -> str:
        if not self._workspace_id:
            raise RuntimeError("No workspace configured")
        return self._workspace_id

    # -------------------------------------------------------------------
    # Hindsight API
    # -------------------------------------------------------------------

    def retain(
        self,
        content: str,
        source: str = "",
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Store a memory.  Returns the created memory record."""
        result = self._client.store(
            workspace_id=self._ws(),
            content=content,
            summary=content[:200],
            memory_type=source or "experience",
            peer_id="hindsight",
        )
        return result

    def recall(
        self,
        query: str,
        limit: int = 20,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search memories.  Returns list of records sorted by relevance."""
        rows = self._client.search(
            workspace_id=self._ws(),
            query=query,
            limit=limit,
            semantic=True,
        )
        if threshold > 0.0:
            rows = [r for r in rows if r.get("score", 0.0) >= threshold]
        return rows

    def reflect(
        self,
        prompt: str = "What are the key themes and patterns in my data?",
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate insights by creating an insight node in the KG.

        The *prompt* is stored as an insight description.  The system
        does not run an LLM call directly — use the MCP server for
        that.  This method creates a structured insight entry that
        downstream LLM tooling can consume.
        """
        ws_id = workspace_id or self._ws()
        result = self._client._call(
            "create_insight",
            [ws_id, "hindsight_reflection", prompt, "synthesized", "{}"],
        )
        return {"status": "ok", "prompt": prompt, "workspace_id": ws_id}

    def forget(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory by ID."""
        return self._client.delete_memory(memory_id)

    def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all memories in this workspace."""
        return self._client.list_memories(workspace_id=self._ws(), limit=limit)

    def stats(self) -> dict[str, Any]:
        """Return workspace statistics."""
        ws_id = self._ws()
        memories = self._client._sql(
            f"SELECT COUNT(*) as cnt FROM memory WHERE workspace_id = '{ws_id}' AND is_active = TRUE"
        )
        sessions = self._client._sql(
            f"SELECT COUNT(*) as cnt FROM session WHERE workspace_id = '{ws_id}'"
        )
        nodes = self._client._sql(
            f"SELECT COUNT(*) as cnt FROM kg_node WHERE workspace_id = '{ws_id}'"
        )
        return {
            "workspace_id": ws_id,
            "memories": memories[0]["cnt"] if memories else 0,
            "sessions": sessions[0]["cnt"] if sessions else 0,
            "kg_nodes": nodes[0]["cnt"] if nodes else 0,
        }

    def reset(self) -> dict[str, Any]:
        """Reset workspace cache."""
        self._workspace_id = ""
        return {"status": "ok"}
