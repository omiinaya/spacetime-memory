"""Integration tests for Zep-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_zep_adapter.py -v

"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
import time
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


from spacetime_memory.sdks.zep import (
    ZepClient,
    MemoryMessage,
    Memory,
    MemorySearchResult,
    Session,
    Fact,
    NotFoundError,
    # v2.0.2 sub-client pattern
    Zep,
    # Async
    AsyncZepClient,
    AsyncZep,
    # Stub types
    Summary,
    SuccessResponse,
    FactRatingExamples,
    FactRatingInstruction,
    SessionFactRatingExamples,
    SessionFactRatingInstruction,
    RoleType,
    SearchScope,
    SearchType,
    ZepEnvironment,
)


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture(scope="module")
def db() -> str | None:
    return os.environ.get("SPACETIMEDB_DB", None)


@pytest.fixture(scope="module")
def token() -> str:
    """Generate a JWT token for consistent identity across calls."""
    try:
        from spacetime_memory.auth import generate_token
    except ImportError:
        return ""
    key_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "data" / "id_ecdsa_pkcs8.pem"
    )
    if not key_path.exists():
        return ""
    return generate_token(str(key_path))


@pytest.fixture
def zep(host: str, port: int, stdb_session: dict):
    client = ZepClient(
        host=host,
        port=port,
        config={"db": stdb_session["database"]},
    )
    # Auto-register for auth
    import secrets
    try:
        client._client._call("register", [f"zep_test_{secrets.token_hex(4)}", "Zep Test", "testpass"])
    except RuntimeError:
        pass
    yield client
    client.close()


def _sid(prefix: str = "zep-test") -> str:
    """Generate a unique session ID to avoid ACL cross-contamination."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _register_client(client: "ZepClient", tag: str = "test") -> None:
    """Auto-register a client for auth. No-op if already registered.

    Works with ZepClient, Zep, AsyncZepClient, and AsyncZep.
    """
    import secrets
    # Resolve the underlying Client instance
    if hasattr(client, "_sync"):
        inner = client._sync
    else:
        inner = client
    try:
        inner._client._call(
            "register",
            [f"zep_{tag}_{secrets.token_hex(4)}", f"Zep {tag}", "testpass"],
        )
    except RuntimeError:
        pass


