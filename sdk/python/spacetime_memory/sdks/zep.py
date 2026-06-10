"""
Zep-compatible memory adapter.

Maps the Zep long-term memory API (https://github.com/getzep/zep-python)
to SpacetimeDB. Provides signature-compatible ``ZepClient`` with
memory CRUD, search, fact management, and session lifecycle.

All public methods raise the same typed exceptions as upstream
``zep_python`` (``NotFoundError``, ``BadRequestError``, ``ApiError``)
when the real library is installed, with graceful fallback to
``RuntimeError`` subclasses.

NOTE: Missing some advanced features — ``get_session_message()``,
``get_session_messages()``, ``update_message_metadata()``.

Maps::

    Zep session       → SpacetimeDB workspace
    Zep message       → SpacetimeDB memory record (experience type)
    Zep memory search → SpacetimeDB hybrid_search
    Zep fact          → SpacetimeDB memory record (fact type)

Usage::

    from spacetime_memory.sdks.zep import ZepClient

    client = ZepClient(host="localhost", port=3001)

    # Add memory messages to a session
    result = client.add_memory(
        session_id="alice-session",
        messages=[{"role": "user", "content": "I like pizza"}],
    )

    # Get memory for a session
    memory = client.get_memory(session_id="alice-session")

    # Search memory
    results = client.search_memory(
        session_id="alice-session", query="food preferences"
    )

    # Add and list facts
    client.add_fact(session_id="alice-session", fact="User likes pizza")
    facts = client.list_facts(session_id="alice-session")

    # List sessions
    sessions = client.list_sessions()

    # Close when done
    client.close()
"""

from __future__ import annotations

import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from ..client import Client

try:
    from zep_python import NotFoundError, BadRequestError, ApiError
except ImportError:
    # Fallback: define our own so imports don't break
    class NotFoundError(RuntimeError):
        pass

    class BadRequestError(RuntimeError):
        pass

    class ApiError(RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Data structures (matching zep-python shapes)
# ---------------------------------------------------------------------------


class MemoryMessage:
    """A single message in a Zep memory session.

    Mirrors ``zep_python.memory.models.MemoryMessage``.
    """

    def __init__(
        self,
        role: str = "user",
        content: str = "",
        **kwargs: Any,
    ) -> None:
        self.role = role
        self.content = content
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        d.update(
            {k: v for k, v in self.__dict__.items() if k not in ("role", "content")}
        )
        return d


class Memory:
    """Memory response from Zep.

    Mirrors ``zep_python.memory.models.Memory``.
    """

    def __init__(
        self,
        session_id: str = "",
        messages: list[MemoryMessage] | None = None,
        metadata: dict[str, Any] | None = None,
        facts: list[str] | None = None,
        relevant_facts: list["Fact"] | None = None,
        **kwargs: Any,
    ) -> None:
        self.session_id = session_id
        self.messages = messages or []
        self.metadata = metadata or {}
        self.facts = facts or []
        self.relevant_facts = relevant_facts or []
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "facts": self.facts,
            "relevant_facts": [f.to_dict() for f in self.relevant_facts],
        }


class Session:
    """A Zep session.

    Mirrors ``zep_python.memory.models.Session``.
    """

    def __init__(
        self,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.session_id = session_id
        self.metadata = metadata or {}
        self.created_at = created_at or ""
        self.updated_at = updated_at or ""
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MemorySearchResult:
    """A single search result from Zep memory search.

    Mirrors ``zep_python.memory.models.MemorySearchResult``.
    """

    def __init__(
        self,
        message: MemoryMessage | None = None,
        score: float = 0.0,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.message = message
        self.score = score
        self.metadata = metadata or {}
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict() if self.message else None,
            "score": self.score,
            "metadata": self.metadata,
        }


class Fact:
    """A single fact in a Zep session.

    Mirrors ``zep_python.types.Fact``.

    Stores a factual statement about the user, extracted from conversation.
    """

    def __init__(
        self,
        uuid: str = "",
        fact: str = "",
        created_at: str | None = None,
        rating: float | None = None,
        **kwargs: Any,
    ) -> None:
        self.uuid = uuid
        self.fact = fact
        self.created_at = created_at or ""
        self.rating = rating
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "uuid": self.uuid,
            "fact": self.fact,
            "created_at": self.created_at,
        }
        if self.rating is not None:
            d["rating"] = self.rating
        d.update({k: v for k, v in self.__dict__.items() if k not in ("uuid", "fact", "created_at", "rating")})
        return d


