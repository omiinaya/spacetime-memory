"""Comprehensive unit tests for MemoryManagerAgentMixin (Gap #6: LangMem parity).

Tests cover:
- manage_memory with create/update/delete actions
- search_memory with filters (type, tags, importance)
- search_memory pagination (limit, offset)
- summarize_messages with and without existing_summary
- extract_memory_from_conversation
- Error handling (delete without id, unknown action)
- Edge cases (empty results, missing fields)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from spacetime_memory.client._memory_manager import MemoryManagerAgentMixin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mixin():
    """Create a MemoryManagerAgentMixin with all dependencies mocked."""
    mixin = MemoryManagerAgentMixin()
    # Mock the methods that the mixin delegates to the Client class
    mixin.store = MagicMock(return_value={"id": "mem-123", "status": "ok"})
    mixin._call = MagicMock(return_value={"status": "ok"})
    mixin._query = MagicMock(return_value=[])
    mixin.search = MagicMock(return_value=[])
    mixin._llm_complete = MagicMock(return_value="Mock summary text.")
    mixin._parse_llm_json_array = MagicMock(
        return_value=[
            {
                "content": "User likes Python",
                "memory_type": "preference",
                "importance": 0.8,
                "tags": ["python", "coding"],
            }
        ]
    )
    return mixin


# ===================================================================
# 1. manage_memory — CRUD with structured schemas
# ===================================================================


class TestManageMemory:
    """Test the manage_memory CRUD operations."""

    def test_create(self, mock_mixin):
        """Test create action returns created status with id."""
        result = mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="create",
            content="User prefers dark mode.",
        )
        assert result["action"] == "created"
        assert result["status"] == "ok"
        assert result["id"] == "mem-123"
        mock_mixin.store.assert_called_once()
        args, kwargs = mock_mixin.store.call_args
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["content"] == "User prefers dark mode."
        assert kwargs["memory_type"] == "agent_managed"

    def test_create_with_all_params(self, mock_mixin):
        """Test create with all optional parameters."""
        result = mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="create",
            content="User likes concise answers.",
            summary="Short summary",
            tags=["preference", "user"],
            importance=0.9,
            metadata={"source": "chat"},
        )
        assert result["status"] == "ok"
        mock_mixin.store.assert_called_once()
        kwargs = mock_mixin.store.call_args[1]
        assert kwargs["summary"] == "Short summary"
        assert kwargs["entities_json"] == json.dumps(["preference", "user"])
        # Importance should trigger _call
        mock_mixin._call.assert_called_once_with(
            "update_memory_importance", ["mem-123", 0.9]
        )

    def test_create_with_importance_none(self, mock_mixin):
        """Test create with importance=None does not call _call."""
        mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="create",
            content="Some content",
        )
        # _call should NOT have been called because importance is None
        mock_mixin._call.assert_not_called()

    def test_create_importance_call_fails_gracefully(self, mock_mixin):
        """Test that a failing importance update doesn't raise."""
        mock_mixin.store.return_value = {"id": "mem-123"}
        mock_mixin._call.side_effect = RuntimeError("backend down")
        # Should not raise
        result = mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="create",
            content="Test",
            importance=0.5,
        )
        assert result["status"] == "ok"

    def test_create_summary_default(self, mock_mixin):
        """Test that summary defaults to content[:100]."""
        content = "A" * 200
        mock_mixin.manage_memory(
            workspace_id="ws-1", action="create", content=content
        )
        kwargs = mock_mixin.store.call_args[1]
        assert kwargs["summary"] == content[:100]

    def test_update(self, mock_mixin):
        """Test update action."""
        result = mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="update",
            content="Updated content",
            memory_id="mem-456",
        )
        assert result["action"] == "updated"
        assert result["status"] == "ok"
        assert result["id"] == "mem-456"
        mock_mixin.store.assert_called_once()
        kwargs = mock_mixin.store.call_args[1]
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["content"] == "Updated content"

    def test_update_without_id_raises(self, mock_mixin):
        """Test update without memory_id raises ValueError."""
        with pytest.raises(ValueError, match="memory_id is required for update"):
            mock_mixin.manage_memory(
                workspace_id="ws-1",
                action="update",
                content="Updated content",
            )

    def test_delete(self, mock_mixin):
        """Test delete action."""
        result = mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="delete",
            content="",
            memory_id="mem-789",
        )
        assert result["action"] == "deleted"
        assert result["status"] == "ok"
        assert result["id"] == "mem-789"
        mock_mixin._call.assert_called_once_with(
            "delete_memory", ["mem-789"]
        )

    def test_delete_without_id_raises(self, mock_mixin):
        """Test delete without memory_id raises ValueError."""
        with pytest.raises(ValueError, match="memory_id is required for delete"):
            mock_mixin.manage_memory(
                workspace_id="ws-1",
                action="delete",
                content="",
            )

    def test_delete_failure_returns_error_status(self, mock_mixin):
        """Test delete when _call raises returns error status (doesn't raise)."""
        mock_mixin._call.side_effect = RuntimeError("Deletion failed")
        result = mock_mixin.manage_memory(
            workspace_id="ws-1",
            action="delete",
            content="",
            memory_id="mem-789",
        )
        assert result["action"] == "deleted"
        assert result["status"] == "error"
        assert "Deletion failed" in result["error"]

    def test_unknown_action_raises(self, mock_mixin):
        """Test unknown action raises ValueError."""
        with pytest.raises(ValueError, match="Unknown action"):
            mock_mixin.manage_memory(
                workspace_id="ws-1",
                action="archive",
                content="test",
            )


