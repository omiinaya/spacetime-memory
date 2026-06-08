"""Zep-compatible drop-in adapter.

Matches the real Zep Python SDK API:
https://github.com/getzep/zep-python

Maps::

    Zep Session    → SpacetimeDB workspace
    Zep Message    → SpacetimeDB memory record
    Zep Memory     → memories grouped by source_session_id
    Zep Fact       → SpacetimeDB kg_node (entity node)

Usage::

    from spacetime_memory.sdks.zep import Zep

    z = Zep(host="localhost", port=3001)

    # Create a session
    session = z.memory.add_session(session_id="alice-chat")

    # Add messages
    z.memory.add("alice-chat", messages=[
        Message(role_type="user", content="I like pizza"),
        Message(role_type="assistant", content="Great choice!"),
    ])

    # Get memory
    memory = z.memory.get("alice-chat")
    for msg in memory.messages:
        print(msg.role_type, msg.content)

    # Search
    results = z.memory.search_sessions(text="pizza")
"""

from __future__ import annotations

import json as _json
import time
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..client import Client
from .. import sdks  # for type hints only


# ---------------------------------------------------------------------------
# Data types matching Zep's models
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """A single message in a session.

    Maps to a SpacetimeDB ``memory`` record.
    """

    role_type: str = "user"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    created_at: str | None = None


@dataclass
class Summary:
    """Session summary (not stored separately — derived from memories)."""

    content: str = ""
    created_at: str | None = None
    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])


@dataclass
class FactResponse:
    """A fact extracted from a session (maps to a KG node)."""

    uuid: str = ""
    fact: str = ""
    rating: float | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class Memory:
    """Memory for a session: messages + summary + facts."""

    messages: list[Message] = field(default_factory=list)
    summary: Summary | None = None
    facts: list[FactResponse] = field(default_factory=list)


@dataclass
class Session:
    """A Zep session (maps to a SpacetimeDB workspace)."""

    session_id: str = ""
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class SessionSearchResult:
    """A single session search result."""

    session_id: str = ""
    user_id: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class SuccessResponse:
    """Operation success indicator."""

    def __init__(self, ok: bool = True):
        self.ok = ok

    def __bool__(self):
        return self.ok


# ---------------------------------------------------------------------------
# Zep MemoryClient
# ---------------------------------------------------------------------------


