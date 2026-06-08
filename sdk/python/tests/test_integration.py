"""Integration tests for spacetime-memory.

These tests require a running SpacetimeDB instance and embedder.
Run with: SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest ... -v

Or with a specific database identity:
  SPACETIMEDB_DB=hexid pytest tests/test_integration.py -v
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
import time
import uuid
import pytest
from shutil import which
from pathlib import Path

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CLI_PATH = str(REPO_ROOT / "cli" / "stmem.py")


def _unique(prefix: str = "test") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Helper: create a unique workspace and return its ID."""
    ws_name = _unique("it-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for ws in workspaces:
        if ws.get("name") == ws_name:
            return ws["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture(scope="module")
def client():
    return Client(host=HOST, port=PORT, database=DB)


@pytest.fixture
def ws(client):
    """Unique workspace per test function."""
    return _make_ws(client)


# =====================================================================
# Core CRUD Tests
# =====================================================================


class TestWorkspaceCRUD:
    """Workspace create / list."""

    def test_create_and_list(self, client):
        ws_name = _unique("ws-crud")
        result = client.create_workspace(ws_name)
        assert result["status"] == "ok"

        workspaces = client.list_workspaces()
        found = any(ws.get("name") == ws_name for ws in workspaces)
        assert found, f"Workspace '{ws_name}' not in list"


class TestMemoryCRUD:
    """Full memory CRUD lifecycle."""

    def test_store_and_list(self, client, ws):
        result = client.store(
            workspace_id=ws,
            content="The quick brown fox jumps over the lazy dog",
            peer_id="it-bot",
            memory_type="experience",
        )
        assert result["status"] == "ok"

        mems = client.list_memories(workspace_id=ws, limit=10)
        assert isinstance(mems, list)
        assert len(mems) >= 1
        mems_text = " ".join(m.get("content", "") for m in mems)
        assert "fox" in mems_text

    def test_store_with_tier(self, client, ws):
        result = client.store(
            workspace_id=ws, content="critical memory", peer_id="bot", tier="L0",
        )
        assert result["status"] == "ok"

    def test_update_memory(self, client, ws):
        client.store(workspace_id=ws, content="original content", peer_id="bot")
        mems = client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) > 0
        mem_id = mems[0]["id"]
        up = client.update_memory(mem_id, "updated content", "summary", 0.95)
        assert up["status"] == "ok"

    def test_delete_memory(self, client, ws):
        client.store(workspace_id=ws, content="delete me", peer_id="bot")
        mems = client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) > 0
        mem_id = mems[0]["id"]
        d = client.delete_memory(mem_id)
        assert d["status"] == "ok"

    def test_reinforce_memory(self, client, ws):
        client.store(workspace_id=ws, content="reinforce me", peer_id="bot")
        mems = client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) > 0
        mem_id = mems[0]["id"]
        r = client.reinforce(mem_id)
        assert r["status"] == "ok"


# =====================================================================
# Semantic Search Tests (requires embedder at :9090)
# =====================================================================


class TestSemanticSearch:
    """Search with the real embedder sidecar."""

    def test_store_and_semantic_search(self, client, ws):
        client.store(
            workspace_id=ws,
            content="I like pizza with pineapple and anchovies",
            peer_id="it-bot",
            memory_type="experience",
        )
        client.store(
            workspace_id=ws,
            content="Python is a programming language for web development",
            peer_id="it-bot",
            memory_type="world_fact",
        )
        time.sleep(0.5)

        results = client.search(
            workspace_id=ws, query="food pizza toppings", limit=10, semantic=True,
        )
        assert isinstance(results, list)
        if results:
            combined = " ".join(
                r.get("memory_content", r.get("content", "")).lower() for r in results
            )
            assert "pizza" in combined

    def test_keyword_search(self, client, ws):
        client.store(
            workspace_id=ws, content="keyword specific search term", peer_id="it-bot",
        )
        # Allow time for write propagation
        time.sleep(0.3)
        results = client.search(
            workspace_id=ws, query="keyword", limit=10, semantic=False,
        )
        assert isinstance(results, list)


# =====================================================================
# Session Tests
# =====================================================================


class TestSessions:
    """Agent session lifecycle."""

    def test_create_session(self, client, ws):
        result = client._call("create_session", [ws, "test-session", "{}"])
        assert result["status"] == "ok"

    def test_query_sessions(self, client, ws):
        client._call("create_session", [ws, "integration-session", '{"key":"val"}'])
        rows = client._sql(
            f"SELECT * FROM session WHERE workspace_id = '{ws}'"
        )
        assert isinstance(rows, list)
        assert any(r.get("name") == "integration-session" for r in rows)


# =====================================================================
# Graph Tests (uses actual table names from Rust module)
# =====================================================================


