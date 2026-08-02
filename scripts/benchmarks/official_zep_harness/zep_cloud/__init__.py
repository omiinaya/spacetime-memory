"""
zep_cloud shim backed by the Spacetime-Memory Zep adapter.

The official Zep LOCOMO harness imports ``from zep_cloud.client import AsyncZep``
and drives the graph API (create / set_ontology / add / search). This module
provides a drop-in ``zep_cloud`` package that maps those calls onto the
Spacetime-Memory engine, so the UNCHANGED Zep harness runs against our memory
stack. graph_id is mapped to a Spacetime-Memory workspace.

Install in the harness venv:
    pip install -e /path/to/zep/benchmarks/locomo  (or add this dir to PYTHONPATH)

Usage (unchanged harness):
    ZEP_API_KEY=dummy python -m benchmarks.locomo.benchmark ingest ...
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


class _GraphShim:
    """Async graph namespace compatible with zep_cloud.AsyncZep.graph."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine  # spacetime_memory Client wrapper

    async def create(self, graph_id: str, name: str = "", description: str = "", **_: Any) -> dict[str, Any]:
        """Create a graph → Spacetime-Memory workspace. Idempotent."""
        return await asyncio.to_thread(self._engine.ensure_graph, graph_id, name, description)

    async def set_ontology(self, entities: Any = None, edges: Any = None, graph_ids: list[str] | None = None, **_: Any) -> dict[str, Any]:
        """Set ontology — our engine infers schema; no-op that returns ok."""
        return {"status": "ok"}

    async def add(self, graph_id: str, type: str = "text", data: str = "", created_at: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Add an episode/message to the graph → store a memory."""
        return await asyncio.to_thread(
            self._engine.graph_add, graph_id, type, data, created_at, **kwargs,
        )

    async def search(
        self,
        query: str,
        graph_id: str,
        scope: str = "messages",
        reranker: str = "cross_encoder",
        limit: int = 15,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Graph search → hybrid semantic search over the workspace."""
        return await asyncio.to_thread(
            self._engine.graph_search, query, graph_id, scope=scope, limit=limit, **kwargs,
        )

    async def add_episode(self, graph_id: str, data: str, created_at: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return await self.add(graph_id, type="episode", data=data, created_at=created_at, **kwargs)

    async def get_episodes(self, graph_id: str, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._engine.list_episodes, graph_id, limit)

    async def delete_episode(self, graph_id: str, episode_id: str, **_: Any) -> dict[str, Any]:
        return {"status": "ok", "id": episode_id}


class AsyncZep:
    """Drop-in AsyncZep backed by Spacetime-Memory.

    Mirrors the zep_cloud async client surface the LOCOMO harness touches:
    ``zep.graph.create/set_ontology/add/search`` (+ episode helpers).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        host: str | None = None,
        port: int | None = None,
        **_: Any,
    ) -> None:
        # Import lazily so the harness can run --help without our SDK.
        from spacetime_memory.sdks.zep import AsyncZep as StmemAsyncZep

        self._api_key = api_key or os.getenv("ZEP_API_KEY", "dummy")
        host = host or os.getenv("STDB_HOST", "127.0.0.1")
        port = int(port or os.getenv("STDB_PORT", "3001"))
        db = os.getenv("STDB_DB", "spacetime-memory-v2")
        self._stmem = StmemAsyncZep(host=host, port=port, config={"db": db})
        # Register/login the identity so reducer calls authenticate.
        try:
            self._stmem._sync._client.register(
                username="zep-benchmark-runner",
                password="benchmark-pass-123",
                display_name="Zep Benchmark Runner",
            )
        except Exception:
            try:
                self._stmem._sync._client.login(
                    username="zep-benchmark-runner", password="benchmark-pass-123",
                )
            except Exception:
                pass
        self.graph = _GraphShim(_EngineAdapter(self._stmem))

    async def __aenter__(self) -> "AsyncZep":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        pass


class _EngineAdapter:
    """Maps harness graph calls onto the Spacetime-Memory Zep adapter."""

    def __init__(self, stmem: Any) -> None:
        self._stmem = stmem
        # The Zep wrapper wraps the raw SDK Client at ._sync._client
        self._raw = stmem._sync._client

    def _ws(self, graph_id: str) -> str:
        """Map graph_id → workspace id (graph ids are already namespaced)."""
        return f"zep-{graph_id}"

    def ensure_graph(self, graph_id: str, name: str, description: str) -> dict[str, Any]:
        ws = self._ws(graph_id)
        try:
            self._raw._call("create_workspace", [name or f"Zep graph {graph_id}", description, ws])
            return {"status": "ok", "id": graph_id}
        except Exception:
            return {"status": "ok", "id": graph_id}  # already exists

    def graph_add(self, graph_id: str, type: str, data: str, created_at: str | None, **kwargs: Any) -> dict[str, Any]:
        ws = self._ws(graph_id)
        self.ensure_graph(graph_id, f"Zep graph {graph_id}", "")
        # Use the SDK's store() so the memory is embedded + indexed for
        # semantic search (calling the reducer directly skips indexing).
        result = self._raw.store(
            workspace_id=ws,
            content=data,
            memory_type="experience",
            source_session_id=created_at or "",
        )
        return {"status": "ok", "id": result.get("id", "")}

    def graph_search(self, query: str, graph_id: str, scope: str = "messages", limit: int = 15, **kwargs: Any) -> dict[str, Any]:
        ws = self._ws(graph_id)
        results = self._raw.search(workspace_id=ws, query=query, limit=limit, semantic=True, cross_encoder=False)
        edges = []
        for r in results if isinstance(results, list) else []:
            edges.append({
                "edge_uuid": r.get("id", ""),
                "fact": r.get("content", r.get("memory", "")),
                "valid_at": r.get("created_at"),
                "score": r.get("score", 0),
                "metadata": {},
            })
        return {"edges": edges}

    def list_episodes(self, graph_id: str, limit: int = 100) -> list[dict[str, Any]]:
        ws = self._ws(graph_id)
        try:
            rows = self._raw._query("memory", ws, {}, ["id", "content", "created_at"])
        except Exception:
            return []
        return [
            {"uuid": r.get("id", ""), "content": r.get("content", ""), "created_at": r.get("created_at")}
            for r in rows[:limit]
        ]


# Also expose MemoryMessage-like helper types the harness may import.
class EntityEdge:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class EntityNode:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
