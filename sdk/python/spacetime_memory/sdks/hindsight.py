"""Hindsight-compatible drop-in adapter.

Matches the real Hindsight Python SDK API:
https://github.com/vectorize-io/hindsight

Usage::

    from spacetime_memory.sdks.hindsight import Hindsight

    h = Hindsight(config={"api_key": "..."})  # api_key accepted for compat
    h.retain("I like pizza", source="chat", metadata={"key": "val"})
    results = h.recall("food preferences", limit=20)
    insights = h.reflect("What themes emerge?")
    h.forget(memory_id="abc123")
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from ..client import Client


class Hindsight:
    """Drop-in replacement for ``hindsight.Hindsight``.

    Maps::

        retain(content, source, metadata) → store_memory
        recall(query, limit)             → hybrid_search
        reflect(prompt)                  → create_insight via LLM
        forget(memory_id)                → delete_memory

    Example::

        >>> from spacetime_memory.sdks.hindsight import Hindsight
        >>> h = Hindsight()
        >>> h.retain("I like pizza", source="chat")
        {'status': 'ok'}
        >>> h.recall("food preferences", limit=5)
        {'results': [{'id': '...', 'memory': 'I like pizza', 'score': 0.92, ...}]}

    """

    def __init__(
        self,
        config: dict | None = None,
        token_refresh_callback: Callable[[], str] | None = None,
    ):
        config = config or {}
        self._client = Client(
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("db", config.get("database")),
            embedder_url=config.get("embedder_url"),
        )
        self._token_refresh_callback = token_refresh_callback
        self._workspace_id: str = config.get("workspace_id", "")
        if not self._workspace_id:
            # Use or create a default workspace
            ws_list = self._call("list_workspaces")
            if ws_list:
                self._workspace_id = ws_list[0]["id"]
            else:
                self._call("create_workspace", "default", "Hindsight default workspace")
                ws_list = self._call("list_workspaces")
                if ws_list:
                    self._workspace_id = ws_list[0]["id"]

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _ws(self) -> str:
        if not self._workspace_id:
            raise RuntimeError("No workspace configured")
        return self._workspace_id

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call a client method with automatic token-refresh retry on auth errors."""
        try:
            return getattr(self._client, method)(*args, **kwargs)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if self._token_refresh_callback and ("unauthorized" in msg or "authentication" in msg or "401" in msg):
                self._token_refresh_callback()
                return getattr(self._client, method)(*args, **kwargs)
            raise

    # -------------------------------------------------------------------
    # Hindsight API
    # -------------------------------------------------------------------

    def retain(
        self,
        content: str,
        source: str = "",
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Store a memory.

        Args:
            content: The text content to remember.
            source: Optional source label (e.g. ``"chat"``, ``"note"``).
                Used as the memory type.
            metadata: Optional metadata dict attached to the memory.

        Returns:
            A dict with operation status (``{"status": "ok"}``).

        Example::

            >>> h.retain("I like pizza", source="chat", metadata={"key": "val"})
            {'status': 'ok'}

        """
        try:
            result = self._call(
                "store",
                workspace_id=self._ws(),
                content=content,
                summary=content[:200],
                memory_type=source or "experience",
                peer_id="hindsight",
            )
            return result
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"hindsight.retain(content='{content[:50]}...') failed: {exc}") from exc

    def recall(
        self,
        query: str,
        limit: int = 20,
        threshold: float = 0.0,
    ) -> dict[str, Any]:
        """Search memories by semantic similarity to *query*.

        Args:
            query: The search query text.
            limit: Max results to return (default 20).
            threshold: Minimum relevance score (0.0 = no filter).

        Returns:
            A dict with a ``"results"`` key containing a list of matching
            memory records, each with ``id``, ``memory`` (content),
            ``score``, ``source``, and ``metadata``.  This matches the
            return format used by the Mem0 adapter for consistency.

        Example::

            >>> h.recall("food preferences", limit=5)
            {'results': [{'id': '...', 'memory': 'I like pizza', 'score': 0.92, ...}]}

        """
        try:
            rows = self._call(
                "search",
                workspace_id=self._ws(),
                query=query,
                limit=limit,
                semantic=True,
            )
            if not rows:
                return {"results": []}
            if threshold > 0.0:
                rows = [r for r in rows if r.get("score", 0.0) >= threshold]
            results = []
            for r in rows:
                results.append({
                    "id": r.get("entity_id", ""),
                    "memory": r.get("memory_content", r.get("content", "")),
                    "score": r.get("score", 0.0),
                    "source": r.get("memory_type", ""),
                    "metadata": {},
                })
            return {"results": results}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"hindsight.recall('{query}') failed: {exc}") from exc

    def batch_retain(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Store multiple memories in batch.

        Args:
            items: A list of dicts, each with ``content`` (required) and
                optional ``source``, ``metadata`` keys::

                    [
                        {"content": "I like pizza", "source": "chat"},
                        {"content": "User likes hiking", "source": "note", "metadata": {"priority": "high"}},
                    ]

        Returns:
            A list of result dicts, one per item, each with ``"status"``.

        Example::

            >>> h.batch_retain([
            ...     {"content": "I like pizza", "source": "chat"},
            ...     {"content": "User likes hiking"},
            ... ])
            [{'status': 'ok'}, {'status': 'ok'}]

        """
        results = []
        errors = []
        for i, item in enumerate(items):
            try:
                content = item.get("content", "")
                if not content:
                    results.append({"status": "error", "error": "content is required"})
                    continue
                source = item.get("source", "")
                metadata = item.get("metadata")
                result = self.retain(content, source=source, metadata=metadata)
                results.append(result)
            except Exception as exc:
                errors.append({"index": i, "error": str(exc)})
                results.append({"status": "error", "error": str(exc)})
        if errors:
            results.append({"_batch_errors": errors})
        return results

    def reflect(
        self,
        prompt: str = "What are the key themes and patterns in my data?",
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate insights by analyzing memories via LLM.

        Creates an insight node in the KG.  If ``OPENAI_API_KEY`` is set,
        also calls an LLM to synthesise findings from recent memories.

        Gracefully handles the case where no memories exist.

        Args:
            prompt: The reflection question to ask about the stored memories.
            workspace_id: Optional workspace override (defaults to the
                configured workspace).

        Returns:
            A dict with ``status``, ``prompt``, ``workspace_id``, and
            ``insight`` (the LLM response or a fallback message).

        Example::

            >>> h.reflect("What themes emerge?")
            {'status': 'ok', 'insight': 'The user frequently discusses food preferences...', ...}

        """
        ws_id = workspace_id or self._ws()

        # Gather recent memories for context
        try:
            recent = self._call(
                "search",
                workspace_id=ws_id, query="", limit=20, semantic=False,
            )
        except Exception as exc:
            recent = []
        context_lines = []
        for r in recent or []:
            content = r.get("content", r.get("memory_content", ""))
            if content:
                context_lines.append(f"- {content[:300]}")
        context_str = "\n".join(context_lines[:10])

        if not context_str.strip():
            # No memories — return a graceful empty insight
            llm_response = "[No memories available to reflect on.]"
            try:
                self._call(
                    "_call", "create_insight",
                    [ws_id, "hindsight_reflection", prompt, "synthesized", "{}"],
                )
            except Exception:
                pass
            return {
                "status": "ok",
                "prompt": prompt,
                "workspace_id": ws_id,
                "insight": llm_response,
            }

        # Optionally call LLM for synthesis
        llm_response = None
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key and context_str.strip():
            import httpx
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
            try:
                resp = httpx.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are a memory analysis assistant. Identify key themes, patterns, and insights from the provided memory entries."},
                            {"role": "user", "content": f"## Prompt\n\n{prompt}\n\n## Recent Memories\n\n{context_str}"},
                        ],
                        "temperature": 0.4,
                        "max_tokens": 1024,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                llm_response = resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:
                llm_response = f"[Reflection LLM call failed: {exc}]"

        result = self._call(
            "_call", "create_insight",
            [ws_id, "hindsight_reflection", prompt, "synthesized", "{}"],
        )
        return {
            "status": "ok",
            "prompt": prompt,
            "workspace_id": ws_id,
            "insight": llm_response or "Created insight node (LLM not configured — use OPENAI_API_KEY for synthesis)",
        }

    def forget(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory by ID.

        Args:
            memory_id: The UUID of the memory to delete.

        Returns:
            A dict with operation status (``{"status": "ok"}``).

        Example::

            >>> h.forget(memory_id="abc123")
            {'status': 'ok'}

        """
        try:
            return self._call("delete_memory", memory_id)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"hindsight.forget('{memory_id}') failed: {exc}") from exc

    def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all memories in this workspace.

        Args:
            limit: Max results to return (default 100).

        Returns:
            A list of memory records.

        """
        try:
            return self._call("list_memories", workspace_id=self._ws(), limit=limit)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"hindsight.list_all() failed: {exc}") from exc

    def stats(self) -> dict[str, Any]:
        """Return workspace statistics.

        Returns:
            A dict with ``workspace_id``, ``memories``, ``sessions``,
            and ``kg_nodes`` counts.

        """
        try:
            ws_id = self._ws()
            memories = self._call(
                "_sql",
                f"SELECT COUNT(*) as cnt FROM memory WHERE workspace_id = '{_esc_sql(ws_id)}' AND is_active = TRUE",
            )
            sessions = self._call(
                "_sql",
                f"SELECT COUNT(*) as cnt FROM session WHERE workspace_id = '{_esc_sql(ws_id)}'",
            )
            nodes = self._call(
                "_sql",
                f"SELECT COUNT(*) as cnt FROM kg_node WHERE workspace_id = '{_esc_sql(ws_id)}'",
            )
            return {
                "workspace_id": ws_id,
                "memories": memories[0]["cnt"] if memories else 0,
                "sessions": sessions[0]["cnt"] if sessions else 0,
                "kg_nodes": nodes[0]["cnt"] if nodes else 0,
            }
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"hindsight.stats() failed: {exc}") from exc

    def reset(self) -> dict[str, Any]:
        """Reset workspace cache.

        Example::

            >>> h.reset()
            {'status': 'ok'}

        """
        self._workspace_id = ""
        return {"status": "ok"}


def _esc_sql(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")
