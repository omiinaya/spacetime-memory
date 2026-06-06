"""Mem0-compatible drop-in adapter.

Usage::

    from spacetime_memory.sdks.mem0 import Memory

    m = Memory()  # reads env vars for host/port/db
    m.add("I like pizza", user_id="alice", agent_id="assistant")
    results = m.search("food preferences", user_id="alice")
    m.delete(memory_id=results["results"][0]["id"])
"""

from __future__ import annotations

from typing import Any

from ..client import Client


class Memory:
    """Drop-in replacement for ``mem0.Memory``.

    Models are not available in spacetime-memory, so *model* and similar
    Mem0-specific options are accepted but silently ignored (or routed as
    metadata).  The adapter maps:

    * ``user_id`` → ``workspace_id``
    * ``agent_id`` → ``peer_id``
    * ``run_id``   → ``source_session_id``
    """

    def __init__(self, config: dict | None = None):
        # Config dict is per Mem0's API — we extract our own settings
        config = config or {}
        self._client = Client(
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("db", config.get("database")),
            embedder_url=config.get("embedder_url"),
        )
        self._user_id_to_ws: dict[str, str] = {}

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _ws(self, user_id: str | None = None) -> str:
        """Resolve workspace_id from user_id, creating if needed."""
        if not user_id:
            return ""
        if user_id not in self._user_id_to_ws:
            ws = self._client.list_workspaces()
            match = [w for w in ws if w.get("name") == user_id]
            if match:
                self._user_id_to_ws[user_id] = match[0]["id"]
            else:
                self._client.create_workspace(user_id, f"Mem0 user: {user_id}")
                ws_list = self._client.list_workspaces()
                match = [w for w in ws_list if w.get("name") == user_id]
                if match:
                    self._user_id_to_ws[user_id] = match[0]["id"]
        return self._user_id_to_ws.get(user_id, "")

    # -------------------------------------------------------------------
    # Mem0 API
    # -------------------------------------------------------------------

    def add(
        self,
        messages: str | list[dict[str, str]],
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        metadata: dict | None = None,
        filters: dict | None = None,
        prompt: str | None = None,
        output_format: str = "v1.1",
    ) -> dict[str, Any]:
        """Store a memory.

        *messages* can be a plain text string (Mem0 v1.x) or a list of
        message dicts (Mem0 v1.1+).  We flatten messages into the content.
        """
        if isinstance(messages, list):
            content = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in messages
            )
            summary = content[:200]
        else:
            content = str(messages)
            summary = ""

        ws_id = self._ws(user_id)

        result = self._client.store(
            workspace_id=ws_id,
            content=content,
            summary=summary or content[:200],
            memory_type="experience",
            peer_id=agent_id or "",
            source_session_id=run_id or "",
        )

        # Return Mem0-compatible shape
        mems = self._client.get_memory("")  # refresh then search
        return {
            "results": [
                {
                    "id": r["id"],
                    "memory": r.get("content", ""),
                    "event": "ADD",
                    "user_id": user_id or "",
                    "agent_id": agent_id or "",
                }
                for r in self._client.search(
                    ws_id, content, limit=1, semantic=True
                )
            ],
            "relation_events": [],
        }

    def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        threshold: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search memories.  Returns Mem0-compatible ``{"results": [...]}``."""
        ws_id = self._ws(user_id)
        rows = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=limit,
            semantic=True,
        )
        results = []
        for r in rows:
            score = r.get("score", 0.0)
            if threshold > 0.0 and score < threshold:
                continue
            results.append({
                "id": r.get("entity_id", ""),
                "memory": r.get("memory_content", r.get("content", "")),
                "score": score,
                "user_id": user_id or "",
                "agent_id": agent_id or "",
                "metadata": {},
            })
        return {"results": results}

    def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get all memories for a user."""
        ws_id = self._ws(user_id)
        rows = self._client.list_memories(workspace_id=ws_id, limit=limit)
        return {
            "results": [
                {
                    "id": r["id"],
                    "memory": r.get("content", ""),
                    "user_id": user_id or "",
                    "agent_id": agent_id or "",
                    "metadata": {},
                }
                for r in rows
            ]
        }

    def update(self, memory_id: str, data: str | dict) -> dict[str, Any]:
        """Update a memory's content."""
        if isinstance(data, dict):
            content = data.get("content", data.get("memory", str(data)))
        else:
            content = str(data)
        return self._client.update_memory(
            memory_id, content=content, summary=content[:200]
        )

    def delete(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory by ID."""
        return self._client.delete_memory(memory_id)

    def delete_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete all memories for a user."""
        ws_id = self._ws(user_id)
        rows = self._client.list_memories(workspace_id=ws_id, limit=9999)
        for r in rows:
            self._client.delete_memory(r["id"])
        return {"status": "ok", "deleted": len(rows)}

    def reset(self) -> dict[str, Any]:
        """Reset all state (clear workspace cache)."""
        self._user_id_to_ws.clear()
        return {"status": "ok"}
