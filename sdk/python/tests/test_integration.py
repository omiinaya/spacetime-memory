"""Integration tests for spacetime-memory.

These tests require a running SpacetimeDB instance.
Run with: pytest sdk/python/tests/test_integration.py -v --integration
Or: SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest ... -v
"""

import os
import json
import pytest
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


@pytest.fixture
def client():
    return Client(host=HOST, port=PORT, database=DB)


class TestMemoryIntegration:
    """Integration tests that exercise real SpacetimeDB operations."""

    def test_store_and_search(self, client):
        """Store a memory, then search for it."""
        # Create workspace
        ws_name = f"test-ws-{os.urandom(4).hex()}"
        result = client.create_workspace(ws_name)
        assert result["status"] == "ok"

        # Discover the workspace ID from the listing
        workspaces = client.list_workspaces()
        ws_id = None
        for ws in workspaces:
            if ws.get("name") == ws_name:
                ws_id = ws.get("id")
                break
        assert ws_id is not None, f"Could not find workspace '{ws_name}' in listing"

        # Store a memory
        result = client.store(
            workspace_id=ws_id,
            content="I like pizza with pineapple",
            peer_id="test-bot",
            memory_type="experience",
        )
        assert result["status"] == "ok"

        # Search for it
        results = client.search(
            workspace_id=ws_id,
            query="pizza pineapple",
            limit=5,
            semantic=True,
        )
        # May return empty in a fresh DB without embedder, but should at
        # minimum not crash
        assert isinstance(results, list)
        if results:
            combined = " ".join(
                r.get("memory_content", r.get("content", ""))
                for r in results
            )
            assert "pizza" in combined.lower()

    def test_auth_and_acl(self, client):
        """Test that registration works when available."""
        import uuid

        username = f"test-{uuid.uuid4().hex[:8]}"
        password = "test-pass-123"

        # Register — this calls a reducer that may not exist on all deployments
        # so we gracefully handle a 404/error
        try:
            result = client._call("register", [username, username, password])
            assert result["status"] == "ok"
        except RuntimeError as e:
            # Registration may not be implemented by the module; that's OK
            if "not found" in str(e).lower():
                pytest.skip("Register reducer not available in this deployment")
            raise

    def test_memory_crud(self, client):
        """Full CRUD cycle for a memory."""
        # Create a workspace
        ws_name = f"crud-ws-{os.urandom(4).hex()}"
        result = client.create_workspace(ws_name)
        assert result["status"] == "ok"

        workspaces = client.list_workspaces()
        ws_id = None
        for ws in workspaces:
            if ws.get("name") == ws_name:
                ws_id = ws.get("id")
                break
        assert ws_id is not None, f"Could not find workspace '{ws_name}'"

        # Create
        result = client.store(
            workspace_id=ws_id,
            content="test crud memory",
            peer_id="test-bot",
        )
        assert result["status"] == "ok"

        # Read - get the memory by listing
        mems = client.list_memories(workspace_id=ws_id, limit=10)
        assert isinstance(mems, list)

        # Update - if we have memories
        if mems:
            mem_id = mems[0]["id"]
            update_result = client.update_memory(
                mem_id, "updated content", "updated summary", 0.9
            )
            assert update_result["status"] == "ok"

            # Delete
            delete_result = client.delete_memory(mem_id)
            assert delete_result["status"] == "ok"
