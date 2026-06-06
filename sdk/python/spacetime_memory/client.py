"""Python client for spacetime-memory.

Provides a high-level Client class that wraps the SpacetimeDB HTTP SQL API,
the reducer-call endpoint, and the Rust ONNX embedder sidecar.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Client:
    """Spacetime-Memory client.

    Minimal config — point at a running SpacetimeDB instance + embedder.
    All methods return parsed dicts: {"status": "ok"} for writes, or
    list[dict] / dict for reads.

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
        timeout: float = 30.0,
    ):
        self.host = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
        self.port = str(port or os.environ.get("SPACETIMEDB_PORT", "3001"))
        self.database = database or os.environ.get(
            "SPACETIMEDB_DB", "spacetime-memory"
        )
        self.embedder_url = (
            embedder_url
            or os.environ.get("EMBEDDER_URL", "http://localhost:9090")
        )

        base = f"http://{self.host}:{self.port}"
        self.sql_url = f"{base}/v1/database/{self.database}/sql"
        self.reducer_url = f"{base}/v1/database/{self.database}/call"
        self._http = httpx.Client(timeout=timeout)

    # -----------------------------------------------------------------------
    # HTTP helpers
    # -----------------------------------------------------------------------

    def _sql(self, query: str) -> list[dict[str, Any]]:
        """Run a SELECT query against the SpacetimeDB SQL API."""
        resp = self._http.post(
            self.sql_url,
            content=query,
            headers={"Content-Type": "text/plain"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"SQL error (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        return _parse_sql_response(resp.text)

    def _call(self, reducer: str, args: list[Any]) -> dict[str, Any]:
        """Call a SpacetimeDB reducer with positional JSON args."""
        resp = self._http.post(
            f"{self.reducer_url}/{reducer}",
            content=json.dumps(args),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Reducer error (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        return {"status": "ok"}

    def _embed(self, text: str) -> list[float]:
        """Get an embedding vector via the Rust ONNX sidecar."""
        try:
            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            if resp.status_code >= 400:
                return []
            return resp.json().get("embedding", [])
        except Exception:
            return []

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts."""
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
                return []
            return resp.json().get("embeddings", [])
        except Exception:
            return []

    # -----------------------------------------------------------------------
    # Workspace
    # -----------------------------------------------------------------------

    def create_workspace(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a new workspace. Returns reducer status."""
        return self._call("create_workspace", [name, description])

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
        clauses = [f"workspace_id = '{_esc(workspace_id)}'"]
        if query:
            escaped = _esc(query)
            clauses.append(
                f"(content LIKE '%{escaped}%' OR summary LIKE '%{escaped}%')"
            )
        if memory_type:
            clauses.append(f"memory_type = '{_esc(memory_type)}'")
        if tier:
            clauses.append(f"tier = '{_esc(tier)}'")
        where = " AND ".join(clauses)
        rows = self._sql(
            f"SELECT * FROM memory WHERE {where}"
        )
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
        """Deactivate a memory."""
        return self._call("deactivate_memory", [memory_id])

    def reinforce(self, memory_id: str) -> dict[str, Any]:
        """Reinforce a memory (bump access_count + strength)."""
        return self._call("reinforce_memory", [memory_id])

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
        if query:
            escaped = _esc(query)
            rows = self._sql(
                "SELECT * FROM kg_node WHERE "
                f"workspace_id = '{_esc(workspace_id)}' AND "
                f"label LIKE '%{escaped}%'"
            )
        else:
            rows = self._sql(
                "SELECT * FROM kg_node WHERE "
                f"workspace_id = '{_esc(workspace_id)}'"
            )
        rows.sort(key=lambda r: r.get("label", ""))
        return rows

    def get_neighbors(self, node_id: str) -> list[dict[str, Any]]:
        """Get edges connected to a node."""
        rows = self._sql(
            "SELECT e.*, src.label AS source_label, tgt.label AS target_label "
            "FROM kg_edge e "
            "LEFT JOIN kg_node src ON e.source_node_id = src.id "
            "LEFT JOIN kg_node tgt ON e.target_node_id = tgt.id "
            f"WHERE e.source_node_id = '{_esc(node_id)}' "
            f"   OR e.target_node_id = '{_esc(node_id)}' "
        )
        rows.sort(key=lambda r: r.get("weight", 0.0), reverse=True)
        return rows

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