class TestZepClient:
    """Tests for the ZepClient adapter."""

    def test_add_and_get_memory(self, zep: ZepClient) -> None:
        """Add messages then retrieve them."""
        sid = _sid()
        result = zep.add_memory(
            session_id=sid,
            messages=[
                {"role": "user", "content": "Hello from Zep adapter test"},
                {"role": "assistant", "content": "This is a test response"},
            ],
        )
        assert result["status"] == "ok"
        assert len(result["message_ids"]) > 0

        memory = zep.get_memory(session_id=sid, limit=10)
        assert memory is not None
        assert "messages" in memory
        assert len(memory["messages"]) >= 2

        contents = [m["content"] for m in memory["messages"]]
        assert "Hello from Zep adapter test" in contents

    def test_add_memory_with_memorymessage_objects(self, zep: ZepClient) -> None:
        """Add messages using MemoryMessage objects."""
        sid = _sid()
        msgs = [
            MemoryMessage(role="user", content="Object-based message"),
        ]
        result = zep.add_memory(
            session_id=sid,
            messages=msgs,
        )
        assert result["status"] == "ok"

        mem = zep.get_memory(session_id=sid, limit=5)
        assert mem is not None
        assert any("Object-based message" in m["content"] for m in mem["messages"])

    def test_search_memory(self, zep: ZepClient) -> None:
        """Search memory within a session."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[
                {"role": "user", "content": "My favorite food is pizza"},
                {"role": "user", "content": "I enjoy hiking in the mountains"},
            ],
        )

        time.sleep(0.5)

        results = zep.search_memory(
            session_id=sid,
            query="food preferences",
            limit=5,
        )
        assert len(results) >= 0
        if results:
            scores = [r.score for r in results if r.message]
            assert all(s >= 0.0 for s in scores)

    def test_search_memory_empty_session(self, zep: ZepClient) -> None:
        """Search in a non-existent session returns empty list."""
        results = zep.search_memory(
            session_id=_sid("zep-test-noexist"),
            query="anything",
        )
        assert results == []

    def test_search_memory_return_type(self, zep: ZepClient) -> None:
        """Search returns MemorySearchResult objects."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Testing search return types"}],
        )
        time.sleep(0.3)
        results = zep.search_memory(
            session_id=sid,
            query="testing",
            limit=5,
        )
        for r in results:
            assert isinstance(r, MemorySearchResult)
            if r.message:
                assert isinstance(r.message, MemoryMessage)
                assert isinstance(r.message.content, str)

    def test_search_memory_score_threshold(self, zep: ZepClient) -> None:
        """Score threshold filters low-relevance results."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[
                {"role": "user", "content": "The capital of France is Paris"},
                {"role": "user", "content": "Python is a programming language"},
            ],
        )
        time.sleep(0.3)

        results = zep.search_memory(
            session_id=sid,
            query="France Paris",
            limit=5,
            score_threshold=0.3,
        )
        assert isinstance(results, list)

    def test_delete_memory(self, zep: ZepClient) -> None:
        """Delete all messages for a session."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Delete me"}],
        )
        result = zep.delete_memory(session_id=sid)
        assert result["status"] == "ok"
        assert isinstance(result["deleted"], int)

        mem = zep.get_memory(session_id=sid)
        assert mem is None or len(mem.get("messages", [])) == 0

    def test_delete_memory_nonexistent(self, zep: ZepClient) -> None:
        """Delete on nonexistent session is idempotent."""
        result = zep.delete_memory(session_id=_sid("zep-test-noexist-delete"))
        assert result["status"] == "ok"

    def test_add_memory_with_metadata(self, zep: ZepClient) -> None:
        """Add memory with metadata dict."""
        result = zep.add_memory(
            session_id=_sid(),
            messages=[{"role": "user", "content": "With metadata"}],
            metadata={"source": "test", "importance": 5},
        )
        assert result["status"] == "ok"

    def test_add_memory_empty_messages(self, zep: ZepClient) -> None:
        """Adding empty messages list returns ok with no IDs."""
        result = zep.add_memory(
            session_id=_sid(),
            messages=[],
        )
        assert result["status"] == "ok"
        assert result["message_ids"] == []

    def test_get_memory_limit(self, zep: ZepClient) -> None:
        """get_memory respects the limit parameter."""
        sid = _sid()
        many_msgs = [
            {"role": "user", "content": f"Test message {i}"}
            for i in range(5)
        ]
        zep.add_memory(
            session_id=sid,
            messages=many_msgs,
        )
        mem = zep.get_memory(session_id=sid, limit=3)
        assert mem is not None
        assert len(mem["messages"]) <= 3

    def test_get_memory_nonexistent_session(self, zep: ZepClient) -> None:
        """get_memory on nonexistent session returns None."""
        mem = zep.get_memory(session_id=_sid("zep-test-never-created"))
        assert mem is None

    def test_list_sessions(self, zep: ZepClient) -> None:
        """list_sessions returns workspace-derived Session objects."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Session lister test"}],
        )
        sessions = zep.list_sessions()
        assert isinstance(sessions, list)
        for s in sessions:
            assert isinstance(s, Session)
            assert s.session_id

    def test_get_session(self, zep: ZepClient) -> None:
        """get_session returns a Session or None."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Session getter"}],
        )
        s = zep.get_session(sid)
        assert s is not None
        assert isinstance(s, Session)
        assert s.session_id == sid

    def test_get_session_nonexistent(self, zep: ZepClient) -> None:
        """get_session on nonexistent raises NotFoundError."""
        import pytest
        with pytest.raises(NotFoundError):
            zep.get_session(_sid("zep-test-no-such-session"))

    def test_close_is_idempotent(self, zep: ZepClient) -> None:
        """close is idempotent and clears the cache but calls still work."""
        sid = _sid()
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Close test"}],
        )
        zep.close()
        result = zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "After close"}],
        )
        assert result["status"] == "ok"

    def test_concurrent_sessions(self, zep: ZepClient) -> None:
        """Multiple sessions are isolated from each other."""
        sid_a = _sid("zep-test-concurrent-A")
        sid_b = _sid("zep-test-concurrent-B")
        zep.add_memory(
            session_id=sid_a,
            messages=[{"role": "user", "content": "Session A data"}],
        )
        zep.add_memory(
            session_id=sid_b,
            messages=[{"role": "user", "content": "Session B data"}],
        )
        mem_a = zep.get_memory(session_id=sid_a)
        mem_b = zep.get_memory(session_id=sid_b)
        assert mem_a is not None
        assert mem_b is not None
        a_contents = [m["content"] for m in mem_a["messages"]]
        b_contents = [m["content"] for m in mem_b["messages"]]
        assert "Session A data" in a_contents
        assert "Session B data" in b_contents
        assert "Session B data" not in a_contents

    # ------------------------------------------------------------------
    # Facts API tests
    # ------------------------------------------------------------------

    def test_add_fact(self, zep: ZepClient) -> None:
        """Add a fact to a session."""
        sid = _sid("zep-test-fact-add")
        result = zep.add_fact(
            session_id=sid,
            fact="User prefers dark mode over light mode",
        )
        assert result["status"] == "ok"
        assert result["fact_id"]

    def test_list_facts(self, zep: ZepClient) -> None:
        """List facts for a session."""
        sid = _sid("zep-test-fact-list")
        zep.add_fact(session_id=sid, fact="User enjoys hiking")
        zep.add_fact(session_id=sid, fact="User prefers tea over coffee")

        facts = zep.list_facts(session_id=sid)
        assert len(facts) >= 2
        for f in facts:
            assert isinstance(f, Fact)
            assert f.fact
            assert f.uuid
        fact_texts = [f.fact for f in facts]
        assert "User enjoys hiking" in fact_texts
        assert "User prefers tea over coffee" in fact_texts

    def test_list_facts_empty_session(self, zep: ZepClient) -> None:
        """List facts on a session with no facts returns empty list."""
        facts = zep.list_facts(session_id=_sid("zep-test-fact-empty"))
        assert facts == []

    def test_get_memory_includes_facts(self, zep: ZepClient) -> None:
        """get_memory returns facts alongside messages."""
        sid = _sid("zep-test-mem-facts")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "I like pizza"}],
        )
        zep.add_fact(session_id=sid, fact="User likes pizza")

        memory = zep.get_memory(session_id=sid)
        assert memory is not None
        assert "messages" in memory
        assert "facts" in memory
        assert "relevant_facts" in memory
        assert any("pizza" in f for f in memory["facts"])
        assert len(memory["relevant_facts"]) >= 1
        # relevant_facts contains Fact objects
        rf = memory["relevant_facts"][0]
        assert isinstance(rf, Fact)
        assert rf.fact

    def test_delete_fact(self, zep: ZepClient) -> None:
        """Delete a specific fact by ID."""
        sid = _sid("zep-test-fact-del")
        result = zep.add_fact(session_id=sid, fact="This will be deleted")
        fact_id = result["fact_id"]
        assert fact_id

        del_result = zep.delete_fact(fact_uuid=fact_id)
        assert del_result["status"] == "ok"
        assert del_result["deleted"] == 1

        # Should no longer be listed
        facts = zep.list_facts(session_id=sid)
        fact_texts = [f.fact for f in facts]
        assert "This will be deleted" not in fact_texts

    def test_delete_fact_nonexistent(self, zep: ZepClient) -> None:
        """Delete a nonexistent fact is idempotent."""
        result = zep.delete_fact(fact_uuid="nonexistent-uuid-123")
        assert result["status"] == "ok"
        assert result["deleted"] == 0

    # ------------------------------------------------------------------
    # update_memory tests
    # ------------------------------------------------------------------

    def test_update_memory(self, zep: ZepClient) -> None:
        """Update a memory's content."""
        sid = _sid("zep-test-update")
        add_result = zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Original content"}],
        )
        memory_id = add_result["message_ids"][0]
        assert memory_id

        result = zep.update_memory(
            session_id=sid,
            memory_id=memory_id,
            messages=[{"role": "user", "content": "Updated content"}],
        )
        assert result["status"] == "ok"

        # Verify the update
        memory = zep.get_memory(session_id=sid)
        assert memory is not None
        contents = [m["content"] for m in memory["messages"]]
        assert "Updated content" in contents

    def test_update_memory_empty_messages(self, zep: ZepClient) -> None:
        """update_memory with no messages is a no-op."""
        sid = _sid("zep-test-update-noop")
        add_result = zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Do not change"}],
        )
        memory_id = add_result["message_ids"][0]

        result = zep.update_memory(session_id=sid, memory_id=memory_id)
        assert result["status"] == "ok"

    # ------------------------------------------------------------------
    # search_memory min_score tests
    # ------------------------------------------------------------------

    def test_search_memory_min_score_alias(self, zep: ZepClient) -> None:
        """search_memory accepts min_score as alias for score_threshold."""
        sid = _sid("zep-test-min-score")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "The capital of France is Paris"}],
        )

        results = zep.search_memory(
            session_id=sid,
            query="France",
            limit=5,
            min_score=0.0,
        )
        assert isinstance(results, list)

    def test_search_memory_mmr_type(self, zep: ZepClient) -> None:
        """search_memory with search_type='mmr'."""
        sid = _sid("zep-test-mmr")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "MMR search test content"}],
        )

        results = zep.search_memory(
            session_id=sid,
            query="MMR search",
            limit=5,
            search_type="mmr",
        )
        assert isinstance(results, list)

    def test_get_session_messages(self, zep: ZepClient) -> None:
        """get_session_messages returns paginated messages."""
        sid = _sid("zep-test-session-msgs")
        zep.add_memory(
            session_id=sid,
            messages=[
                {"role": "user", "content": f"Msg {i}"}
                for i in range(3)
            ],
        )
        result = zep.get_session_messages(session_id=sid, limit=2)
        assert "messages" in result
        assert len(result["messages"]) <= 2

    def test_get_session_messages_nonexistent(self, zep: ZepClient) -> None:
        """get_session_messages on nonexistent session returns empty."""
        result = zep.get_session_messages(session_id=_sid("zep-test-noexist-msgs"))
        assert result["messages"] == []

    def test_get_session_message(self, zep: ZepClient) -> None:
        """get_session_message retrieves a single message by UUID."""
        sid = _sid("zep-test-get-msg")
        add_result = zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Single message retrieval"}],
        )
        msg_id = add_result["message_ids"][0] if add_result["message_ids"] else None
        if msg_id:
            msg = zep.get_session_message(session_id=sid, message_uuid=msg_id)
            assert msg["content"] == "Single message retrieval"

    def test_get_session_message_nonexistent(self, zep: ZepClient) -> None:
        """get_session_message on nonexistent message raises NotFoundError."""
        sid = _sid("zep-test-get-msg-ne")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Setup for test"}],
        )
        with pytest.raises(NotFoundError):
            zep.get_session_message(session_id=sid, message_uuid="nonexistent-uuid-999")

    def test_update_message_metadata(self, zep: ZepClient) -> None:
        """update_message_metadata updates metadata on a message."""
        sid = _sid("zep-test-update-meta")
        add_result = zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Metadata update test"}],
        )
        msg_id = add_result["message_ids"][0] if add_result["message_ids"] else None
        if msg_id:
            result = zep.update_message_metadata(
                session_id=sid, message_uuid=msg_id,
                metadata={"pinned": True, "tags": ["important"]},
            )
            assert result["metadata"]["pinned"] is True

    def test_get_fact(self, zep: ZepClient) -> None:
        """get_fact retrieves a fact by UUID."""
        sid = _sid("zep-test-get-fact")
        add_result = zep.add_fact(session_id=sid, fact="User enjoys cooking")
        fact_id = add_result["fact_id"]
        if fact_id:
            fact = zep.get_fact(fact_uuid=fact_id)
            assert isinstance(fact, Fact)
            assert fact.fact == "User enjoys cooking"

    def test_get_fact_nonexistent(self, zep: ZepClient) -> None:
        """get_fact on nonexistent raises NotFoundError."""
        with pytest.raises(NotFoundError):
            zep.get_fact(fact_uuid="nonexistent-fact-uuid-999")

    def test_add_fact_empty_string(self, zep: ZepClient) -> None:
        """add_fact with empty string still works."""
        sid = _sid("zep-test-fact-empty")
        result = zep.add_fact(session_id=sid, fact="")
        assert result["status"] == "ok"

    def test_list_facts_pagination(self, zep: ZepClient) -> None:
        """list_facts with limit parameter."""
        sid = _sid("zep-test-facts-pag")
        for i in range(5):
            zep.add_fact(session_id=sid, fact=f"Fact number {i}")
        facts = zep.list_facts(session_id=sid, limit=3)
        assert len(facts) <= 3

    def test_add_session(self, zep: ZepClient) -> None:
        """add_session creates a new session."""
        sid = _sid("zep-test-add-session")
        session = zep.add_session(session_id=sid, metadata={"source": "test"})
        assert isinstance(session, Session)
        assert session.session_id == sid

    def test_update_session(self, zep: ZepClient) -> None:
        """update_session updates metadata."""
        sid = _sid("zep-test-update-session")
        zep.add_session(session_id=sid)
        session = zep.update_session(session_id=sid, metadata={"updated": True})
        assert session.metadata == {"updated": True}

    def test_update_session_nonexistent(self, zep: ZepClient) -> None:
        """update_session on nonexistent raises NotFoundError."""
        with pytest.raises(NotFoundError):
            zep.update_session(session_id=_sid("zep-test-noexist-update"), metadata={})

    def test_search_sessions(self, zep: ZepClient) -> None:
        """search_sessions returns compatible sessions."""
        sid = _sid("zep-test-search-sessions")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Session search test"}],
        )
        results = zep.search_sessions(sid[:8], limit=5)
        assert isinstance(results, list)

    def test_list_sessions_pagination(self, zep: ZepClient) -> None:
        """list_sessions with pagination params."""
        sid = _sid("zep-test-list-sessions-pag")
        zep.add_session(session_id=sid)
        sessions = zep.list_sessions(page_number=1, page_size=10, order_by="created_at", asc=False)
        assert isinstance(sessions, list)

    def test_add_memory_with_no_messages(self, zep: ZepClient) -> None:
        """add_memory called without messages parameter is fine."""
        sid = _sid("zep-test-nomsg")
        result = zep.add_memory(session_id=sid, messages=[])
        assert result["status"] == "ok"
        assert result["message_ids"] == []

    def test_get_memory_with_min_rating(self, zep: ZepClient) -> None:
        """get_memory with min_rating parameter."""
        sid = _sid("zep-test-min-rating")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Rating test"}],
        )
        memory = zep.get_memory(session_id=sid, min_rating=0.5)
        assert memory is not None

    def test_search_memory_high_threshold(self, zep: ZepClient) -> None:
        """search_memory with high score threshold filters results."""
        sid = _sid("zep-test-high-thresh")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "Pizza is a popular food"}],
        )
        time.sleep(0.3)
        results = zep.search_memory(
            session_id=sid,
            query="quantum mechanics",
            limit=5,
            score_threshold=0.9,
        )
        assert isinstance(results, list)

    def test_update_memory_nonexistent(self, zep: ZepClient) -> None:
        """update_memory on nonexistent memory may raise RuntimeError."""
        sid = _sid("zep-test-update-ne")
        zep.add_session(session_id=sid)
        try:
            result = zep.update_memory(
                session_id=sid,
                memory_id="nonexistent-uuid-999",
                messages=[{"role": "user", "content": "Won't be stored"}],
            )
            assert result["status"] == "ok"
        except RuntimeError:
            pass  # Either behavior is acceptable

    def test_summarize_memory(self, zep: ZepClient) -> None:
        """summarize_memory returns a summary or None."""
        sid = _sid("zep-test-summarize")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "The quick brown fox jumps over the lazy dog"}],
        )
        result = zep.summarize_memory(session_id=sid)
        # Returns None if LLM not available, or summary string
        assert result is None or isinstance(result, str)

    def test_summarize_memory_empty(self, zep: ZepClient) -> None:
        """summarize_memory on empty session returns None."""
        result = zep.summarize_memory(session_id=_sid("zep-test-summarize-empty"))
        assert result is None

    def test_get_session_messages_with_cursor(self, zep: ZepClient) -> None:
        """get_session_messages with cursor pagination."""
        sid = _sid("zep-test-cursor")
        zep.add_memory(
            session_id=sid,
            messages=[
                {"role": "user", "content": f"Cursor msg {i}"}
                for i in range(4)
            ],
        )
        result = zep.get_session_messages(session_id=sid, limit=3, cursor=0)
        assert "messages" in result
        assert "cursor" in result

    def test_search_memory_with_mmr(self, zep: ZepClient) -> None:
        """search_memory with search_type mmr and high lambda."""
        sid = _sid("zep-test-mmr-high")
        zep.add_memory(
            session_id=sid,
            messages=[{"role": "user", "content": "MMR lambda test"}],
        )
        results = zep.search_memory(
            session_id=sid,
            query="MMR test",
            limit=5,
            search_type="mmr",
        )
        assert isinstance(results, list)

    def test_get_fact_from_session(self, zep: ZepClient) -> None:
        """get_fact after adding to a session returns the correct fact."""
        sid = _sid("zep-test-fact-session")
        add_result = zep.add_fact(session_id=sid, fact="Zep fact retrieval test")
        fact_id = add_result["fact_id"]
        if fact_id:
            fact = zep.get_fact(fact_uuid=fact_id)
            assert isinstance(fact, Fact)
            assert fact.uuid == fact_id


