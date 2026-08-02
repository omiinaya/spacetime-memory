"""
Spacetime-Memory Client
=======================

Async client implementing the SAME interface as Mem0Client (add / search /
delete_user) but backed by the Spacetime-Memory engine (our mem0-compatible
adapter on SpacetimeDB). This lets the OFFICIAL Mem0 benchmark harness run
completely unchanged — same ingest chunking, same prompts, same judge, same
metrics — with Spacetime-Memory as the memory backend. The only thing that
differs is which engine answers `add`/`search`.

Usage:
    python -m benchmarks.locomo.run \
        --project-name stmem-v2 \
        --backend stmem \
        --stmem-db spacetime-memory-v2 \
        --stmem-host 127.0.0.1 --stmem-port 3001
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class StmemClient:
    """Async wrapper around the Spacetime-Memory SDK exposing Mem0's interface.

    The benchmark harness calls:
      add(messages, user_id, timestamp=None)  -> dict with "results" key
      search(query, user_id, top_k=200)       -> list[dict] sorted by score
      delete_user(user_id)                    -> bool

    We map those onto the Spacetime-Memory client. The adapter stores each
    conversation chunk as a memory (memory_type=experience) scoped to a
    per-user workspace, so search is workspace-scoped and per-user isolated.
    """

    def __init__(
        self,
        db: str = "spacetime-memory-v2",
        host: str = "127.0.0.1",
        port: int = 3001,
        embedder_url: str | None = None,
        tantivy_url: str | None = None,
        max_retries: int = 5,
        retry_delay: float = 5.0,
        rpm: int = 60,
        timeout: float = 300.0,
        **_: Any,
    ):
        self.db = db
        self.host = host
        self.port = port
        self.embedder_url = embedder_url or os.getenv(
            "STDB_EMBEDDER_URL", "http://127.0.0.1:9093/v1"
        )
        self.tantivy_url = tantivy_url or os.getenv("STDB_TANTIVY_URL", "http://127.0.0.1:9091")
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.rpm = rpm
        self.timeout = timeout
        self._client = None
        self._lock = asyncio.Lock()
        self._ws_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Lazy client init (imports SDK on first use so the harness can still
    # run --evaluate-only without our SDK installed).
    # ------------------------------------------------------------------
    async def _get_client(self):
        async with self._lock:
            if self._client is None:
                from spacetime_memory import Client

                self._client = Client(
                    host=self.host,
                    port=self.port,
                    database=self.db,
                    embedder_url=self.embedder_url,
                    tantivy_url=self.tantivy_url,
                    verbose=False,
                )
                # Register/login so the identity is a real account (first user
                # becomes admin; subsequent runs reuse the same account).
                try:
                    self._client.register(
                        username="benchmark-runner",
                        password="benchmark-pass-123",
                        display_name="Benchmark Runner",
                    )
                except Exception:
                    try:
                        self._client.login(username="benchmark-runner", password="benchmark-pass-123")
                    except Exception:
                        pass
        return self._client

    def _ws_id(self, user_id: str) -> str:
        """Deterministic workspace id per user (hash of user_id)."""
        if user_id in self._ws_cache:
            return self._ws_cache[user_id]
        import hashlib

        digest = hashlib.sha256(user_id.encode()).hexdigest()[:32]
        ws = f"bench-{digest}"
        self._ws_cache[user_id] = ws
        return ws

    async def _ensure_workspace(self, client, ws: str) -> None:
        """Create the per-user workspace if it does not exist yet.

        Workspaces are created PUBLIC: the benchmark harness runs with
        ephemeral identities (a fresh anonymous identity per process), and a
        private workspace would only be searchable by the identity that
        created it. LOCOMO data is synthetic benchmark content, so public
        visibility is correct — any authenticated caller can search.
        """
        try:
            rows = client._query("workspace", "", {"id": ws}, ["id"])
            if not rows:
                client._call("create_workspace", [f"Benchmark {ws[:8]}", "created by benchmark runner", ws])
                try:
                    client._call("set_workspace_visibility", [ws, True])
                except Exception:
                    # Visibility flip is best-effort; creation is the critical part.
                    pass
        except Exception:
            # Race with parallel workers — creation is idempotent-ish; swallow.
            pass

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------
    async def add(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        observation_date: str | None = None,
        timestamp: int | None = None,
        custom_instructions: str | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        """Store a conversation chunk as one memory. Returns {'results': [...]}."""
        client = await self._get_client()
        ws = self._ws_id(user_id)
        await self._ensure_workspace(client, ws)

        content = "\n".join(f"[{m.get('role', '')}] {m.get('content', '')}" for m in messages)

        for attempt in range(self.max_retries):
            try:
                result = client.store(
                    workspace_id=ws,
                    content=content,
                    memory_type="experience",
                    source_session_id=str(timestamp or ""),
                )
                return {
                    "results": [
                        {
                            "memory": content,
                            "event": "ADD",
                            "id": result.get("id", ""),
                            "created_at": int(time.time()),
                        }
                    ]
                }
            except Exception as exc:
                logger.warning(
                    "ADD attempt %d/%d failed (user=%s): %s",
                    attempt + 1, self.max_retries, user_id, str(exc)[:200],
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("ADD failed after %d attempts for user=%s", self.max_retries, user_id)
                    return None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int = 200,
        rerank: bool = False,
        score_debug: bool = False,
    ) -> list[dict]:
        """Search memories. Returns list sorted by score descending."""
        client = await self._get_client()
        ws = self._ws_id(user_id)

        for attempt in range(self.max_retries):
            try:
                results = client.search(
                    workspace_id=ws,
                    query=query,
                    limit=top_k,
                    semantic=True,
                    cross_encoder=False,
                )
                normalised = []
                for r in results if isinstance(results, list) else []:
                    score = r.get("score", 0)
                    memory = r.get("content", r.get("memory", ""))
                    normalised.append({
                        "memory": memory,
                        "score": score if isinstance(score, (int, float)) else 0.0,
                        "id": r.get("id", ""),
                        "created_at": r.get("created_at"),
                    })
                normalised.sort(key=lambda x: x.get("score", 0), reverse=True)
                return normalised[:top_k]
            except Exception as exc:
                logger.warning(
                    "SEARCH attempt %d/%d failed (user=%s): %s",
                    attempt + 1, self.max_retries, user_id, str(exc)[:200],
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("SEARCH failed after %d attempts for user=%s", self.max_retries, user_id)
                    return []

    # ------------------------------------------------------------------
    # Delete user
    # ------------------------------------------------------------------
    async def delete_user(self, user_id: str) -> bool:
        """Delete all memories for a user (delete their workspace memories)."""
        client = await self._get_client()
        ws = self._ws_id(user_id)
        await self._ensure_workspace(client, ws)
        try:
            rows = client._query("memory", ws, {}, ["id"])
            for row in rows:
                try:
                    client._call("delete_memory", [row["id"]])
                except Exception:
                    pass
            return True
        except Exception as exc:
            logger.warning("DELETE_USER failed (user=%s): %s", user_id, str(exc)[:200])
            return False

    async def get_user_profile(self, user_id: str) -> dict | None:
        """Optional hook used by the harness with --user-profile. Returns None."""
        return None

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "StmemClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
