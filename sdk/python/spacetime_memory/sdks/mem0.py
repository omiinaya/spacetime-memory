"""
Mem0-compatible drop-in adapter.

Matches the real Mem0 Python SDK API exactly:
https://github.com/mem0ai/mem0

Usage::

    from spacetime_memory.sdks.mem0 import Memory

    m = Memory(config={"host": "localhost", "port": 3001})
    m.add("I like pizza", user_id="alice", agent_id="assistant")
    results = m.search("food preferences", user_id="alice")
    memory = m.get(memory_id=results["results"][0]["id"])
    all_mems = m.get_all(filters={"user_id": "alice"})
    m.update(memory_id=memory_id, data="I love pizza")
    m.delete(memory_id=memory_id)
    history = m.history(memory_id=memory_id)
    m.reset()
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any, Callable

from ..client import Client
from ..llm import LLMClient

logger = logging.getLogger(__name__)


class Memory:
    """Drop-in replacement for ``mem0.Memory``.

    Models are not available in spacetime-memory, so *model* and similar
    Mem0-specific options are accepted but silently ignored (or routed as
    metadata).  The adapter maps:

    * ``user_id``  → ``workspace_id``
    * ``agent_id`` → ``peer_id``
    * ``run_id``   → ``source_session_id``

    Example::

        >>> from spacetime_memory.sdks.mem0 import Memory
        >>> m = Memory()
        >>> result = m.add("I like pizza", user_id="alice")
        >>> result["results"][0]["memory"]
        'I like pizza'

    """

    def __init__(
        self,
        config: dict | None = None,
        token_refresh_callback: Callable[[], str] | None = None,
    ):
        # Config dict is per Mem0's API — we extract our own settings
        config = config or {}
        self._client = Client(
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("db", config.get("database")),
            embedder_url=config.get("embedder_url"),
        )
        self._user_id_to_ws: dict[str, str] = {}
        self._token_refresh_callback = token_refresh_callback

    @classmethod
    def from_config(cls, config_dict: dict[str, Any]) -> Memory:
        """Create a Memory instance from a config dict (Mem0 v2+ compat).

        Args:
            config_dict: Mem0 configuration dictionary.

        Returns:
            A new Memory instance.
        """
        return cls(config=config_dict)

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _ws(self, user_id: str | None = None) -> str:
        """Resolve workspace_id from user_id, creating if needed."""
        if not user_id:
            return ""
        if user_id not in self._user_id_to_ws:
            ws = self._call("list_workspaces")
            match = [w for w in ws if w.get("name") == user_id]
            if match:
                self._user_id_to_ws[user_id] = match[0]["id"]
            else:
                self._call("create_workspace", user_id, f"Mem0 user: {user_id}")
                ws_list = self._call("list_workspaces")
                match = [w for w in ws_list if w.get("name") == user_id]
                if match:
                    self._user_id_to_ws[user_id] = match[0]["id"]
        return self._user_id_to_ws.get(user_id, "")

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call a client method with automatic token-refresh retry on auth errors."""
        try:
            result = getattr(self._client, method)(*args, **kwargs)
            return result
        except RuntimeError as exc:
            msg = str(exc).lower()
            if self._token_refresh_callback and ("unauthorized" in msg or "authentication" in msg or "401" in msg):
                self._token_refresh_callback()
                # Retry once after refresh
                result = getattr(self._client, method)(*args, **kwargs)
                return result
            raise

    def _extract_ids_from_filters(self, filters: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
        """Extract user_id, agent_id, run_id from a Mem0 v2 filters dict."""
        if not filters:
            return None, None, None
        return (
            filters.get("user_id"),
            filters.get("agent_id"),
            filters.get("run_id"),
        )

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
        infer: bool = True,
        prompt: str | None = None,
        output_format: str = "v1.1",
        memory_type: str | None = None,
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
            infer: If True (default):
                - For string content: searches for semantically similar
                  existing memories.  If a close match (score > 0.85) is
                  found, the new content is appended to the existing memory
                  (UPDATE) instead of creating a new entry.
                - For message-list content: concatenates message contents
                  into a single string (no role prefixes).
                If False, behaves as a plain store with role-prefixed
                formatting for message lists.
            prompt: Optional prompt for inference (accepted for compatibility).
            output_format: Output format version (default ``"v1.1"``).
            memory_type: Specifies memory type (``procedural_memory`` or None).

        Returns:
            A dict with a ``"results"`` key containing a list of stored
            memory records, each with ``id``, ``memory``, ``event``,
            ``user_id``, and ``agent_id``.

        Example::

            >>> m.add("I like pizza", user_id="alice", agent_id="assistant")
            {'results': [{'id': '...', 'memory': 'I like pizza', ...}], 'relation_events': []}

        """
        # For backward compatibility, extract from filters if provided
        if filters and not user_id:
            user_id = filters.get("user_id", user_id)
        if filters and not agent_id:
            agent_id = filters.get("agent_id", agent_id)
        if filters and not run_id:
            run_id = filters.get("run_id", run_id)

        try:
            if isinstance(messages, list):
                if infer:
                    # infer=True with list: concatenate message contents only
                    content = " ".join(
                        m.get("content", "")
                        for m in messages
                        if m.get("content")
                    )
                    summary = ""
                else:
                    content = "\n".join(
                        f"{m.get('role', 'user')}: {m.get('content', '')}"
                        for m in messages
                    )
                    summary = content[:200]
            else:
                content = str(messages)
                summary = ""

            ws_id = self._ws(user_id)

            # When infer=True and content is a string, try to merge with
            # similar existing memories instead of creating a new one.
            if infer and isinstance(messages, str) and user_id:
                search_result = self.search(query=content, user_id=user_id, limit=5)
                close_matches = [
                    r for r in search_result.get("results", [])
                    if r.get("score", 0) > 0.85
                ]
                if close_matches:
                    best_match = close_matches[0]
                    mem_id = best_match["id"]
                    existing_content = best_match.get("memory", "")
                    merged = f"{existing_content}\n{content}"
                    self.update(memory_id=mem_id, data=merged)
                    # LLM fact extraction on merged content
                    try:
                        llm = LLMClient()
                        if llm.available:
                            facts = llm.extract_facts(merged)
                            if facts:
                                self._call("update_memory", mem_id, json.dumps({"extracted_facts": facts}))
                    except Exception:
                        pass
                    return {
                        "results": [{
                            "id": mem_id,
                            "memory": merged,
                            "event": "UPDATE",
                            "user_id": user_id or "",
                            "agent_id": agent_id or "",
                        }],
                        "relation_events": [],
                    }

            # LLM fact extraction when infer=True
            extracted_facts = None
            if infer:
                try:
                    llm = LLMClient()
                    if llm.available:
                        extracted_facts = llm.extract_facts(content)
                except Exception:
                    pass

            meta = {}
            if extracted_facts:
                meta["extracted_facts"] = extracted_facts

            self._call(
                "store",
                workspace_id=ws_id,
                content=content,
                summary=summary or content[:200],
                memory_type="experience",
                peer_id=agent_id or "",
                source_session_id=run_id or "",
                entities_json=json.dumps(meta) if meta else "{}",
            )

            # If user_id is provided, scope the stored memory to that user
            if user_id:
                stored = self._call("search", ws_id, content, limit=1, semantic=True)
                if stored:
                    mem_id = stored[0].get("entity_id", "") or stored[0].get("id", "")
                    if mem_id:
                        try:
                            self._client._call("set_memory_scope", [mem_id, user_id])
                        except Exception as exc:
                            logger.warning(
                                "mem0.add: set_memory_scope failed for %s: %s",
                                mem_id, exc,
                            )

            # Return Mem0-compatible shape — search for the stored memory
            search_results = self._call("search", ws_id, content, limit=1, semantic=True)
            return {
                "results": [
                    {
                        "id": r.get("entity_id", ""),
                        "memory": r.get("memory_content", r.get("content", "")),
                        "event": "ADD",
                        "user_id": user_id or "",
                        "agent_id": agent_id or "",
                    }
                    for r in search_results
                ],
                "relation_events": [],
            }
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.add('{messages!r}') failed: {exc}") from exc

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
        try:
            rows = self._call("get_memory", memory_id)
            # Filter to active memories only (delete is soft)
            rows = [r for r in rows if r.get("is_active", True)] if rows else []
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
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.get('{memory_id}') failed: {exc}") from exc

    def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        threshold: float = 0.0,
        *,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        rerank: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search memories by semantic similarity to *query*.

        Supports both Mem0 v1.x keyword signatures and v2.x ``filters`` dict.

        Args:
            query: The search query text.
            user_id: Optional user filter (Mem0 v1 compat).
            agent_id: Optional agent filter (Mem0 v1 compat).
            run_id: Optional run/session filter (Mem0 v1 compat).
            limit: Max results to return (default 100).
            threshold: Minimum relevance score (0.0 = no filter).
            top_k: Mem0 v2+ alias for ``limit``.
            filters: Mem0 v2+ filters dict (e.g. ``{"user_id": "u1"}``).
            rerank: If True, apply reranking (accepted for compatibility).
            **kwargs: Additional Mem0 keyword arguments (accepted for
                compatibility but ignored).

        Returns:
            A dict with a ``"results"`` key containing a list of matching
            memory records, each with ``id``, ``memory``, ``score``,
            ``user_id``, ``agent_id``, and ``metadata``.  Always returns
            a dict (even for empty results).

        Example::

            >>> m.search("food preferences", user_id="alice")
            {'results': [{'id': '...', 'memory': 'I like pizza', 'score': 0.92, ...}]}

        """
        # Extract from filters dict (Mem0 v2 compat)
        if filters is not None:
            fu, fa, fr = self._extract_ids_from_filters(filters)
            user_id = user_id or fu
            agent_id = agent_id or fa
            run_id = run_id or fr

        # top_k overrides limit if both provided
        effective_limit = top_k if top_k is not None else limit
        # Mem0 v2 default threshold is 0.1, but we keep 0.0 for backward compat
        effective_threshold = threshold

        ws_id = self._ws(user_id)

        try:
            rows = self._call(
                "search",
                workspace_id=ws_id,
                query=query,
                limit=effective_limit,
                semantic=True,
            )
            results = []
            for r in rows or []:
                score = r.get("score", 0.0)
                if effective_threshold > 0.0 and score < effective_threshold:
                    continue
                # If user_id is specified, verify user_scope isolation
                mem_id = r.get("entity_id", "")
                if user_id and mem_id:
                    # Fetch the full record to check user_scope
                    mem_records = self._call("get_memory", mem_id)
                    if mem_records:
                        mem_user_scope = mem_records[0].get("user_scope", "")
                        if mem_user_scope != "" and mem_user_scope != user_id:
                            continue  # Skip: scoped to a different user
                results.append({
                    "id": mem_id,
                    "memory": r.get("memory_content", r.get("content", "")),
                    "score": score,
                    "user_id": user_id or "",
                    "agent_id": agent_id or "",
                    "metadata": {},
                })
            return {"results": results}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.search('{query}') failed: {exc}") from exc

    def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """List all memories for a user.

        Supports both Mem0 v1.x keyword signatures and v2.x ``filters`` dict.

        Args:
            user_id: User whose memories to list (Mem0 v1 compat).
            agent_id: Optional agent filter (Mem0 v1 compat).
            run_id: Optional run/session filter (Mem0 v1 compat).
            limit: Max results to return (default 100).
            filters: Mem0 v2+ filters dict (e.g. ``{"user_id": "u1"}``).
            top_k: Mem0 v2+ alias for ``limit``.
            **kwargs: Additional Mem0 keyword arguments (accepted for
                compatibility but ignored).

        Returns:
            A dict with a ``"results"`` key containing a list of memory
            records, each with ``id``, ``memory``, ``user_id``, ``agent_id``,
            and ``metadata``.

        Example::

            >>> m.get_all(user_id="alice")
            {'results': [{'id': '...', 'memory': 'I like pizza', ...}]}

        """
        # Extract from filters dict (Mem0 v2 compat)
        if filters is not None:
            fu, fa, fr = self._extract_ids_from_filters(filters)
            user_id = user_id or fu
            agent_id = agent_id or fa
            run_id = run_id or fr

        effective_limit = top_k if top_k is not None else limit

        try:
            if user_id:
                ws_id = self._ws(user_id)
                # List all memories in workspace, then filter by user_scope
                all_mems = self._call("list_memories", workspace_id=ws_id, limit=1000)
                rows = [
                    r for r in all_mems
                    if r.get("user_scope", "") in ("", user_id)
                ][:effective_limit]
            else:
                ws_id = self._ws(None)
                rows = self._call("list_memories", workspace_id=ws_id, limit=effective_limit)
            return {
                "results": [
                    {
                        "id": r.get("id", r.get("entity_id", "")),
                        "memory": r.get("content", ""),
                        "user_id": user_id or "",
                        "agent_id": agent_id or "",
                        "metadata": {},
                    }
                    for r in rows
                ]
            }
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.get_all(user_id='{user_id}') failed: {exc}") from exc

    def update(
        self,
        memory_id: str,
        data: str | dict,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a memory's content and/or metadata.

        Args:
            memory_id: The UUID of the memory to update.
            data: New content as a string, or a dict with ``"content"`` or
                ``"memory"`` keys.
            metadata: Optional metadata dict (Mem0 v2+). Stored for
                compatibility but not persisted in the current implementation.

        Returns:
            A dict with operation status.

        Example::

            >>> m.update(memory_id="abc123", data="I love pizza")
            {'message': 'Memory updated successfully!'}

        """
        try:
            if isinstance(data, dict):
                content = data.get("content", data.get("memory", str(data)))
            else:
                content = str(data)
            self._call(
                "update_memory", memory_id, content=content, summary=content[:200]
            )
            return {"message": "Memory updated successfully!"}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.update('{memory_id}') failed: {exc}") from exc

    def delete(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory by ID.

        Args:
            memory_id: The UUID of the memory to delete.

        Returns:
            A dict with operation status.

        Example::

            >>> m.delete(memory_id="abc123")
            {'message': 'Memory deleted successfully!'}

        """
        try:
            self._call("delete_memory", memory_id)
            return {"message": "Memory deleted successfully!"}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.delete('{memory_id}') failed: {exc}") from exc

    def delete_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        *,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete all memories for a user by iterating get_all().

        Args:
            user_id: User whose memories to delete (Mem0 v1 compat).
            agent_id: Optional agent filter (Mem0 v1 compat).
            run_id: Optional run/session filter (Mem0 v1 compat).
            filters: Mem0 v2+ filters dict (e.g. ``{"user_id": "u1"}``).

        Returns:
            A dict with status and count of deleted memories.

        """
        # Extract from filters dict (Mem0 v2 compat)
        if filters is not None:
            fu, fa, fr = self._extract_ids_from_filters(filters)
            user_id = user_id or fu
            agent_id = agent_id or fa
            run_id = run_id or fr

        try:
            result = self.get_all(user_id=user_id, agent_id=agent_id, run_id=run_id)
            memories = result.get("results", [])
            for mem in memories:
                mem_id = mem.get("id", "")
                if mem_id:
                    self._call("delete_memory", mem_id)
            return {"status": "ok", "deleted": len(memories)}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.delete_all(user_id='{user_id}') failed: {exc}") from exc

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
        try:
            return self._call("get_memory_history", memory_id)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.history('{memory_id}') failed: {exc}") from exc

    def reset(self) -> dict[str, Any]:
        """Reset all state (clear workspace cache).

        Example::

            >>> m.reset()
            {'status': 'ok'}

        """
        self._user_id_to_ws.clear()
        return {"status": "ok"}

    def close(self) -> None:
        """Close the underlying HTTP client (idempotent).

        Mem0 v2+ compat.
        """
        self._user_id_to_ws.clear()