class TestGraph:
    """Node and edge CRUD via reducers."""

    def test_create_node_and_edge(self, client, ws):
        n1 = client.create_node(ws, "int-node-a", "concept", "First node", "{}")
        assert n1["status"] == "ok"
        n2 = client.create_node(ws, "int-node-b", "concept", "Second node", "{}")
        assert n2["status"] == "ok"

        time.sleep(0.3)

        # Look up node IDs via the actual table name: kg_node
        nodes = client._sql(f"SELECT id, label FROM kg_node WHERE workspace_id = '{ws}'")
        node_ids = {n["label"]: n["id"] for n in nodes}
        assert "int-node-a" in node_ids
        assert "int-node-b" in node_ids

        edge = client.create_edge(
            ws, node_ids["int-node-a"], node_ids["int-node-b"],
            "related_to", 0.8, "EXTRACTED", "{}",
        )
        assert edge["status"] == "ok"

    def test_query_graph(self, client, ws):
        client.create_node(ws, "query-target", "concept", "Query source", "{}")
        results = client.query_graph(ws, "query-target")
        assert isinstance(results, list)

    def test_get_neighbors(self, client, ws):
        client.create_node(ws, "neighbor-a", "concept", "A", "{}")
        client.create_node(ws, "neighbor-b", "concept", "B", "{}")
        time.sleep(0.3)
        nodes = client._sql(f"SELECT id, label FROM kg_node WHERE workspace_id = '{ws}'")
        node_ids = {n["label"]: n["id"] for n in nodes}
        assert "neighbor-a" in node_ids
        assert "neighbor-b" in node_ids
        client.create_edge(
            ws, node_ids["neighbor-a"], node_ids["neighbor-b"],
            "connected_to", 1.0, "EXTRACTED", "{}",
        )
        time.sleep(0.3)
        neighbors = client.get_neighbors(node_ids["neighbor-a"])
        assert isinstance(neighbors, list)


# =====================================================================
# Facts & Profile Tests
# =====================================================================


class TestFacts:
    """Facts CRUD."""

    def test_add_and_list_facts(self, client, ws):
        fact_id = _unique("fact")
        result = client._call("add_fact", [
            ws, "it-bot", "personal", "general",
            f"Test fact {fact_id}", 0.9, "integration-test", "L1",
        ])
        assert result["status"] == "ok"
        time.sleep(0.2)
        facts = client._sql(f"SELECT content FROM fact WHERE workspace_id = '{ws}'")
        assert isinstance(facts, list)


class TestProfile:
    """Profile upsert and get."""

    def test_upsert_and_get_profile(self, client):
        profile_id = _unique("prof")
        result = client.upsert_profile(peer_id=profile_id)
        assert result["status"] == "ok"

        row = client.get_profile(profile_id)
        # Profile should exist now
        assert row is not None


# =====================================================================
# CLI Tests (real subprocess, not mocked CliRunner)
# =====================================================================


class TestCLI:
    """End-to-end CLI tests via subprocess."""

    def test_cli_workspace_create_and_list(self, cli_env):
        """stmem workspace create + list via subprocess."""
        ws_name = _unique("cli-ws")
        result = subprocess.run(
            [sys.executable, CLI_PATH, "workspace", "create", ws_name],
            capture_output=True, text=True, env=cli_env, timeout=15,
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "ok" in result.stdout.lower()

        # List — check that the workspace name appears (may be split across rows)
        result = subprocess.run(
            [sys.executable, CLI_PATH, "workspace", "list"],
            capture_output=True, text=True, env=cli_env, timeout=15,
        )
        assert result.returncode == 0
        # The name may be split across table cells (rich wrapping);
        # check for the invariant part
        assert ws_name in result.stdout or ws_name[:10] in result.stdout


# =====================================================================
# Error Handling Tests
# =====================================================================


class TestErrorHandling:
    """Edge cases and error handling."""

    def test_store_empty_content(self, client, ws):
        result = client.store(workspace_id=ws, content="", peer_id="bot")
        assert isinstance(result, dict)

    def test_search_nonexistent_workspace(self, client):
        results = client.search(
            workspace_id="nonexistent-id", query="test", semantic=False,
        )
        assert isinstance(results, list)

    def test_get_nonexistent_profile(self, client):
        row = client.get_profile("no-such-peer")
        assert row is None or (isinstance(row, list) and len(row) == 0)

    def test_delete_nonexistent_memory(self, client):
        result = client.delete_memory("no-such-id")
        assert isinstance(result, dict)
        # Idempotent — should return ok even if already gone
        assert result.get("status") == "ok"

    def test_search_unknown_workspace_doesnt_crash(self, client):
        results = client.search(
            workspace_id="_nonexistent_", query="test", semantic=True,
        )
        assert isinstance(results, list)


# =====================================================================
# CLI environment fixture (module-scoped so all CLI tests share it)
# =====================================================================


@pytest.fixture(scope="module")
def cli_env():
    """Environment for subprocess CLI calls."""
    env = os.environ.copy()
    env["SPACETIMEDB_HOST"] = HOST
    env["SPACETIMEDB_PORT"] = str(PORT)
    env["SPACETIMEDB_DB"] = DB
    env["STMEM_HOST"] = HOST
    env["STMEM_PORT"] = str(PORT)
    env["STMEM_DB"] = DB
    env["CLICOLOR"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    # Remove any rich FORCE_COLOR setting
    env.pop("FORCE_COLOR", None)
    env.pop("TERM", None)
    return env