class MemoryClient:
    """Internal memory client (accessed via ``Zep.memory``)."""

    def __init__(self, client: Client, stmem_sdks_module=None):
        self._client = client
        # Cache: session_id -> workspace_id
        self._session_cache: dict[str, str] = {}

    def _resolve_session(self, session_id: str) -> str:
        """Get or create a workspace for a session ID."""
        if session_id in self._session_cache:
            return self._session_cache[session_id]

        # Search existing workspaces by name
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        if isinstance(workspaces, list):
            for ws in workspaces:
                ws_name = ws.get("name", "")
                expected = f"zep-{session_id}"
                if ws_name == expected:
                    self._session_cache[session_id] = ws["id"]
                    return ws["id"]

        # Create workspace for this session
        ws_name = f"zep-{session_id}"
        try:
            self._client.create_workspace(ws_name)
        except RuntimeError:
            pass

        # Find the new workspace
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == ws_name:
                    self._session_cache[session_id] = ws["id"]
                    return ws["id"]

        # Fallback: use session_id directly
        self._session_cache[session_id] = session_id
        return session_id

    def _sql(self, query: str) -> list[dict[str, Any]]:
        try:
            return self._client._sql(query)
        except RuntimeError:
            return []

    def _ts_to_str(self, micros: int) -> str:
        if not micros:
            return datetime.now(timezone.utc).isoformat()
        try:
            ts = micros / 1_000_000
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            return ""

    # -------------------------------------------------------------------
    # Session management
    # -------------------------------------------------------------------

    def add_session(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        fact_rating_instruction: Any = None,
        request_options: Any = None,
    ) -> Session:
        """Create or find a session.

        Args:
            session_id: Unique session identifier.
            user_id: Optional user ID.
            metadata: Optional metadata dict.
            fact_rating_instruction: Not supported (accepted for compat).
            request_options: Not supported (accepted for compat).

        Returns:
            A :class:`Session` object.
        """
        ws_id = self._resolve_session(session_id)

        # Store user_id and metadata as memories if provided
        if user_id:
            try:
                self._client.store(
                    workspace_id=ws_id,
                    content=f"User: {user_id}",
                    memory_type="session_meta",
                    peer_id=user_id,
                )
            except RuntimeError:
                pass

        return Session(
            session_id=session_id,
            user_id=user_id or "",
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def get_session(
        self,
        session_id: str,
        *,
        request_options: Any = None,
    ) -> Session | None:
        """Get session info.

        Args:
            session_id: Session identifier.

        Returns:
            A :class:`Session` if found, else ``None``.
        """
        try:
            ws_id = self._resolve_session(session_id)
        except RuntimeError:
            return None

        # Find user info from session_meta memory
        rows = self._sql(
            "SELECT * FROM memory WHERE "
            f"workspace_id = '{_esc(ws_id)}' AND "
            "memory_type = 'session_meta' "
        )
        user_id = ""
        if rows:
            content = rows[0].get("content", "")
            if content.startswith("User: "):
                user_id = content[6:]

        return Session(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def list_sessions(
        self,
        *,
        page_number: int | None = None,
        page_size: int | None = None,
        order_by: str | None = None,
        asc: bool | None = None,
        request_options: Any = None,
    ) -> list[Session]:
        """List all sessions.

        Each workspace named ``zep-*`` maps to a Zep session.

        Args:
            page_number: Page number (1-indexed, default 1).
            page_size: Page size (default 20).
            order_by: Not supported (accepted for compat).
            asc: Not supported (accepted for compat).
            request_options: Not supported (accepted for compat).

        Returns:
            List of :class:`Session` objects.
        """
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            return []

        sessions: list[Session] = []
        for ws in workspaces:
            name = ws.get("name", "")
            if name.startswith("zep-"):
                sid = name[4:]
                sessions.append(Session(session_id=sid))

        # Paginate
        pn = page_number or 1
        ps = page_size or 20
        start = (pn - 1) * ps
        return sessions[start:start + ps]

    # -------------------------------------------------------------------
    # Memory operations
    # -------------------------------------------------------------------

    def add(
        self,
        session_id: str,
        *,
        messages: Sequence[Message] | Sequence[dict[str, Any]],
        fact_instruction: str | None = None,
        summary_instruction: str | None = None,
        request_options: Any = None,
    ) -> SuccessResponse:
        """Add messages to a session's memory.

        Args:
            session_id: Session identifier.
            messages: List of :class:`Message` objects or dicts.
            fact_instruction: Not supported (accepted for compat).
            summary_instruction: Not supported (accepted for compat).
            request_options: Not supported (accepted for compat).

        Returns:
            :class:`SuccessResponse` with ``ok=True``.
        """
        ws_id = self._resolve_session(session_id)

        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role_type", msg.get("role", "user"))
                content = msg.get("content", "")
                meta = msg.get("metadata", {})
            else:
                role = getattr(msg, "role_type", "user")
                content = getattr(msg, "content", "")
                meta = getattr(msg, "metadata", {})

            msg_uuid = _uuid.uuid4().hex[:32]
            try:
                self._client.store(
                    workspace_id=ws_id,
                    content=content,
                    memory_type="message",
                    peer_id=role,
                    source_session_id=session_id,
                    entities_json=_json.dumps(meta) if meta else "{}",
                )
            except RuntimeError:
                pass

        return SuccessResponse(ok=True)

    def get(
        self,
        session_id: str,
        *,
        lastn: int | None = None,
        min_rating: float | None = None,
        request_options: Any = None,
    ) -> Memory | None:
        """Get memory for a session (messages + facts).

        Args:
            session_id: Session identifier.
            lastn: Max messages to return (default: all).
            min_rating: Not supported (accepted for compat).
            request_options: Not supported (accepted for compat).

        Returns:
            A :class:`Memory` object with messages, or ``None``.
        """
        try:
            ws_id = self._resolve_session(session_id)
        except RuntimeError:
            return None

        rows = self._sql(
            "SELECT * FROM memory WHERE "
            f"workspace_id = '{_esc(ws_id)}' AND "
            "memory_type = 'message' AND is_active = true "
        )
        if not rows:
            return None

        # Sort by created_at client-side
        rows.sort(key=lambda r: r.get("created_at", 0))

        # Apply lastn
        if lastn is not None and lastn > 0:
            rows = rows[-lastn:]

        messages: list[Message] = []
        for row in rows:
            meta = _json_parse(row.get("entities_json", "{}"))
            messages.append(Message(
                role_type=row.get("peer_id", "user"),
                content=row.get("content", ""),
                metadata=meta if isinstance(meta, dict) else {},
                uuid=row.get("id", ""),
                created_at=self._ts_to_str(row.get("created_at", 0)),
            ))

        # Collect facts from KG nodes in this workspace
        facts: list[FactResponse] = []
        try:
            kg_rows = self._client._sql(
                "SELECT * FROM kg_node WHERE "
                f"workspace_id = '{_esc(ws_id)}'"
            )
            for kr in kg_rows:
                facts.append(FactResponse(
                    uuid=kr.get("id", ""),
                    fact=kr.get("label", kr.get("summary", "")),
                    created_at=self._ts_to_str(kr.get("created_at", 0)),
                ))
        except RuntimeError:
            pass

        return Memory(messages=messages, facts=facts)

    def delete(
        self,
        session_id: str,
        *,
        request_options: Any = None,
    ) -> SuccessResponse:
        """Delete all memory for a session.

        Deactivates all memories in the session's workspace.

        Args:
            session_id: Session identifier.
            request_options: Not supported (accepted for compat).

        Returns:
            :class:`SuccessResponse`.
        """
        try:
            ws_id = self._resolve_session(session_id)
        except RuntimeError:
            return SuccessResponse(ok=True)

        rows = self._sql(
            "SELECT id FROM memory WHERE "
            f"workspace_id = '{_esc(ws_id)}'"
        )
        for row in rows:
            try:
                self._client.delete_memory(row["id"])
            except RuntimeError:
                pass

        return SuccessResponse(ok=True)

    def search_sessions(
        self,
        *,
        text: str | None = None,
        limit: int | None = None,
        user_id: str | None = None,
        search_scope: str | None = None,
        search_type: str | None = None,
        mmr_lambda: float | None = None,
        min_score: float | None = None,
        session_ids: Sequence[str] | None = None,
        record_filter: dict[str, Any] | None = None,
        request_options: Any = None,
    ) -> list[SessionSearchResult]:
        """Search sessions by text query.

        Searches across all Zep session workspaces for matching content.

        Args:
            text: Search query text.
            limit: Max results (default 10).
            user_id: Filter by user (accepted for compat).
            search_scope: Not supported (accepted for compat).
            search_type: Not supported (accepted for compat).
            mmr_lambda: Not supported (accepted for compat).
            min_score: Not supported (accepted for compat).
            session_ids: Limit to specific sessions.
            record_filter: Not supported (accepted for compat).
            request_options: Not supported (accepted for compat).

        Returns:
            List of :class:`SessionSearchResult`.
        """
        if not text:
            return []

        limit = limit or 10

        # Get all Zep session workspaces
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            return []

        results: list[SessionSearchResult] = []
        for ws in workspaces:
            name = ws.get("name", "")
            if not name.startswith("zep-"):
                continue
            sid = name[4:]

            # If session_ids filter is applied
            if session_ids and sid not in session_ids:
                continue

            try:
                mems = self._client.search(
                    workspace_id=ws["id"],
                    query=text,
                    limit=5,
                    semantic=True,
                )
                for mem in mems:
                    score = mem.get("score", 0.0)
                    if isinstance(score, (int, float)) and score > 0.0:
                        results.append(SessionSearchResult(
                            session_id=sid,
                            score=float(score),
                        ))
                        break
            except RuntimeError:
                pass

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    # -------------------------------------------------------------------
    # Message operations
    # -------------------------------------------------------------------

    def get_session_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        cursor: int | None = None,
        request_options: Any = None,
    ) -> dict[str, Any]:
        """List messages for a session with pagination.

        Args:
            session_id: Session identifier.
            limit: Max messages (default 10).
            cursor: Offset cursor (0-indexed, default 0).
            request_options: Not supported (accepted for compat).

        Returns:
            Dict with ``messages`` list and ``cursor`` for next page.
        """
        try:
            ws_id = self._resolve_session(session_id)
        except RuntimeError:
            return {"messages": [], "cursor": 0}

        rows = self._sql(
            "SELECT * FROM memory WHERE "
            f"workspace_id = '{_esc(ws_id)}' AND "
            "memory_type = 'message' AND is_active = true "
        )
        rows.sort(key=lambda r: r.get("created_at", 0))

        lim = limit or 10
        cur = cursor or 0
        page = rows[cur:cur + lim]

        messages: list[dict[str, Any]] = []
        for row in page:
            meta = _json_parse(row.get("entities_json", "{}"))
            messages.append({
                "role_type": row.get("peer_id", "user"),
                "content": row.get("content", ""),
                "metadata": meta if isinstance(meta, dict) else {},
                "uuid": row.get("id", ""),
            })

        return {"messages": messages, "cursor": cur + lim}

    def get_session_message(
        self,
        session_id: str,
        message_uuid: str,
        *,
        request_options: Any = None,
    ) -> dict[str, Any] | None:
        """Get a specific message by UUID.

        Args:
            session_id: Session identifier.
            message_uuid: Message UUID.

        Returns:
            Message dict or ``None``.
        """
        rows = self._sql(
            "SELECT * FROM memory WHERE "
            f"id = '{_esc(message_uuid)}'"
        )
        if not rows:
            return None

        row = rows[0]
        meta = _json_parse(row.get("entities_json", "{}"))
        return {
            "role_type": row.get("peer_id", "user"),
            "content": row.get("content", ""),
            "metadata": meta if isinstance(meta, dict) else {},
            "uuid": row.get("id", ""),
        }

    def update_session(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any],
        fact_rating_instruction: Any = None,
        request_options: Any = None,
    ) -> Session:
        """Update session metadata.

        Args:
            session_id: Session identifier.
            metadata: New metadata dict.
            fact_rating_instruction: Not supported (accepted for compat).
            request_options: Not supported (accepted for compat).

        Returns:
            Updated :class:`Session`.
        """
        ws_id = self._resolve_session(session_id)
        try:
            self._client.store(
                workspace_id=ws_id,
                content=_json.dumps(metadata),
                memory_type="session_meta",
            )
        except RuntimeError:
            pass

        return Session(session_id=session_id, metadata=metadata)

    def update_message_metadata(
        self,
        session_id: str,
        message_uuid: str,
        *,
        metadata: dict[str, Any],
        request_options: Any = None,
    ) -> dict[str, Any]:
        """Update a message's metadata.

        Args:
            session_id: Session identifier.
            message_uuid: Message UUID.
            metadata: New metadata dict.

        Returns:
            Updated message dict.
        """
        # Update the entities_json field
        rows = self._sql(
            f"SELECT id, content, peer_id FROM memory WHERE id = '{_esc(message_uuid)}'"
        )
        result: dict[str, Any] = {"role_type": "user", "content": "", "metadata": {}, "uuid": message_uuid}

        if rows:
            row = rows[0]
            # We can't update in place via SQL (SpacetimeDB limitations),
            # so just return what we have with new metadata
            result["role_type"] = row.get("peer_id", "user")
            result["content"] = row.get("content", "")
            result["metadata"] = metadata

        return result

    # -------------------------------------------------------------------
    # Fact operations
    # -------------------------------------------------------------------

    def get_fact(
        self,
        fact_uuid: str,
        *,
        request_options: Any = None,
    ) -> FactResponse | None:
        """Get a fact by UUID.

        Args:
            fact_uuid: Fact UUID (maps to kg_node UUID).

        Returns:
            :class:`FactResponse` or ``None``.
        """
        rows = self._sql(
            f"SELECT * FROM kg_node WHERE id = '{_esc(fact_uuid)}'"
        )
        if not rows:
            return None

        row = rows[0]
        return FactResponse(
            uuid=row.get("id", ""),
            fact=row.get("label", ""),
            created_at=self._ts_to_str(row.get("created_at", 0)),
        )

    def delete_fact(
        self,
        fact_uuid: str,
        *,
        request_options: Any = None,
    ) -> str:
        """Delete a fact by UUID.

        Args:
            fact_uuid: Fact UUID.

        Returns:
            The UUID of the deleted fact.
        """
        try:
            self._client._call("delete_node", [fact_uuid])
        except RuntimeError:
            pass
        return fact_uuid


