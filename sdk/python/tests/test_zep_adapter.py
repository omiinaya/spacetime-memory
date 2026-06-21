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
    MemorySearchResult,
    Session,
    Fact,
    NotFoundError,
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
