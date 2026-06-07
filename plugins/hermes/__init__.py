"""SpacetimeDB memory plugin — MemoryProvider interface.

Connects to a running spacetime-memory module (SpacetimeDB + embedder sidecar)
for persistent cross-session recall, semantic search, knowledge graph access,
and markdown notes.

Config via environment variables:
  SPACETIMEDB_HOST       — host (default: localhost)
  SPACETIMEDB_PORT       — port (default: 3001)
  SPACETIMEDB_DB        — database name (default: spacetime-memory)
  EMBEDDER_URL           — embedder sidecar URL (default: http://localhost:9090)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error

logger = logging.getLogger(__name__)

# Circuit breaker
_BREAKER_THRESHOLD = 5
_BREAKER_COOLDOWN_SECS = 120

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    return {
        "host": os.environ.get("SPACETIMEDB_HOST", "localhost"),
        "port": os.environ.get("SPACETIMEDB_PORT", "3001"),
        "database": os.environ.get("SPACETIMEDB_DB", "spacetime-memory"),
        "embedder_url": os.environ.get("EMBEDDER_URL", "http://localhost:9090"),
    }


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "name": "spacetime_search",
    "description": (
        "Search all memories, notes, and knowledge-graph nodes by semantic meaning "
        "and keywords. Returns ranked results across all entity types."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "limit": {"type": "integer", "description": "Max results (default: 10, max: 50)."},
        },
        "required": ["query"],
    },
}

STORE_SCHEMA = {
    "name": "spacetime_store",
    "description": (
        "Store a durable memory, fact, or observation. "
        "Auto-embeds for semantic search. Use for preferences, corrections, decisions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The fact or memory to store."},
            "summary": {"type": "string", "description": "Optional short summary."},
            "memory_type": {
                "type": "string",
                "description": "Type: world_fact, experience, mental_model (default: experience).",
                "enum": ["world_fact", "experience", "mental_model"],
            },
        },
        "required": ["content"],
    },
}

NOTE_SEARCH_SCHEMA = {
    "name": "spacetime_notes",
    "description": (
        "Search or list markdown notes. Returns titles, dates, backlink counts. "
        "Use to find notes relevant to the conversation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional keyword to search note titles/content."},
            "limit": {"type": "integer", "description": "Max results (default: 20)."},
        },
        "required": [],
    },
}

KG_SCHEMA = {
    "name": "spacetime_kg",
    "description": (
        "Query the knowledge graph — find nodes, their connections, and communities. "
        "Use for understanding relationships between entities."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Node label or keyword to search for."},
        },
        "required": ["query"],
    },
}

PROFILE_SCHEMA = {
    "name": "spacetime_profile",
    "description": (
        "Get or create a user profile with static facts and dynamic context. "
        "Use for long-term user modeling."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "peer_id": {"type": "string", "description": "Peer/user identifier."},
            "fact": {"type": "string", "description": "Optional fact to add to profile."},
        },
        "required": ["peer_id"],
    },
}


# ---------------------------------------------------------------------------
# Minimal HTTP client (no SDK dependency needed)
# ---------------------------------------------------------------------------

class _SpacetimeClient:
    """Thin HTTP client for the SpacetimeDB module.

    Uses httpx if available, falls back to urllib.
    """

    def __init__(self, host: str, port: str, database: str, embedder_url: str):
        self.base = f"http://{host}:{port}"
        self.reducer_url = f"{self.base}/v1/database/{database}/call"
        self.sql_url = f"{self.base}/v1/database/{database}/sql"
        self.embedder_url = embedder_url
        self._httpx = None

    def _ensure_client(self):
        if self._httpx is not None:
            return
        try:
            import httpx
            self._httpx = httpx.Client(timeout=30.0)
        except ImportError:
            pass

    def _call(self, reducer: str, args: list) -> dict:
        self._ensure_client()
        if self._httpx:
            resp = self._httpx.post(
                f"{self.reducer_url}/{reducer}",
                content=json.dumps(args),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"Reducer error ({resp.status_code}): {resp.text[:300]}")
            return {"status": "ok"}
        # Fallback: urllib
        import urllib.request
        data = json.dumps(args).encode()
        req = urllib.request.Request(
            f"{self.reducer_url}/{reducer}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        if resp.status >= 400:
            raise RuntimeError(f"Reducer error ({resp.status}): {resp.read()[:300]}")
        return {"status": "ok"}

    def _sql(self, query: str) -> list[dict]:
        self._ensure_client()
        if self._httpx:
            resp = self._httpx.post(
                self.sql_url,
                content=query,
                headers={"Content-Type": "text/plain"},
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"SQL error ({resp.status_code}): {resp.text[:300]}")
            return self._parse_sql_response(resp.text)
        # Fallback urllib
        import urllib.request
        data = query.encode()
        req = urllib.request.Request(
            self.sql_url, data=data,
            headers={"Content-Type": "text/plain"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        return self._parse_sql_response(resp.read().decode())

    def _embed(self, text: str) -> list[float]:
        if not text.strip():
            return []
        self._ensure_client()
        try:
            if self._httpx:
                resp = self._httpx.post(
                    f"{self.embedder_url}/embed",
                    content=json.dumps({"text": text}),
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )
                if resp.status_code >= 400:
                    return []
                return resp.json().get("embedding", [])
            import urllib.request
            data = json.dumps({"text": text}).encode()
            req = urllib.request.Request(
                f"{self.embedder_url}/embed",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            return json.loads(resp.read()).get("embedding", [])
        except Exception:
            return []

    @staticmethod
    def _parse_sql_response(raw: str) -> list[dict]:
        if not raw.strip():
            return []
        tables = json.loads(raw)
        results = []
        for table in tables:
            elements = table.get("schema", {}).get("elements", [])
            col_names = []
            for el in elements:
                nc = el.get("name", {})
                if isinstance(nc, dict) and "some" in nc:
                    col_names.append(nc["some"])
                else:
                    col_names.append("?col?")
            for row in table.get("rows", []):
                rd = {}
                for i, val in enumerate(row):
                    key = col_names[i] if i < len(col_names) else f"col{i}"
                    rd[key] = val
                results.append(rd)
        return results


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

class SpacetimeMemoryProvider(MemoryProvider):
    """SpacetimeDB memory with hybrid search, knowledge graph, and notes."""

    def __init__(self):
        self._config = None
        self._client = None
        self._client_lock = threading.Lock()
        self._host = "localhost"
        self._port = "3001"
        self._database = "spacetime-memory"
        self._embedder_url = "http://localhost:9090"
        self._user_id = "hermes-user"
        self._workspace_id = "default"
        self._prefetch_result = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread = None
        # Circuit breaker
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    @property
    def name(self) -> str:
        return "spacetime"

    def is_available(self) -> bool:
        """Quick availability — checks if we can reach the SpacetimeDB HTTP API."""
        cfg = _load_config()
        host = cfg["host"]
        port = cfg["port"]
        import urllib.request
        try:
            resp = urllib.request.urlopen(f"http://{host}:{port}/health", timeout=3)
            return True
        except Exception:
            return False

    def save_config(self, values, hermes_home):
        """Write config to $HERMES_HOME/spacetime.json."""
        import json as _json
        from pathlib import Path
        config_path = Path(hermes_home) / "spacetime.json"
        existing = {}
        if config_path.exists():
            try:
                existing = _json.loads(config_path.read_text())
            except Exception:
                pass
        existing.update(values)
        from utils import atomic_json_write
        atomic_json_write(config_path, existing, mode=0o600)

    def get_config_schema(self):
        return [
            {"key": "host", "description": "SpacetimeDB host", "default": "localhost"},
            {"key": "port", "description": "SpacetimeDB port", "default": "3001"},
            {"key": "database", "description": "Database name", "default": "spacetime-memory"},
            {"key": "embedder_url", "description": "Embedder sidecar URL", "default": "http://localhost:9090"},
        ]

    def _get_client(self) -> _SpacetimeClient:
        with self._client_lock:
            if self._client is not None:
                return self._client
            self._client = _SpacetimeClient(
                host=self._host,
                port=self._port,
                database=self._database,
                embedder_url=self._embedder_url,
            )
            return self._client

    def _is_breaker_open(self) -> bool:
        if self._consecutive_failures < _BREAKER_THRESHOLD:
            return False
        if time.monotonic() >= self._breaker_open_until:
            self._consecutive_failures = 0
            return False
        return True

    def _record_success(self):
        self._consecutive_failures = 0

    def _record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= _BREAKER_THRESHOLD:
            self._breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_SECS
            logger.warning(
                "Spacetime circuit breaker tripped after %d failures. Pausing %ds.",
                self._consecutive_failures, _BREAKER_COOLDOWN_SECS,
            )

    def initialize(self, session_id: str, **kwargs) -> None:
        cfg = _load_config()
        # Also check $HERMES_HOME/spacetime.json for overrides
        try:
            from hermes_constants import get_hermes_home
            config_path = get_hermes_home() / "spacetime.json"
            if config_path.exists():
                import json as _json
                file_cfg = _json.loads(config_path.read_text())
                cfg.update({k: v for k, v in file_cfg.items() if v is not None and v != ""})
        except Exception:
            pass

        self._host = cfg["host"]
        self._port = cfg["port"]
        self._database = cfg["database"]
        self._embedder_url = cfg["embedder_url"]
        self._user_id = kwargs.get("user_id") or "hermes-user"
        self._workspace_id = kwargs.get("workspace_id") or "default"

        logger.info(
            "Spacetime memory provider initialised: %s:%s/%s",
            self._host, self._port, self._database,
        )

    def system_prompt_block(self) -> str:
        return (
            "# SpacetimeDB Memory\n"
            f"Active. Connected to {self._host}:{self._port}/{self._database}.\n"
            "Use spacetime_search to find memories/notes/nodes, "
            "spacetime_store to save facts, "
            "spacetime_notes to browse markdown notes, "
            "spacetime_kg to query the knowledge graph, "
            "spacetime_profile for user modeling."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=3.0)
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""
        if not result:
            return ""
        return f"## SpacetimeDB Context\n{result}"

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if self._is_breaker_open() or not query.strip():
            return

        def _run():
            try:
                client = self._get_client()
                emb = client._embed(query)
                emb_json = json.dumps(emb) if emb else "[]"
                strategies = json.dumps(["semantic", "keyword", "temporal"])
                client._call("hybrid_search", [
                    self._workspace_id, query, emb_json,
                    "", "", 8, strategies,
                ])
                rows = client._sql(
                    "SELECT hr.*, m.content AS memory_content "
                    "FROM hybrid_result hr "
                    "LEFT JOIN memory m ON hr.entity_id = m.id AND hr.entity_type = 'memory' "
                    f"WHERE hr.workspace_id = '{self._workspace_id}' "
                    "ORDER BY hr.score DESC LIMIT 5"
                )
                if rows:
                    lines = []
                    for r in rows:
                        content = r.get("memory_content") or r.get("entity_id", "")
                        score = r.get("score", 0)
                        lines.append(f"- [{score:.2f}] {content[:200]}")
                    with self._prefetch_lock:
                        self._prefetch_result = "\n".join(lines)
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("Spacetime prefetch failed: %s", e)

        self._prefetch_thread = threading.Thread(target=_run, daemon=True, name="spacetime-prefetch")
        self._prefetch_thread.start()

    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages: list = None) -> None:
        """Store each turn as a memory entry for later recall."""
        if self._is_breaker_open():
            return

        def _sync():
            try:
                client = self._get_client()
                # Embed the user message for semantic retrieval
                combined = f"User: {user_content[:500]}\nAssistant: {assistant_content[:500]}"
                emb = client._embed(user_content[:1024])
                emb_json = json.dumps(emb) if emb else "[]"

                # Store as experience memory
                client._call("store_memory", [
                    self._workspace_id,
                    self._user_id,          # peer_id
                    "hermes",                # observer_id
                    "experience",
                    combined,
                    assistant_content[:200],
                    "[]",                    # entities_json
                    0.7,                     # confidence
                    session_id,
                    "",
                ])
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.warning("Spacetime sync failed: %s", e)

        threading.Thread(target=_sync, daemon=True, name="spacetime-sync").start()

    def get_tool_schemas(self) -> list[dict]:
        return [SEARCH_SCHEMA, STORE_SCHEMA, NOTE_SEARCH_SCHEMA, KG_SCHEMA, PROFILE_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if self._is_breaker_open():
            return json.dumps({
                "error": "SpacetimeDB temporarily unavailable (multiple failures). Will retry."
            })

        try:
            client = self._get_client()
        except Exception as e:
            return tool_error(str(e))

        if tool_name == "spacetime_search":
            return self._handle_search(client, args)
        elif tool_name == "spacetime_store":
            return self._handle_store(client, args)
        elif tool_name == "spacetime_notes":
            return self._handle_notes(client, args)
        elif tool_name == "spacetime_kg":
            return self._handle_kg(client, args)
        elif tool_name == "spacetime_profile":
            return self._handle_profile(client, args)

        return tool_error(f"Unknown tool: {tool_name}")

    def _handle_search(self, client: _SpacetimeClient, args: dict) -> str:
        query = args.get("query", "")
        limit = min(int(args.get("limit", 10)), 50)
        if not query:
            # Return recent memories
            try:
                mems = client._sql(
                    "SELECT id, content, summary, memory_type, created_at, score "
                    "FROM memory WHERE is_active = true "
                    f"AND workspace_id = '{self._workspace_id}' "
                    "ORDER BY created_at DESC LIMIT 20"
                )
                self._record_success()
                return json.dumps({
                    "results": [{"content": m.get("content", ""), "type": m.get("memory_type", "memory"), "score": 1.0} for m in mems],
                    "count": len(mems),
                })
            except Exception as e:
                self._record_failure()
                return tool_error(f"Search failed: {e}")

        try:
            emb = client._embed(query)
            emb_json = json.dumps(emb) if emb else "[]"
            strategies = json.dumps(["semantic", "keyword", "temporal"])
            client._call("hybrid_search", [
                self._workspace_id, query, emb_json,
                "", "", limit, strategies,
            ])

            # Read results from hybrid_result table
            rows = client._sql(
                "SELECT hr.*, m.content AS memory_content, m.summary AS memory_summary, "
                "n.title AS note_title, n.content AS note_content "
                "FROM hybrid_result hr "
                "LEFT JOIN memory m ON hr.entity_id = m.id AND hr.entity_type = 'memory' "
                "LEFT JOIN note n ON hr.entity_id = n.id AND hr.entity_type = 'note' "
                f"WHERE hr.workspace_id = '{self._workspace_id}' "
                "ORDER BY hr.score DESC"
            )

            results = []
            for r in rows[:limit]:
                content = (
                    r.get("memory_content") or r.get("note_content") or r.get("entity_id", "")
                )
                summary = r.get("memory_summary") or r.get("note_title") or ""
                score = r.get("score", 0)
                ent_type = r.get("entity_type", "unknown")
                results.append({
                    "content": content[:500],
                    "summary": summary[:200] if summary else "",
                    "score": score,
                    "type": ent_type,
                })

            self._record_success()
            return json.dumps({"results": results, "count": len(results)})
        except Exception as e:
            self._record_failure()
            return tool_error(f"Search failed: {e}")

    def _handle_store(self, client: _SpacetimeClient, args: dict) -> str:
        content = args.get("content", "")
        summary = args.get("summary", "")
        memory_type = args.get("memory_type", "experience")

        if not content:
            return tool_error("Missing required parameter: content")

        try:
            emb = client._embed(content[:1024])
            emb_json = json.dumps(emb) if emb else "[]"
            client._call("store_memory", [
                self._workspace_id, self._user_id, "hermes",
                memory_type, content, summary, "[]",
                0.9, "", "",
            ])
            self._record_success()
            return json.dumps({"result": "Memory stored.", "type": memory_type})
        except Exception as e:
            self._record_failure()
            return tool_error(f"Store failed: {e}")

    def _handle_notes(self, client: _SpacetimeClient, args: dict) -> str:
        query = args.get("query", "")
        limit = min(int(args.get("limit", 20)), 50)

        try:
            if query:
                rows = client._sql(
                    "SELECT id, title, content, note_date, backlink_count, updated_at "
                    "FROM note WHERE is_active = true "
                    f"AND workspace_id = '{self._workspace_id}' "
                    "AND (title LIKE '%{q}%' OR content LIKE '%{q}%') "
                    "ORDER BY updated_at DESC "
                    f"LIMIT {limit}"
                )
            else:
                rows = client._sql(
                    "SELECT id, title, content, note_date, backlink_count, updated_at "
                    "FROM note WHERE is_active = true "
                    f"AND workspace_id = '{self._workspace_id}' "
                    "ORDER BY updated_at DESC "
                    f"LIMIT {limit}"
                )
            self._record_success()
            notes = [{
                "title": r.get("title", "Untitled") or "Untitled",
                "note_date": r.get("note_date", ""),
                "backlinks": r.get("backlink_count", 0),
                "content_preview": (r.get("content", "") or "")[:200],
            } for r in rows]
            return json.dumps({"notes": notes, "count": len(notes)})
        except Exception as e:
            self._record_failure()
            return tool_error(f"Notes query failed: {e}")

    def _handle_kg(self, client: _SpacetimeClient, args: dict) -> str:
        query = args.get("query", "")
        try:
            if query:
                nodes = client._sql(
                    "SELECT id, label, node_type, summary "
                    "FROM kg_node WHERE "
                    f"workspace_id = '{self._workspace_id}' AND "
                    f"label LIKE '%{query}%' "
                    "LIMIT 20"
                )
            else:
                nodes = client._sql(
                    "SELECT id, label, node_type, summary "
                    "FROM kg_node WHERE "
                    f"workspace_id = '{self._workspace_id}' "
                    "LIMIT 20"
                )
            self._record_success()
            return json.dumps({
                "nodes": [{
                    "label": n.get("label", ""),
                    "type": n.get("node_type", ""),
                    "summary": (n.get("summary", "") or "")[:200],
                } for n in nodes],
                "count": len(nodes),
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"KG query failed: {e}")

    def _handle_profile(self, client: _SpacetimeClient, args: dict) -> str:
        peer_id = args.get("peer_id", "")
        fact = args.get("fact", "")

        if not peer_id:
            return tool_error("Missing required parameter: peer_id")

        try:
            existing = client._sql(
                "SELECT id, peer_id, static_facts_json, dynamic_context_json "
                f"FROM profile WHERE peer_id = '{peer_id}'"
            )

            if fact:
                if existing:
                    # Add fact to dynamic context
                    client._call("add_dynamic_context", [peer_id, fact, "hermes"])
                else:
                    # Create profile with fact
                    client._call("upsert_profile", [
                        peer_id, "[]", json.dumps([fact]),
                        "{}", "[]",
                    ])

            # Re-fetch
            profiles = client._sql(
                "SELECT id, peer_id, static_facts_json, dynamic_context_json, "
                "preferences_json, tags_json "
                f"FROM profile WHERE peer_id = '{peer_id}'"
            )

            self._record_success()
            if not profiles:
                return json.dumps({"result": f"No profile for {peer_id}."})
            p = profiles[0]
            return json.dumps({
                "peer_id": peer_id,
                "static_facts": p.get("static_facts_json", "[]"),
                "dynamic_context": p.get("dynamic_context_json", "[]"),
                "preferences": p.get("preferences_json", "{}"),
            })
        except Exception as e:
            self._record_failure()
            return tool_error(f"Profile failed: {e}")

    def shutdown(self) -> None:
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=5.0)
        with self._client_lock:
            if self._client and self._client._httpx:
                try:
                    self._client._httpx.close()
                except Exception:
                    pass
            self._client = None


def register(ctx) -> None:
    """Register SpacetimeDB as a memory provider plugin."""
    ctx.register_memory_provider(SpacetimeMemoryProvider())