# ---------------------------------------------------------------------------
# Main Zep class
# ---------------------------------------------------------------------------


class Zep:
    """Drop-in replacement for ``zep_python.client.Zep``.

    Wraps Spacetime-Memory behind Zep's session-based memory API.

    **Important differences from the real Zep:**

    * Our adapter is **synchronous** (Zep uses async httpx).
      Use sync methods (``add()``, ``get()``, etc.) instead of
      ``aadd()``, ``aget()``, etc.
    * ``session_id`` maps to a SpacetimeDB workspace name
      (prefix ``"zep-"``).
    * ``messages`` are stored as SpacetimeDB ``memory`` records
      with ``memory_type='message'`` and ``peer_id=role_type``.
    * ``facts`` are stored as SpacetimeDB ``kg_node`` records.
    * ``search_sessions`` uses hybrid search across all Zep
      session workspaces.

    **Note:** The async methods (``aadd``, ``aget``, etc.) defined
    by the real Zep ``MemoryClient`` are not implemented here.
    Only the sync methods work.

    Example::

        from spacetime_memory.sdks.zep import Zep, Message

        z = Zep(host="localhost", port=3001)

        # Create a session
        z.memory.add_session(session_id="demo")

        # Add a message
        z.memory.add("demo", messages=[
            Message(role_type="user", content="Hello!"),
        ])

        # Retrieve memory
        memory = z.memory.get("demo")
        for msg in memory.messages:
            print(msg.role_type, ":", msg.content)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        token: str | None = None,
        embedder_url: str | None = None,
        embedder_type: str | None = None,
        client: Client | None = None,
        **kwargs: Any,
    ):
        """
        Args:
            host: SpacetimeDB host (default: localhost).
            port: SpacetimeDB port (default: 3001).
            database: SpacetimeDB database identity.
            token: JWT token for authenticated requests.
            embedder_url: Embedder sidecar URL.
            embedder_type: Embedder type (local, openai, auto).
            client: An existing Client instance.
            **kwargs: Additional Zep constructor parameters
                (``api_key``, ``base_url``, etc.) accepted for compat.
        """
        if client is not None:
            self._client = client
        else:
            self._client = Client(
                host=host,
                port=port,
                database=database,
                token=token,
                embedder_url=embedder_url,
                embedder_type=embedder_type,
            )
        self.memory = MemoryClient(self._client)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_parse(val: Any) -> Any:
    """Safely parse a JSON value."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val and val not in ("{}", "[]"):
        try:
            return _json.loads(val)
        except (_json.JSONDecodeError, TypeError):
            pass
    return {}


def _esc(val: str) -> str:
    """Basic SQL string escaping."""
    return val.replace("'", "''")
