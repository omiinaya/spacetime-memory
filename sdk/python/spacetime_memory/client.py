"""Python client for spacetime-memory.

Provides a high-level Client class that wraps the SpacetimeDB HTTP SQL API,
the reducer-call endpoint, and embedder support (Rust ONNX sidecar + OpenAI
API fallback).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message mapping (human-readable)
# ---------------------------------------------------------------------------

_SQL_ERROR_MAP: dict[str, str] = {
    "table.*does not exist": "Table not found. Check that the module is published.",
    "column.*does not exist": "Column not found. Check the field name.",
    "duplicate key value": "Duplicate record. A record with this ID already exists.",
    "violates foreign key": "Referenced record not found. Check that the related record exists.",
    "syntax error": "SQL syntax error. Check your query syntax.",
    "permission denied": "Permission denied. You may not have access to this resource.",
}

_REDUCER_ERROR_MAP: dict[str, str] = {
    "not found": "Record not found. Check the ID.",
    "unauthorized": "Authentication required. Please login first.",
    "already exists": "Record already exists with this identifier.",
    "validation error": "Invalid input. Check the format of your data.",
    "rate limit": "Too many requests. Please wait before trying again.",
}


class EmbedderUnavailableError(ConnectionError):
    """Raised when the embedding sidecar is unreachable and no fallback is configured."""

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Client:
    """Spacetime-Memory client.

    Minimal config — point at a running SpacetimeDB instance + embedder.
    All methods return parsed dicts: {"status": "ok"} for writes, or
    list[dict] / dict for reads.

    Embedder type can be one of:

    - ``"local"`` — use the Rust ONNX sidecar (default behaviour)
    - ``"openai"`` — use OpenAI's embeddings API
    - ``"auto"`` — try the sidecar first, fall back to OpenAI if unavailable

    When using ``"openai"`` or ``"auto"`` fallback, set ``OPENAI_API_KEY``
    environment variable.

    Example::

        client = Client()
        ws_id = client.create_workspace("test")["id"]
        client.store(ws_id, "I like pizza", memory_type="experience")
        results = client.search(ws_id, "food preferences", semantic=True)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        embedder_url: str | None = None,
        embedder_type: str | None = None,
        timeout: float = 30.0,
        verbose: bool = False,
        token: str | None = None,
    ):
        self.host = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
        self.port = str(port or os.environ.get("SPACETIMEDB_PORT", "3001"))
        self.database = database or os.environ.get(
            "SPACETIMEDB_DB", "c200e409f602c06527d0aa66dc2d05718a6b62c4c3317b5498951cea41782713"
        )
        self.embedder_url = (
            embedder_url
            or os.environ.get("EMBEDDER_URL", "http://localhost:9090")
        )
        self.embedder_type = (
            embedder_type
            or os.environ.get("EMBEDDER_TYPE", "auto")
        )
        self.verbose = verbose
        self.token = token or os.environ.get("SPACETIMEDB_TOKEN")

        base = f"http://{self.host}:{self.port}"
        self.sql_url = f"{base}/v1/database/{self.database}/sql"
        self.reducer_url = f"{base}/v1/database/{self.database}/call"
        self._http = httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        """Return common HTTP headers, including auth if a token is set."""
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @classmethod
    def from_token_file(
        cls,
        token_path: str,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        **kwargs: Any,
    ) -> "Client":
        """Create a Client using a JWT token stored in a file.

        The token file can be created with:
            python -c "from spacetime_memory.auth import generate_token; \\
                print(generate_token('data/id_ecdsa_pkcs8.pem'))" > /path/to/token.jwt
        """
        token = Path(token_path).read_text().strip()
        return cls(host=host, port=port, database=database, token=token, **kwargs)

    # -----------------------------------------------------------------------
    # HTTP helpers
    # -----------------------------------------------------------------------

    def _sql(self, query: str) -> list[dict[str, Any]]:
        """Run a SELECT query against the SpacetimeDB SQL API."""
        headers = {"Content-Type": "text/plain"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = self._http.post(
            self.sql_url,
            content=query,
            headers=headers,
        )
        if resp.status_code >= 400:
            error_text = resp.text[:500]
            if self.verbose:
                raise RuntimeError(
                    f"SQL error (HTTP {resp.status_code}): {error_text}"
                )
            friendly = self._map_sql_error(error_text)
            raise RuntimeError(friendly)
        return _parse_sql_response(resp.text)

    def _map_sql_error(self, error_text: str) -> str:
        """Map raw SQL error text to a human-friendly message."""
        for pattern, message in _SQL_ERROR_MAP.items():
            if re.search(pattern, error_text, re.IGNORECASE):
                return f"{message} (raw: {error_text[:200]})"
        return f"Database error: {error_text[:300]}"

    def _map_reducer_error(self, error_text: str) -> str:
        """Map raw reducer error text to a human-friendly message."""
        for pattern, message in _REDUCER_ERROR_MAP.items():
            if re.search(pattern, error_text, re.IGNORECASE):
                return f"{message} (raw: {error_text[:200]})"
        return f"Reducer error: {error_text[:300]}"

    def _call(self, reducer: str, args: list[Any]) -> dict[str, Any]:
        """Call a SpacetimeDB reducer with positional JSON args."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = self._http.post(
            f"{self.reducer_url}/{reducer}",
            content=json.dumps(args),
            headers=headers,
        )
        if resp.status_code >= 400:
            error_text = resp.text[:500]
            if self.verbose:
                raise RuntimeError(
                    f"Reducer error (HTTP {resp.status_code}): {error_text}"
                )
            friendly = self._map_reducer_error(error_text)
            raise RuntimeError(friendly)
        return {"status": "ok"}

    def _embed(self, text: str) -> list[float]:
        """Get an embedding vector.

        Behaviour depends on ``embedder_type``:
        - ``"local"``: use the Rust ONNX sidecar (raises on failure)
        - ``"openai"``: call OpenAI embeddings API
        - ``"auto"``: try sidecar first, fall back to OpenAI. If both fail,
          raises ``EmbedderUnavailableError`` with a combined message.
        """
        if self.embedder_type == "openai":
            return self._embed_openai(text)
        if self.embedder_type == "local":
            return self._embed_local(text)

        # "auto" — try local, fall back to OpenAI
        try:
            return self._embed_local(text)
        except EmbedderUnavailableError:
            logger.info("Local embedder unavailable, falling back to OpenAI")
            result = self._embed_openai(text)
            if result:
                return result
            raise EmbedderUnavailableError(
                "Embedder unavailable (local sidecar down, OpenAI fallback also failed). "
                "Check EMBEDDER_URL and OPENAI_API_KEY."
            )

    def _embed_local(self, text: str) -> list[float]:
        """Get an embedding vector via the Rust ONNX sidecar."""
        try:
            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            if resp.status_code >= 400:
                raise EmbedderUnavailableError(
                    f"Embedder returned HTTP {resp.status_code} for text (len={len(text)})"
                )
            return resp.json().get("embedding", [])
        except httpx.TimeoutException:
            raise EmbedderUnavailableError(f"Embedder timed out for text (len={len(text)})")
        except httpx.ConnectError:
            raise EmbedderUnavailableError(
                f"Embedder connection refused at {self.embedder_url}. Is the sidecar running?"
            )
        except Exception:
            logger.exception("Unexpected error in _embed for text (len=%d)", len(text))
            raise

    def _embed_openai(self, text: str) -> list[float]:
        """Embed via OpenAI API."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, cannot use OpenAI embedder fallback")
            return []
        try:
            resp = self._http.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": text, "model": "text-embedding-ada-002"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
        except httpx.TimeoutException:
            logger.warning("OpenAI embedder timed out for text (len=%d)", len(text))
            return []
        except Exception:
            logger.exception("OpenAI embedder failed for text (len=%d)", len(text))
            return []

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts.

        Behaviour follows ``embedder_type`` — see :meth:`_embed`.
        """
        if not texts:
            return []
        if self.embedder_type == "openai":
            return self._embed_batch_openai(texts)
        if self.embedder_type == "local":
            return self._embed_batch_local(texts)

        # "auto" — try local, fall back to OpenAI
        result = self._embed_batch_local(texts)
        if result:
            return result
        logger.info("Local embedder unavailable for batch, falling back to OpenAI")
        return self._embed_batch_openai(texts)

    def _embed_batch_local(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts via the Rust ONNX sidecar."""
        if not texts:
            return []
        try:
            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"text": "", "texts": texts}),
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Embedder returned HTTP %d for batch (count=%d): %s",
                    resp.status_code, len(texts), resp.text[:200],
                )
                return []
            return resp.json().get("embeddings", [])
        except httpx.TimeoutException:
            logger.warning("Embedder timed out for batch (count=%d)", len(texts))
            return []
        except httpx.ConnectError:
            logger.warning("Embedder connection refused for batch (count=%d) — is the sidecar running?", len(texts))
            return []
        except Exception:
            logger.exception("Unexpected error in _embed_batch (count=%d)", len(texts))
            return []

    def _embed_batch_openai(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts via OpenAI API."""
        if not texts:
            return []
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, cannot use OpenAI embedder fallback")
            return []
        try:
            resp = self._http.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": texts, "model": "text-embedding-ada-002"},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            # OpenAI returns data in order matching input
            results = [item["embedding"] for item in data["data"]]
            return results
        except httpx.TimeoutException:
            logger.warning("OpenAI embedder timed out for batch (count=%d)", len(texts))
            return []
        except Exception:
            logger.exception("OpenAI embedder failed for batch (count=%d)", len(texts))
            return []

    def check_embedder_health(self) -> dict[str, Any]:
        """Check if the embedder sidecar is running. Returns status info."""
        try:
            resp = self._http.get(f"{self.embedder_url}/health", timeout=5.0)
            if resp.status_code == 200:
                embedder_status = resp.json()
                embedder_status["reachable"] = True
                return embedder_status
            return {"status": "error", "code": resp.status_code, "reachable": True}
        except Exception as e:
            return {"status": "error", "message": str(e), "reachable": False}

    def ping(self) -> dict[str, Any]:
        """Quick connectivity check against SpacetimeDB.

        Hits the database info endpoint and reports latency.
        """
        import time
        start = time.monotonic()
        try:
            resp = self._http.get(
                f"http://{self.host}:{self.port}/v1/database/{self.database}",
                headers=self._headers(),
                timeout=5.0,
            )
            elapsed = time.monotonic() - start
            if resp.status_code < 400:
                return {"status": "ok", "latency_ms": round(elapsed * 1000, 1)}
            return {
                "status": "error",
                "message": f"HTTP {resp.status_code}",
                "latency_ms": round(elapsed * 1000, 1),
            }
        except Exception as e:
            elapsed = time.monotonic() - start
            return {"status": "error", "message": str(e), "latency_ms": round(elapsed * 1000, 1)}

    def health(self) -> dict[str, Any]:
        """Comprehensive health check: SpacetimeDB + embedder.

        Returns a dict with status for each component.
        """
        db_check = self.ping()
        emb_check = self.check_embedder_health()

        all_ok = db_check.get("status") == "ok" and emb_check.get("reachable", False)

        return {
            "status": "ok" if all_ok else "degraded",
            "database": db_check,
            "embedder": emb_check,
            "token_configured": bool(self.token),
        }

    # -----------------------------------------------------------------------
    # Workspace
    # -----------------------------------------------------------------------

    def create_workspace(self, name: str, description: str = "", id: str | None = None) -> dict[str, Any]:
        """Create a new workspace. Returns reducer status.
        If *id* is omitted, generates a UUID client-side matching the reducer's
        UUID v4 format so callers can discover it immediately via list_workspaces.
        """
        import uuid
        ws_id = id if id else uuid.uuid4().hex[:32]
        return self._call("create_workspace", [name, description, ws_id])

    def list_workspaces(self) -> list[dict[str, Any]]:
        """List all workspaces."""
        return self._sql("SELECT * FROM workspace")

    # -----------------------------------------------------------------------
    # Memory
    # -----------------------------------------------------------------------

    @dataclass
    class MemoryRecord:
        id: str
        workspace_id: str
        peer_id: str
        observer_id: str
        memory_type: str
        content: str
        summary: str
        entities_json: str
        confidence: float
        is_active: bool
        created_at: int
        expires_at: int
        updated_at: int
        tier: str
        access_count: int
        strength: float
        version: int
        trust_score: float
        feedback_count: int
        consolidated_to: str

        @classmethod
        def from_dict(cls, d: dict) -> "Client.MemoryRecord":
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def store(
        self,
        workspace_id: str,
        content: str = "",
        summary: str = "",
        memory_type: str = "experience",
        peer_id: str = "",
        observer_id: str = "",
        entities_json: str = "[]",
        confidence: float = 0.8,
        source_session_id: str = "",
        source_message_id: str = "",
        tier: str = "",
    ) -> dict[str, Any]:
        """Store a memory. Auto-indexes via the embedder."""
        result = self._call("store_memory", [
            workspace_id, peer_id, observer_id,
            memory_type, content, summary, entities_json,
            confidence, source_session_id, source_message_id,
        ])

        # Auto-index
        emb = self._embed(content)
        if emb:
            mems = self._sql(
                "SELECT id FROM memory WHERE "
                f"workspace_id = '{_esc(workspace_id)}' AND "
                f"peer_id = '{_esc(peer_id)}' "
            )
            if mems:
                self._call("index_entity", [
                    workspace_id, "memory", mems[-1]["id"],
                    content, json.dumps(emb),
                ])

        if tier and tier in ("L0", "L1", "L2"):
            mems = self._sql(
                "SELECT id FROM memory WHERE "
                f"workspace_id = '{_esc(workspace_id)}' AND "
                f"peer_id = '{_esc(peer_id)}' "
            )
            if mems:
                self._call("update_memory_tier", [mems[-1]["id"], tier])

        return result

    def search(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        limit: int = 20,
        semantic: bool = True,
    ) -> list[dict[str, Any]]:
        """Search memories.  When *semantic* is True uses hybrid search."""
        if semantic:
            emb = self._embed(query)
            emb_json = json.dumps(emb) if emb else "[]"
            strategies = json.dumps(["semantic", "keyword", "graph", "temporal"])
            self._call("hybrid_search", [
                workspace_id, query, emb_json,
                memory_type, tier, limit, strategies,
            ])
            qhash = _query_hash(query)
            rows = self._sql(
                "SELECT * FROM hybrid_result "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"  AND query_hash = '{_esc(qhash)}' "
            )
            rows.sort(key=lambda r: r.get("score", 0.0), reverse=True)
            # Look up content from source tables in Python
            mem_ids = [r.get("entity_id", "") for r in rows if r.get("entity_type") == "memory"]
            node_ids = [r.get("entity_id", "") for r in rows if r.get("entity_type") == "node"]
            mem_map = {}
            node_map = {}
            for mid in mem_ids:
                mems = self._sql(f"SELECT id, content FROM memory WHERE id = '{_esc(mid)}'")
                if mems:
                    mem_map[mid] = mems[0].get("content", "")
            for nid in node_ids:
                nodes = self._sql(f"SELECT id, label FROM kg_node WHERE id = '{_esc(nid)}'")
                if nodes:
                    node_map[nid] = nodes[0].get("label", "")
            for r in rows:
                eid = r.get("entity_id", "")
                if r.get("entity_type") == "memory":
                    r["memory_content"] = mem_map.get(eid, "")
                elif r.get("entity_type") == "node":
                    r["memory_content"] = node_map.get(eid, "")
                else:
                    r["memory_content"] = ""
            return rows[:limit]

        # Non-semantic (keyword) fallback
        # SpacetimeDB SQL doesn't support LIKE, so we fetch all and filter client-side
        clauses = [f"workspace_id = '{_esc(workspace_id)}'"]
        if memory_type:
            clauses.append(f"memory_type = '{_esc(memory_type)}'")
        if tier:
            clauses.append(f"tier = '{_esc(tier)}'")
        where = " AND ".join(clauses)
        try:
            rows = self._sql(
                f"SELECT * FROM memory WHERE {where}"
            )
        except RuntimeError as e:
            if "unsupported" in str(e).lower() or "like" in str(e).lower():
                rows = self._sql(f"SELECT * FROM memory WHERE {clauses[0]}")
            else:
                raise

        # Client-side keyword filter (SpacetimeDB doesn't support LIKE)
        if query:
            q = query.lower()
            rows = [
                r for r in rows
                if q in r.get("content", "").lower()
                or q in r.get("summary", "").lower()
            ]

        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return rows[:limit]

    def get_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """Get a single memory by ID.  Auto-reinforces on read."""
        results = self._sql(
            f"SELECT * FROM memory WHERE id = '{_esc(memory_id)}'"
        )
        if results:
            try:
                self._call("reinforce_memory", [memory_id])
            except Exception:
                pass
        return results

    def update_memory(
        self, memory_id: str, content: str, summary: str = "", confidence: float = 0.8
    ) -> dict[str, Any]:
        """Update a memory's content/summary/confidence."""
        return self._call("update_memory", [memory_id, content, summary, confidence])

    def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Deactivate a memory. Idempotent — succeeds if already deleted."""
        try:
            return self._call("deactivate_memory", [memory_id])
        except RuntimeError as e:
            if "not found" in str(e).lower():
                return {"status": "ok", "note": "already deleted"}
            raise

    def reinforce(self, memory_id: str) -> dict[str, Any]:
        """Reinforce a memory (bump access_count + strength)."""
        return self._call("reinforce_memory", [memory_id])

    def rate_memory(
        self, memory_id: str, rating: str, peer_id: str
    ) -> dict[str, Any]:
        """Rate a memory to adjust its trust score.

        Args:
            memory_id: The memory to rate.
            rating: "helpful" (score 5), "unhelpful" (score 1),
                    or an integer string "1"–"5" for graded feedback.
            peer_id: The peer submitting the rating.
        """
        return self._call("rate_memory", [memory_id, rating, peer_id])

    def escalate_memories(self, workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20) -> dict[str, Any]:
        """Batch-escalate memory tiers based on access_count thresholds.

        Args:
            workspace_id: The workspace to escalate memories in.
            l2_to_l1: Access count threshold for L2→L1 escalation (default: 5).
            l1_to_l0: Access count threshold for L1→L0 escalation (default: 20).
        """
        return self._call("escalate_memories", [workspace_id, l2_to_l1, l1_to_l0])

    def list_memories(
        self, workspace_id: str, memory_type: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        """List active memories in a workspace."""
        clauses = [
            f"workspace_id = '{_esc(workspace_id)}'",
            "is_active = true",
        ]
        if memory_type:
            clauses.append(f"memory_type = '{_esc(memory_type)}'")
        where = " AND ".join(clauses)
        rows = self._sql(
            f"SELECT * FROM memory WHERE {where}"
        )
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return rows[:limit]

    def get_user_memories(
        self, user_scope: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        """Get all memories scoped to a specific user within a workspace.
        
        Calls the ``get_user_memories`` reducer which populates the
        ``user_memory_result`` table, then reads from it.
        
        Args:
            user_scope: The user identity hash to filter by.
            workspace_id: The workspace to search in.
        
        Returns:
            List of memory records scoped to the given user.
        """
        self._call("get_user_memories", [user_scope, workspace_id])
        rows = self._sql(
            "SELECT * FROM user_memory_result WHERE "
            f"user_scope = '{_esc(user_scope)}' AND "
            f"workspace_id = '{_esc(workspace_id)}' "
            "ORDER BY created_at DESC"
        )
        return rows

    # -----------------------------------------------------------------------
    # Directory (context directory tree)
    # -----------------------------------------------------------------------

    def list_directory(self, directory_id: str) -> list[dict[str, Any]]:
        """Get children of a directory."""
        self._call("get_children", [directory_id, True])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"query_hash = '{_esc(directory_id)}' "
            "ORDER BY depth ASC, name ASC"
        )

    def traverse_directory(self, workspace_id: str, root_directory_id: str) -> list[dict[str, Any]]:
        """Recursive BFS traversal of directory tree."""
        self._call("traverse_recursive", [workspace_id, root_directory_id])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"query_hash = '{_esc(root_directory_id)}' "
            "ORDER BY depth ASC, name ASC"
        )

    def get_directory(self, workspace_id: str, path_or_id: str) -> list[dict[str, Any]]:
        """Get a directory by ID or path."""
        self._call("get_directory", [workspace_id, path_or_id])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}' "
            "ORDER BY depth ASC"
        )

    def create_directory(self, workspace_id: str, name: str, path: str, parent_id: str = "", description: str = "") -> dict[str, Any]:
        """Create a directory in the context directory tree."""
        return self._call("create_directory", [workspace_id, name, path, parent_id, description])

    def link_memory_to_directory(self, directory_id: str, memory_id: str, workspace_id: str) -> dict[str, Any]:
        """Link a memory to a directory."""
        return self._call("link_memory_to_directory", [directory_id, memory_id, workspace_id])

    def unlink_memory_from_directory(self, directory_id: str, memory_id: str) -> dict[str, Any]:
        """Unlink a memory from a directory."""
        return self._call("unlink_memory_from_directory", [directory_id, memory_id])

    # -----------------------------------------------------------------------
    # Batch update & history (Mem0 parity)
    # -----------------------------------------------------------------------

    def batch_update_memories(self, workspace_id: str, memory_ids: list[str], updates: dict[str, Any]) -> dict[str, Any]:
        """Batch update multiple memories. Mem0 parity.
        updates can contain: content, summary, confidence, tier, is_active
        """
        return self._call("batch_update_memories", [
            workspace_id, json.dumps(memory_ids), json.dumps(updates)
        ])

    def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory. Mem0 parity."""
        return self._sql(
            "SELECT * FROM memory_version WHERE "
            f"memory_id = '{_esc(memory_id)}' "
            "ORDER BY version DESC"
        )

    # -----------------------------------------------------------------------
    # Search with metadata/location filters (Honcho parity)
    # -----------------------------------------------------------------------

    def search_with_filters(self, workspace_id: str, query: str = "",
                             memory_type: str = "",
                             tier: str = "",
                             metadata_filter: str = "",
                             location_filter: str = "",
                             limit: int = 20) -> list[dict[str, Any]]:
        """Search with metadata and location filters. Honcho parity."""
        # For metadata/location filters, we do a keyword search first then filter in Python
        rows = self.search(workspace_id, query, memory_type, tier, limit, semantic=True)
        if metadata_filter:
            import json
            mf = json.loads(metadata_filter) if isinstance(metadata_filter, str) else metadata_filter
            filtered = []
            for r in rows:
                meta_str = r.get("metadata_json", "{}")
                try:
                    meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                except Exception:
                    meta = {}
                matches = all(meta.get(k) == v for k, v in mf.items())
                if matches:
                    filtered.append(r)
            rows = filtered[:limit]
        if location_filter:
            loc = location_filter.lower()
            rows = [r for r in rows if loc in r.get("content", "").lower() or loc in r.get("summary", "").lower()][:limit]
        return rows

    # -----------------------------------------------------------------------
    # Knowledge Graph
    # -----------------------------------------------------------------------

    def create_node(
        self,
        workspace_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Create a knowledge-graph node and auto-index it."""
        result = self._call("create_node", [
            workspace_id, label, node_type, summary, metadata_json,
        ])
        content = f"{label}: {summary}" if summary else label
        emb = self._embed(content)
        if emb:
            nodes = self._sql(
                "SELECT id FROM kg_node WHERE "
                f"workspace_id = '{_esc(workspace_id)}' AND "
                f"label = '{_esc(label)}' "
            )
            if nodes:
                self._call("index_entity", [
                    workspace_id, "node", nodes[-1]["id"],
                    content, json.dumps(emb),
                ])
        return result

    def create_edge(
        self,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: str = "EXTRACTED",
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Create a directed, typed edge between two KG nodes."""
        return self._call("create_edge", [
            workspace_id, source_node_id, target_node_id,
            relation, weight, confidence, metadata_json,
        ])

    def query_graph(
        self, workspace_id: str, query: str = ""
    ) -> list[dict[str, Any]]:
        """Search KG nodes by label within a workspace."""
        rows = self._sql(
            "SELECT * FROM kg_node WHERE "
            f"workspace_id = '{_esc(workspace_id)}'"
        )
        if query:
            # Client-side filter (SpacetimeDB doesn't support LIKE)
            q = query.lower()
            rows = [
                r for r in rows
                if q in r.get("label", "").lower()
                or q in r.get("summary", "").lower()
            ]
        return rows

    def get_neighbors(self, node_id: str) -> list[dict[str, Any]]:
        """Get edges connected to a node."""
        edges = self._sql(
            f"SELECT * FROM kg_edge WHERE "
            f"source_node_id = '{_esc(node_id)}' "
            f"OR target_node_id = '{_esc(node_id)}' "
        )
        # Enrich with labels
        node_ids = set()
        for e in edges:
            node_ids.add(e.get("source_node_id", ""))
            node_ids.add(e.get("target_node_id", ""))
        node_ids.discard("")
        label_map = {}
        for nid in node_ids:
            rows = self._sql(f"SELECT id, label FROM kg_node WHERE id = '{_esc(nid)}'")
            if rows:
                label_map[nid] = rows[0].get("label", "")

        for e in edges:
            e["source_label"] = label_map.get(e.get("source_node_id", ""), "")
            e["target_label"] = label_map.get(e.get("target_node_id", ""), "")
        edges.sort(key=lambda r: r.get("weight", 0.0), reverse=True)
        return edges

    def detect_communities(self, workspace_id: str) -> dict[str, Any]:
        """Run label-propagation community detection."""
        return self._call("detect_communities", [workspace_id])

    def seed_communities(self, workspace_id: str) -> dict[str, Any]:
        """Seed unassigned nodes into new communities."""
        return self._call("seed_communities", [workspace_id])

    # -----------------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------------

    def run_maintenance(self) -> dict[str, Any]:
        """Trigger periodic maintenance (expire, decay, dedup)."""
        return self._call("manual_maintenance", [])

    def dedup(self, workspace_id: str) -> dict[str, Any]:
        """Run dedup within a workspace."""
        return self._call("dedup_memories", [workspace_id])

    # -----------------------------------------------------------------------
    # Merge suggestions
    # -----------------------------------------------------------------------

    def suggest_merges(self, workspace_id: str, threshold: float = 0.8) -> dict[str, Any]:
        """Scan active memories and record merge suggestions.

        Args:
            workspace_id: The workspace to scan.
            threshold: Minimum cosine similarity threshold (default: 0.8).

        Returns:
            Reducer status.
        """
        return self._call("suggest_merges", [workspace_id, threshold])

    def approve_merge(self, suggestion_id: str) -> dict[str, Any]:
        """Approve a pending merge suggestion.

        Deactivates the source memory into the target (survivor) memory.

        Args:
            suggestion_id: The ID of the MergeSuggestion row.

        Returns:
            Reducer status.
        """
        return self._call("approve_merge", [suggestion_id])

    def reject_merge(self, suggestion_id: str) -> dict[str, Any]:
        """Reject a pending merge suggestion without merging.

        Args:
            suggestion_id: The ID of the MergeSuggestion row.

        Returns:
            Reducer status.
        """
        return self._call("reject_merge", [suggestion_id])

    # -----------------------------------------------------------------------
    # Session
    # -----------------------------------------------------------------------

    def get_peer_sessions(self, peer_id: str) -> list[dict[str, Any]]:
        """List sessions a peer has participated in."""
        rows = self._sql(
            "SELECT s.*, sp.role, sp.joined_at "
            "FROM session s "
            "INNER JOIN session_participant sp ON s.id = sp.session_id "
            f"WHERE sp.peer_id = '{_esc(peer_id)}'"
        )
        rows.sort(key=lambda r: r.get("joined_at", 0), reverse=True)
        return rows

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve messages for a session."""
        rows = self._sql(
            "SELECT * FROM message WHERE "
            f"session_id = '{_esc(session_id)}'"
        )
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    # -----------------------------------------------------------------------
    # Profile
    # -----------------------------------------------------------------------

    def get_profile(self, peer_id: str) -> list[dict[str, Any]]:
        """Get a peer's profile."""
        return self._sql(
            f"SELECT * FROM profile WHERE peer_id = '{_esc(peer_id)}'"
        )

    def upsert_profile(
        self,
        peer_id: str,
        static_facts_json: str = "[]",
        dynamic_context_json: str = "[]",
        preferences_json: str = "{}",
        tags_json: str = "[]",
    ) -> dict[str, Any]:
        """Create or update a peer profile."""
        return self._call("upsert_profile", [
            peer_id, static_facts_json, dynamic_context_json,
            preferences_json, tags_json,
        ])

    # -----------------------------------------------------------------------
    # Knowledge Graph — additional queries
    # -----------------------------------------------------------------------

    def get_node(self, node_id: str) -> list[dict[str, Any]]:
        """Get a KG node by ID."""
        return self._sql(
            f"SELECT * FROM kg_node WHERE id = '{_esc(node_id)}'"
        )

    def get_community(self, community_id: int) -> dict[str, Any]:
        """Get community details and its nodes."""
        community = self._sql(
            f"SELECT * FROM kg_community WHERE id = {int(community_id)}"
        )
        nodes = self._sql(
            f"SELECT * FROM kg_node WHERE community_id = {int(community_id)}"
        )
        return {
            "community": community[0] if community else None,
            "nodes": nodes,
        }

    def compute_pagerank(self, workspace_id: str, damping: float = 0.85, max_iterations: int = 100) -> dict[str, Any]:
        """Compute PageRank centrality for all nodes in a workspace.

        Args:
            workspace_id: The workspace to compute PageRank for.
            damping: PageRank damping factor (default: 0.85).
            max_iterations: Maximum iterations (default: 100).

        Returns:
            Reducer status.
        """
        return self._call("compute_pagerank", [workspace_id, damping, max_iterations])

    def compute_community_hierarchy(self, workspace_id: str) -> dict[str, Any]:
        """Build hierarchical community dendrogram using agglomerative clustering.

        Args:
            workspace_id: The workspace to build hierarchy for.

        Returns:
            Reducer status.
        """
        return self._call("compute_community_hierarchy", [workspace_id])

    # -----------------------------------------------------------------------
    # Peer queries
    # -----------------------------------------------------------------------

    def list_peers(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """List peers, optionally filtered by workspace."""
        if workspace_id:
            return self._sql(
                f"SELECT * FROM peer WHERE workspace_id = '{_esc(workspace_id)}'"
            )
        return self._sql("SELECT * FROM peer")

    # -----------------------------------------------------------------------
    # Context pack queries
    # -----------------------------------------------------------------------

    def list_context_packs(self, workspace_id: str) -> list[dict[str, Any]]:
        """List context packs for a workspace."""
        return self._sql(
            f"SELECT * FROM context_pack WHERE workspace_id = '{_esc(workspace_id)}'"
        )

    def list_context_entries(self, pack_id: str) -> list[dict[str, Any]]:
        """List entries in a context pack."""
        return self._sql(
            f"SELECT * FROM context_entry WHERE pack_id = '{_esc(pack_id)}'"
        )

    def list_context_deltas(self, previous_pack_id: str) -> list[dict[str, Any]]:
        """List delta entries for a pack."""
        return self._sql(
            f"SELECT * FROM context_delta WHERE previous_pack_id = '{_esc(previous_pack_id)}'"
        )

    # -----------------------------------------------------------------------
    # Notes (markdown documents with wikilink backlinking)
    # -----------------------------------------------------------------------

    def create_note(
        self,
        workspace_id: str = "default",
        title: str = "",
        content: str = "",
        note_date: str = "",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Create a note. If *embed* is True, auto-embeds via the sidecar."""
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        return self._call("create_note", [
            workspace_id, title, content, note_date, embedding_json,
        ])

    def update_note(
        self,
        note_id: str,
        title: str = "",
        content: str = "",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Update a note. Re-embeds if content changes and *embed* is True."""
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        return self._call("update_note", [note_id, title, content, embedding_json])

    def delete_note(self, note_id: str) -> dict[str, Any]:
        """Delete a note and its backlinks."""
        return self._call("delete_note", [note_id])

    def list_notes(
        self, workspace_id: str = "default", include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        """List notes in a workspace."""
        clauses = [f"workspace_id = '{_esc(workspace_id)}'"]
        if not include_inactive:
            clauses.append("is_active = true")
        where = " AND ".join(clauses)
        rows = self._sql(f"SELECT * FROM note WHERE {where}")
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        return rows

    def get_note(self, note_id: str) -> list[dict[str, Any]]:
        """Get a note by ID."""
        return self._sql(f"SELECT * FROM note WHERE id = '{_esc(note_id)}'")

    def get_note_by_date(self, note_date: str) -> list[dict[str, Any]]:
        """Get a note by its date string (YYYY-MM-DD)."""
        return self._sql(
            f"SELECT * FROM note WHERE note_date = '{_esc(note_date)}' AND is_active = true"
        )

    def get_note_by_title(self, title: str) -> list[dict[str, Any]]:
        """Find a note by exact title."""
        return self._sql(
            f"SELECT * FROM note WHERE title = '{_esc(title)}' AND is_active = true"
        )

    def get_backlinks(self, note_id: str) -> list[dict[str, Any]]:
        """Get all notes that link *to* the given note."""
        return self._sql(
            "SELECT nb.*, n.title AS source_title "
            "FROM note_backlink nb "
            "LEFT JOIN note n ON nb.source_note_id = n.id "
            f"WHERE nb.target_note_id = '{_esc(note_id)}'"
        )

    def get_outgoing_links(self, note_id: str) -> list[dict[str, Any]]:
        """Get all notes that the given note links *to*."""
        return self._sql(
            "SELECT nb.*, n.title AS target_title "
            "FROM note_backlink nb "
            "LEFT JOIN note n ON nb.target_note_id = n.id "
            f"WHERE nb.source_note_id = '{_esc(note_id)}'"
        )

    # -------------------------------------------------------------------
    # KG Graph Traversal
    # -------------------------------------------------------------------

    def graph_bfs(self, workspace_id: str, start_node_id: str, max_depth: int = 3) -> None:
        """BFS traversal from a start node up to max_depth.
        Results are in graph_traversal_result table, keyed by query_id."""
        self._call("graph_bfs", [workspace_id, start_node_id, max_depth])

    def shortest_path(self, workspace_id: str, source_id: str, target_id: str, max_hops: int = 6) -> None:
        """Shortest path between two nodes.
        Results in shortest_path_result table, ordered by step_order."""
        self._call("shortest_path", [workspace_id, source_id, target_id, max_hops])

    def get_neighbors_via_reducer(self, workspace_id: str, node_id: str) -> None:
        """Get immediate neighbours of a node.
        Results in graph_traversal_result table with depth=1."""
        self._call("get_neighbors", [workspace_id, node_id])

    # -------------------------------------------------------------------
    # Tours
    # -------------------------------------------------------------------

    def create_tour(self, workspace_id: str, title: str, description: str = "") -> None:
        """Create a new guided tour."""
        self._call("create_tour", [workspace_id, title, description])

    def add_tour_stop(self, tour_id: str, node_id: str, heading: str, description: str = "") -> None:
        """Add a stop to a tour."""
        self._call("add_tour_stop", [tour_id, node_id, heading, description])

    def delete_tour(self, tour_id: str) -> None:
        """Delete a tour and all its stops."""
        self._call("delete_tour", [tour_id])

    # -------------------------------------------------------------------
    # Backup & Restore
    # -------------------------------------------------------------------

    _BACKUP_TABLES = [
        "workspace",
        "space_permission",
        "memory",
        "memory_version",
        "kg_node",
        "kg_edge",
        "kg_community",
        "session",
        "session_participant",
        "message",
        "profile",
        "note",
        "fact",
        "peer",
        "context_pack",
        "context_entry",
        "directory",
        "directory_link",
        "backlink",
        "merge_suggestion",
        "connector_config",
    ]

    def backup(self, output_path: str | None = None) -> dict[str, Any]:
        """Export all user data tables to a JSON file.

        Args:
            output_path: Path to write the backup file. If None, generates
                a filename like ``spacetime-memory-backup-YYYY-MM-DD.json``.

        Returns:
            Dict with backup metadata: tables backed up, row counts, file path.
        """
        import datetime

        manifest: dict[str, list[dict[str, Any]]] = {}
        total_rows = 0
        backed_up = []

        for table in self._BACKUP_TABLES:
            try:
                rows = self._sql(f"SELECT * FROM {table}")
            except RuntimeError:
                continue  # table doesn't exist in this module version
            if rows:
                manifest[table] = rows
                total_rows += len(rows)
                backed_up.append(table)
            else:
                manifest[table] = []

        if output_path is None:
            date = datetime.date.today().isoformat()
            output_path = f"spacetime-memory-backup-{date}.json"

        payload = {
            "version": "0.3.0",
            "created_at": datetime.datetime.utcnow().isoformat(),
            "tables": manifest,
            "stats": {
                "table_count": len(backed_up),
                "total_rows": total_rows,
            },
        }

        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        return {
            "status": "ok",
            "path": output_path,
            "tables": backed_up,
            "total_rows": total_rows,
        }

    def restore(self, input_path: str) -> dict[str, Any]:
        """Import a backup file into the current database.

        Args:
            input_path: Path to the backup JSON file.

        Returns:
            Dict with restore metadata: tables restored, row counts.
        """
        with open(input_path, "r") as f:
            payload = json.load(f)

        manifest = payload.get("tables", {})
        total_restored = 0
        restored = []

        for table, rows in manifest.items():
            if not rows:
                continue
            if not rows[0]:
                continue
            try:
                col_names = list(rows[0].keys())
                placeholders = ", ".join(col_names)
                for row in rows:
                    values = []
                    for col in col_names:
                        val = row.get(col)
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, bool):
                            values.append("true" if val else "false")
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        else:
                            values.append(f"'{_esc(str(val))}'")
                    sql = f"INSERT INTO {table} ({placeholders}) VALUES ({', '.join(values)})"
                    try:
                        self._sql(sql)
                    except RuntimeError:
                        pass  # may be a duplicate or schema mismatch
                restored.append(table)
                total_restored += len(rows)
            except Exception:
                continue

        return {
            "status": "ok",
            "input_path": input_path,
            "tables": restored,
            "total_rows": total_restored,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


def _query_hash(query: str) -> str:
    """Deterministic hash matching the Rust hybrid_query reducer."""
    h = 0
    for b in query.encode("utf-8"):
        h = ((h * 6364136223846793005) + b) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _parse_sql_response(raw: str) -> list[dict[str, Any]]:
    """Parse SpacetimeDB's positional-array SQL response into dicts."""
    if not raw.strip():
        return []
    tables = json.loads(raw)
    results: list[dict[str, Any]] = []
    for table in tables:
        elements = table.get("schema", {}).get("elements", [])
        col_names: list[str] = []
        for el in elements:
            name_container = el.get("name", {})
            if isinstance(name_container, dict) and "some" in name_container:
                col_names.append(name_container["some"])
            else:
                col_names.append("?col?")
        for row in table.get("rows", []):
            row_dict: dict[str, Any] = {}
            for i, val in enumerate(row):
                key = col_names[i] if i < len(col_names) else f"col{i}"
                row_dict[key] = val
            results.append(row_dict)
    return results
