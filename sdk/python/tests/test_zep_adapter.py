"""Integration tests for the Zep adapter.

Requires a running SpacetimeDB instance.
"""

from __future__ import annotations

import os
import pytest

from spacetime_memory import Client
from spacetime_memory.sdks.zep import (
    FactResponse,
    Memory,
    Message,
    Session,
    SessionSearchResult,
    Zep,
)
from spacetime_memory.auth import generate_token

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", None)


def _generate_test_token() -> str:
    key_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "id_ecdsa_pkcs8.pem"
    )
    key_path = os.path.abspath(key_path)
    if os.path.exists(key_path):
        return generate_token(key_path)
    return ""


@pytest.fixture(scope="module")
def token() -> str:
    return _generate_test_token()


@pytest.fixture(scope="module")
def client(token: str) -> Client:
    kwargs = {"host": HOST, "port": PORT, "token": token}
    if DB:
        kwargs["database"] = DB
    return Client(**kwargs)


@pytest.fixture(scope="module")
def zep(client: Client) -> Zep:
    return Zep(client=client)


class TestZep:
    """Tests for the Zep-compatible adapter."""

    def test_add_session(self, zep: Zep):
        """Creating a session returns a Session object."""
        session = zep.memory.add_session(session_id="test-session-1")
        assert isinstance(session, Session)
        assert session.session_id == "test-session-1"

    def test_get_session(self, zep: Zep):
        """Getting an existing session returns it."""
        zep.memory.add_session(session_id="test-session-2", user_id="alice")
        session = zep.memory.get_session("test-session-2")
        assert session is not None
        assert session.session_id == "test-session-2"

    def test_get_session_nonexistent(self, zep: Zep):
        """Getting a nonexistent session returns None."""
        session = zep.memory.get_session("nonexistent-session-uuid")
        assert session is None or isinstance(session, Session)

    def test_add_messages(self, zep: Zep):
        """Adding messages to a session succeeds."""
        zep.memory.add_session(session_id="test-session-3")
        result = zep.memory.add("test-session-3", messages=[
            Message(role_type="user", content="I like pizza"),
            Message(role_type="assistant", content="Great choice!"),
        ])
        assert result.ok is True

    def test_get_memory(self, zep: Zep):
        """Getting memory returns messages."""
        zep.memory.add_session(session_id="test-session-4")
        zep.memory.add("test-session-4", messages=[
            Message(role_type="user", content="Hello world"),
        ])
        memory = zep.memory.get("test-session-4")
        assert memory is not None
        assert isinstance(memory, Memory)
        assert len(memory.messages) >= 1

    def test_get_memory_nonexistent(self, zep: Zep):
        """Getting memory for a nonexistent session returns None."""
        memory = zep.memory.get("nonexistent-session-memory")
        assert memory is None

    def test_get_memory_lastn(self, zep: Zep):
        """Getting memory with lastn returns only the last N messages."""
        zep.memory.add_session(session_id="test-session-5")
        zep.memory.add("test-session-5", messages=[
            Message(role_type="user", content=f"Message {i}") for i in range(10)
        ])
        memory = zep.memory.get("test-session-5", lastn=3)
        assert memory is not None
        assert len(memory.messages) <= 3

    def test_list_sessions(self, zep: Zep):
        """Listing sessions returns created sessions."""
        sessions = zep.memory.list_sessions()
        assert isinstance(sessions, list)
        # Should have at least the sessions we created
        session_ids = {s.session_id for s in sessions}
        assert "test-session-1" in session_ids

    def test_search_sessions(self, zep: Zep):
        """Searching sessions returns relevant results."""
        zep.memory.add_session(session_id="test-search-session")
        zep.memory.add("test-search-session", messages=[
            Message(role_type="user", content="I love eating pepperoni pizza"),
        ])
        results = zep.memory.search_sessions(text="pizza")
        assert isinstance(results, list)

    def test_search_sessions_empty(self, zep: Zep):
        """Searching with no text returns empty."""
        results = zep.memory.search_sessions(text="")
        assert results == []

    def test_get_session_messages(self, zep: Zep):
        """Getting session messages returns paginated results."""
        zep.memory.add_session(session_id="test-session-6")
        zep.memory.add("test-session-6", messages=[
            Message(role_type="user", content=f"Msg {i}") for i in range(5)
        ])
        result = zep.memory.get_session_messages("test-session-6", limit=3)
        assert "messages" in result
        assert "cursor" in result
        assert len(result["messages"]) <= 3

    def test_get_session_message(self, zep: Zep):
        """Getting a specific message by UUID works."""
        # First add a message and get its UUID
        zep.memory.add_session(session_id="test-session-7")
        zep.memory.add("test-session-7", messages=[
            Message(role_type="user", content="Find me by UUID"),
        ])
        memory = zep.memory.get("test-session-7")
        assert memory is not None and len(memory.messages) > 0
        msg_uuid = memory.messages[0].uuid

        result = zep.memory.get_session_message("test-session-7", msg_uuid)
        assert result is not None
        assert result["content"] == "Find me by UUID"

    def test_update_session(self, zep: Zep):
        """Updating session metadata works."""
        zep.memory.add_session(session_id="test-session-8")
        updated = zep.memory.update_session(
            "test-session-8", metadata={"theme": "dark"}
        )
        assert isinstance(updated, Session)
        assert updated.metadata.get("theme") == "dark"

    def test_update_message_metadata(self, zep: Zep):
        """Updating message metadata works."""
        zep.memory.add_session(session_id="test-session-9")
        zep.memory.add("test-session-9", messages=[
            Message(role_type="user", content="Update my meta"),
        ])
        memory = zep.memory.get("test-session-9")
        assert memory is not None and len(memory.messages) > 0
        msg_uuid = memory.messages[0].uuid

        updated = zep.memory.update_message_metadata(
            "test-session-9", msg_uuid, metadata={"source": "test"}
        )
        assert updated["metadata"]["source"] == "test"

    def test_delete_session(self, zep: Zep):
        """Deleting a session's memory succeeds."""
        zep.memory.add_session(session_id="test-session-delete")
        zep.memory.add("test-session-delete", messages=[
            Message(role_type="user", content="Delete me"),
        ])
        result = zep.memory.delete("test-session-delete")
        assert result.ok is True

    def test_delete_nonexistent_session(self, zep: Zep):
        """Deleting a nonexistent session returns ok."""
        result = zep.memory.delete("nonexistent-delete-session")
        assert result.ok is True

    def test_session_with_user_id(self, zep: Zep):
        """Creating a session with user_id stores it."""
        session = zep.memory.add_session(
            session_id="test-session-user", user_id="bob"
        )
        assert session.user_id == "bob"

    def test_messages_with_dict(self, zep: Zep):
        """Adding messages as dicts works (compat with Zep API)."""
        zep.memory.add_session(session_id="test-session-dict")
        result = zep.memory.add("test-session-dict", messages=[
            {"role_type": "user", "content": "Dict message"},
        ])
        assert result.ok is True
        memory = zep.memory.get("test-session-dict")
        assert memory is not None
        assert any("Dict message" in m.content for m in memory.messages)