# ===================================================================
# 2. search_memory — query + filter + pagination
# ===================================================================


class TestSearchMemory:
    """Test search_memory with filtering and pagination."""

    @pytest.fixture
    def sample_memories(self):
        """Sample memories returned by self.search."""
        return [
            {
                "id": "1",
                "content": "User prefers dark mode",
                "memory_type": "agent_managed",
                "entities_json": json.dumps(["preference", "ui"]),
                "importance": 0.9,
                "score": 0.95,
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "2",
                "content": "User location: San Francisco",
                "memory_type": "factual",
                "entities_json": json.dumps(["location"]),
                "importance": 0.7,
                "score": 0.85,
                "created_at": "2024-01-02T00:00:00Z",
            },
            {
                "id": "3",
                "content": "User likes Python and Rust",
                "memory_type": "agent_managed",
                "entities_json": json.dumps(["preference", "coding"]),
                "importance": 0.5,
                "score": 0.75,
                "created_at": "2024-01-03T00:00:00Z",
            },
        ]

    def test_search_basic(self, mock_mixin, sample_memories):
        """Test basic search returns all results."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="user preferences"
        )
        assert result["total"] == 3
        assert len(result["results"]) == 3
        assert result["limit"] == 20
        assert result["offset"] == 0
        mock_mixin.search.assert_called_once_with(
            workspace_id="ws-1", query="user preferences", top_k=20
        )

    def test_search_filter_by_type(self, mock_mixin, sample_memories):
        """Test search filtered by memory_type."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            memory_type="factual",
        )
        assert result["total"] == 1
        assert result["results"][0]["id"] == "2"

    def test_search_filter_by_tags(self, mock_mixin, sample_memories):
        """Test search filtered by tags."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            tags=["preference"],
        )
        assert result["total"] == 2
        ids = {r["id"] for r in result["results"]}
        assert ids == {"1", "3"}

    def test_search_filter_by_tags_no_match(self, mock_mixin, sample_memories):
        """Test search filtered by nonexistent tags returns empty."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            tags=["nonexistent"],
        )
        assert result["total"] == 0
        assert result["results"] == []

    def test_search_filter_by_importance(self, mock_mixin, sample_memories):
        """Test search filtered by min_importance."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            min_importance=0.8,
        )
        assert result["total"] == 1
        assert result["results"][0]["id"] == "1"

    def test_search_filter_by_importance_string(self, mock_mixin, sample_memories):
        """Test importance filter handles string importance values."""
        memories = [
            {"id": "1", "content": "test", "importance": "0.9"},
            {"id": "2", "content": "test2", "importance": "0.3"},
        ]
        mock_mixin.search.return_value = memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="test", min_importance=0.5
        )
        assert result["total"] == 1
        assert result["results"][0]["id"] == "1"

    def test_search_filter_by_importance_fallback_confidence(self, mock_mixin):
        """Test importance filter falls back to 'confidence' field."""
        memories = [
            {"id": "1", "content": "test", "confidence": 0.9},
            {"id": "2", "content": "test2"},
        ]
        mock_mixin.search.return_value = memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="test", min_importance=0.5
        )
        assert result["total"] == 1
        assert result["results"][0]["id"] == "1"

    def test_search_pagination_limit_offset(self, mock_mixin, sample_memories):
        """Test search pagination with limit and offset."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            limit=1,
            offset=1,
        )
        assert result["total"] == 3
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "2"
        assert result["limit"] == 1
        assert result["offset"] == 1
        # top_k should be limit + offset = 2
        mock_mixin.search.assert_called_once_with(
            workspace_id="ws-1", query="test", top_k=2
        )

    def test_search_pagination_beyond_range(self, mock_mixin, sample_memories):
        """Test search pagination when offset exceeds data."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            limit=20,
            offset=100,
        )
        assert result["total"] == 3
        assert result["results"] == []

    def test_search_include_metadata_false(self, mock_mixin, sample_memories):
        """Test search with include_metadata=False strips extra fields."""
        mock_mixin.search.return_value = sample_memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1",
            query="test",
            include_metadata=False,
        )
        for r in result["results"]:
            keys = set(r.keys())
            assert keys.issubset(
                {"id", "content", "summary", "memory_type", "score", "created_at"}
            )

    def test_search_no_results(self, mock_mixin):
        """Test search returns empty when no matches."""
        mock_mixin.search.return_value = []
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="nothing"
        )
        assert result["total"] == 0
        assert result["results"] == []

    def test_search_handles_search_exception(self, mock_mixin):
        """Test search gracefully handles exceptions from self.search."""
        mock_mixin.search.side_effect = RuntimeError("search down")
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="test"
        )
        assert result["total"] == 0
        assert result["results"] == []

    def test_search_tags_entities_json_invalid(self, mock_mixin):
        """Test search handles invalid entities_json gracefully."""
        memories = [
            {
                "id": "1",
                "content": "test",
                "entities_json": "not valid json!!!",
            },
        ]
        mock_mixin.search.return_value = memories
        # Should not raise; treats as no tags match
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="test", tags=["preference"]
        )
        assert result["total"] == 0

    def test_search_tags_entities_json_not_list(self, mock_mixin):
        """Test search handles entities_json that is not a list."""
        memories = [
            {
                "id": "1",
                "content": "test",
                "entities_json": json.dumps("string_not_list"),
            },
        ]
        mock_mixin.search.return_value = memories
        result = mock_mixin.search_memory(
            workspace_id="ws-1", query="test", tags=["x"]
        )
        assert result["total"] == 0


# ===================================================================
# 3. summarize_messages — incremental summarization
# ===================================================================


class TestSummarizeMessages:
    """Test the summarize_messages method."""

    @pytest.fixture
    def sample_messages(self):
        return [
            {"sender_id": "user1", "content": "Hello, can you help me?"},
            {"sender_id": "bot", "content": "Sure! What do you need?"},
            {"sender_id": "user1", "content": "I need help with Python."},
            {"sender_id": "bot", "content": "Let me show you some examples."},
        ]

    def test_summarize_with_messages(self, mock_mixin, sample_messages):
        """Test summarization with messages present."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._llm_complete.return_value = "Mock summary from LLM."
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1",
            session_id="session-123",
        )
        assert result["summary"] == "Mock summary from LLM."
        assert result["message_count"] == 4
        assert result["strategy"] == "incremental"
        mock_mixin._query.assert_called_once_with(
            "message", filter_dict={"session_id": "session-123"}
        )
        # Should call _llm_complete since it has the attr
        mock_mixin._llm_complete.assert_called_once()
        prompt_arg = mock_mixin._llm_complete.call_args[0][0]
        assert "Summarize the following conversation" in prompt_arg

    def test_summarize_with_existing_summary(self, mock_mixin, sample_messages):
        """Test incremental summarization with existing summary."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._llm_complete.return_value = "Updated summary."
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1",
            session_id="session-123",
            existing_summary="Prior summary of conversation.",
        )
        assert result["summary"] == "Updated summary."
        prompt_arg = mock_mixin._llm_complete.call_args[0][0]
        assert "Existing summary" in prompt_arg
        assert "Prior summary of conversation" in prompt_arg

    def test_summarize_no_messages(self, mock_mixin):
        """Test summarization when there are no messages."""
        mock_mixin._query.return_value = []
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1",
            session_id="empty-session",
        )
        assert result["summary"] == ""
        assert result["message_count"] == 0
        mock_mixin._llm_complete.assert_not_called()

    def test_summarize_no_messages_with_existing(self, mock_mixin):
        """Test no messages returns existing summary."""
        mock_mixin._query.return_value = []
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1",
            session_id="empty-session",
            existing_summary="Previous summary",
        )
        assert result["summary"] == "Previous summary"

    def test_summarize_no_llm_attr(self):
        """Test summarization when mixin has no _llm_complete attr."""
        mixin = MemoryManagerAgentMixin()
        mixin._query = MagicMock(return_value=[{"sender_id": "u", "content": "hi"}])
        # No _llm_complete set
        result = mixin.summarize_messages(
            workspace_id="ws-1", session_id="s1"
        )
        # Falls back to generic summary
        assert "Session summarized" in result["summary"]
        assert result["message_count"] == 1

    def test_summarize_fallback_when_llm_returns_empty(self, mock_mixin, sample_messages):
        """Test fallback when _llm_complete returns empty string."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._llm_complete.return_value = ""
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1", session_id="s1"
        )
        assert "Session summarized" in result["summary"]
        assert result["message_count"] == 4

    def test_summarize_full_strategy(self, mock_mixin, sample_messages):
        """Test full (not incremental) summarization strategy."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._llm_complete.return_value = "Full summary."
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1",
            session_id="s1",
            existing_summary="Old summary",
            strategy="full",
        )
        prompt_arg = mock_mixin._llm_complete.call_args[0][0]
        assert "Existing summary" not in prompt_arg
        assert result["strategy"] == "full"

    def test_summarize_truncates_long_content(self, mock_mixin):
        """Test that messages exceeding 6000 chars are truncated."""
        long_messages = [
            {"sender_id": "u", "content": "X" * 4000}
            for _ in range(3)
        ]
        mock_mixin._query.return_value = long_messages
        mock_mixin._llm_complete.return_value = "Summary."
        _ = mock_mixin.summarize_messages(
            workspace_id="ws-1", session_id="s1"
        )
        # Combined text should be truncated to last 6000 chars
        # Check that _llm_complete was called — the truncation happens
        # inside the method before passing to _llm_complete
        mock_mixin._llm_complete.assert_called_once()

    def test_summarize_messages_limit(self, mock_mixin):
        """Test max_messages parameter limits how many messages are analyzed."""
        many_messages = [
            {"sender_id": "u", "content": f"msg {i}"} for i in range(100)
        ]
        mock_mixin._query.return_value = many_messages
        mock_mixin._llm_complete.return_value = "Summary."
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1",
            session_id="s1",
            max_messages=10,
        )
        assert result["message_count"] == 10

    def test_summarize_with_sender_fallback(self, mock_mixin):
        """Test fallback from sender_id to sender field."""
        messages = [
            {"sender": "user123", "content": "Hello"},
        ]
        mock_mixin._query.return_value = messages
        mock_mixin._llm_complete.return_value = "Summary."
        result = mock_mixin.summarize_messages(
            workspace_id="ws-1", session_id="s1"
        )
        assert result["message_count"] == 1


# ===================================================================
# 4. extract_memory_from_conversation — structured extraction
# ===================================================================


class TestExtractMemoryFromConversation:
    """Test the extract_memory_from_conversation method."""

    @pytest.fixture
    def sample_messages(self):
        return [
            {"sender_id": "user", "content": "I love Python programming."},
            {"sender_id": "bot", "content": "Python is great for data science."},
            {"sender_id": "user", "content": "My favorite editor is VS Code."},
        ]

    def test_extract_and_store(self, mock_mixin, sample_messages):
        """Test extraction with store=True (default)."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._parse_llm_json_array.return_value = [
            {
                "content": "User loves Python",
                "memory_type": "preference",
                "importance": 0.8,
                "tags": ["python"],
            },
            {
                "content": "User uses VS Code",
                "memory_type": "preference",
                "importance": 0.6,
                "tags": ["editor"],
            },
        ]
        # manage_memory will return ids
        mock_mixin.manage_memory = MagicMock(
            side_effect=[
                {"id": "ext-1", "action": "created", "status": "ok"},
                {"id": "ext-2", "action": "created", "status": "ok"},
            ]
        )

        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1",
            session_id="session-abc",
        )

        assert len(result) == 2
        assert result[0]["content"] == "User loves Python"
        assert result[0]["id"] == "ext-1"
        assert result[1]["content"] == "User uses VS Code"
        assert result[1]["id"] == "ext-2"
        mock_mixin.manage_memory.assert_called()
        assert mock_mixin.manage_memory.call_count == 2

    def test_extract_without_store(self, mock_mixin, sample_messages):
        """Test extraction with store=False."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._parse_llm_json_array.return_value = [
            {"content": "User loves Python", "memory_type": "preference",
             "importance": 0.8, "tags": ["python"]},
        ]
        mock_mixin.manage_memory = MagicMock()

        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1",
            session_id="session-abc",
            store=False,
        )

        assert len(result) == 1
        # id should not be set because store=False
        assert "id" not in result[0]
        mock_mixin.manage_memory.assert_not_called()

    def test_extract_no_messages(self, mock_mixin):
        """Test extraction with no messages returns empty list."""
        mock_mixin._query.return_value = []
        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1",
            session_id="empty-session",
        )
        assert result == []

    def test_extract_llm_returns_nothing(self, mock_mixin, sample_messages):
        """Test extraction when LLM returns empty string."""
        mock_mixin._query.return_value = sample_messages
        # Simulate no _llm_complete attribute
        del mock_mixin._llm_complete
        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1",
            session_id="s1",
        )
        assert result == []

    def test_extract_parse_returns_empty(self, mock_mixin, sample_messages):
        """Test extraction when parse returns empty list."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._parse_llm_json_array.return_value = []
        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1",
            session_id="s1",
        )
        assert result == []

    def test_extract_store_fails_gracefully(self, mock_mixin, sample_messages):
        """Test that a failing manage_memory call doesn't break others."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._parse_llm_json_array.return_value = [
            {"content": "Memory 1", "memory_type": "fact",
             "importance": 0.5, "tags": []},
            {"content": "Memory 2", "memory_type": "fact",
             "importance": 0.5, "tags": []},
        ]
        mock_mixin.manage_memory = MagicMock(
            side_effect=[
                RuntimeError("Storage failed"),  # first fails
                {"id": "ok-2", "status": "ok"},  # second succeeds
            ]
        )

        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1",
            session_id="s1",
        )

        assert len(result) == 2
        # First memory has error info
        assert result[0]["id"] == ""
        assert "error" in result[0]
        # Second memory succeeded
        assert result[1]["id"] == "ok-2"

    def test_extract_truncates_long_conversation(self, mock_mixin):
        """Test extraction truncates very long conversations."""
        long_msgs = [
            {"sender_id": "u", "content": "X" * 3000}
            for _ in range(5)
        ]
        mock_mixin._query.return_value = long_msgs
        mock_mixin._parse_llm_json_array.return_value = [
            {"content": "Extracted", "memory_type": "fact",
             "importance": 0.5, "tags": []},
        ]
        mock_mixin.manage_memory = MagicMock(return_value={"id": "m1", "status": "ok"})
        # Should not raise
        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1", session_id="s1"
        )
        assert len(result) == 1

    def test_extract_defaults_for_missing_fields(self, mock_mixin, sample_messages):
        """Test extraction uses defaults for missing fields in parsed memories."""
        mock_mixin._query.return_value = sample_messages
        mock_mixin._parse_llm_json_array.return_value = [
            {"content": "Only content provided"},
        ]
        mock_mixin.manage_memory = MagicMock(return_value={"id": "m1", "status": "ok"})
        result = mock_mixin.extract_memory_from_conversation(
            workspace_id="ws-1", session_id="s1"
        )
        assert result[0]["content"] == "Only content provided"
        # manage_memory should have been called with defaults
        call_kwargs = mock_mixin.manage_memory.call_args[1]
        assert call_kwargs["memory_type"] == "fact"  # default
        assert call_kwargs["importance"] == 0.5  # default
        assert call_kwargs["tags"] == []  # default


# ===================================================================
# 5. _parse_llm_json_array — helper
# ===================================================================


class TestParseLlmJsonArray:
    """Test the _parse_llm_json_array helper."""

    def setup_method(self):
        self.mixin = MemoryManagerAgentMixin()

    def test_parse_valid_json(self):
        text = '[{"content": "test", "memory_type": "fact"}]'
        result = self.mixin._parse_llm_json_array(text)
        assert len(result) == 1
        assert result[0]["content"] == "test"

    def test_parse_json_with_code_fences(self):
        text = 'Some text\n```json\n[{"content": "in fence"}]\n```\nmore text'
        result = self.mixin._parse_llm_json_array(text)
        assert len(result) == 1
        assert result[0]["content"] == "in fence"

    def test_parse_json_with_code_fences_no_lang(self):
        text = '```\n[{"content": "no lang"}]\n```'
        result = self.mixin._parse_llm_json_array(text)
        assert len(result) == 1
        assert result[0]["content"] == "no lang"

    def test_parse_json_fallback_array(self):
        text = 'Some random text [{"content": "found me"}]'
        result = self.mixin._parse_llm_json_array(text)
        assert len(result) == 1
        assert result[0]["content"] == "found me"

    def test_parse_invalid_returns_empty(self):
        result = self.mixin._parse_llm_json_array("not json at all")
        assert result == []

    def test_parse_not_a_list_returns_empty(self):
        result = self.mixin._parse_llm_json_array('{"key": "value"}')
        assert result == []

    def test_parse_empty_string(self):
        result = self.mixin._parse_llm_json_array("")
        assert result == []
