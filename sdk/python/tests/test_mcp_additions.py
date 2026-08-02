# ── require_api_key decorator ─────────────────────────────────────────────

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)


class TestRequireApiKey:
    """Tests for the require_api_key decorator."""

    def test_no_key_sync_passes_through(self):
        """When MCP_API_KEY is empty (default), sync decorator passes through."""
        from server.mcp.main import require_api_key

        @require_api_key
        def my_tool(arg1, kw1=None):
            return f"{arg1}-{kw1}"

        result = my_tool("hello", kw1="world")
        assert result == "hello-world"

    def test_no_key_async_passes_through(self):
        """When MCP_API_KEY is empty, async decorator passes through."""
        from server.mcp.main import require_api_key

        @require_api_key
        async def my_async_tool():
            return "async_ok"

        import asyncio

        result = asyncio.run(my_async_tool())
        assert result == "async_ok"

    def test_valid_key_via_args(self, monkeypatch):
        """Valid Bearer token via args context."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "authorized"

        result = my_tool(MockCtx())
        assert result == "authorized"

    def test_valid_key_via_kwargs_ctx(self, monkeypatch):
        """Valid Bearer token via ctx kwarg."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"Authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx=None):
            return "authorized"

        result = my_tool(ctx=MockCtx())
        assert result == "authorized"

    def test_wrong_key_raises_error(self, monkeypatch):
        """Wrong Bearer token raises PermissionError."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer wrong-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "should_not_reach"

        import pytest

        with pytest.raises(PermissionError, match="Unauthorized"):
            my_tool(MockCtx())

    def test_no_request_context_stdio(self, monkeypatch):
        """No request context (stdio mode) should pass through even with key set."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        @require_api_key
        def my_tool(arg):
            return arg

        result = my_tool("stdio_value")
        assert result == "stdio_value"

    def test_args_without_request_property(self, monkeypatch):
        """First arg without .request attribute should not match context."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        @require_api_key
        def my_tool(x, y):
            return f"{x}-{y}"

        result = my_tool("a", "b")
        assert result == "a-b"

    def test_async_with_valid_key(self, monkeypatch):
        """Async function with valid key should pass."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"Authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_async_tool(ctx):
            return "async_authorized"

        import asyncio

        result = asyncio.run(my_async_tool(MockCtx()))
        assert result == "async_authorized"

    def test_async_wrong_key_raises_error(self, monkeypatch):
        """Async function with wrong key raises PermissionError."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer wrong"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_async_tool(ctx):
            return "should_not_reach"

        import asyncio

        import pytest

        with pytest.raises(PermissionError, match="Unauthorized"):
            asyncio.run(my_async_tool(MockCtx()))

    def test_context_via_kwargs_context_key(self, monkeypatch):
        """Valid key via kwargs key 'context'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(context=None):
            return "authorized"

        result = my_tool(context=MockCtx())
        assert result == "authorized"

    def test_context_via_kwargs_request_key(self, monkeypatch):
        """Valid key via kwargs key 'request'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockRequestObj:
            request = MockRequest()

        @require_api_key
        def my_tool(request=None):
            return "authorized"

        result = my_tool(request=MockRequestObj())
        assert result == "authorized"

    def test_scope_style_headers(self, monkeypatch):
        """When request has 'scope' instead of 'headers'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequestMeta:
            scope = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequestMeta()

        @require_api_key
        def my_tool(ctx):
            return "scoped_ok"

        result = my_tool(MockCtx())
        assert result == "scoped_ok"

    def test_non_dict_headers_with_get(self, monkeypatch):
        """When headers has .get() method but is not a dict."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from unittest.mock import MagicMock

        from server.mcp.main import require_api_key

        mock_headers = MagicMock()
        mock_headers.get.return_value = "Bearer test-key"

        class MockRequest:
            headers = mock_headers

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "ok"

        result = my_tool(MockCtx())
        assert result == "ok"

    def test_no_key_skip_auth_message_logged(self, monkeypatch):
        """Line 62: when MCP_API_KEY is set, the log message is triggered.
        We simulate by checking that the module's MCP_API_KEY is non-empty."""
        # Already tested implicitly: when MCP_API_KEY is set, the log runs.
        # The line is at module level, so it runs when the module loads
        # with MCP_API_KEY set. We just need to ensure the import triggers it.
        monkeypatch.setenv("MCP_API_KEY", "trigger-key")
        # Reload to trigger module-level code with key set
        import importlib

        import server.mcp.main as mcp_main

        importlib.reload(mcp_main)
        # Key should be non-empty after reload
        assert mcp_main.MCP_API_KEY == "trigger-key"


# ── get_client ────────────────────────────────────────────────────────────


class TestGetClient:
    """Tests for the get_client() singleton."""

    def test_first_call_creates_client(self, monkeypatch):
        """First call to get_client should create a Client."""
        monkeypatch.setattr("server.mcp.main._client", None)
        from server.mcp.main import get_client

        client = get_client()
        from spacetime_memory import Client

        assert isinstance(client, Client)

    def test_second_call_returns_cached(self, monkeypatch):
        """Second call returns cached client (same object)."""
        monkeypatch.setattr("server.mcp.main._client", None)
        from server.mcp.main import get_client

        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    def test_get_client_global_reset(self, monkeypatch):
        """After resetting _client to None, get_client creates new instance."""
        monkeypatch.setattr("server.mcp.main._client", None)
        from server.mcp.main import get_client

        c1 = get_client()
        monkeypatch.setattr("server.mcp.main._client", None)
        c2 = get_client()
        assert c1 is not c2


# ── _embed / _embed_batch ─────────────────────────────────────────────────


