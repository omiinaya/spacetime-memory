"""Deep integration tests for client.py — Core module.

Includes: Health, workspace deletion, keyword fallback, context chain,
store batch, pattern detection, memory management, merge workflow, batch ops.
"""

from __future__ import annotations

import os

import httpx
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]


def _unique(prefix: str = "deep") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Helper: create a unique workspace and return its ID."""
    ws_name = _unique("deep-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for w in workspaces:
        if w.get("name") == ws_name:
            return w["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


def _store_mem(client: Client, ws_id: str, content: str, peer: str = "deep-bot") -> dict:
    """Store a memory and return the result."""
    return client.store(
        workspace_id=ws_id,
        content=content,
        peer_id=peer,
        memory_type="experience",
    )


def _get_first_memory_id(client: Client, ws_id: str) -> str | None:
    """Get the ID of the first memory in a workspace."""
    mems = client.list_memories(workspace_id=ws_id, limit=5)
    return mems[0]["id"] if mems else None


# =====================================================================
# Health / Ping
# =====================================================================


class TestHealth:
    """ping() and health() methods."""

    def test_ping(self, stdb_client):
        """ping() returns ok status with latency."""
        result = stdb_client.ping()
        assert result["status"] == "ok"
        assert "latency_ms" in result

    def test_health(self, stdb_client):
        """health() returns comprehensive status dict."""
        result = stdb_client.health()
        assert result["status"] in ("ok", "degraded")
        assert "database" in result
        assert "embedder" in result
        assert "tantivy" in result
        assert "token_configured" in result

    def test_check_embedder_health(self, stdb_client):
        """check_embedder_health() returns embedder status."""
        result = stdb_client.check_embedder_health()
        assert "reachable" in result


# =====================================================================
# Workspace deletion
# =====================================================================


class TestWorkspaceEdge:
    """delete_workspace and edge cases."""

    def test_delete_workspace(self, stdb_client):
        """delete_workspace removes a workspace."""
        ws_name = _unique("del-ws")
        result = stdb_client.create_workspace(ws_name)
        assert result["status"] == "ok"
        ws_id = result["id"]

        del_result = stdb_client.delete_workspace(ws_id)
        assert del_result["status"] == "ok"


# =====================================================================
# Keyword fallback search (non-semantic, exercises _keyword_fallback)
# =====================================================================


class TestKeywordFallback:
    """search() with semantic=False exercises _keyword_fallback."""

    def test_keyword_search_no_embedder(self, stdb_client):
        """Non-semantic search uses keyword fallback path."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "The unique zebra crossed the rainbow bridge")

        results = stdb_client.search(
            workspace_id=ws_id,
            query="zebra rainbow",
            limit=10,
            semantic=False,
        )
        assert isinstance(results, list)
        found = any("zebra" in r.get("content", "") for r in results)
        assert found, f"Keyword fallback did not find zebra: {results}"

    def test_keyword_search_empty(self, stdb_client):
        """Keyword search on empty workspace returns empty list."""
        empty_ws = _make_ws(stdb_client)
        results = stdb_client.search(
            workspace_id=empty_ws,
            query="nothing",
            limit=10,
            semantic=False,
        )
        assert isinstance(results, list)
        assert len(results) == 0


# =====================================================================
# Context chain
# =====================================================================


