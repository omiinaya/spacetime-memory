"""Mem0-compatible adapter for Spacetime-Memory.

Provides a drop-in replacement for ``mem0.Memory`` that uses Spacetime-Memory
as the storage backend.

Usage::

    from stmem_adapter_mem0 import Memory

    m = Memory()
    m.add("I like pizza", user_id="alice", agent_id="assistant")
    results = m.search("food preferences", user_id="alice")
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from spacetime_memory import Client
from spacetime_memory.client import _esc


def _to_mem0_memory(stmem_mem: dict[str, Any], score: float | None = None) -> dict[str, Any]:
    """Convert a Spacetime-Memory record to Mem0's memory format."""
    mem0: dict[str, Any] = {
        "id": stmem_mem.get("id", ""),
        "memory": stmem_mem.get("content", ""),
        "hash": _content_hash(stmem_mem.get("content", "")),
        "created_at": _ts_to_iso(stmem_mem.get("created_at", 0)),
        "updated_at": _ts_to_iso(stmem_mem.get("updated_at", 0)),
        "user_id": stmem_mem.get("user_scope", None) or stmem_mem.get("peer_id", None),
        "agent_id": stmem_mem.get("peer_id", None),
        "run_id": stmem_mem.get("source_session_id", None) or None,
        "metadata": {},
    }
    # Parse stored metadata if available
    entities = stmem_mem.get("entities_json", "{}")
    if entities and entities != "{}":
        try:
            meta = json.loads(entities) if isinstance(entities, str) else entities
            if isinstance(meta, dict):
                mem0["metadata"] = meta
        except (json.JSONDecodeError, TypeError):
            pass
    if score is not None:
        mem0["score"] = score
    # Add categories from memory_type
    mem_type = stmem_mem.get("memory_type", "")
    if mem_type:
        mem0["categories"] = [mem_type]
    return mem0


def _from_mem0_kwargs(
    user_id: str | None, agent_id: str | None, run_id: str | None,
) -> dict[str, str]:
    """Build common filter kwargs for SDK calls from Mem0 parameters."""
    kwargs: dict[str, str] = {}
    if user_id:
        kwargs["user_scope"] = user_id
    if agent_id:
        kwargs["peer_id"] = agent_id
    if run_id:
        kwargs["source_session_id"] = run_id
    return kwargs


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _ts_to_iso(ts: int | float) -> str:
    if ts == 0:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts / 1_000_000, tz=timezone.utc).isoformat() if ts > 1e12 else \
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _now_micros() -> int:
    return int(time.time() * 1_000_000)