class TestEmbed:
    """Tests for _embed and _embed_batch convenience wrappers."""

    def test_embed_calls_client(self, mock_mcp_client):
        from server.mcp.main import _embed

        mock_mcp_client._embed.return_value = [0.1, 0.2, 0.3]
        result = _embed("hello world")
        assert result == [0.1, 0.2, 0.3]
        mock_mcp_client._embed.assert_called_once_with("hello world")

    def test_embed_batch_calls_client(self, mock_mcp_client):
        from server.mcp.main import _embed_batch

        mock_mcp_client._embed_batch.return_value = [[0.1], [0.2]]
        result = _embed_batch(["text1", "text2"])
        assert result == [[0.1], [0.2]]
        mock_mcp_client._embed_batch.assert_called_once_with(["text1", "text2"])

    def test_embed_empty_string(self, mock_mcp_client):
        from server.mcp.main import _embed

        mock_mcp_client._embed.return_value = []
        result = _embed("")
        assert result == []

    def test_embed_batch_empty_list(self, mock_mcp_client):
        from server.mcp.main import _embed_batch

        mock_mcp_client._embed_batch.return_value = []
        result = _embed_batch([])
        assert result == []


# ── Workspace tools ───────────────────────────────────────────────────────


class TestCreateWorkspace:
    """Tests for the create_workspace MCP tool."""

    def test_creates_workspace(self, mock_mcp_client):
        from server.mcp.main import create_workspace

        mock_mcp_client.create_workspace.return_value = {
            "id": "ws_new",
            "name": "Test",
            "description": "A test workspace",
        }
        result = create_workspace(name="Test", description="A test workspace")
        assert result["name"] == "Test"
        mock_mcp_client.create_workspace.assert_called_once_with(
            "Test", "A test workspace"
        )

    def test_creates_with_default_description(self, mock_mcp_client):
        from server.mcp.main import create_workspace

        mock_mcp_client.create_workspace.return_value = {"id": "ws2", "name": "Minimal"}
        result = create_workspace(name="Minimal")
        assert result["name"] == "Minimal"
        mock_mcp_client.create_workspace.assert_called_once_with("Minimal", "")


class TestListWorkspaces:
    """Tests for the list_workspaces MCP tool."""

    def test_lists_all(self, mock_mcp_client):
        from server.mcp.main import list_workspaces

        mock_mcp_client.list_workspaces.return_value = [
            {"id": "ws1", "name": "Alpha"},
            {"id": "ws2", "name": "Beta"},
        ]
        result = list_workspaces()
        assert len(result) == 2
        assert result[0]["name"] == "Alpha"
        mock_mcp_client.list_workspaces.assert_called_once_with()

    def test_empty_list(self, mock_mcp_client):
        from server.mcp.main import list_workspaces

        mock_mcp_client.list_workspaces.return_value = []
        result = list_workspaces()
        assert result == []


class TestUpdateWorkspace:
    """Tests for the update_workspace MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_workspace

        mock_mcp_client.update_workspace.return_value = {"status": "ok"}
        result = update_workspace(id="ws1", name="New Name", description="New desc")
        assert result["status"] == "ok"
        mock_mcp_client.update_workspace.assert_called_once_with(
            "ws1", "New Name", "New desc"
        )


class TestSetWorkspaceVisibility:
    """Tests for the set_workspace_visibility MCP tool."""

    def test_set_public(self, mock_mcp_client):
        from server.mcp.main import set_workspace_visibility

        mock_mcp_client.set_workspace_visibility.return_value = {"status": "ok"}
        result = set_workspace_visibility(workspace_id="ws1", is_public=True)
        assert result["status"] == "ok"
        mock_mcp_client.set_workspace_visibility.assert_called_once_with("ws1", True)

    def test_set_private(self, mock_mcp_client):
        from server.mcp.main import set_workspace_visibility

        mock_mcp_client.set_workspace_visibility.return_value = {"status": "ok"}
        set_workspace_visibility(workspace_id="ws1", is_public=False)
        mock_mcp_client.set_workspace_visibility.assert_called_once_with("ws1", False)


class TestGetWorkspaceContext:
    """Tests for the get_workspace_context MCP tool."""

    def test_gets_context(self, mock_mcp_client):
        from server.mcp.main import get_workspace_context

        mock_mcp_client.get_workspace_context.return_value = {
            "workspace_id": "ws1",
            "context": "Project context",
        }
        result = get_workspace_context(workspace_id="ws1")
        assert result["context"] == "Project context"
        mock_mcp_client.get_workspace_context.assert_called_once_with("ws1")


# ── Memory tools ──────────────────────────────────────────────────────────


class TestStoreMemory:
    """Tests for the store_memory MCP tool."""

    def test_stores_minimal(self, mock_mcp_client):
        from server.mcp.main import store_memory

        mock_mcp_client.store.return_value = {"id": "mem_new"}
        result = store_memory(workspace_id="ws1", peer_id="peer1", content="Test memory")
        assert result["id"] == "mem_new"
        mock_mcp_client.store.assert_called_once()

    def test_stores_with_all_params(self, mock_mcp_client):
        from server.mcp.main import store_memory

        mock_mcp_client.store.return_value = {"id": "mem2"}
        store_memory(
            workspace_id="ws1",
            peer_id="peer1",
            observer_id="obs1",
            memory_type="observation",
            content="Observed something",
            summary="Summary",
            entities_json='[{"name": "Entity1"}]',
            confidence=0.95,
            source_session_id="sess1",
            source_message_id="msg1",
            tier="L0",
            images_json="[]",
        )
        call_kw = mock_mcp_client.store.call_args[1]
        assert call_kw["workspace_id"] == "ws1"
        assert call_kw["memory_type"] == "observation"
        assert call_kw["confidence"] == 0.95
        assert call_kw["tier"] == "L0"


class TestSearchMemories:
    """Tests for the search_memories MCP tool."""

    def test_searches(self, mock_mcp_client):
        from server.mcp.main import search_memories

        mock_mcp_client.search.return_value = [
            {"id": "m1", "content": "Result 1"},
        ]
        result = search_memories(workspace_id="ws1", query_text="test")
        assert len(result) == 1
        mock_mcp_client.search.assert_called_once()

    def test_with_filters(self, mock_mcp_client):
        from server.mcp.main import search_memories

        mock_mcp_client.search.return_value = []
        search_memories(
            workspace_id="ws1",
            query_text="ML",
            memory_type="note",
            tier="L1",
            limit=10,
            rerank=True,
            entity_types=["memory"],
            before=1000.0,
            after=100.0,
            return_schema="llm",
        )
        call_kw = mock_mcp_client.search.call_args[1]
        assert call_kw["memory_type"] == "note"
        assert call_kw["tier"] == "L1"
        assert call_kw["rerank"] is True
        assert call_kw["entity_types"] == ["memory"]


class TestHybridSearch:
    """Tests for the hybrid_search MCP tool."""

    def test_hybrid(self, mock_mcp_client):
        from server.mcp.main import hybrid_search

        mock_mcp_client.search.return_value = [{"id": "h1"}]
        result = hybrid_search(workspace_id="ws1", query_text="AI")
        assert len(result) == 1
        mock_mcp_client.search.assert_called_once()

    def test_with_params(self, mock_mcp_client):
        from server.mcp.main import hybrid_search

        mock_mcp_client.search.return_value = []
        hybrid_search(
            workspace_id="ws1",
            query_text="test",
            memory_type="note",
            tier="L0",
            limit=5,
            strategies="semantic,keyword",
            rerank=False,
        )
        call_kw = mock_mcp_client.search.call_args[1]
        assert call_kw["limit"] == 5
        assert call_kw["rerank"] is False


class TestGetMemory:
    """Tests for the get_memory MCP tool."""

    def test_gets_memory(self, mock_mcp_client):
        from server.mcp.main import get_memory

        mock_mcp_client.get_memory.return_value = [{"id": "m1", "content": "Test"}]
        result = get_memory(id="m1")
        assert result[0]["id"] == "m1"
        mock_mcp_client.get_memory.assert_called_once_with("m1")

    def test_not_found(self, mock_mcp_client):
        from server.mcp.main import get_memory

        mock_mcp_client.get_memory.return_value = []
        result = get_memory(id="nonexistent")
        assert result == []


class TestGetMemoryHistory:
    """Tests for the get_memory_history MCP tool."""

    def test_gets_history(self, mock_mcp_client):
        from server.mcp.main import get_memory_history

        mock_mcp_client.get_memory_history.return_value = [
            {"version": 1, "content": "v1"},
            {"version": 2, "content": "v2"},
        ]
        result = get_memory_history(memory_id="m1")
        assert len(result) == 2
        mock_mcp_client.get_memory_history.assert_called_once_with("m1")


class TestUpdateMemory:
    """Tests for the update_memory MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_memory

        mock_mcp_client.update_memory.return_value = {"status": "ok"}
        result = update_memory(memory_id="m1", content="new", summary="sum", confidence=0.9, expires_at=0)
        assert result["status"] == "ok"
        mock_mcp_client.update_memory.assert_called_once_with("m1", "new", "sum", 0.9, 0)

    def test_default_expires_at(self, mock_mcp_client):
        from server.mcp.main import update_memory

        mock_mcp_client.update_memory.return_value = {"status": "ok"}
        update_memory(memory_id="m1")
        mock_mcp_client.update_memory.assert_called_once_with("m1", "", "", 0.0, -1)