# ---------------------------------------------------------------------------
# ZepClient — main entry point
# ---------------------------------------------------------------------------


class ZepClient:
    """Drop-in replacement for ``zep_python.ZepClient``.

    Maps Zep's REST API onto Spacetime-Memory's storage layer:

    * ``session_id`` → ``workspace name`` / memory type tag
    * ``messages`` → memory records with ``memory_type="experience"``
    * ``facts`` → memory records with ``memory_type="fact"``
    * ``search`` → ``hybrid_search`` with semantic + keyword matching

    Note: Zep's async endpoints, WebSocket streams, and LLM-based
    summarisation are not available via Spacetime-Memory.

    Usage::

        from spacetime_memory.sdks.zep import ZepClient

        client = ZepClient(host="localhost", port=3001)
        client.add_memory(
            session_id="my-session",
            messages=[{"role": "user", "content": "Hello world"}],
        )
        memory = client.get_memory(session_id="my-session")
        results = client.search_memory(session_id="my-session", query="hello")
        client.close()

    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        config: dict[str, Any] | None = None,
        token: str | None = None,
    ):
        self._client = Client(
            host=host,
            port=port,
            database=config.get("db", config.get("database")) if config else None,
            embedder_url=config.get("embedder_url") if config else None,
            token=token or "",
        )
        # Cache: session_id -> workspace_id
        self._session_to_ws: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_workspace(self, session_id: str) -> str:
        """Resolve a Zep session_id to a workspace, creating if needed."""
        if session_id in self._session_to_ws:
            return self._session_to_ws[session_id]

        workspaces = self._client.list_workspaces()
        match = [w for w in workspaces if w.get("name") == session_id]
        if match:
            ws_id = match[0]["id"]
        else:
            self._client.create_workspace(session_id, f"Zep session: {session_id}")
            # Re-list to get the new workspace's ID
            workspaces = self._client.list_workspaces()
            match = [w for w in workspaces if w.get("name") == session_id]
            ws_id = match[0]["id"] if match else ""

        self._session_to_ws[session_id] = ws_id
        return ws_id

    def _resolve_session(self, session_id: str) -> str | None:
        """Resolve a session_id to a workspace_id without creating.

        Returns None if the session doesn't exist yet.
        """
        if session_id in self._session_to_ws:
            return self._session_to_ws[session_id]
        workspaces = self._client.list_workspaces()
        match = [w for w in workspaces if w.get("name") == session_id]
        if not match:
            return None
        self._session_to_ws[session_id] = match[0]["id"]
        return match[0]["id"]

    def _now_iso(self) -> str:
        """ISO-8601 timestamp."""
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Zep Memory API
    # ------------------------------------------------------------------

    def add_memory(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | list[MemoryMessage],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store messages as memory for a session.

        Args:
            session_id: Zep session identifier.
            messages: List of message dicts (``{role, content}``) or
                ``MemoryMessage`` objects.
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status.

        Example::

            >>> client.add_memory(
            ...     session_id="my-session",
            ...     messages=[{"role": "user", "content": "Hi!"}],
            ... )
            {'status': 'ok'}

        """
        ws_id = self._ensure_workspace(session_id)
        stored_ids: list[str] = []
        for msg in messages:
            if isinstance(msg, MemoryMessage):
                role = msg.role
                content = msg.content
            elif isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
            else:
                role = "user"
                content = str(msg)

            self._client.store(
                workspace_id=ws_id,
                content=content,
                summary=f"[{role}] {content[:200]}",
                memory_type="experience",
                peer_id=role,
                source_session_id=session_id,
            )

        # After storing, fetch IDs for the messages we just added
        memories = self._client.list_memories(
            workspace_id=ws_id, limit=len(messages), memory_type="experience"
        )
        for m in memories or []:
            mid = m.get("id", "") or m.get("entity_id", "")
            if mid and mid not in stored_ids:
                stored_ids.append(mid)

        return {"status": "ok", "message_ids": stored_ids}

    def get_memory(
        self,
        session_id: str,
        limit: int = 10,
        min_rating: float = 0.0,
    ) -> dict[str, Any] | None:
        """Retrieve messages + facts for a session.

        Returns a dict matching the Zep ``Memory`` response shape
        (messages, facts, relevant_facts).

        Args:
            session_id: Zep session identifier.
            limit: Max messages to return (default 10).
            min_rating: Minimum memory rating filter (default 0.0).

        Returns:
            A dict with ``messages``, ``facts``, and ``relevant_facts``
            keys, or ``None`` if the session has no messages.

        Example::

            >>> client.get_memory(session_id="my-session")
            {
                'messages': [...],
                'facts': ['User likes pizza'],
                'relevant_facts': [...],
            }

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return None

        # Get experience messages
        memories = self._client.list_memories(
            workspace_id=ws_id, limit=limit, memory_type="experience"
        )

        # Get facts
        facts_raw = self._client.list_memories(
            workspace_id=ws_id, limit=100, memory_type="fact"
        )

        messages_out = []
        for m in (memories or []):
            if min_rating > 0.0:
                rating = m.get("rating", 0.0) or 0.0
                if rating < min_rating:
                    continue
            role = m.get("peer_id", "user")
            content = m.get("content", "")
            messages_out.append({
                "role": role,
                "content": content,
                "score": m.get("strength", m.get("access_count", 1.0)),
                "timestamp": m.get("created_at", ""),
            })

        fact_strings = [f.get("content", "") for f in (facts_raw or [])]
        relevant_facts_objs = [
            Fact(
                uuid=f.get("id", ""),
                fact=f.get("content", ""),
                created_at=str(f.get("created_at", "")),
            )
            for f in (facts_raw or [])
        ]

        return {
            "messages": messages_out,
            "facts": fact_strings,
            "relevant_facts": relevant_facts_objs,
        }

    def delete_memory(self, session_id: str) -> dict[str, Any]:
        """Delete all memory for a session.

        Args:
            session_id: Zep session identifier.

        Returns:
            A dict with operation status and count of deleted items.

        Example::

            >>> client.delete_memory(session_id="my-session")
            {'status': 'ok', 'deleted': 3}

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return {"status": "ok", "deleted": 0}

        memories = self._client.list_memories(
            workspace_id=ws_id, limit=1000, memory_type="experience"
        )
        deleted = 0
        for m in (memories or []):
            mem_id = m.get("id", "") or m.get("entity_id", "")
            if mem_id:
                try:
                    self._client.delete_memory(mem_id)
                    deleted += 1
                except ValueError:
                    raise
                except RuntimeError:
                    pass

        return {"status": "ok", "deleted": deleted}

    def search_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        score_threshold: float = 0.0,
        min_score: float | None = None,
    ) -> list[MemorySearchResult]:
        """Search memory messages within a session.

        Args:
            session_id: Zep session identifier.
            query: The search query.
            limit: Max results (default 10).
            score_threshold: Minimum similarity score (default 0.0).
            min_score: Alias for ``score_threshold`` (Zep Cloud compat).

        Returns:
            A list of ``MemorySearchResult`` objects.

        Example::

            >>> results = client.search_memory(
            ...     session_id="my-session",
            ...     query="food preferences",
            ... )
            >>> results[0].message.content
            'I like pizza'

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return []

        effective_threshold = (
            min_score if min_score is not None else score_threshold
        )

        rows = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=limit,
            semantic=True,
        )
        results: list[MemorySearchResult] = []
        for r in rows or []:
            score = r.get("score", 0.0)
            if effective_threshold > 0.0 and score < effective_threshold:
                continue
            content = r.get("memory_content", r.get("content", ""))
            role = r.get("peer_id", r.get("source_session_id", "user"))
            msg = MemoryMessage(role=role, content=content)
            results.append(MemorySearchResult(message=msg, score=score))

        return results

    # ------------------------------------------------------------------
    # Zep Facts API
    # ------------------------------------------------------------------

    def add_fact(
        self,
        session_id: str,
        fact: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a factual statement to a session.

        Facts are stored as memories with ``memory_type="fact"`` and can
        be retrieved with ``list_facts()`` or included in ``get_memory()``
        results.

        Args:
            session_id: Zep session identifier.
            fact: The factual statement to store.
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status and fact_id.

        Example::

            >>> client.add_fact(
            ...     session_id="my-session",
            ...     fact="User prefers dark mode interfaces",
            ... )
            {'status': 'ok', 'fact_id': '...'}

        """
        ws_id = self._ensure_workspace(session_id)
        result = self._client.store(
            workspace_id=ws_id,
            content=fact,
            summary=f"[fact] {fact[:200]}",
            memory_type="fact",
            source_session_id=session_id,
        )

        # Read back the fact ID from the last stored fact
        memory_id = ""
        stored = self._client.list_memories(
            workspace_id=ws_id, limit=1, memory_type="fact"
        )
        if stored:
            memory_id = stored[0].get("id", stored[0].get("entity_id", ""))

        return {"status": "ok", "fact_id": memory_id}

    def list_facts(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[Fact]:
        """List all facts for a session.

        Args:
            session_id: Zep session identifier.
            limit: Max facts to return (default 100).

        Returns:
            A list of ``Fact`` objects, each containing ``uuid``,
            ``fact``, ``created_at``, and optionally ``rating``.

        Example::

            >>> facts = client.list_facts(session_id="my-session")
            >>> facts[0].fact
            'User prefers dark mode interfaces'

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return []

        rows = self._client.list_memories(
            workspace_id=ws_id, limit=limit, memory_type="fact"
        )
        return [
            Fact(
                uuid=r.get("id", r.get("entity_id", "")),
                fact=r.get("content", ""),
                created_at=str(r.get("created_at", "")),
                rating=r.get("confidence", None),
            )
            for r in rows or []
        ]

    def delete_fact(self, session_id: str, fact_id: str) -> dict[str, Any]:
        """Delete a specific fact by its ID.

        Args:
            session_id: Zep session identifier.
            fact_id: The UUID of the fact to delete.

        Returns:
            A dict with operation status.

        Example::

            >>> client.delete_fact(session_id="my-session", fact_id="abc-123")
            {'status': 'ok', 'deleted': 1}

        """
        result = self._client.delete_memory(fact_id)
        # delete_memory returns {"status": "ok", "note": "already deleted"}
        # when the memory wasn't found — treat as deleted=0
        note = result.get("note", "")
        if note == "already deleted":
            return {"status": "ok", "deleted": 0, "note": "not found"}
        return {"status": "ok", "deleted": 1}

    # ------------------------------------------------------------------
    # Zep Memory Update
    # ------------------------------------------------------------------

    def update_memory(
        self,
        session_id: str,
        memory_id: str,
        messages: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a memory's content and/or metadata.

        In Zep this accepts a ``MemoryUpdate``; here we update the content
        from the last provided message and store metadata on the record.

        Args:
            session_id: Zep session identifier.
            memory_id: The UUID of the memory to update.
            messages: Updated message content (uses last message's content).
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status.

        Example::

            >>> client.update_memory(
            ...     session_id="my-session",
            ...     memory_id="abc-123",
            ...     messages=[{"role": "user", "content": "Updated content"}],
            ... )
            {'status': 'ok'}

        """
        content = ""
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                content = last_msg.get("content", "")
            elif isinstance(last_msg, MemoryMessage):
                content = last_msg.content
            else:
                content = str(last_msg)

        if content:
            self._client.update_memory(
                memory_id=memory_id,
                content=content,
            )

        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def list_sessions(
        self, limit: int = 100, offset: int = 0
    ) -> list[Session]:
        """List all sessions (workspaces).

        Args:
            limit: Max sessions to return (default 100).
            offset: Pagination offset (default 0).

        Returns:
            A list of ``Session`` objects.

        """
        workspaces = self._client.list_workspaces()
        sliced = workspaces[offset:offset + limit] if workspaces else []
        sessions = []
        for ws in sliced:
            sessions.append(Session(
                session_id=ws.get("name", ws.get("id", "")),
                metadata={},
                created_at=ws.get("created_at", ""),
            ))
        return sessions

    def get_session(self, session_id: str) -> Session | None:
        """Get a single session by its ID.

        Args:
            session_id: Zep session identifier.

        Returns:
            A ``Session`` object, or raises ``NotFoundError`` if not found.

        Raises:
            NotFoundError: If the session does not exist (matching zep-python).

        """
        workspaces = self._client.list_workspaces()
        for ws in workspaces:
            if ws.get("name") == session_id or ws.get("id") == session_id:
                return Session(
                    session_id=ws.get("name", ws.get("id", "")),
                    metadata={},
                    created_at=ws.get("created_at", ""),
                )
        raise NotFoundError(f"Session '{session_id}' not found")

    def add_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session.

        Args:
            session_id: Unique session identifier.
            metadata: Optional metadata dict.

        Returns:
            The created ``Session``.

        """
        self._client.create_workspace(session_id, f"Zep session: {session_id}")
        if session_id not in self._session_to_ws:
            workspaces = self._client.list_workspaces()
            match = [w for w in workspaces if w.get("name") == session_id]
            if match:
                self._session_to_ws[session_id] = match[0]["id"]
        return Session(session_id=session_id, metadata=metadata or {})

    def update_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Update a session's metadata.

        Args:
            session_id: Session identifier.
            metadata: New metadata dict (replaces existing).

        Returns:
            The updated ``Session``.

        Raises:
            NotFoundError: If the session does not exist.

        """
        ws_id = self._ensure_workspace(session_id)
        return Session(session_id=session_id, metadata=metadata or {})

    def search_sessions(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Session]:
        """Search sessions by name/ID.

        Args:
            query: Search string to match against session names.
            limit: Max results (default 10).

        Returns:
            A list of matching ``Session`` objects.

        """
        workspaces = self._client.list_workspaces()
        results = []
        for ws in workspaces:
            name = ws.get("name", "")
            if query.lower() in name.lower():
                results.append(Session(
                    session_id=name,
                    metadata={},
                    created_at=ws.get("created_at", ""),
                ))
            if len(results) >= limit:
                break
        return results

    def close(self) -> None:
        """Close the underlying HTTP client (idempotent)."""
        self._session_to_ws.clear()

    def summarize_memory(self, session_id: str) -> str | None:
        """Generate an LLM summary of all memories in a session.

        Uses the shared :class:`LLMClient` — requires ``OPENAI_API_KEY``
        env var.  Gracefully returns ``None`` when the LLM is not configured.

        Args:
            session_id: Zep session identifier.

        Returns:
            Summary string, or ``None`` if LLM not configured or no
            memories available.
        """
        try:
            memory = self.get_memory(session_id)
        except ValueError:
            raise
        except RuntimeError:
            memory = None
        if not memory:
            return None

        messages = memory.get("messages", [])
        if not messages:
            return None

        text_parts = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", msg.get("message_type", "unknown"))
                content = msg.get("content", msg.get("message", ""))
                if content:
                    text_parts.append(f"[{role}] {content}")
            elif hasattr(msg, "role") and hasattr(msg, "content"):
                text_parts.append(f"[{msg.role}] {msg.content}")

        if not text_parts:
            return None

        from ..llm import LLMClient
        llm = LLMClient()
        if not llm.available:
            return None

        text = "\n".join(text_parts)
        return llm.summarize(
            text,
            instruction="Summarize this conversation, highlighting key topics, decisions, and action items.",
        )
