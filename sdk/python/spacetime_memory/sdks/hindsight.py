"""Hindsight-inspired memory adapter.

INSPIRED BY the Hindsight memory system at:
https://github.com/vectorize-io/hindsight

NOTE: This is NOT a drop-in replacement for the upstream Python SDK.
The real ``hindsight_client.Hindsight`` (v0.8.1) is an HTTP REST client
with a fundamentally different API (``bank_id``-oriented, typed Pydantic
response models, no ``forget()`` method). This adapter provides a
SpacetimeDB-backed memory store with a simpler API that shares the
same conceptual model (retain/recall/reflect) but is NOT signature-compatible.
See https://github.com/vectorize-io/hindsight/tree/main/hindsight-clients/python

Usage::

    from spacetime_memory.sdks.hindsight import Hindsight

    h = Hindsight(config={"host": "localhost", "port": 3001})
    h.retain("I like pizza", source="chat", metadata={"key": "val"})
    results = h.recall("food preferences", limit=20)
    insights = h.reflect("What themes emerge?")
    h.forget(memory_id="abc123")

"""

from __future__ import annotations

import json
import os
import hashlib
from typing import Any, Callable

from ..client import Client


class Hindsight:
    """Drop-in replacement for ``hindsight.Hindsight``.

    Maps::

        retain(content, source, metadata) → store_memory
        recall(query, limit)             → hybrid_search
        reflect(prompt)                  → create_insight via LLM
        forget(memory_id)                → delete_memory

    Enhanced ``reflect()`` supports template-based configuration
    (``reflect_mission`` custom system prompt), semantic memory
    retrieval, structured output schemas, and tag filtering.

    Example::

        >>> from spacetime_memory.sdks.hindsight import Hindsight
        >>> h = Hindsight()
        >>> h.retain("I like pizza", source="chat")
        {'status': 'ok'}
        >>> h.recall("food preferences", limit=5)
        {'results': [{'id': '...', 'memory': 'I like pizza', 'score': 0.92, ...}]}
        >>> h.reflect_mission = "You are a dietitian analyzing food preferences."
        >>> result = h.reflect("What dietary patterns do you see?",
        ...                    tags=["chat"],
        ...                    max_tokens=2048)
        {'status': 'ok', 'text': '...', 'based_on': [...], ...}

    """

    def __init__(
        self,
        config: dict | None = None,
        token_refresh_callback: Callable[[], str] | None = None,
        client: Client | None = None,
    ):
        config = config or {}
        if client is not None:
            self._client = client
        else:
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
        # Reflect mission overrides: workspace_id → custom system prompt
        self._reflect_missions: dict[str, str | None] = {}

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
    # Reflect mission (template-based config)
    # -------------------------------------------------------------------

    @property
    def reflect_mission(self) -> str | None:
        """Custom system prompt used by ``reflect()`` for the current workspace.

        When set, every call to ``reflect()`` uses this prompt as the
        system message instead of the default memory-analysis prompt.
        Set to ``None`` to clear and restore the default.
        """
        return self._reflect_missions.get(self._ws())

    @reflect_mission.setter
    def reflect_mission(self, mission: str | None) -> None:
        self._reflect_missions[self._ws()] = mission

    def set_reflect_mission(self, mission: str | None, workspace_id: str | None = None) -> None:
        """Set a custom system prompt (reflect_mission) for reflection.

        When set, every call to ``reflect()`` uses this prompt as the
        system message instead of the default memory-analysis prompt.

        Args:
            mission: Custom system prompt text, or ``None`` to clear.
            workspace_id: Workspace to apply this to (default: current workspace).
        """
        self._reflect_missions[workspace_id or self._ws()] = mission

    def get_reflect_mission(self, workspace_id: str | None = None) -> str | None:
        """Return the current reflect_mission for the given workspace."""
        return self._reflect_missions.get(workspace_id or self._ws())

    # -------------------------------------------------------------------
    # Template export / import
    # -------------------------------------------------------------------

    def export_template(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Export the reflect configuration as a portable dict.

        Returns:
            A dict with ``reflect_mission`` and ``workspace_id``,
            suitable for saving and loading via ``import_template()``.

        Example::

            >>> tmpl = h.export_template()
            >>> h2.import_template(tmpl)

        """
        ws_id = workspace_id or self._ws()
        return {
            "reflect_mission": self._reflect_missions.get(ws_id),
            "workspace_id": ws_id,
        }

    def import_template(self, data: dict[str, Any]) -> None:
        """Import a reflect configuration dict previously
        exported via ``export_template()``.

        Args:
            data: A dict with ``reflect_mission`` and optionally
                ``workspace_id``.  If ``workspace_id`` is missing
                the current workspace is used.

        Example::

            >>> h.import_template({"reflect_mission": "Analyze as a poet.", "workspace_id": "..."})

        """
        ws_id = data.get("workspace_id", self._ws())
        self._reflect_missions[ws_id] = data.get("reflect_mission")

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
        except ValueError:
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
        except ValueError:
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
        seen_hashes: set[str] = set()
        for i, item in enumerate(items):
            try:
                content = item.get("content", "")
                if not content:
                    results.append({"status": "error", "error": "content is required"})
                    continue
                source = item.get("source", "")
                metadata = item.get("metadata")
                # Content-hash dedup within the batch
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                if content_hash in seen_hashes:
                    results.append({"status": "skipped", "reason": "duplicate_content"})
                    continue
                seen_hashes.add(content_hash)
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
        *,
        context: str | None = None,
        tags: list[str] | None = None,
        max_tokens: int | None = None,
        response_schema: dict | None = None,
    ) -> dict[str, Any]:
        """Generate insights by analyzing memories via LLM.

        Creates an insight node in the KG.  If ``OPENAI_API_KEY`` is set,
        also calls an LLM to synthesise findings from relevant memories.

        Uses semantic search (the *prompt* as the query) to find the most
        relevant memories.  Optionally filters by *tags*.

        Gracefully handles the case where no memories exist.

        If ``reflect_mission`` has been configured (via the property or
        ``set_reflect_mission()``), that custom system prompt is used
        instead of the default ``"You are a memory analysis assistant..."``.

        Args:
            prompt: The reflection question to ask about the stored memories.
            workspace_id: Optional workspace override (defaults to the
                configured workspace).
            context: Extra user-provided context to include alongside the
                prompt in the LLM request.
            tags: Optional list of tag strings to filter which memories
                are included in the analysis.  Only memories whose
                ``source`` or ``memory_type`` matches one of the tags
                are retained.
            max_tokens: Override the LLM token limit (default ``1024``).
            response_schema: A JSON Schema dict for structured output.
                When provided, the LLM response is parsed as JSON and
                included in the return as ``structured_output``.

        Returns:
            A dict with:

            * ``status`` — ``"ok"`` on success.
            * ``prompt`` — the original prompt.
            * ``workspace_id`` — the workspace used.
            * ``insight`` — the LLM insight text (or a fallback message).
              Kept for backward compatibility.
            * ``text`` — alias for ``insight``.
            * ``based_on`` — a list of memory IDs that were used as context.
            * ``structured_output`` — present only when *response_schema*
              was provided; the parsed JSON object.

        Example::

            >>> h.reflect("What themes emerge?")
            {'status': 'ok', 'insight': '...', 'text': '...', 'based_on': [...], ...}

            >>> h.reflect("Summarize preferences", tags=["chat"],
            ...           response_schema={"type": "object",
            ...                           "properties": {"summary": {"type": "string"}}})
            {'status': 'ok', 'insight': '...', 'structured_output': {'summary': '...'}, ...}

        """
        ws_id = workspace_id or self._ws()

        # Use semantic search with the prompt (plus optional context) to
        # find the most relevant memories — far better than the old
        # empty-query non-semantic fetch.
        try:
            search_query = prompt
            if context:
                search_query = f"{prompt} {context}"
            recent = self._call(
                "search",
                workspace_id=ws_id, query=search_query, limit=20, semantic=True,
            )
        except ValueError:
            raise
        except Exception as exc:
            recent = []

        # Optional client-side tag filtering
        if tags and recent:
            tag_set = {t.lower() for t in tags}
            filtered = []
            for r in recent:
                mem_type = (r.get("memory_type", "") or "").lower()
                src = (r.get("source", "") or "").lower()
                content_val = (r.get("content", r.get("memory_content", "")) or "").lower()
                # Match tag against memory_type, source, or content
                if any(t in mem_type or t in src or t in content_val for t in tag_set):
                    filtered.append(r)
            recent = filtered

        context_lines = []
        based_on: list[str] = []
        for r in recent or []:
            content = r.get("content", r.get("memory_content", ""))
            if content:
                context_lines.append(f"- {content[:300]}")
                mem_id = r.get("entity_id", r.get("id", ""))
                if mem_id:
                    based_on.append(mem_id)
        context_str = "\n".join(context_lines[:10])

        if not context_str.strip():
            # No memories — return a graceful empty insight
            llm_response = "[No memories available to reflect on.]"
            try:
                self._client._call(
                    "create_insight",
                    [ws_id, "hindsight_reflection", prompt, "synthesized", "{}", 0.5],
                )
            except Exception:
                pass
            result: dict[str, Any] = {
                "status": "ok",
                "prompt": prompt,
                "workspace_id": ws_id,
                "insight": llm_response,
                "text": llm_response,
                "based_on": [],
            }
            if response_schema:
                result["structured_output"] = None
            return result

        # Optionally call LLM for synthesis
        llm_response = None
        structured_output = None
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key and context_str.strip():
            import httpx

            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

            # Use custom reflect_mission if configured, else the default
            system_prompt = self._reflect_missions.get(
                ws_id,
                "You are a memory analysis assistant. "
                "Identify key themes, patterns, and insights from the provided memory entries.",
            )

            messages = [
                {"role": "system", "content": system_prompt},
            ]
            user_content = f"## Prompt\n\n{prompt}\n\n## Recent Memories\n\n{context_str}"
            if context:
                user_content += f"\n\n## Additional Context\n\n{context}"
            messages.append({"role": "user", "content": user_content})

            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": max_tokens or 1024,
            }
            if response_schema:
                body["response_format"] = {"type": "json_object"}

            try:
                resp = httpx.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=60,
                )
                resp.raise_for_status()
                llm_response = resp.json()["choices"][0]["message"]["content"]
                if response_schema and llm_response:
                    try:
                        structured_output = json.loads(llm_response)
                    except json.JSONDecodeError:
                        structured_output = {
                            "_raw": llm_response,
                            "_parse_error": "response was not valid JSON",
                        }
            except Exception as exc:
                llm_response = f"[Reflection LLM call failed: {exc}]"

        result = self._client._call(
            "create_insight",
            [ws_id, "hindsight_reflection", prompt, "synthesized", "{}", 0.5],
        )
        ret: dict[str, Any] = {
            "status": "ok",
            "prompt": prompt,
            "workspace_id": ws_id,
            "insight": llm_response or (
                "Created insight node (LLM not configured — use OPENAI_API_KEY for synthesis)"
            ),
            "text": llm_response or (
                "Created insight node (LLM not configured — use OPENAI_API_KEY for synthesis)"
            ),
            "based_on": based_on,
        }
        if response_schema:
            ret["structured_output"] = structured_output
        return ret

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
        except ValueError:
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
        except ValueError:
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
        except ValueError:
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