class TestDeleteMemory:
    """Tests for the delete_memory MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_memory

        mock_mcp_client.delete_memory.return_value = {"status": "ok"}
        result = delete_memory(memory_id="m1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_memory.assert_called_once_with("m1")


class TestUpdateMemoryTier:
    """Tests for the update_memory_tier MCP tool."""

    def test_updates_tier(self, mock_mcp_client):
        from server.mcp.main import update_memory_tier

        mock_mcp_client.update_memory_tier.return_value = {"id": "m1", "tier": "L1"}
        result = update_memory_tier(memory_id="m1", tier="L1")
        assert result["tier"] == "L1"
        mock_mcp_client.update_memory_tier.assert_called_once_with("m1", "L1")


# ── Tag tools ─────────────────────────────────────────────────────────────


class TestCreateTag:
    """Tests for the create_tag MCP tool."""

    def test_creates_tag(self, mock_mcp_client):
        from server.mcp.main import create_tag

        mock_mcp_client.create_tag.return_value = {"id": "tag1", "name": "important"}
        result = create_tag(workspace_id="ws1", name="important")
        assert result["name"] == "important"
        mock_mcp_client.create_tag.assert_called_once_with("ws1", "important", "#808080")

    def test_with_custom_color(self, mock_mcp_client):
        from server.mcp.main import create_tag

        mock_mcp_client.create_tag.return_value = {"id": "tag2"}
        create_tag(workspace_id="ws1", name="urgent", color="#FF0000")
        mock_mcp_client.create_tag.assert_called_once_with("ws1", "urgent", "#FF0000")


class TestTagMemory:
    """Tests for the tag_memory MCP tool."""

    def test_tags_memory(self, mock_mcp_client):
        from server.mcp.main import tag_memory

        mock_mcp_client.tag_memory.return_value = {"status": "ok"}
        result = tag_memory(memory_id="m1", tag_id="tag1")
        assert result["status"] == "ok"
        mock_mcp_client.tag_memory.assert_called_once_with("m1", "tag1")


class TestUntagMemory:
    """Tests for the untag_memory MCP tool."""

    def test_untags(self, mock_mcp_client):
        from server.mcp.main import untag_memory

        mock_mcp_client.untag_memory.return_value = {"status": "ok"}
        result = untag_memory(memory_id="m1", tag_id="tag1")
        assert result["status"] == "ok"
        mock_mcp_client.untag_memory.assert_called_once_with("m1", "tag1")


class TestListTags:
    """Tests for the list_tags MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_tags

        mock_mcp_client.list_tags.return_value = [
            {"id": "t1", "name": "important"},
            {"id": "t2", "name": "urgent"},
        ]
        result = list_tags(workspace_id="ws1")
        assert len(result) == 2
        mock_mcp_client.list_tags.assert_called_once_with("ws1")

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_tags

        mock_mcp_client.list_tags.return_value = []
        result = list_tags(workspace_id="ws1")
        assert result == []


class TestDeleteTagMCP:
    """Tests for the delete_tag MCP tool (avoid name clash)."""

    def test_deletes_tag(self, mock_mcp_client):
        from server.mcp.main import delete_tag

        result = delete_tag(tag_id="tag1")
        assert result["status"] == "ok"
        assert result["deleted_tag_id"] == "tag1"
        mock_mcp_client.delete_tag.assert_called_once_with("tag1")


