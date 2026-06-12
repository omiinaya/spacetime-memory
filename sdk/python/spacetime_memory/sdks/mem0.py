"""
Mem0-compatible drop-in adapter.

Matches the real Mem0 Python SDK API (https://github.com/mem0ai/mem0):
https://github.com/mem0ai/mem0

All public method signatures (``add``, ``search``, ``get_all``, ``get``,
``delete``, ``history``, ``update``) accept the same keyword arguments
as upstream ``mem0.Memory``. Return shapes match (``{"results": [...]}``).
The ``graph`` property provides entity store access.

NOTE: Constructor differs from upstream — accepts a plain ``config`` dict
instead of a typed ``MemoryConfig`` object. The upstream also requires
an LLM provider config which our adapter doesn't need.

**Error contract:**
- ``ValueError`` for invalid inputs (empty ``text``, missing required args)
- ``RuntimeError`` / ``SpacetimeDBError`` for backend failures (DB down,
  connection errors).  These propagate from the underlying ``Client``.
- ``logger.warning`` logged for transient issues (LLM extraction, KG
  node creation failures) — the operation degrades gracefully rather
  than crashing.
- Graph search returns ``[]`` on failure (logged), consistent with
  mem0's ``get_all`` returning empty for missing data.

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
from typing import Any, Callable

from ..client import Client
from ..llm import LLMClient

logger = logging.getLogger(__name__)


class _GraphStore:
    """Mem0-compatible graph / entity store.

    Real Mem0 stores entities in a separate vector-store collection.
    We back it with SpacetimeDB's ``kg_node`` table — a real knowledge
    graph with typed nodes, edges, and community detection.

    The API shape matches Mem0's ``Memory.graph`` attribute so callers
    can use the same patterns::

        >>> m = Memory()
        >>> m.graph.add("Alice", entity_type="person", user_id="alice")
        >>> results = m.graph.search("Alice", user_id="alice")
        >>> all_nodes = m.graph.get_all(user_id="alice")
    """

    def __init__(self, memory: Memory):
        self._memory = memory

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ws(self, user_id: str | None = None) -> str:
        return self._memory._ws(user_id)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._memory._call(method, *args, **kwargs)

    def _tag(self, user_id: str | None = None) -> str:
        """Build a tag suffix used to scope entities to a user."""
        return f"mem0_user:{user_id}" if user_id else "mem0_global"

    # ------------------------------------------------------------------
    # Mem0 graph API
    # ------------------------------------------------------------------

    def add(
        self,
        text: str,
        entity_type: str = "concept",
        user_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Add an entity to the graph.

        Args:
            text: Entity label / name (e.g. ``"Alice"``, ``"Python"``).
            entity_type: Semantic type (e.g. ``"person"``, ``"language"``,
                ``"concept"``).  Default ``"concept"``.
            user_id: Owner user (scopes the node to a workspace).
            agent_id: Optional agent scope.
            metadata: Optional extra properties stored in the node's
                ``metadata_json``.

        Returns:
            Dict with the created node info.

        Raises:
            ValueError: If ``text`` is empty.
        """
        if not text or not text.strip():
            raise ValueError("graph.add() requires non-empty text")
        ws_id = self._ws(user_id)
        meta = dict(metadata or {})
        if agent_id:
            meta["agent_id"] = agent_id
        meta["tag"] = self._tag(user_id)
        result = self._call(
            "create_node",
            workspace_id=ws_id,
            label=text.strip(),
            node_type=entity_type,
            summary=text.strip(),
            metadata_json=json.dumps(meta),
        )
        return result if isinstance(result, dict) else {"status": "ok", "id": str(result)}

    def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search graph entities by label.

        Args:
            query: Text to search for (label substring match).
            user_id: Scope results to this user's workspace.
            limit: Max results (default 10).

        Returns:
            List of matching ``kg_node`` records.
        """
        ws_id = self._ws(user_id)
        rows = self._call("query_graph", workspace_id=ws_id, query=query)
        tag = self._tag(user_id)
        filtered = [r for r in rows if r.get("metadata_json", "").endswith(f'"tag": "{tag}"') or r.get("metadata_json", "") == ""]
        return filtered[:limit]

    def get_all(
        self,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List all graph entities for a user.

        Args:
            user_id: Owner user.
            limit: Max results (default 100).

        Returns:
            List of node records.
        """
        ws_id = self._ws(user_id)
        rows = self._call("query_graph", workspace_id=ws_id, query="")
        tag = self._tag(user_id)
        filtered = [r for r in rows if r.get("metadata_json", "").endswith(f'"tag": "{tag}"') or r.get("metadata_json", "") == ""]
        return filtered[:limit]

    def delete(self, entity_id: str) -> dict[str, Any]:
        """Delete a graph entity by node ID.

        Args:
            entity_id: The ``kg_node`` UUID to remove.

        Returns:
            Operation status dict.
        """
        # Soft-delete: set is_active=False via the delete_node reducer
        self._call("delete_node", entity_id)
        return {"status": "ok", "deleted": entity_id}