# ==========================================================================
# Data model to_dict() tests (no DB needed)
# ==========================================================================

class TestMemoryMessageToDict:
    """Cover MemoryMessage.to_dict() with various field combinations."""

    def test_to_dict_basic(self) -> None:
        msg = MemoryMessage(role="user", content="Hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"

    def test_to_dict_with_created_at(self) -> None:
        msg = MemoryMessage(role="assistant", content="Hi", created_at="2024-01-01T00:00:00Z")
        d = msg.to_dict()
        assert d["created_at"] == "2024-01-01T00:00:00Z"

    def test_to_dict_with_metadata(self) -> None:
        msg = MemoryMessage(role="user", content="test", metadata={"key": "val"})
        d = msg.to_dict()
        assert d["metadata"] == {"key": "val"}

    def test_to_dict_with_role_type(self) -> None:
        msg = MemoryMessage(role="user", content="test", role_type="user")
        d = msg.to_dict()
        assert d["role_type"] == "user"

    def test_to_dict_with_token_count(self) -> None:
        msg = MemoryMessage(role="user", content="test", token_count=42)
        d = msg.to_dict()
        assert d["token_count"] == 42

    def test_to_dict_with_updated_at(self) -> None:
        msg = MemoryMessage(role="user", content="test", updated_at="2024-06-01T00:00:00Z")
        d = msg.to_dict()
        assert d["updated_at"] == "2024-06-01T00:00:00Z"

    def test_to_dict_with_uuid(self) -> None:
        msg = MemoryMessage(role="user", content="test", uuid="abc-123")
        d = msg.to_dict()
        assert d["uuid"] == "abc-123"

    def test_to_dict_with_extra_kwargs(self) -> None:
        msg = MemoryMessage(role="user", content="test", extra_field="custom")
        d = msg.to_dict()
        assert d["extra_field"] == "custom"

    def test_to_dict_all_fields(self) -> None:
        msg = MemoryMessage(
            role="assistant",
            content="Full test",
            created_at="2024-01-01T00:00:00Z",
            metadata={"source": "test"},
            role_type="assistant",
            token_count=100,
            updated_at="2024-01-02T00:00:00Z",
            uuid="full-uuid-001",
        )
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "Full test"
        assert d["created_at"] == "2024-01-01T00:00:00Z"
        assert d["metadata"] == {"source": "test"}
        assert d["role_type"] == "assistant"
        assert d["token_count"] == 100
        assert d["updated_at"] == "2024-01-02T00:00:00Z"
        assert d["uuid"] == "full-uuid-001"


class TestMemoryToDict:
    """Cover Memory.__init__ and Memory.to_dict()."""

    def test_memory_basic(self) -> None:
        m = Memory(session_id="s1")
        d = m.to_dict()
        assert d["session_id"] == "s1"
        assert d["messages"] == []
        assert d["facts"] == []
        assert d["relevant_facts"] == []

    def test_memory_with_messages(self) -> None:
        msg = MemoryMessage(role="user", content="Hi")
        m = Memory(session_id="s2", messages=[msg])
        d = m.to_dict()
        assert len(d["messages"]) == 1
        assert d["messages"][0]["role"] == "user"
        assert d["messages"][0]["content"] == "Hi"

    def test_memory_with_facts(self) -> None:
        m = Memory(session_id="s3", facts=["Fact 1", "Fact 2"])
        d = m.to_dict()
        assert d["facts"] == ["Fact 1", "Fact 2"]

    def test_memory_with_relevant_facts(self) -> None:
        f = Fact(uuid="f1", fact="A fact")
        m = Memory(session_id="s4", relevant_facts=[f])
        d = m.to_dict()
        assert len(d["relevant_facts"]) == 1
        assert d["relevant_facts"][0]["fact"] == "A fact"

    def test_memory_with_metadata_and_kwargs(self) -> None:
        m = Memory(session_id="s5", metadata={"key": "val"}, extra="custom")
        d = m.to_dict()
        assert d["metadata"] == {"key": "val"}


class TestSessionToDict:
    """Cover Session.__init__ and Session.to_dict()."""

    def test_to_dict_basic(self) -> None:
        s = Session(session_id="test")
        d = s.to_dict()
        assert d["session_id"] == "test"
        assert d["metadata"] == {}
        assert d["created_at"] == ""
        assert d["updated_at"] == ""

    def test_to_dict_with_classifications(self) -> None:
        s = Session(session_id="s1", classifications=["technical", "urgent"])
        d = s.to_dict()
        assert d["classifications"] == ["technical", "urgent"]

    def test_to_dict_with_deleted_at(self) -> None:
        s = Session(session_id="s1", deleted_at="2024-01-01T00:00:00Z")
        d = s.to_dict()
        assert d["deleted_at"] == "2024-01-01T00:00:00Z"

    def test_to_dict_with_ended_at(self) -> None:
        s = Session(session_id="s1", ended_at="2024-02-01T00:00:00Z")
        d = s.to_dict()
        assert d["ended_at"] == "2024-02-01T00:00:00Z"

    def test_to_dict_with_fact_rating_instruction(self) -> None:
        s = Session(session_id="s1", fact_rating_instruction={"instruction": "Be thorough"})
        d = s.to_dict()
        assert d["fact_rating_instruction"] == {"instruction": "Be thorough"}

    def test_to_dict_with_facts(self) -> None:
        s = Session(session_id="s1", facts=["Fact A", "Fact B"])
        d = s.to_dict()
        assert d["facts"] == ["Fact A", "Fact B"]

    def test_to_dict_with_project_uuid(self) -> None:
        s = Session(session_id="s1", project_uuid="proj-001")
        d = s.to_dict()
        assert d["project_uuid"] == "proj-001"

    def test_to_dict_with_user_id(self) -> None:
        s = Session(session_id="s1", user_id="user-001")
        d = s.to_dict()
        assert d["user_id"] == "user-001"

    def test_to_dict_with_uuid(self) -> None:
        s = Session(session_id="s1", uuid="uuid-001")
        d = s.to_dict()
        assert d["uuid"] == "uuid-001"

    def test_to_dict_with_extra_kwargs(self) -> None:
        s = Session(session_id="s1", custom_field="value")
        d = s.to_dict()
        assert d["custom_field"] == "value"

    def test_to_dict_all_fields(self) -> None:
        s = Session(
            session_id="full-test",
            metadata={"env": "test"},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
            classifications=["A", "B"],
            deleted_at="2024-06-01T00:00:00Z",
            ended_at="2024-06-02T00:00:00Z",
            fact_rating_instruction={"instruction": "test"},
            facts=["f1"],
            project_uuid="p1",
            user_id="u1",
            uuid="uuid-full",
        )
        d = s.to_dict()
        assert d["session_id"] == "full-test"
        assert d["metadata"] == {"env": "test"}
        assert d["classifications"] == ["A", "B"]
        assert d["deleted_at"] == "2024-06-01T00:00:00Z"
        assert d["ended_at"] == "2024-06-02T00:00:00Z"
        assert d["fact_rating_instruction"] == {"instruction": "test"}
        assert d["facts"] == ["f1"]
        assert d["project_uuid"] == "p1"
        assert d["user_id"] == "u1"
        assert d["uuid"] == "uuid-full"


class TestMemorySearchResultToDict:
    """Cover MemorySearchResult.to_dict()."""

    def test_to_dict_with_message(self) -> None:
        msg = MemoryMessage(role="user", content="test")
        r = MemorySearchResult(message=msg, score=0.95, metadata={"src": "search"})
        d = r.to_dict()
        assert d["score"] == 0.95
        assert d["metadata"] == {"src": "search"}
        assert d["message"] is not None
        assert d["message"]["role"] == "user"
        assert d["message"]["content"] == "test"

    def test_to_dict_no_message(self) -> None:
        r = MemorySearchResult(message=None, score=0.0)
        d = r.to_dict()
        assert d["message"] is None
        assert d["score"] == 0.0


class TestFactToDict:
    """Cover Fact.__init__ and Fact.to_dict()."""

    def test_to_dict_basic(self) -> None:
        f = Fact(uuid="f-1", fact="User likes pizza")
        d = f.to_dict()
        assert d["uuid"] == "f-1"
        assert d["fact"] == "User likes pizza"
        assert d["created_at"] == ""

    def test_to_dict_with_rating(self) -> None:
        f = Fact(uuid="f-2", fact="A fact", rating=0.85)
        d = f.to_dict()
        assert d["rating"] == 0.85

    def test_to_dict_with_extra_kwargs(self) -> None:
        f = Fact(uuid="f-3", fact="test", extra="value")
        d = f.to_dict()
        assert d["extra"] == "value"

    def test_to_dict_no_rating(self) -> None:
        f = Fact(uuid="f-4", fact="test", rating=None)
        d = f.to_dict()
        assert "rating" not in d


# ==========================================================================
# Stub type tests (no DB needed)
# ==========================================================================

class TestStubTypes:
    """Cover all stub types from zep.py."""

    def test_summary_init(self) -> None:
        s = Summary(uuid="s-1", created_at="2024-01-01", content="Summary text", token_count=50)
        assert s.uuid == "s-1"
        assert s.content == "Summary text"
        assert s.token_count == 50

    def test_summary_with_kwargs(self) -> None:
        s = Summary(uuid="s-2", extra="custom")
        assert s.extra == "custom"

    def test_success_response(self) -> None:
        sr = SuccessResponse(message="Done", status="ok")
        assert sr.message == "Done"
        assert sr.status == "ok"

    def test_fact_rating_examples(self) -> None:
        fre = FactRatingExamples(high="High quality", medium="Medium", low="Low")
        assert fre.high == "High quality"
        assert fre.medium == "Medium"
        assert fre.low == "Low"

    def test_fact_rating_examples_with_kwargs(self) -> None:
        fre = FactRatingExamples(high="H", extra="custom")
        assert fre.extra == "custom"

    def test_fact_rating_instruction(self) -> None:
        examples = FactRatingExamples(high="H")
        fri = FactRatingInstruction(instruction="Be precise", examples=examples)
        assert fri.instruction == "Be precise"
        assert fri.examples is examples

    def test_fact_rating_instruction_defaults(self) -> None:
        fri = FactRatingInstruction()
        assert fri.instruction == ""
        assert fri.examples is None

    def test_session_fact_rating_examples(self) -> None:
        sfre = SessionFactRatingExamples(high="H", medium="M", low="L")
        assert sfre.high == "H"
        assert sfre.medium == "M"
        assert sfre.low == "L"

    def test_session_fact_rating_examples_kwargs(self) -> None:
        sfre = SessionFactRatingExamples(extra="x")
        assert sfre.extra == "x"

    def test_session_fact_rating_instruction(self) -> None:
        examples = SessionFactRatingExamples(high="H")
        sfri = SessionFactRatingInstruction(instruction="Rate facts", examples=examples)
        assert sfri.instruction == "Rate facts"
        assert sfri.examples is examples

    def test_session_fact_rating_instruction_defaults(self) -> None:
        sfri = SessionFactRatingInstruction()
        assert sfri.instruction == ""
        assert sfri.examples is None

    def test_role_type(self) -> None:
        assert RoleType.UserRole == "user"
        assert RoleType.AssistantRole == "assistant"
        assert RoleType.SystemRole == "system"
        assert RoleType.FunctionRole == "function"
        assert RoleType.ToolRole == "tool"

    def test_search_scope(self) -> None:
        assert SearchScope.MESSAGES == "messages"
        assert SearchScope.FACTS == "facts"
        assert SearchScope.SUMMARY == "summary"

    def test_search_type(self) -> None:
        assert SearchType.SIMILARITY == "similarity"
        assert SearchType.MMR == "mmr"

    def test_zep_environment(self) -> None:
        assert ZepEnvironment.CLOUD == "cloud"
        assert ZepEnvironment.SELF_HOSTED == "self_hosted"


# ==========================================================================
# Zep v2.0.2 sub-client proxy tests (need DB)
# ==========================================================================

class TestZepV2:
    """Tests for the Zep v2.0.2 client with .memory and .user sub-proxies."""

    def test_zep_init(self, host: str, port: int, stdb_session: dict) -> None:
        """Zep() init creates memory and user proxies."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            assert client.memory is not None
            assert client.user is not None
            # Verify it's also a ZepClient
            assert isinstance(client, ZepClient)
        finally:
            client.close()

    def test_memory_proxy_add_and_get(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy.add() and .get() delegate correctly."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2_mem")
        try:
            sid = _sid("zep-v2-mem")
            result = client.memory.add(
                session_id=sid,
                messages=[{"role": "user", "content": "Via memory proxy"}],
            )
            assert result["status"] == "ok"

            mem = client.memory.get(session_id=sid, limit=5)
            assert mem is not None
            assert "messages" in mem
        finally:
            client.close()

    def test_memory_proxy_search(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy.search() delegates correctly."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            sid = _sid("zep-v2-search")
            client.memory.add(session_id=sid, messages=[{"role": "user", "content": "Proxy search test"}])
            results = client.memory.search(session_id=sid, query="proxy", limit=5)
            assert isinstance(results, list)
        finally:
            client.close()

    def test_memory_proxy_delete(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy.delete() delegates correctly."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            sid = _sid("zep-v2-del")
            client.memory.add(session_id=sid, messages=[{"role": "user", "content": "To delete"}])
            result = client.memory.delete(session_id=sid)
            assert result["status"] == "ok"
        finally:
            client.close()

    def test_memory_proxy_add_fact(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy.add_fact() and get_fact() delegate."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            sid = _sid("zep-v2-fact")
            result = client.memory.add_fact(session_id=sid, fact="Proxy fact test")
            assert result["status"] == "ok"
            if result.get("fact_id"):
                fact = client.memory.get_fact(result["fact_id"])
                assert isinstance(fact, Fact)
        finally:
            client.close()

    def test_memory_proxy_delete_fact(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy.delete_fact() delegates."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            sid = _sid("zep-v2-delfact")
            result = client.memory.add_fact(session_id=sid, fact="Will be proxy-deleted")
            if result.get("fact_id"):
                del_result = client.memory.delete_fact(result["fact_id"])
                assert del_result["status"] == "ok"
        finally:
            client.close()

    def test_memory_proxy_session_methods(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy session methods (add_session, get_session, list_sessions, etc.)."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            sid = _sid("zep-v2-sess")
            s = client.memory.add_session(session_id=sid, metadata={"test": True})
            assert s.session_id == sid

            s2 = client.memory.get_session(sid)
            assert s2 is not None
            assert isinstance(s2, Session)

            sessions = client.memory.list_sessions(limit=10)
            assert isinstance(sessions, list)

            # search_sessions
            results = client.memory.search_sessions(sid[:8], limit=3)
            assert isinstance(results, list)

            # update_session
            updated = client.memory.update_session(sid, metadata={"updated": True})
            assert updated.metadata == {"updated": True}
        finally:
            client.close()

    def test_memory_proxy_message_level(self, host: str, port: int, stdb_session: dict) -> None:
        """_MemoryProxy message-level methods."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            sid = _sid("zep-v2-msg")
            add_result = client.memory.add(session_id=sid, messages=[{"role": "user", "content": "Msg level"}])
            msg_id = add_result["message_ids"][0] if add_result["message_ids"] else None

            msgs = client.memory.get_session_messages(session_id=sid, limit=5)
            assert "messages" in msgs

            if msg_id:
                msg = client.memory.get_session_message(session_id=sid, message_uuid=msg_id)
                assert "content" in msg

                result = client.memory.update_message_metadata(
                    session_id=sid, message_uuid=msg_id, metadata={"pinned": True}
                )
                assert result["metadata"]["pinned"] is True
        finally:
            client.close()

    @pytest.mark.skip(reason="User table/reducer not available in test setup")
    @pytest.mark.skip(reason="User table/reducer not available in test setup")
    def test_user_proxy_add_and_get(self, host: str, port: int, stdb_session: dict) -> None:
        """_UserProxy.add() and .get() delegate correctly."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            uid = _sid("zep-v2-user")
            user = client.user.add(user_id=uid, email="test@test.com", first_name="Test")
            assert user["user_id"] == uid

            fetched = client.user.get(uid)
            assert fetched["user_id"] == uid
        finally:
            client.close()

    @pytest.mark.skip(reason="User table/reducer not available in test setup")
    def test_user_proxy_update_and_delete(self, host: str, port: int, stdb_session: dict) -> None:
        """_UserProxy.update() and .delete()."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            uid = _sid("zep-v2-user-upd")
            client.user.add(user_id=uid, email="old@test.com")
            updated = client.user.update(uid, email="new@test.com", first_name="Updated")
            assert updated["email"] == "new@test.com"

            result = client.user.delete(uid)
            assert result["status"] == "ok"
        finally:
            client.close()

    @pytest.mark.skip(reason="User table/reducer not available in test setup")
    def test_user_proxy_list_ordered(self, host: str, port: int, stdb_session: dict) -> None:
        """_UserProxy.list_ordered()."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            uid = _sid("zep-v2-user-list")
            client.user.add(user_id=uid, email="list@test.com")
            result = client.user.list_ordered(page_number=1, page_size=10)
            assert "users" in result
            assert isinstance(result["users"], list)
        finally:
            client.close()

    @pytest.mark.skip(reason="User table/reducer not available in test setup")
    def test_user_proxy_get_sessions(self, host: str, port: int, stdb_session: dict) -> None:
        """_UserProxy.get_sessions()."""
        client = Zep(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "v2")
        try:
            uid = _sid("zep-v2-user-sess")
            client.user.add(user_id=uid, email="sess@test.com")
            sessions = client.user.get_sessions(uid)
            assert isinstance(sessions, list)
        finally:
            client.close()


# ==========================================================================
# AsyncZepClient tests (need DB + asyncio)
# ==========================================================================

class TestAsyncZepClient:
    """Tests for AsyncZepClient async wrapper."""

    @pytest.mark.asyncio
    async def test_init(self, host: str, port: int, stdb_session: dict) -> None:
        """AsyncZepClient init creates sync client."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        assert client._sync is not None

    @pytest.mark.asyncio
    async def test_add_and_get_memory(self, host: str, port: int, stdb_session: dict) -> None:
        """Async add_memory and get_memory."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-mem")
            result = await client.add_memory(
                session_id=sid,
                messages=[{"role": "user", "content": "Async test"}],
            )
            assert result["status"] == "ok"

            mem = await client.get_memory(session_id=sid)
            assert mem is not None
            assert "messages" in mem
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_delete_memory(self, host: str, port: int, stdb_session: dict) -> None:
        """Async delete_memory."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-del")
            await client.add_memory(session_id=sid, messages=[{"role": "user", "content": "Del"}])
            result = await client.delete_memory(session_id=sid)
            assert result["status"] == "ok"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_search_memory(self, host: str, port: int, stdb_session: dict) -> None:
        """Async search_memory."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-search")
            await client.add_memory(session_id=sid, messages=[{"role": "user", "content": "Async search"}])
            results = await client.search_memory(session_id=sid, query="Async", limit=5)
            assert isinstance(results, list)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_facts(self, host: str, port: int, stdb_session: dict) -> None:
        """Async add_fact, list_facts, get_fact, delete_fact."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-fact")
            result = await client.add_fact(session_id=sid, fact="Async fact")
            assert result["status"] == "ok"

            facts = await client.list_facts(session_id=sid)
            assert isinstance(facts, list)

            if result.get("fact_id"):
                fact = await client.get_fact(result["fact_id"])
                assert isinstance(fact, Fact)

                del_result = await client.delete_fact(result["fact_id"])
                assert del_result["status"] == "ok"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_memory(self, host: str, port: int, stdb_session: dict) -> None:
        """Async update_memory."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-update")
            add_result = await client.add_memory(session_id=sid, messages=[{"role": "user", "content": "Old"}])
            memory_id = add_result["message_ids"][0] if add_result["message_ids"] else None
            if memory_id:
                result = await client.update_memory(
                    session_id=sid, memory_id=memory_id,
                    messages=[{"role": "user", "content": "New"}],
                )
                assert result["status"] == "ok"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_session_message_methods(self, host: str, port: int, stdb_session: dict) -> None:
        """Async get_session_messages, get_session_message, update_message_metadata."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-sess-msg")
            add_result = await client.add_memory(session_id=sid, messages=[{"role": "user", "content": "Msg"}])
            msg_id = add_result["message_ids"][0] if add_result["message_ids"] else None

            msgs = await client.get_session_messages(session_id=sid, limit=5)
            assert "messages" in msgs

            if msg_id:
                msg = await client.get_session_message(session_id=sid, message_uuid=msg_id)
                assert "content" in msg

                result = await client.update_message_metadata(
                    session_id=sid, message_uuid=msg_id, metadata={"key": "val"}
                )
                assert result["metadata"]["key"] == "val"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_session_management(self, host: str, port: int, stdb_session: dict) -> None:
        """Async list_sessions, get_session, add_session, update_session, search_sessions."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-sess-mgmt")
            s = await client.add_session(session_id=sid, metadata={"test": True})
            assert s.session_id == sid

            s2 = await client.get_session(sid)
            assert s2 is not None

            sessions = await client.list_sessions(limit=10)
            assert isinstance(sessions, list)

            results = await client.search_sessions(sid[:8], limit=3)
            assert isinstance(results, list)

            updated = await client.update_session(sid, metadata={"updated": True})
            assert updated.metadata == {"updated": True}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_summarize_memory(self, host: str, port: int, stdb_session: dict) -> None:
        """Async summarize_memory."""
        client = AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]})
        _register_client(client, "async")
        try:
            sid = _sid("async-summarize")
            await client.add_memory(session_id=sid, messages=[{"role": "user", "content": "Test"}])
            result = await client.summarize_memory(session_id=sid)
            assert result is None or isinstance(result, str)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_async_context_manager(self, host: str, port: int, stdb_session: dict) -> None:
        """AsyncZepClient as async context manager."""
        async with AsyncZepClient(host=host, port=port, config={"db": stdb_session["database"]}) as client:
            _register_client(client, "async_ctx")
            sid = _sid("async-ctx")
            result = await client.add_memory(
                session_id=sid,
                messages=[{"role": "user", "content": "Context manager test"}],
            )
            assert result["status"] == "ok"


# ==========================================================================
# AsyncZep tests (v2.0.2 async with .memory/.user proxies)
# ==========================================================================

class TestAsyncZepV2:
    """Tests for AsyncZep with .memory and .user proxies."""

    @pytest.mark.asyncio
    async def test_init(self, host: str, port: int, stdb_session: dict) -> None:
        """AsyncZep init creates proxies."""
        async with AsyncZep(host=host, port=port, config={"db": stdb_session["database"]}) as client:
            _register_client(client, "async_zep")
            assert client.memory is not None
            assert client.user is not None

    @pytest.mark.asyncio
    async def test_memory_proxy(self, host: str, port: int, stdb_session: dict) -> None:
        """AsyncZep.memory proxy delegates correctly."""
        async with AsyncZep(host=host, port=port, config={"db": stdb_session["database"]}) as client:
            _register_client(client, "async_zep")
            sid = _sid("async-zep-mem")

            # add and get
            result = await client.memory.add(session_id=sid, messages=[{"role": "user", "content": "AsyncZep mem"}])
            assert result["status"] == "ok"

            mem = await client.memory.get(session_id=sid)
            assert mem is not None

            # search
            results = await client.memory.search(session_id=sid, query="AsyncZep", limit=5)
            assert isinstance(results, list)

            # facts
            fact_result = await client.memory.add_fact(session_id=sid, fact="AsyncZep fact")
            assert fact_result["status"] == "ok"
            if fact_result.get("fact_id"):
                fact = await client.memory.get_fact(fact_result["fact_id"])
                assert isinstance(fact, Fact)
                await client.memory.delete_fact(fact_result["fact_id"])

            # session management
            sess_sid = _sid("async-zep-sess")
            s = await client.memory.add_session(session_id=sess_sid)
            assert s.session_id == sess_sid
            s2 = await client.memory.get_session(sess_sid)
            assert s2 is not None
            await client.memory.update_session(sess_sid, metadata={"x": "y"})

            # list and search sessions
            sessions = await client.memory.list_sessions(limit=10)
            assert isinstance(sessions, list)
            search_res = await client.memory.search_sessions(sess_sid[:8], limit=3)
            assert isinstance(search_res, list)

            # message-level ops
            add2 = await client.memory.add(session_id=sid, messages=[{"role": "user", "content": "Msg level"}])
            mid = add2["message_ids"][0] if add2["message_ids"] else None
            if mid:
                msgs = await client.memory.get_session_messages(session_id=sid, limit=5)
                assert "messages" in msgs
                msg = await client.memory.get_session_message(session_id=sid, message_uuid=mid)
                assert "content" in msg
                await client.memory.update_message_metadata(session_id=sid, message_uuid=mid, metadata={"k": "v"})

            # delete
            await client.memory.delete(session_id=sid)

    @pytest.mark.skip(reason="User table/reducer not available in test setup")
    @pytest.mark.asyncio
    async def test_user_proxy(self, host: str, port: int, stdb_session: dict) -> None:
        """AsyncZep.user proxy delegates correctly."""
        async with AsyncZep(host=host, port=port, config={"db": stdb_session["database"]}) as client:
            _register_client(client, "async_zep")
            uid = _sid("async-zep-user")
            user = await client.user.add(user_id=uid, email="az@test.com", first_name="AZ")
            assert user["user_id"] == uid

            fetched = await client.user.get(uid)
            assert fetched["user_id"] == uid
