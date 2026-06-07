"""Mem0-compatible drop-in adapter.

Matches the real Mem0 Python SDK API exactly:
https://github.com/mem0ai/mem0

Usage::

    from spacetime_memory.sdks.mem0 import Memory

    m = Memory(config={"host": "localhost", "port": 3001})
    m.add("I like pizza", user_id="alice", agent_id="assistant")
    results = m.search("food preferences", user_id="alice")
    memory = m.get(memory_id=results["results"][0]["id"])
    all_mems = m.get_all(user_id="alice")
    m.update(memory_id=memory_id, data="I love pizza")
    m.delete(memory_id=memory_id)
    history = m.history(memory_id=memory_id)
    m.reset()
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

    Example::

        >>> from spacetime_memory.sdks.mem0 import Memory
        >>> m = Memory()
        >>> result = m.add("I like pizza", user_id="alice")
        >>> result["results"][0]["memory"]
        'I like pizza'

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

        Args:
            messages: A plain text string (Mem0 v1.x) or a list of message
                dicts (Mem0 v1.1+).  We flatten messages into the content.
            user_id: Identifier for the user whose memory this belongs to.
                Mapped to a workspace.
            agent_id: Identifier for the agent storing the memory.
            run_id: Run / session identifier.
            metadata: Optional metadata dict.
            filters: Optional query filters (accepted for compatibility).
            prompt: Optional prompt for inference (accepted for compatibility).
            output_format: Output format version (default ``"v1.1"``).

        Returns:
            A dict with a ``"results"`` key containing a list of stored
            memory records, each with ``id``, ``memory``, ``event``,
            ``user_id``, and ``agent_id``.

        Example::

            >>> m.add("I like pizza", user_id="alice", agent_id="assistant")
            {'results': [{'id': '...', 'memory': 'I like pizza', ...}], 'relation_events': []}

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

        self._client.store(
            workspace_id=ws_id,
            content=content,
            summary=summary or content[:200],
            memory_type="experience",
            peer_id=agent_id or "",
            source_session_id=run_id or "",
        )

        # Return Mem0-compatible shape — search for the stored memory
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

    def get(self, memory_id: str) -> dict[str, Any]:
        """Retrieve a single memory by its ID.

        Args:
            memory_id: The UUID of the memory to retrieve.

        Returns:
            A dict with a ``"results"`` key containing a single-element list
            with the memory record (``id``, ``memory``, ``user_id``, etc.).

        Example::

            >>> m.get(memory_id="abc123")
            {'results': [{'id': 'abc123', 'memory': 'I like pizza', ...}]}

        """
        rows = self._client.get_memory(memory_id)
        if rows:
            record = rows[0]
            result = {
                "id": record.get("id", ""),
                "memory": record.get("content", ""),
                "user_id": record.get("peer_id", ""),
                "agent_id": record.get("observer_id", ""),
                "metadata": {},
            }
        else:
            result = {}
        return {"results": [result] if result else []}

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
        """Search memories by semantic similarity to *query*.

        Args:
            query: The search query text.
            user_id: Optional user filter.
            agent_id: Optional agent filter (accepted for compatibility).
            run_id: Optional run/session filter.
            limit: Max results to return (default 100).
            threshold: Minimum relevance score (0.0 = no filter).
            **kwargs: Additional Mem0 keyword arguments (accepted for
                compatibility but ignored).

        Returns:
            A dict with a ``"results"`` key containing a list of matching
            memory records, each with ``id``, ``memory``, ``score``,
            ``user_id``, ``agent_id``, and ``metadata``.

        Example::

            >>> m.search("food preferences", user_id="alice")
            {'results': [{'id': '...', 'memory': 'I like pizza', 'score': 0.92, ...}]}

        """
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
        """List all memories for a user.

        Args:
            user_id: User whose memories to list.
            agent_id: Optional agent filter (accepted for compatibility).
            run_id: Optional run/session filter.
            limit: Max results to return (default 100).

        Returns:
            A dict with a ``"results"`` key containing a list of memory
            records, each with ``id``, ``memory``, ``user_id``, ``agent_id``,
            and ``metadata``.

        Example::

            >>> m.get_all(user_id="alice")
            {'results': [{'id': '...', 'memory': 'I like pizza', ...}]}

        """
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
        """Update a memory's content.

        Args:
            memory_id: The UUID of the memory to update.
            data: New content as a string, or a dict with ``"content"`` or
                ``"memory"`` keys.

        Returns:
            A dict with operation status (``{"status": "ok"}``).

        Example::

            >>> m.update(memory_id="abc123", data="I love pizza")
            {'status': 'ok'}

        """
        if isinstance(data, dict):
            content = data.get("content", data.get("memory", str(data)))
        else:
            content = str(data)
        return self._client.update_memory(
            memory_id, content=content, summary=content[:200]
        )

    def delete(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory by ID.

        Args:
            memory_id: The UUID of the memory to delete.

        Returns:
            A dict with operation status (``{"status": "ok"}``).

        Example::

            >>> m.delete(memory_id="abc123")
            {'status': 'ok'}

        """
        return self._client.delete_memory(memory_id)

    def delete_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete all memories for a user.

        Args:
            user_id: User whose memories to delete.
            agent_id: Optional agent filter.
            run_id: Optional run/session filter.

        Returns:
            A dict with status and count of deleted memories.

        """
        ws_id = self._ws(user_id)
        rows = self._client.list_memories(workspace_id=ws_id, limit=9999)
        for r in rows:
            self._client.delete_memory(r["id"])
        return {"status": "ok", "deleted": len(rows)}

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory.

        Args:
            memory_id: The UUID of the memory.

        Returns:
            A list of version dicts, each containing ``version``, ``content``,
            ``summary``, ``confidence``, and timestamp fields, sorted newest
            first.

        Example::

            >>> m.history(memory_id="abc123")
            [{'version': 2, 'content': 'I love pizza', ...},
             {'version': 1, 'content': 'I like pizza', ...}]

        """
        return self._client.get_memory_history(memory_id)

    def reset(self) -> dict[str, Any]:
        """Reset all state (clear workspace cache).

        Example::

            >>> m.reset()
            {'status': 'ok'}

        """
        self._user_id_to_ws.clear()
        return {"status": "ok"}