def _resolve_llm(
    llm_config: dict[str, Any] | None = None,
) -> LLMClient | None:
    """Resolve an ``LLMClient``, optionally with custom per-user config.

    ``llm_config`` can contain:
        - ``model`` (default ``"gpt-4o-mini"``)
        - ``api_key`` (per-user override)
        - ``base_url`` (custom endpoint)

    Returns ``None`` if no ``OPENAI_API_KEY`` is available.
    """
    if not llm_config:
        return LLMClient()
    return LLMClient(
        model=llm_config.get("model", "gpt-4o-mini"),
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("base_url"),
    )


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
        config: Any | None = None,
        token_refresh_callback: Callable[[], str] | None = None,
    ):
        # Accept either dict or mem0's MemoryConfig Pydantic model
        if isinstance(config, dict):
            cfg = config
        elif hasattr(config, "model_dump"):
            cfg = config.model_dump()
        else:
            cfg = config or {}
        self._client = Client(
            host=cfg.get("host"),
            port=cfg.get("port"),
            database=cfg.get("db", cfg.get("database")),
            embedder_url=cfg.get("embedder_url"),
        )
        self._user_id_to_ws: dict[str, str] = {}
        self._token_refresh_callback = token_refresh_callback
        self._graph_store: _GraphStore | None = None

        # Per-user LLM config overrides: {user_id: {provider, model, api_key, base_url}}
        self._llm_overrides: dict[str, dict[str, Any]] = {}
        # Process any llm_config entries from the top-level config
        llm_config = cfg.get("llm_config", {})
        if isinstance(llm_config, dict):
            for uid, cfg in llm_config.items():
                if isinstance(cfg, dict):
                    self._llm_overrides[uid] = cfg

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
    # Graph (entity store) — Mem0 v2+ compat
    # -------------------------------------------------------------------

    @property
    def graph(self) -> _GraphStore:
        """Access the entity / graph store.

        Example::

            >>> m.graph.add("Alice", entity_type="person", user_id="alice")
            >>> for node in m.graph.search("Alice", user_id="alice"):
            ...     print(node["label"])
        """
        if self._graph_store is None:
            self._graph_store = _GraphStore(self)
        return self._graph_store

    # -------------------------------------------------------------------
    # Per-user LLM config
    # -------------------------------------------------------------------

    def set_llm_config(
        self,
        user_id: str,
        llm_config: dict[str, Any],
    ) -> None:
        """Set a per-user LLM config override.

        Args:
            user_id: The user to configure for.
            llm_config: Dict with optional keys ``provider``, ``model``,
                ``api_key``, ``base_url``.
        """
        self._llm_overrides[user_id] = llm_config

    def _resolve_llm_for(
        self,
        user_id: str | None = None,
    ) -> LLMClient | None:
        """Resolve an ``LLMClient`` respecting any per-user override."""
        if user_id and user_id in self._llm_overrides:
            return _resolve_llm(self._llm_overrides[user_id])
        return LLMClient()

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
                else:
                    raise ValueError(
                        f"Could not resolve or create workspace for user_id='{user_id}'"
                    )
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

    def _store_facts_as_kg_nodes(
        self,
        facts: list[str],
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[str]:
        """Create ``kg_node`` entries from extracted-fact strings.

        Args:
            facts: List of fact strings from ``LLMClient.extract_facts()``.
            user_id: Owner user for workspace scoping.
            agent_id: Optional agent scope.

        Returns a list of node IDs that were created (empty on failure).
        """
        ws_id = self._ws(user_id)
        if not ws_id or not facts:
            return []
        node_ids: list[str] = []
        for fact in facts:
            if len(fact.strip()) < 4:
                continue
            try:
                meta: dict[str, Any] = {"tag": f"mem0_user:{user_id}" if user_id else "mem0_global"}
                if agent_id:
                    meta["agent_id"] = agent_id
                result = self._call(
                    "create_node",
                    workspace_id=ws_id,
                    label=fact,
                    node_type="fact",
                    summary=fact,
                    metadata_json=json.dumps(meta),
                )
                if isinstance(result, dict):
                    nid = result.get("id", "")
                    if nid:
                        node_ids.append(nid)
            except Exception:
                logger.debug("Failed to create KG node for fact: %s", fact)
        return node_ids

    def _get_graph_context(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[str]:
        """Search the KG for entities relevant to *query* and return labels."""
        ws_id = self._ws(user_id)
        try:
            rows = self._call("query_graph", workspace_id=ws_id, query=query)
            return [r.get("label", "") for r in rows[:limit] if r.get("label")]
        except Exception as exc:
            logger.warning("_GraphStore.search() failed: %s", exc)
            return []

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
                When *infer* is True and an LLM is available, entity facts
                are extracted and stored as ``kg_node`` entries in the
                knowledge graph (Mem0 graph-memory equivalent).
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
                        llm = self._resolve_llm_for(user_id)
                        if llm and llm.available:
                            facts = llm.extract_facts(merged)
                            if facts:
                                self._store_facts_as_kg_nodes(
                                    facts, user_id, agent_id,
                                )
                                self._call(
                                    "update_memory", mem_id,
                                    json.dumps({"extracted_facts": facts}),
                                )
                    except Exception as exc:
                        logger.warning("Failed to update memory with KG facts: %s", exc)
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
                    llm = self._resolve_llm_for(user_id)
                    if llm and llm.available:
                        extracted_facts = llm.extract_facts(content)
                except Exception as exc:
                    logger.warning("LLM fact extraction failed: %s", exc)

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

            # If fact extraction yielded results, persist as KG nodes
            if extracted_facts:
                self._store_facts_as_kg_nodes(extracted_facts, user_id, agent_id)

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
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"mem0.add() failed: {exc}") from exc

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
        except ValueError:
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
        graph_context: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search memories by semantic similarity to *query*.

        Supports both Mem0 v1.x keyword signatures and v2.x ``filters`` dict.

        When *graph_context* is True (default), the knowledge graph is
        queried for entities matching the search terms, and matching KG
        node labels are included in each result's ``metadata.graph_context``.
        This mirrors Mem0's entity-based search boosting behaviour.

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
            graph_context: If True, enrich results with KG entity context
                (default True).
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

        # Gather graph context for the search query
        graph_entities = []
        if graph_context:
            graph_entities = self._get_graph_context(query, user_id)

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

                meta: dict[str, Any] = {}
                if graph_entities:
                    meta["graph_context"] = graph_entities

                results.append({
                    "id": mem_id,
                    "memory": r.get("memory_content", r.get("content", "")),
                    "score": score,
                    "user_id": user_id or "",
                    "agent_id": agent_id or "",
                    "metadata": meta,
                })
            return {"results": results}
        except RuntimeError:
            raise
        except ValueError:
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
                ],
            }
        except RuntimeError:
            raise
        except ValueError:
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
        except ValueError:
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
        except ValueError:
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
        except ValueError:
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
        except ValueError:
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

    # -------------------------------------------------------------------
    # chat() — RAG + LLM response (Mem0 v2 forward-looking)
    # -------------------------------------------------------------------

    def chat(
        self,
        query: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        messages: list[dict[str, str]] | None = None,
        memory_type: str | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a chat response augmented by stored memories.

        This implements an augmented-generation workflow:
          1. Store the user's message as a memory (via ``add()``).
          2. Search for relevant past memories (via ``search()``).
          3. Build a prompt with the search results as context.
          4. Generate a response via ``LLMClient``.
          5. Store the assistant's response as a memory.

        Args:
            query: The user's current message text.
            user_id: User / session scope.
            agent_id: Agent scope (default ``"assistant"``).
            run_id: Optional run ID.
            messages: Optional conversation history (list of
                ``{"role": ..., "content": ...}`` dicts).  If provided,
                the history is used to augment the prompt.
            memory_type: Optional memory type (default None).
            llm_config: Optional per-invocation LLM config overrides
                (provider, model, api_key, base_url).

        Returns:
            A dict with ``"response"`` (the generated text),
            ``"context"`` (list of relevant memory texts), and
            ``"memories"`` (list of memory records).

        Example::

            >>> result = m.chat("What do I like?", user_id="alice")
            >>> result["response"]
            'Based on your memories, you like pizza.'
            >>> result["context"]
            ['I like pizza']

        Notes:
            The real Mem0 ``chat()`` is still ``NotImplementedError``
            as of v2.x.  This implementation is forward-looking and
            will gracefully degrade (return the query alone) if no
            ``OPENAI_API_KEY`` is configured.
        """
        agent_id = agent_id or "assistant"

        # 1. Store the query
        self.add(
            query,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            memory_type=memory_type,
        )

        # 2. Search for relevant past memories
        search_results = self.search(
            query,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            limit=10,
        )
        context_texts = [
            r.get("memory", "") for r in search_results.get("results", [])
            if r.get("memory")
        ]

        # 3. Build the prompt
        system_prompt = (
            "You are a helpful assistant with access to the user's stored memories. "
            "Use the following relevant memories to answer the user's question. "
            "If the memories are not relevant, answer normally."
        )

        context_block = ""
        if context_texts:
            context_block = "\nRelevant memories:\n" + "\n".join(
                f"- {t}" for t in context_texts
            )

        history_block = ""
        if messages:
            history_block = "\nConversation history:\n" + "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in messages
            )

        user_prompt = (
            f"{context_block}"
            f"{history_block}"
            f"\nUser: {query}\nAssistant:"
        )

        # 4. Generate response via LLM
        llm = _resolve_llm(llm_config)
        response_text = query  # fallback
        if llm and llm.available:
            try:
                response_text = llm.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                ) or query
            except Exception as exc:
                logger.warning("mem0.chat() LLM call failed: %s", exc)
                response_text = query

        # 5. Store the assistant response
        self.add(
            response_text,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            memory_type=memory_type,
        )

        return {
            "response": response_text,
            "context": context_texts,
            "memories": search_results.get("results", []),
        }

    def create_memory_tool(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a memory tool for agent frameworks.

        .. deprecated:: 2.0
            This method was removed from upstream Mem0 v2.0.  It existed
            in v1.x as a way to generate a tool definition for agent
            frameworks (LangChain, CrewAI, etc.).  The SpacetimeDB adapter
            does not implement it — use :meth:`chat` for RAG-augmented
            responses or :meth:`search` + :meth:`add` for manual memory
            management.

        Returns:
            A dict with ``\"status\": \"not_implemented\"`` and a
            deprecation note.
        """
        return {
            "status": "not_implemented",
            "note": "create_memory_tool was removed from Mem0 v2.0. "
                    "Use chat() for RAG or search()+add() directly.",
        }