class Memory:
    """Mem0-compatible memory interface backed by Spacetime-Memory.

    Each ``(user_id, agent_id)`` pair is mapped to a Spacetime-Memory workspace.
    Workspaces are auto-created on first use.
    """

    def __init__(
        self,
        client: Client | None = None,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        token: str | None = None,
        embedder_url: str | None = None,
    ):
        """Initialize the Mem0 adapter.

        Args:
            client: An existing Spacetime-Memory Client. If omitted, creates one.
            host: SpacetimeDB host (default: localhost).
            port: SpacetimeDB port (default: 3001).
            database: SpacetimeDB database identity.
            token: JWT token for auth.
            embedder_url: Embedder sidecar URL (default: http://localhost:9090).
        """
        if client is not None:
            self._client = client
        else:
            self._client = Client(
                host=host, port=port, database=database,
                token=token, embedder_url=embedder_url,
            )

    def _workspace_for(self, user_id: str | None, agent_id: str | None) -> str:
        """Get or create a workspace for a (user_id, agent_id) pair.

        Includes the caller identity in the workspace key to avoid
        conflicts when multiple JWT identities use the same adapter.
        """
        caller_key = "anon"
        try:
            # Derive a stable key from the JWT identity
            # (only available if a token is set on the client)
            if self._client.token:
                import hashlib as _hl
                caller_key = _hl.sha256(self._client.token.encode()).hexdigest()[:12]
        except Exception:
            pass
        ws_name = f"mem0-{caller_key}-user-{user_id or 'none'}-agent-{agent_id or 'none'}"
        # Truncate to avoid overly long names
        ws_name = ws_name[:80]
        # Try to find existing workspace
        workspaces = self._client.list_workspaces()
        for ws in workspaces:
            if ws.get("name") == ws_name:
                return ws["id"]
        # Create new workspace
        result = self._client.create_workspace(ws_name)
        if result.get("status") != "ok":
            # Fallback: get the workspace again (may have been created by another call)
            workspaces = self._client.list_workspaces()
            for ws in workspaces:
                if ws.get("name") == ws_name:
                    return ws["id"]
            raise RuntimeError(f"Failed to create workspace: {result}")
        workspaces = self._client.list_workspaces()
        for ws in workspaces:
            if ws.get("name") == ws_name:
                return ws["id"]
        raise RuntimeError("Workspace created but not found")

    def add(
        self,
        messages: str | list[dict[str, str]],
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Store a memory or list of messages.

        Args:
            messages: A single text string, or a list of message dicts
                (``[{"role": "user", "content": "..."}]``).
                When a list is provided, attempts LLM fact extraction to
                store individual memories (real Mem0 behavior), falling
                back to concatenation if no LLM is available.
            user_id: User identifier.
            agent_id: Agent identifier.
            run_id: Run/thread identifier.
            metadata: Optional metadata dict.

        Returns:
            List of stored memory dicts in Mem0 format.
        """
        ws_id = self._workspace_for(user_id, agent_id)

        # If messages is a conversation list, try LLM fact extraction (Mem0 behavior)
        if isinstance(messages, list):
            conversation = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in messages if m.get('content')
            )
            # Try LLM extraction
            extracted = None
            try:
                from spacetime_memory.llm import LLMClient
                llm = LLMClient()
                if llm.available:
                    extracted = llm.extract_facts(conversation)
            except Exception:
                pass

            if extracted and len(extracted) > 0:
                results = []
                for fact in extracted:
                    results.extend(self.add(
                        fact, user_id=user_id, agent_id=agent_id,
                        run_id=run_id, metadata=metadata,
                    ))
                return results

            # Fallback: concatenate message contents
            texts = [conversation]
        else:
            texts = [messages]

        results = []
        for text in texts:
            mem_result = self._client.store(
                workspace_id=ws_id,
                content=text,
                memory_type="experience",
                entities_json=json.dumps(metadata) if metadata else "{}",
                peer_id=agent_id or "",
                source_session_id=run_id or "",
            )
            if mem_result.get("status") == "ok":
                # Set user_scope if provided
                if user_id:
                    mems_before = self._client._sql(
                        "SELECT id FROM memory WHERE "
                        f"workspace_id = '{_esc(ws_id)}' AND "
                        f"content = '{_esc(text[:200])}' "
                    )
                    if mems_before:
                        latest = mems_before[-1]
                        self._client._call("set_memory_scope", [latest["id"], user_id])
                # Read back the stored memory
                mems = self._client._sql(
                    "SELECT * FROM memory WHERE "
                    f"workspace_id = '{_esc(ws_id)}' AND "
                    f"content = '{_esc(text[:200])}' "
                )
                mems.sort(key=lambda r: r.get("created_at", 0), reverse=True)
                if mems:
                    results.append(_to_mem0_memory(mems[0]))
                else:
                    results.append({"id": "", "memory": text, "status": "stored"})
            else:
                results.append({"id": "", "memory": text, "status": "error"})

        return results

    def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
        threshold: float = 0.0,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search memories.

        Args:
            query: Search text.
            user_id: Filter by user.
            agent_id: Filter by agent.
            limit: Max results.
            threshold: Minimum relevance score (0.0 = no filter).
            **kwargs: Additional Mem0 parameters (ignored).

        Returns:
            List of matching memory dicts with ``score``.
        """
        ws_id = self._workspace_for(user_id, agent_id)
        results = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=limit,
            semantic=True,
        )
        # Filter by threshold
        if threshold > 0.0:
            results = [r for r in results if r.get("score", 0.0) >= threshold]
        return [_to_mem0_memory(r, score=r.get("score")) for r in results]

    def get(self, memory_id: str) -> dict[str, Any] | None:
        """Get a specific memory by ID."""
        rows = self._client._sql(f"SELECT * FROM memory WHERE id = '{_esc(memory_id)}'")
        if not rows:
            return None
        return _to_mem0_memory(rows[0])

    def get_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get all memories for a user/agent pair."""
        ws_id = self._workspace_for(user_id, agent_id)
        rows = self._client._sql(
            "SELECT * FROM memory WHERE "
            f"workspace_id = '{_esc(ws_id)}' AND "
            "is_active = true"
        )
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return [_to_mem0_memory(r) for r in rows[:limit]]

    def update(self, memory_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a memory."""
        content = data.get("memory", data.get("content", ""))
        return self._client.update_memory(
            memory_id,
            content=content,
        )

    def delete(self, memory_id: str) -> dict[str, Any]:
        """Delete a memory by ID."""
        return self._client.delete_memory(memory_id)

    def delete_all(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete all memories for a user/agent pair.

        Note: Mem0 removes all memories permanently. We deactivate them.
        """
        ws_id = self._workspace_for(user_id, agent_id)
        mems = self._client._sql(
            "SELECT id FROM memory WHERE "
            f"workspace_id = '{_esc(ws_id)}' AND is_active = true"
        )
        count = 0
        for mem in mems:
            try:
                self._client.delete_memory(mem["id"])
                count += 1
            except RuntimeError:
                pass
        return {"status": "ok", "deleted_count": count}

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory.

        Returns list of memory snapshots (previous versions).
        Returns empty list if version tracking isn't enabled in the module.
        """
        try:
            rows = self._client._sql(
                f"SELECT * FROM memory_version WHERE memory_id = '{_esc(memory_id)}'"
            )
            rows.sort(key=lambda r: r.get("version", 0), reverse=True)
            return [_to_mem0_memory(r) for r in rows]
        except RuntimeError:
            return []

    # ── Entity store (Mem0 graph API) ──────────────────────────────────

    @property
    def graph(self) -> GraphStore:
        """Mem0-compatible graph / entity store.

        Real Mem0 stores entities in a vector collection. We back it with
        SpacetimeDB's ``entity_link`` table with alias support.

        Usage::

            >>> m = Memory()
            >>> m.graph.add("Alice", entity_type="person", user_id="alice")
            >>> results = m.graph.search("Alice", user_id="alice")
        """
        if not hasattr(self, "_graph_store"):
            self._graph_store = GraphStore(self)
        return self._graph_store


class GraphStore:
    """Mem0-compatible entity store backed by entity_link table."""

    def __init__(self, memory: Memory) -> None:
        self._mem = memory

    def _ws(self, user_id: str | None = None) -> str:
        return self._mem._workspace_for(user_id, None)

    def _tag(self, user_id: str | None = None) -> str:
        return f"mem0_user:{user_id}" if user_id else "mem0_global"

    def add(
        self,
        label: str,
        entity_type: str = "concept",
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add an entity to the store.

        Deduplicates by label — if an entity with the same label exists
        in the same user scope, creates an alias instead of a duplicate.
        """
        ws_id = self._ws(user_id)
        tag = self._tag(user_id)

        # Check for existing entity with same label (fuzzy via entity_link)
        existing = self.search(label, user_id=user_id, limit=1)
        if existing and existing[0].get("label", "").lower() == label.lower():
            return {"id": existing[0]["id"], "label": label, "status": "exists"}

        meta = json.dumps({"tag": tag, **(metadata or {})})
        result = self._mem._client._call(
            "create_entity_link",
            [ws_id, label, entity_type, meta],
        )
        rid = result.get("entity_id", result.get("id", ""))
        return {"id": rid, "label": label, "entity_type": entity_type, "status": "created"}

    def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search entities by label."""
        ws_id = self._ws(user_id)
        tag = self._tag(user_id)

        # Use SDK's semantic search via hybrid_search with entity_type filter
        try:
            results = self._mem._client.search(
                workspace_id=ws_id, query=query, limit=limit, semantic=True,
            )
            # Filter to kg_node results matching our tag
            tag_str = f'"tag": "{tag}"'
            entities = []
            for r in results:
                meta = r.get("metadata_json", "")
                if tag_str in meta or r.get("entity_type") == "node":
                    entities.append({
                        "id": r.get("entity_id", ""),
                        "label": r.get("content", "")[:100],
                        "entity_type": "concept",
                        "score": r.get("score", 0.0),
                        "metadata": _safe_json(r.get("metadata_json", "{}")),
                    })
            return entities[:limit]
        except Exception:
            return []

    def get_all(
        self,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get all entities for a user scope."""
        ws_id = self._ws(user_id)
        tag = self._tag(user_id)
        tag_str = f'"tag": "{tag}"'

        try:
            # Query entity_link table — may be private, try reducer first
            results = self._mem._client.search(
                workspace_id=ws_id, query="", limit=limit, semantic=False,
            )
            entities = []
            seen: set[str] = set()
            for r in results:
                eid = r.get("entity_id", "")
                if eid in seen:
                    continue
                seen.add(eid)
                entities.append({
                    "id": eid,
                    "label": r.get("content", "")[:100],
                    "entity_type": "concept",
                })
            return entities[:limit]
        except Exception:
            return []

    def delete(self, entity_id: str) -> dict[str, Any]:
        """Delete an entity by ID."""
        try:
            self._mem._client._call("delete_entity_link", [entity_id])
            return {"status": "deleted", "id": entity_id}
        except Exception:
            return {"status": "error", "id": entity_id}


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}


def _esc(val: str) -> str:
    """Basic SQL string escaping."""
    return val.replace("'", "''")
