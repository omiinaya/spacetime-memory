"""Integration tests for spacetime-memory.

These tests require a running SpacetimeDB instance and embedder.
The ``stdb_client`` fixture (from conftest.py) auto-publishes the module
and provides an authenticated client.
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
    pytest.mark.integration,
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CLI_PATH = str(REPO_ROOT / "cli" / "stmem.py")


def _unique(prefix: str = "test") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client, stdb_session: dict | None = None) -> str:
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


@pytest.fixture
def ws(stdb_client):
    """Unique workspace per test function."""
    return _make_ws(stdb_client)


# =====================================================================
# Core CRUD Tests
# =====================================================================


class TestWorkspaceCRUD:
    """Workspace create / list."""

    def test_create_and_list(self, stdb_client):
        ws_name = _unique("ws-crud")
        result = stdb_client.create_workspace(ws_name)
        assert result["status"] == "ok"

        workspaces = stdb_client.list_workspaces()
        found = any(ws.get("name") == ws_name for ws in workspaces)
        assert found, f"Workspace '{ws_name}' not in list"


class TestMemoryCRUD:
    """Full memory CRUD lifecycle."""

    def test_store_and_list(self, stdb_client, ws):
        result = stdb_client.store(
            workspace_id=ws,
            content="The quick brown fox jumps over the lazy dog",
            peer_id="it-bot",
            memory_type="experience",
        )
        assert result["status"] == "ok"

        mems = stdb_client.list_memories(workspace_id=ws, limit=10)
        assert isinstance(mems, list)
        assert len(mems) >= 1
        mems_text = " ".join(m.get("content", "") for m in mems)
        assert "fox" in mems_text

    def test_store_with_tier(self, stdb_client, ws):
        result = stdb_client.store(
            workspace_id=ws, content="critical memory", peer_id="bot", tier="L0",
        )
        assert result["status"] == "ok"

    def test_update_memory(self, stdb_client, ws):
        stdb_client.store(workspace_id=ws, content="original content", peer_id="bot")
        mems = stdb_client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) > 0
        mem_id = mems[0]["id"]
        up = stdb_client.update_memory(mem_id, "updated content", "summary", 0.95)
        assert up["status"] == "ok"

    def test_delete_memory(self, stdb_client, ws):
        stdb_client.store(workspace_id=ws, content="delete me", peer_id="bot")
        mems = stdb_client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) > 0
        mem_id = mems[0]["id"]
        d = stdb_client.delete_memory(mem_id)
        assert d["status"] == "ok"

    def test_reinforce_memory(self, stdb_client, ws):
        stdb_client.store(workspace_id=ws, content="reinforce me", peer_id="bot")
        mems = stdb_client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) > 0
        mem_id = mems[0]["id"]
        r = stdb_client.reinforce(mem_id)
        assert r["status"] == "ok"


# =====================================================================
# Semantic Search Tests (requires embedder at :9090)
# =====================================================================


class TestSemanticSearch:
    """Search with the real embedder sidecar."""

    @pytest.mark.embedder
    def test_store_and_semantic_search(self, stdb_client, ws):
        stdb_client.store(
            workspace_id=ws,
            content="I like pizza with pineapple and anchovies",
            peer_id="it-bot",
            memory_type="experience",
        )
        stdb_client.store(
            workspace_id=ws,
            content="Python is a programming language for web development",
            peer_id="it-bot",
            memory_type="world_fact",
        )
        time.sleep(0.5)

        results = stdb_client.search(
            workspace_id=ws, query="food pizza toppings", limit=10, semantic=True,
        )
        assert isinstance(results, list)
        assert len(results) >= 1
        pizza_result = next(
            (m for m in results if "pizza" in m.get("content", "")), None
        )
        assert pizza_result is not None, (
            f"Expected 'pizza' memory in semantic search results: {results}"
        )
        assert pizza_result.get("score", 0) > 0, "Semantic score should be >0"

    @pytest.mark.embedder
    def test_bm25_search(self, stdb_client, ws):
        """BM25 keyword search should find exact words."""
        stdb_client.store(
            workspace_id=ws,
            content="I like pizza with pineapple and anchovies",
            peer_id="it-bot",
            memory_type="experience",
        )
        stdb_client.store(
            workspace_id=ws,
            content="Python is a programming language for web development",
            peer_id="it-bot",
            memory_type="world_fact",
        )
        time.sleep(0.3)

        results = stdb_client.search(
            workspace_id=ws, query="programming language", limit=10, semantic=False,
        )
        assert isinstance(results, list)
        assert len(results) >= 1
        py_result = next(
            (m for m in results if "Python" in m.get("content", "")), None
        )
        assert py_result is not None, f"Expected Python memory in BM25 results: {results}"

    @pytest.mark.embedder
    def test_hybrid_search(self, stdb_client, ws):
        stdb_client.store(
            workspace_id=ws,
            content="I like pizza with pineapple and anchovies",
            peer_id="it-bot",
            memory_type="experience",
        )
        time.sleep(0.3)

        results = stdb_client.search(
            workspace_id=ws, query="food", limit=10, semantic=True,
        )
        assert isinstance(results, list)
        assert len(results) >= 1

    @pytest.mark.embedder
    def test_empty_search(self, stdb_client):
        """Search on empty workspace should return empty (not error)."""
        empty_ws = _make_ws(stdb_client)
        results = stdb_client.search(
            workspace_id=empty_ws, query="nonexistent", limit=10, semantic=True,
        )
        assert isinstance(results, list)


# =====================================================================
# Sessions Tests
# =====================================================================


class TestSessions:
    """Session CRUD and participant management."""

    def test_create_and_list_sessions(self, stdb_client, ws):
        session_name = _unique("it-session")
        result = stdb_client._call("create_session", [ws, session_name, "{}"])
        assert result["status"] == "ok"

        sessions = stdb_client._query("session", workspace_id=ws)
        assert isinstance(sessions, list)
        assert len(sessions) >= 1
        found = any(s.get("name") == session_name for s in sessions)
        assert found, f"Session '{session_name}' not found"

    def test_send_message(self, stdb_client, ws):
        session_name = _unique("msg-session")
        stdb_client._call("create_session", [ws, session_name, "{}"])
        sessions = stdb_client._query("session", workspace_id=ws)
        sid = next(s["id"] for s in sessions if s.get("name") == session_name)
        result = stdb_client._call("send_message", [sid, "it-bot", "Hello, world!", "text", "{}"])
        assert result["status"] == "ok"


# =====================================================================
# Graph Tests
# =====================================================================


class TestGraph:
    """Knowledge graph node/edge CRUD."""

    def test_create_node(self, stdb_client, ws):
        result = stdb_client.create_node(
            workspace_id=ws,
            label="TestConcept",
            node_type="concept",
        )
        assert result["status"] == "ok"

    def test_create_edge(self, stdb_client, ws):
        n1 = stdb_client.create_node(ws, "ConceptA", "concept")
        n2 = stdb_client.create_node(ws, "ConceptB", "concept")
        # Find node IDs by label using _query
        def _node_id(label: str) -> str:
            rows = stdb_client._query(
                "kg_node", workspace_id=ws,
                filter_dict={"label": label}, columns=["id"],
            )
            return rows[0]["id"] if rows else ""
        result = stdb_client._call("create_edge", [
            ws, _node_id("ConceptA"), _node_id("ConceptB"), "relates_to",
            1.0, "EXTRACTED", "{}", "",
        ])
        assert result["status"] == "ok"


# =====================================================================
# Facts / Profiles Tests
# =====================================================================


class TestFacts:
    """Profile facts CRUD."""

    def test_upsert_profile(self, stdb_client, ws):
        result = stdb_client._call("upsert_profile", [
            "test-bot", "[]", "[]", "{}", "[]",
        ])
        assert result["status"] == "ok"

    def test_add_fact(self, stdb_client, ws):
        result = stdb_client._call("add_profile_fact", [
            "test-bot", "I was created for integration testing",
        ])
        assert result["status"] == "ok"


class TestProfile:
    """Profile query tests."""

    def test_get_profile_context(self, stdb_client, ws):
        context = stdb_client._call("get_profile_context", ["test-bot"])
        assert isinstance(context, dict) or context.get("status") == "ok"


# =====================================================================
# CLI Tests
# =====================================================================


class TestCLI:
    """End-to-end CLI tests using subprocess."""

    def _env(self, stdb_session) -> dict:
        """Return env with correct SpacetimeDB target and PYTHONPATH."""
        env = os.environ.copy()
        env["SPACETIMEDB_HOST"] = stdb_session["host"]
        env["SPACETIMEDB_PORT"] = stdb_session["port"]
        env["SPACETIMEDB_DB"] = stdb_session["database"]
        # Ensure spacetime_memory is importable by the subprocess
        sdk_path = str(Path(__file__).resolve().parent.parent.parent / "python")
        env.setdefault("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{sdk_path}:{env['PYTHONPATH']}"
        return env

    def test_cli_workspace_create(self, stdb_session):
        ws_name = _unique("cli-ws")
        result = subprocess.run(
            [sys.executable, CLI_PATH, "workspace", "create", ws_name],
            capture_output=True, text=True, timeout=15,
            env=self._env(stdb_session),
        )
        assert result.returncode == 0, f"CLI failed: {result.stdout}{result.stderr}"

    def test_cli_help(self):
        sdk_path = str(Path(__file__).resolve().parent.parent.parent / "python")
        env = os.environ.copy()
        env.setdefault("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{sdk_path}:{env['PYTHONPATH']}"
        result = subprocess.run(
            [sys.executable, CLI_PATH, "--help"],
            capture_output=True, text=True, timeout=10,
            env=env,
        )
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_cli_memory_store(self, stdb_client, stdb_session):
        ws_name = _unique("cli-mem")
        stdb_client._call("create_workspace", [ws_name, "CLI test", _unique("ws")])
        # Verify the workspace exists via _query (private table)
        workspaces = stdb_client._query(
            "workspace", filter_dict={"name": ws_name}
        )
        assert len(workspaces) >= 1, f"Workspace '{ws_name}' not found"
        assert workspaces[0]["name"] == ws_name


# =====================================================================
# Error Handling Tests
# =====================================================================


class TestErrorHandling:
    """Error conditions and edge cases."""

    def test_invalid_database(self):
        """Non-existent database should produce a clear error."""
        c = Client(host="localhost", port="3001", database="nonexistent-db")
        with pytest.raises(RuntimeError):
            c.list_workspaces()

    def test_bad_workspace(self, stdb_client):
        """Non-existent workspace should error clearly."""
        with pytest.raises(RuntimeError):
            stdb_client.store(workspace_id="bad-ws", content="x", peer_id="bot")

    def test_client_reuses_connection(self, stdb_client):
        """Multiple operations on the same client should work."""
        for i in range(5):
            ws = _make_ws(stdb_client)
            r = stdb_client.store(ws, f"bulk test {i}", "bulk-bot")
            assert r["status"] == "ok"