class TestBatchTagMemories:
    """Tests for the batch_tag_memories MCP tool."""

    def test_batch_tags(self, mock_mcp_client):
        from server.mcp.main import batch_tag_memories

        mock_mcp_client.batch_tag_memories.return_value = {"status": "ok"}
        result = batch_tag_memories(tag_id="tag1", memory_ids_json='["m1", "m2"]')
        assert result["status"] == "ok"
        mock_mcp_client.batch_tag_memories.assert_called_once_with(
            "tag1", ["m1", "m2"]
        )


class TestBatchUntagMemories:
    """Tests for the batch_untag_memories MCP tool."""

    def test_batch_untags(self, mock_mcp_client):
        from server.mcp.main import batch_untag_memories

        mock_mcp_client.batch_untag_memories.return_value = {"status": "ok"}
        result = batch_untag_memories(tag_id="tag1", memory_ids_json='["m1", "m2"]')
        assert result["status"] == "ok"
        mock_mcp_client.batch_untag_memories.assert_called_once_with(
            "tag1", ["m1", "m2"]
        )


# ── store_batch ───────────────────────────────────────────────────────────


class TestStoreBatch:
    """Tests for the store_batch MCP tool."""

    def test_stores_batch(self, mock_mcp_client):
        from server.mcp.main import store_batch

        mock_mcp_client.store_batch.return_value = [{"id": "m1"}, {"id": "m2"}]
        result = store_batch(
            items_json='[{"content": "Hello", "memory_type": "observation"}]',
        )
        assert "Stored 2 memories" in result
        mock_mcp_client.store_batch.assert_called_once()

    def test_invalid_json(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(items_json="not json")
        assert "Error" in result
        assert "invalid JSON" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_not_a_list(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(items_json='"just a string"')
        assert "Error" in result
        assert "list of dicts" in result
        mock_mcp_client.store_batch.assert_not_called()

    def test_not_dicts(self, mock_mcp_client):
        from server.mcp.main import store_batch

        result = store_batch(items_json='[1, 2, 3]')
        assert "Error" in result
        mock_mcp_client.store_batch.assert_not_called()


# ── Note tools ────────────────────────────────────────────────────────────


class TestCreateNote:
    """Tests for the create_note MCP tool."""

    def test_creates_note(self, mock_mcp_client):
        from server.mcp.main import create_note

        mock_mcp_client.create_note.return_value = {"id": "note1", "title": "Test"}
        result = create_note(workspace_id="ws1", title="Test", content="Hello")
        assert result["title"] == "Test"
        mock_mcp_client.create_note.assert_called_once_with(
            workspace_id="ws1",
            title="Test",
            content="Hello",
            note_date="",
            embed=True,
        )

    def test_with_date_and_no_embed(self, mock_mcp_client):
        from server.mcp.main import create_note

        mock_mcp_client.create_note.return_value = {"id": "n2"}
        create_note(
            workspace_id="ws1",
            title="Dated",
            content="Content",
            note_date="2026-07-23",
            embed=False,
        )
        mock_mcp_client.create_note.assert_called_once_with(
            workspace_id="ws1",
            title="Dated",
            content="Content",
            note_date="2026-07-23",
            embed=False,
        )


class TestGetNote:
    """Tests for the get_note MCP tool."""

    def test_gets_note(self, mock_mcp_client):
        from server.mcp.main import get_note

        mock_mcp_client.get_note.return_value = [{"id": "n1", "title": "Test"}]
        result = get_note(note_id="n1")
        assert result[0]["title"] == "Test"
        mock_mcp_client.get_note.assert_called_once_with("n1")


class TestUpdateNote:
    """Tests for the update_note MCP tool."""

    def test_updates_note(self, mock_mcp_client):
        from server.mcp.main import update_note

        mock_mcp_client.update_note.return_value = {"status": "ok"}
        result = update_note(note_id="n1", title="Updated", content="New content")
        assert result["status"] == "ok"
        mock_mcp_client.update_note.assert_called_once_with(
            note_id="n1",
            title="Updated",
            content="New content",
            embed=True,
        )


class TestDeleteNote:
    """Tests for the delete_note MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_note

        mock_mcp_client.delete_note.return_value = {"status": "ok"}
        result = delete_note(note_id="n1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_note.assert_called_once_with("n1")


class TestListNotes:
    """Tests for the list_notes MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_notes

        mock_mcp_client.list_notes.return_value = [
            {"id": "n1", "title": "Note 1"},
        ]
        result = list_notes(workspace_id="ws1")
        assert len(result) == 1
        mock_mcp_client.list_notes.assert_called_once_with("ws1")

    def test_default_workspace(self, mock_mcp_client):
        from server.mcp.main import list_notes

        mock_mcp_client.list_notes.return_value = []
        list_notes()
        mock_mcp_client.list_notes.assert_called_once_with("default")


class TestGetNoteByTitle:
    """Tests for the get_note_by_title MCP tool."""

    def test_gets_by_title(self, mock_mcp_client):
        from server.mcp.main import get_note_by_title

        mock_mcp_client.get_note_by_title.return_value = [
            {"id": "n1", "title": "My Note"},
        ]
        result = get_note_by_title(title="My Note")
        assert result[0]["title"] == "My Note"
        mock_mcp_client.get_note_by_title.assert_called_once_with("My Note")


class TestGetNoteHistory:
    """Tests for the get_note_history MCP tool."""

    def test_gets_history(self, mock_mcp_client):
        from server.mcp.main import get_note_history

        mock_mcp_client.get_note_history.return_value = [
            {"version": 1, "title": "v1"},
        ]
        result = get_note_history(note_id="n1")
        assert len(result) == 1
        mock_mcp_client.get_note_history.assert_called_once_with("n1")


class TestGetBacklinks:
    """Tests for the get_backlinks MCP tool."""

    def test_gets_backlinks(self, mock_mcp_client):
        from server.mcp.main import get_backlinks

        mock_mcp_client.get_backlinks.return_value = [
            {"note_id": "n1", "title": "Source"},
        ]
        result = get_backlinks(note_id="n1")
        assert len(result) == 1
        mock_mcp_client.get_backlinks.assert_called_once_with("n1")


class TestGetOutgoingLinks:
    """Tests for the get_outgoing_links MCP tool."""

    def test_gets_outgoing(self, mock_mcp_client):
        from server.mcp.main import get_outgoing_links

        mock_mcp_client.get_outgoing_links.return_value = [
            {"note_id": "n1", "target_title": "Target"},
        ]
        result = get_outgoing_links(note_id="n1")
        assert len(result) == 1
        mock_mcp_client.get_outgoing_links.assert_called_once_with("n1")


# ── Document tools ────────────────────────────────────────────────────────


class TestCreateDocument:
    """Tests for the create_document MCP tool."""

    def test_creates_document(self, mock_mcp_client):
        from server.mcp.main import create_document

        mock_mcp_client.create_document.return_value = {"id": "doc1", "title": "Doc"}
        result = create_document(
            workspace_id="ws1",
            title="Doc",
            content="Content here",
        )
        assert result["id"] == "doc1"
        mock_mcp_client.create_document.assert_called_once()

    def test_with_metadata(self, mock_mcp_client):
        from server.mcp.main import create_document

        mock_mcp_client.create_document.return_value = {"id": "doc2"}
        create_document(
            workspace_id="ws1",
            title="Meta",
            content="Doc content",
            metadata_json='{"source": "web"}',
        )
        call_kw = mock_mcp_client.create_document.call_args[1]
        assert call_kw["metadata"] == {"source": "web"}


class TestGetDocument:
    """Tests for the get_document MCP tool."""

    def test_gets(self, mock_mcp_client):
        from server.mcp.main import get_document

        mock_mcp_client.get_document.return_value = {"id": "doc1", "title": "Doc"}
        result = get_document(doc_id="doc1")
        assert result["title"] == "Doc"
        mock_mcp_client.get_document.assert_called_once_with("doc1")

    def test_not_found(self, mock_mcp_client):
        from server.mcp.main import get_document

        mock_mcp_client.get_document.return_value = None
        result = get_document(doc_id="nonexistent")
        assert result is None


class TestListDocuments:
    """Tests for the list_documents MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_documents

        mock_mcp_client.list_documents.return_value = [
            {"id": "d1", "title": "Doc 1"},
        ]
        result = list_documents(workspace_id="ws1")
        assert len(result) == 1
        mock_mcp_client.list_documents.assert_called_once_with("ws1")


class TestGetDocumentChunks:
    """Tests for the get_document_chunks MCP tool."""

    def test_gets_chunks(self, mock_mcp_client):
        from server.mcp.main import get_document_chunks

        mock_mcp_client.get_document_chunks.return_value = [
            {"index": 0, "content": "chunk1"},
            {"index": 1, "content": "chunk2"},
        ]
        result = get_document_chunks(doc_id="doc1")
        assert len(result) == 2
        mock_mcp_client.get_document_chunks.assert_called_once_with("doc1")


class TestDeleteDocument:
    """Tests for the delete_document MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_document

        mock_mcp_client.delete_document.return_value = {"status": "ok"}
        result = delete_document(doc_id="doc1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_document.assert_called_once_with("doc1")


# ── Memory lifecycle / maintenance tools ─────────────────────────────────


class TestReinforceMemory:
    """Tests for the reinforce_memory MCP tool."""

    def test_reinforces(self, mock_mcp_client):
        from server.mcp.main import reinforce_memory

        mock_mcp_client.reinforce.return_value = {"status": "ok"}
        result = reinforce_memory(memory_id="m1")
        assert result["status"] == "ok"
        mock_mcp_client.reinforce.assert_called_once_with("m1")


class TestRateMemory:
    """Tests for the rate_memory MCP tool."""

    def test_rates_helpful(self, mock_mcp_client):
        from server.mcp.main import rate_memory

        mock_mcp_client.rate_memory.return_value = {"status": "ok"}
        result = rate_memory(memory_id="m1", rating="helpful", peer_id="p1")
        assert result["status"] == "ok"
        mock_mcp_client.rate_memory.assert_called_once_with("m1", "helpful", "p1")


class TestEscalateMemories:
    """Tests for the escalate_memories MCP tool."""

    def test_escalates(self, mock_mcp_client):
        from server.mcp.main import escalate_memories

        result = escalate_memories(workspace_id="ws1", l2_to_l1=5, l1_to_l0=20)
        assert "escalation triggered" in result.lower()
        mock_mcp_client.escalate_memories.assert_called_once_with("ws1", 5, 20)


class TestDedupMemories:
    """Tests for the dedup_memories MCP tool."""

    def test_dedups(self, mock_mcp_client):
        from server.mcp.main import dedup_memories

        result = dedup_memories(workspace_id="ws1")
        assert "Dedup complete" in result
        mock_mcp_client.dedup.assert_called_once_with("ws1")


class TestConsolidateMemories:
    """Tests for the consolidate_memories MCP tool."""

    def test_consolidates(self, mock_mcp_client):
        from server.mcp.main import consolidate_memories

        result = consolidate_memories(
            workspace_id="ws1",
            source_ids_json='["m1", "m2"]',
            target_content="Consolidated content",
            target_summary="Consolidated summary",
        )
        assert "Consolidation complete" in result
        mock_mcp_client.consolidate_memories.assert_called_once_with(
            "ws1", ["m1", "m2"], "Consolidated content", "Consolidated summary"
        )


class TestSuggestMerges:
    """Tests for the suggest_merges MCP tool."""

    def test_suggests(self, mock_mcp_client):
        from server.mcp.main import suggest_merges

        result = suggest_merges(workspace_id="ws1", threshold=0.85)
        assert "Merge suggestion scan complete" in result
        mock_mcp_client.suggest_merges.assert_called_once_with("ws1", 0.85)


class TestApproveMerge:
    """Tests for the approve_merge MCP tool."""

    def test_approves(self, mock_mcp_client):
        from server.mcp.main import approve_merge

        result = approve_merge(suggestion_id="sg-1")
        assert "approved" in result
        mock_mcp_client.approve_merge.assert_called_once_with("sg-1")


class TestRejectMerge:
    """Tests for the reject_merge MCP tool."""

    def test_rejects(self, mock_mcp_client):
        from server.mcp.main import reject_merge

        result = reject_merge(suggestion_id="sg-1")
        assert "rejected" in result
        mock_mcp_client.reject_merge.assert_called_once_with("sg-1")


class TestSetMemoryScope:
    """Tests for the set_memory_scope MCP tool."""

    def test_sets_scope(self, mock_mcp_client):
        from server.mcp.main import set_memory_scope

        result = set_memory_scope(memory_id="m1", user_scope="alice")
        assert "scoped to" in result
        assert "alice" in result
        mock_mcp_client.set_memory_scope.assert_called_once_with("m1", "alice")

    def test_makes_shared(self, mock_mcp_client):
        from server.mcp.main import set_memory_scope

        result = set_memory_scope(memory_id="m1", user_scope="")
        assert "shared" in result
        mock_mcp_client.set_memory_scope.assert_called_once_with("m1", "")


# ── Profile tools ─────────────────────────────────────────────────────────


class TestGetProfile:
    """Tests for the get_profile MCP tool."""

    def test_gets_profile(self, mock_mcp_client):
        from server.mcp.main import get_profile

        mock_mcp_client.get_profile.return_value = [
            {"peer_id": "p1", "name": "Alice"},
        ]
        result = get_profile(peer_id="p1")
        assert result[0]["name"] == "Alice"
        mock_mcp_client.get_profile.assert_called_once_with("p1")


class TestUpsertProfile:
    """Tests for the upsert_profile MCP tool."""

    def test_upserts(self, mock_mcp_client):
        from server.mcp.main import upsert_profile

        mock_mcp_client.upsert_profile.return_value = {"status": "ok"}
        result = upsert_profile(
            peer_id="p1",
            static_facts_json='[{"key": "expertise", "value": "AI"}]',
        )
        assert result["status"] == "ok"
        mock_mcp_client.upsert_profile.assert_called_once_with(
            "p1",
            '[{"key": "expertise", "value": "AI"}]',
            "[]",
            "{}",
            "[]",
        )


# ── Knowledge Graph tools ─────────────────────────────────────────────────


class TestCreateNode:
    """Tests for the create_node MCP tool."""

    def test_creates_node(self, mock_mcp_client):
        from server.mcp.main import create_node

        mock_mcp_client.create_node.return_value = {"id": "node1"}
        result = create_node(
            workspace_id="ws1",
            label="AI",
            node_type="concept",
            summary="Artificial Intelligence",
        )
        assert result["id"] == "node1"
        mock_mcp_client.create_node.assert_called_once_with(
            "ws1", "AI", "concept", "Artificial Intelligence", "{}"
        )


class TestDeleteNode:
    """Tests for the delete_node MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_node

        mock_mcp_client.delete_node.return_value = {"status": "ok"}
        result = delete_node(node_id="n1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_node.assert_called_once_with("n1")


class TestUpdateEdge:
    """Tests for the update_edge MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_edge

        mock_mcp_client.update_edge.return_value = {"status": "ok"}
        result = update_edge(edge_id="e1", relation="related_to", weight=0.5)
        assert result["status"] == "ok"
        mock_mcp_client.update_edge.assert_called_once_with(
            "e1", "related_to", 0.5, "{}"
        )

    def test_with_metadata(self, mock_mcp_client):
        from server.mcp.main import update_edge

        mock_mcp_client.update_edge.return_value = {"status": "ok"}
        update_edge(
            edge_id="e1",
            relation="informed_by",
            metadata_json='{"source": "paper"}',
        )
        mock_mcp_client.update_edge.assert_called_once_with(
            "e1", "informed_by", 1.0, '{"source": "paper"}'
        )


class TestDeleteEdge:
    """Tests for the delete_edge MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_edge

        mock_mcp_client.delete_edge.return_value = {"status": "ok"}
        result = delete_edge(edge_id="e1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_edge.assert_called_once_with("e1")


class TestGetEdgeHistory:
    """Tests for the get_edge_history MCP tool."""

    def test_gets_history(self, mock_mcp_client):
        from server.mcp.main import get_edge_history

        mock_mcp_client.get_edge_history.return_value = [
            {"version": 1, "relation": "r1"},
        ]
        result = get_edge_history(edge_group_id="eg1")
        assert len(result) == 1
        mock_mcp_client.get_edge_history.assert_called_once_with("eg1")


# ── get_memory_stats ──────────────────────────────────────────────────────


class TestGetMemoryStats:
    """Tests for the get_memory_stats MCP tool."""

    def test_returns_stats(self, mock_mcp_client):
        from server.mcp.main import get_memory_stats

        mock_mcp_client.get_memory_stats.return_value = {
            "workspace_id": "ws1",
            "total_memories": 100,
            "active_memories": 80,
        }
        result = get_memory_stats(workspace_id="ws1")
        import json

        parsed = json.loads(result)
        assert parsed["total_memories"] == 100
        mock_mcp_client.get_memory_stats.assert_called_once_with("ws1")

    def test_no_stats(self, mock_mcp_client):
        from server.mcp.main import get_memory_stats

        mock_mcp_client.get_memory_stats.return_value = None
        result = get_memory_stats(workspace_id="empty")
        import json

        parsed = json.loads(result)
        assert "error" in parsed


# ── Misc tools ────────────────────────────────────────────────────────────


class TestExpireMemories:
    """Tests for the expire_memories MCP tool."""

    def test_expires(self, mock_mcp_client):
        from server.mcp.main import expire_memories

        mock_mcp_client.expire_memories.return_value = {"status": "ok"}
        result = expire_memories()
        assert result["status"] == "ok"
        mock_mcp_client.expire_memories.assert_called_once_with()


class TestGetPeerSessions:
    """Tests for the get_peer_sessions MCP tool."""

    def test_gets_sessions(self, mock_mcp_client):
        from server.mcp.main import get_peer_sessions

        mock_mcp_client.get_peer_sessions.return_value = [
            {"session_id": "s1", "peer_id": "p1"},
        ]
        result = get_peer_sessions(peer_id="p1")
        assert len(result) == 1
        mock_mcp_client.get_peer_sessions.assert_called_once_with("p1")


class TestGetSessionMessages:
    """Tests for the get_session_messages MCP tool."""

    def test_gets_messages(self, mock_mcp_client):
        from server.mcp.main import get_session_messages

        mock_mcp_client.get_session_messages.return_value = [
            {"message_id": "msg1", "content": "Hello"},
        ]
        result = get_session_messages(session_id="s1")
        assert len(result) == 1
        mock_mcp_client.get_session_messages.assert_called_once_with("s1")


class TestCreateTour:
    """Tests for the create_tour MCP tool."""

    def test_creates_tour(self, mock_mcp_client):
        from server.mcp.main import create_tour

        result = create_tour(workspace_id="ws1", title="My Tour", description="A guided tour")
        assert "Tour" in result
        assert "My Tour" in result
        mock_mcp_client.create_tour.assert_called_once_with("ws1", "My Tour", "A guided tour")


class TestAddTourStop:
    """Tests for the add_tour_stop MCP tool."""

    def test_adds_stop(self, mock_mcp_client):
        from server.mcp.main import add_tour_stop

        result = add_tour_stop(tour_id="tour1", node_id="n1", heading="Intro", description="Start here")
        assert "Intro" in result
        mock_mcp_client.add_tour_stop.assert_called_once_with("tour1", "n1", "Intro", "Start here")


# ── Fact tools ────────────────────────────────────────────────────────────


class TestAddFact:
    """Tests for the add_fact MCP tool."""

    def test_adds_fact(self, mock_mcp_client):
        from server.mcp.main import add_fact

        result = add_fact(
            workspace_id="ws1",
            peer_id="p1",
            content="Alice is an AI researcher",
        )
        assert "Fact added" in result
        mock_mcp_client.add_fact.assert_called_once_with(
            "ws1", "p1", "Alice is an AI researcher", "dynamic", "custom", 0.8, "manual", "L1"
        )


class TestListFacts:
    """Tests for the list_facts MCP tool."""

    def test_lists_facts(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = [
            {"json_data": '[{"id": "f1", "content": "Fact 1"}]'}
        ]
        result = list_facts(workspace_id="ws1")
        assert len(result) == 1
        assert result[0]["id"] == "f1"
        mock_mcp_client.list_facts.assert_called_once_with("ws1", "", "", "", "")

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = []
        result = list_facts(workspace_id="ws1")
        assert result == []

    def test_with_filters(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = [
            {"json_data": "[]"}
        ]
        list_facts(workspace_id="ws1", peer_id="p1", fact_type="static", tier="L1", category="bio")
        mock_mcp_client.list_facts.assert_called_once_with("ws1", "p1", "static", "L1", "bio")


# ── Directory tools ───────────────────────────────────────────────────────


class TestCreateDirectory:
    """Tests for the create_directory MCP tool."""

    def test_creates(self, mock_mcp_client):
        from server.mcp.main import create_directory

        result = create_directory(
            workspace_id="ws1",
            name="Projects",
            path="/projects",
            parent_id="root",
            description="Project dirs",
        )
        assert "Projects" in result
        mock_mcp_client.create_directory.assert_called_once_with(
            "ws1", "Projects", "/projects", "root", "Project dirs"
        )


class TestTraverseDirectory:
    """Tests for the traverse_directory MCP tool."""

    def test_traverses(self, mock_mcp_client):
        from server.mcp.main import traverse_directory

        mock_mcp_client.traverse_directory.return_value = [
            {"id": "d1", "name": "subdir", "level": 1},
        ]
        result = traverse_directory(workspace_id="ws1", root_directory_id="d1")
        assert "d1" in result
        mock_mcp_client.traverse_directory.assert_called_once_with("ws1", "d1")


class TestListDirectoryMCP:
    """Tests for the list_directory MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_directory

        mock_mcp_client.list_directory.return_value = [
            {"id": "child1", "name": "Child Dir"},
        ]
        result = list_directory(directory_id="d1")
        assert "child1" in result
        mock_mcp_client.list_directory.assert_called_once_with("d1")


class TestSearchDirectoryContents:
    """Tests for the search_directory_contents MCP tool."""

    def test_searches(self, mock_mcp_client):
        from server.mcp.main import search_directory_contents

        mock_mcp_client.search_directory_contents.return_value = {
            "directory_id": "d1",
            "subdirectory_ids_json": "[]",
            "memory_ids_json": '["m1"]',
        }
        result = search_directory_contents(
            workspace_id="ws1", directory_path="/projects"
        )
        assert "d1" in result
        mock_mcp_client.search_directory_contents.assert_called_once_with(
            "ws1", "/projects"
        )


# ── Space access tools ────────────────────────────────────────────────────


class TestGrantSpaceAccess:
    """Tests for the grant_space_access MCP tool."""

    def test_grants(self, mock_mcp_client):
        from server.mcp.main import grant_space_access

        result = grant_space_access(workspace_id="ws1", peer_id="p1", permission="editor")
        assert "editor" in result
        mock_mcp_client.grant_space_access.assert_called_once_with("ws1", "p1", "editor")


class TestRevokeSpaceAccess:
    """Tests for the revoke_space_access MCP tool."""

    def test_revokes(self, mock_mcp_client):
        from server.mcp.main import revoke_space_access

        result = revoke_space_access(workspace_id="ws1", peer_id="p1")
        assert "Revoked" in result
        mock_mcp_client.revoke_space_access.assert_called_once_with("ws1", "p1")


class TestListSpaceMembers:
    """Tests for the list_space_members MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_space_members

        mock_mcp_client.list_space_members.return_value = [
            {"peer_id": "p1", "permission": "owner"},
            {"peer_id": "p2", "permission": "editor"},
        ]
        result = list_space_members(workspace_id="ws1")
        assert len(result) == 2
        mock_mcp_client.list_space_members.assert_called_once_with("ws1")


# ── Agent step tools ──────────────────────────────────────────────────────


class TestAddAgentStep:
    """Tests for the add_agent_step MCP tool."""

    def test_adds_step(self, mock_mcp_client):
        from server.mcp.main import add_agent_step

        result = add_agent_step(
            session_id="sess1",
            workspace_id="ws1",
            step_type="thought",
            content="I should search for X",
            summary="Search intent",
        )
        assert "Agent step recorded" in result
        mock_mcp_client.add_agent_step.assert_called_once_with(
            session_id="sess1",
            workspace_id="ws1",
            step_type="thought",
            content="I should search for X",
            summary="Search intent",
        )


class TestGetSessionSteps:
    """Tests for the get_session_steps MCP tool."""

    def test_gets_steps(self, mock_mcp_client):
        from server.mcp.main import get_session_steps

        mock_mcp_client.get_session_steps.return_value = [
            {"step_type": "thought", "content": "Thinking..."},
        ]
        result = get_session_steps(session_id="sess1")
        assert len(result) == 1
        mock_mcp_client.get_session_steps.assert_called_once_with("sess1")


# ── Connector tools ───────────────────────────────────────────────────────


class TestRegisterConnector:
    """Tests for the register_connector MCP tool."""

    def test_registers(self, mock_mcp_client):
        from server.mcp.main import register_connector

        result = register_connector(
            name="arXiv RSS",
            connector_type="rss",
            config_json='{"url": "https://export.arxiv.org/rss/cs.AI"}',
            workspace_id="ws1",
            schedule_secs=300,
        )
        assert "arXiv RSS" in result
        mock_mcp_client.register_connector.assert_called_once_with(
            name="arXiv RSS",
            connector_type="rss",
            config_json='{"url": "https://export.arxiv.org/rss/cs.AI"}',
            workspace_id="ws1",
            schedule_secs=300,
        )


class TestUpdateConnector:
    """Tests for the update_connector MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_connector

        result = update_connector(
            id="conn1",
            name="Updated RSS",
            connector_type="rss",
            config_json='{"url": "https://new.url"}',
            workspace_id="ws1",
            schedule_secs=600,
            is_active=False,
        )
        assert "updated" in result.lower()
        mock_mcp_client.update_connector.assert_called_once_with(
            id="conn1",
            name="Updated RSS",
            connector_type="rss",
            config_json='{"url": "https://new.url"}',
            workspace_id="ws1",
            schedule_secs=600,
            is_active=False,
        )


class TestDeleteConnectorMCP:
    """Tests for the delete_connector MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_connector

        result = delete_connector(id="conn1")
        assert "deleted" in result.lower()
        mock_mcp_client.delete_connector.assert_called_once_with("conn1")


class TestListConnectors:
    """Tests for the list_connectors MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_connectors

        mock_mcp_client._sql.return_value = [
            {
                "id": "conn1",
                "name": "RSS Feed",
                "connector_type": "rss",
                "workspace_id": "ws1",
                "schedule_secs": 300,
                "is_active": True,
                "created_at": 1000,
            },
        ]
        result = list_connectors()
        assert "RSS Feed" in result
        mock_mcp_client._sql.assert_called_once()

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_connectors

        mock_mcp_client._sql.return_value = []
        result = list_connectors()
        assert "No connectors" in result


# ── Compounder-based tools not yet covered ────────────────────────────────


class TestFindNearDuplicates:
    """Tests for the find_near_duplicates MCP tool (uses Compounder)."""

    def test_finds_duplicates(self, mock_compounder):
        from server.mcp.main import find_near_duplicates

        mock_compounder.find_near_duplicates.return_value = [
            {
                "entity_id": "e1",
                "entity_type": "memory",
                "score": 0.95,
                "content": "Sample text",
            },
        ]
        result = find_near_duplicates(
            content="Sample text to check",
            workspace_id="ws1",
            threshold=0.92,
            limit=5,
        )
        assert "Found 1 near-duplicate" in result
        assert "0.9500" in result
        mock_compounder.find_near_duplicates.assert_called_once_with(
            content="Sample text to check",
            workspace_id="ws1",
            threshold=0.92,
            limit=5,
        )

    def test_no_duplicates(self, mock_compounder):
        from server.mcp.main import find_near_duplicates

        mock_compounder.find_near_duplicates.return_value = []
        result = find_near_duplicates(content="Unique text")
        assert "No near-duplicates" in result


class TestCrossLink:
    """Tests for the cross_link MCP tool (uses Compounder)."""

    def test_cross_links(self, mock_compounder):
        from server.mcp.main import cross_link

        mock_compounder.cross_link.return_value = {
            "links_created": 5,
            "pairs_checked": 100,
        }
        result = cross_link(workspace_id="ws1")
        assert "Cross-link complete" in result
        assert "5" in result
        assert "100" in result
        mock_compounder.cross_link.assert_called_once_with(workspace_id="ws1")

    def test_default_workspace(self, mock_compounder):
        from server.mcp.main import cross_link

        mock_compounder.cross_link.return_value = {"links_created": 0, "pairs_checked": 0}
        cross_link()
        mock_compounder.cross_link.assert_called_once_with(workspace_id="default")


class TestSuggestConnections:
    """Tests for the suggest_connections MCP tool (uses Compounder)."""

    def test_suggests(self, mock_compounder):
        from server.mcp.main import suggest_connections

        mock_compounder.suggest_connections.return_value = [
            {
                "source_label": "RLHF",
                "target_label": "PPO",
                "common_count": 3,
            },
        ]
        result = suggest_connections(workspace_id="ws1")
        assert "Found 1 connection suggestion" in result
        assert "RLHF" in result
        mock_compounder.suggest_connections.assert_called_once_with(
            workspace_id="ws1"
        )

    def test_no_suggestions(self, mock_compounder):
        from server.mcp.main import suggest_connections

        mock_compounder.suggest_connections.return_value = []
        result = suggest_connections(workspace_id="ws1")
        assert "No connection suggestions" in result


class TestExportWorkspace:
    """Tests for the export_workspace MCP tool (uses Compounder)."""

    def test_exports(self, mock_compounder):
        from server.mcp.main import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 10,
            "output_dir": "/tmp/export",
            "errors": [],
        }
        result = export_workspace(output_dir="/tmp/export", workspace_id="ws1")
        assert "Exported 10 file(s)" in result
        assert "/tmp/export" in result
        mock_compounder.export_workspace.assert_called_once_with(
            output_dir="/tmp/export",
            workspace_id="ws1",
            include_kg=False,
            include_system_notes=False,
        )

    def test_with_errors(self, mock_compounder):
        from server.mcp.main import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 8,
            "output_dir": "/tmp/export",
            "errors": ["Failed to write note n1"],
        }
        result = export_workspace(output_dir="/tmp/export", workspace_id="ws1")
        assert "8 file(s)" in result
        assert "Errors: 1" in result
        assert "Failed to write note n1" in result