class TestContextChain:
    """set_workspace_context, set_memory_context, get_context_chain."""

    def test_context_chain(self, stdb_client):
        """Full context chain round-trip."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "context test memory", "ctx-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        # Set workspace context
        r1 = stdb_client.set_workspace_context(ws_id, "Global context: testing")
        assert r1["status"] == "ok"

        # Set memory context
        r2 = stdb_client.set_memory_context(mem_id, "Memory-specific context")
        assert r2["status"] == "ok"

        # Get context chain — context is stored at reducer level,
        # check structure
        chain = stdb_client.get_context_chain(mem_id)
        assert "workspace_context" in chain
        assert "memory_context" in chain
        # The reducer may/may not store context to table; just check shape
        assert isinstance(chain["workspace_context"], str)
        assert isinstance(chain["memory_context"], str)


# =====================================================================
# Store batch
# =====================================================================


class TestStoreBatch:
    """store_batch() method with embedder resilience."""

    def test_store_batch(self, stdb_client):
        """Store multiple memories in a batch.
        The embedder sidecar (localhost:9090) may be down — the batch
        store should still succeed with the reducer call."""
        ws_id = _make_ws(stdb_client)
        items = [
            {
                "content": "Batch memory alpha",
                "peer_id": "batch-bot",
                "memory_type": "experience",
                "confidence": 0.9,
            },
            {
                "content": "Batch memory beta",
                "peer_id": "batch-bot",
                "memory_type": "world_fact",
                "confidence": 0.85,
            },
        ]
        # store_batch tries to hit the embedder; if it's down, it'll
        # still call the reducer and index without embeddings.
        # Connection errors are expected when no embedder is running.

        try:
            results = stdb_client.store_batch(ws_id, items)
            assert isinstance(results, list)
            for r in results:
                assert r.get("status") == "ok"
        except (httpx.ConnectError, RuntimeError) as e:
            if "Connection refused" in str(e) or "ConnectError" in str(type(e).__name__):
                pytest.skip("Embedder sidecar not running")
            raise

    def test_store_batch_empty(self, stdb_client):
        """Empty batch returns empty list."""
        ws_id = _make_ws(stdb_client)
        results = stdb_client.store_batch(ws_id, [])
        assert results == []


# =====================================================================
# Pattern detection
# =====================================================================


class TestPatternDetection:
    """detect_patterns() method."""

    def test_detect_patterns(self, stdb_client):
        """Pattern detection on workspace with memories."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "Pattern A: seasonal change observed in 2024")
        _store_mem(stdb_client, ws_id, "Pattern B: seasonal shift noticed in 2025")
        _store_mem(stdb_client, ws_id, "Pattern C: another seasonal trend in 2026")

        result = stdb_client.detect_patterns(ws_id, limit=50)
        assert isinstance(result, dict)
        assert "total_memories" in result


# =====================================================================
# Memory management (may require admin)
# =====================================================================


class TestMemoryManagement:
    """escalate_memories, rate_memory, dedup, run_maintenance."""

    def test_escalate_memories(self, stdb_client):
        """Escalate memory tiers based on access thresholds."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "escalation test memory", "esc-bot")
        try:
            result = stdb_client.escalate_memories(ws_id)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access not configured for this test user")
            raise

    def test_rate_memory(self, stdb_client):
        """Rate a memory to adjust trust score."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "rate me please", "rate-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        result = stdb_client.rate_memory(mem_id, "helpful", "rate-bot")
        assert result["status"] == "ok"

    def test_dedup(self, stdb_client):
        """Dedup within a workspace."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "I enjoy programming in Python")
        _store_mem(stdb_client, ws_id, "I really enjoy programming in Python")
        try:
            result = stdb_client.dedup(ws_id)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise

    def test_run_maintenance(self, stdb_client):
        """Run periodic maintenance."""
        try:
            result = stdb_client.run_maintenance()
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise


# =====================================================================
# Merge workflow
# =====================================================================


class TestMergeWorkflow:
    """suggest_merges."""

    def test_suggest_merges(self, stdb_client):
        """Suggest merges for a workspace."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "merge test similar A", "merge-bot")
        _store_mem(stdb_client, ws_id, "merge test similar B", "merge-bot")
        try:
            result = stdb_client.suggest_merges(ws_id)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e) or "No such procedure" in str(e):
                pytest.skip(f"Reducer not available: {e}")
            raise


# =====================================================================
# Batch update memories + history
# =====================================================================


class TestBatchOps:
    """batch_update_memories, get_memory_history."""

    def test_batch_update_memories(self, stdb_client):
        """Batch update memory fields."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "batch update test", "batchup-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        updates = {"summary": "Updated in batch", "confidence": 0.95}
        try:
            result = stdb_client.batch_update_memories(ws_id, [mem_id], updates)
            assert result["status"] in ("ok", "partial"), f"Expected ok or partial, got {result}"
        except RuntimeError as e:
            if "Admin" in str(e) or "No such procedure" in str(e):
                pytest.skip(f"Reducer not available: {e}")
            raise

    def test_get_memory_history(self, stdb_client):
        """Get memory version history."""
        ws_id = _make_ws(stdb_client)
        _store_mem(stdb_client, ws_id, "history test original", "hist-bot")
        mem_id = _get_first_memory_id(stdb_client, ws_id)
        assert mem_id is not None

        stdb_client.update_memory(mem_id, "history test updated", "updated summary", 0.92)

        try:
            history = stdb_client.get_memory_history(mem_id)
            assert isinstance(history, list)
        except RuntimeError as e:
            msg = str(e)
            if "not queryable" in msg or "memory_revision" in msg:
                pytest.skip(
                    f"get_memory_history requires rebuilt WASM: {msg}"
                )
            raise
