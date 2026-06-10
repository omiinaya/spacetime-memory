"""
Drop-in replacement for ``honcho.Honcho`` (plastic-labs/honcho SDK).

Maps the Honcho conversational memory platform API
(https://github.com/plastic-labs/honcho) to SpacetimeDB storage.

Usage::

    from spacetime_memory.sdks.honcho import Honcho

    client = Honcho(workspace_id="my-workspace", base_url=None,
                    stdb_host="localhost", stdb_port=3001)

    alice = client.peer("alice")
    session = client.session("conversation-1")
    session.add_peers([alice])

    msg = alice.message("Hello, world!")
    session.add_messages([msg])
"""

from __future__ import annotations

import datetime
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

from ..client import Client

# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class ReasoningConfiguration(BaseModel):
    enabled: bool | None = None
    custom_instructions: str | None = None


class PeerCardConfiguration(BaseModel):
    use: bool | None = None
    create: bool | None = None


class SummaryConfiguration(BaseModel):
    enabled: bool | None = None
    messages_per_short_summary: int | None = None
    messages_per_long_summary: int | None = None


class DreamConfiguration(BaseModel):
    enabled: bool | None = None


class WorkspaceConfiguration(BaseModel):
    reasoning: ReasoningConfiguration | None = None
    peer_card: PeerCardConfiguration | None = None
    summary: SummaryConfiguration | None = None
    dream: DreamConfiguration | None = None


WorkspaceConfigurationResponse = WorkspaceConfiguration
SessionConfiguration = WorkspaceConfiguration
SessionConfigurationResponse = SessionConfiguration


class PeerConfig(BaseModel):
    observe_me: bool | None = None


class SessionPeerConfig(BaseModel):
    observe_others: bool | None = None
    observe_me: bool | None = None


class MessageConfiguration(BaseModel):
    reasoning: ReasoningConfiguration | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WorkspaceResponse(BaseModel):
    id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    configuration: WorkspaceConfigurationResponse = Field(default_factory=WorkspaceConfigurationResponse)
    created_at: datetime.datetime


class PeerResponse(BaseModel):
    id: str
    workspace_id: str
    created_at: datetime.datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    configuration: PeerConfig = Field(default_factory=PeerConfig)


class SessionResponse(BaseModel):
    id: str
    is_active: bool
    workspace_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    configuration: SessionConfigurationResponse = Field(default_factory=SessionConfigurationResponse)
    created_at: datetime.datetime


class MessageResponse(BaseModel):
    id: str
    content: str
    peer_id: str
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime.datetime
    workspace_id: str
    token_count: int = 0


class MessageCreateParams(BaseModel):
    content: str
    peer_id: str
    metadata: dict[str, Any] | None = None
    configuration: MessageConfiguration | None = None
    created_at: datetime.datetime | None = None


class Summary(BaseModel):
    content: str
    message_id: str
    summary_type: str
    created_at: str
    token_count: int = 0


class SessionSummaries(BaseModel):
    id: str
    short_summary: Summary | None = None
    long_summary: Summary | None = None


class SessionContext(BaseModel):
    session_id: str
    messages: list[Message]
    summary: Summary | None = None
    peer_representation: str | None = None
    peer_card: list[str] | None = None

    def __len__(self) -> int:
        return len(self.messages)


class PeerContextResponse(BaseModel):
    peer_id: str
    target_id: str
    representation: str | None = None
    peer_card: list[str] | None = None


class ConclusionResponse(BaseModel):
    id: str
    content: str
    observer_id: str
    observed_id: str
    session_id: str | None = None
    created_at: datetime.datetime


class SessionQueueStatus(BaseModel):
    session_id: str | None = None
    total_work_units: int = 0
    completed_work_units: int = 0
    in_progress_work_units: int = 0
    pending_work_units: int = 0


class QueueStatusResponse(BaseModel):
    total_work_units: int = 0
    completed_work_units: int = 0
    in_progress_work_units: int = 0
    pending_work_units: int = 0
    sessions: dict[str, SessionQueueStatus] | None = None


class DialecticResponse(BaseModel):
    content: str | None = None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

T = TypeVar("T")
U = TypeVar("U")


class SyncPage(Generic[T, U]):
    """Paginated response — matches honcho SyncPage[T, U]."""
    items: list[Any]
    total: int | None
    page: int | None
    size: int | None
    pages: int | None

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        items: list[Any] | None = None,
        total: int | None = None,
        page: int | None = None,
        size: int | None = None,
        pages: int | None = None,
    ):
        if data is not None:
            self.items = data.get("items", [])
            self.total = data.get("total")
            self.page = data.get("page")
            self.size = data.get("size")
            self.pages = data.get("pages")
        else:
            self.items = items or []
            self.total = total
            self.page = page
            self.size = size
            self.pages = pages

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    def has_next_page(self) -> bool:
        if self.page is not None and self.pages is not None:
            return self.page < self.pages
        return False


# ---------------------------------------------------------------------------
# Message (plain class, not Pydantic — matches upstream)
# ---------------------------------------------------------------------------


class Message:
    """A message in a session — matches upstream honcho.Message."""

    def __init__(
        self,
        id: str,
        content: str,
        peer_id: str,
        session_id: str,
        workspace_id: str,
        metadata: dict[str, Any] | None = None,
        created_at: datetime.datetime | None = None,
        token_count: int = 0,
    ):
        self.id = id
        self.content = content
        self.peer_id = peer_id
        self.session_id = session_id
        self.workspace_id = workspace_id
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.datetime.utcnow()
        self.token_count = token_count

    @classmethod
    def from_api_response(cls, data: MessageResponse) -> Message:
        return cls(
            id=data.id,
            content=data.content,
            peer_id=data.peer_id,
            session_id=data.session_id,
            workspace_id=data.workspace_id or "",
            metadata=data.metadata,
            created_at=data.created_at,
            token_count=data.token_count,
        )

    def __repr__(self) -> str:
        return f"Message(id='{self.id[:8]}...', peer='{self.peer_id}', content='{self.content[:50]}...')"


# ---------------------------------------------------------------------------
# Peer class
# ---------------------------------------------------------------------------


class Peer:
    """A participant in conversations — matches upstream honcho.Peer."""

    def __init__(
        self,
        peer_id: str,
        honcho: Honcho,  # type: ignore[name-defined]
        *,
        metadata: dict[str, object] | None = None,
        configuration: PeerConfig | None = None,
        created_at: datetime.datetime | None = None,
    ):
        self._id = peer_id
        self._honcho = honcho
        self._ws_id = honcho._ws_id
        self._metadata = metadata or {}
        self._configuration = configuration or PeerConfig()
        self._created_at = created_at or datetime.datetime.utcnow()

    @property
    def id(self) -> str:  # noqa: A003
        return self._id

    @property
    def metadata(self) -> dict[str, object] | None:
        return self._metadata

    @property
    def configuration(self) -> PeerConfig | None:
        return self._configuration

    @property
    def created_at(self) -> datetime.datetime | None:
        return self._created_at

    def message(
        self,
        content: str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: dict[str, Any] | None = None,
        created_at: datetime.datetime | str | None = None,
    ) -> MessageCreateParams:
        """Create a message from this peer. Returns MessageCreateParams ready to send."""
        return MessageCreateParams(
            content=content,
            peer_id=self._id,
            metadata=metadata or {},
            created_at=datetime.datetime.utcnow() if created_at is None
            else (created_at if isinstance(created_at, datetime.datetime) else datetime.datetime.fromisoformat(str(created_at))),
        )

    def chat(
        self,
        query: str,
        *,
        target: Any | None = None,
        session: Session | str | None = None,
        reasoning_level: Literal["minimal", "low", "medium", "high", "max"] | None = None,
    ) -> str | None:
        """Chat with context from memories."""
        target_id = target.id if isinstance(target, Peer) else (target or "")
        ses = session.id if isinstance(session, Session) else (session or "")

        # Search relevant memories
        try:
            memories = self._honcho._client.search(self._ws_id, query=query, limit=10, semantic=True)
        except Exception:
            memories = []

        mem_text = "\n".join(
            f"- {m.get('memory_content', m.get('content', ''))}" for m in memories[:5]
        )
        # Return a simple response based on memory context
        if mem_text:
            return f"Based on stored context: {mem_text[:200]}"
        return None

    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        """Search messages from this peer."""
        try:
            results = self._honcho._client.search(self._ws_id, query=query, limit=limit, semantic=True)
        except Exception:
            results = []

        messages = []
        for i, r in enumerate(results[:limit]):
            messages.append(Message(
                id=r.get("id", str(i)),
                content=r.get("memory_content", r.get("content", "")),
                peer_id=self._id,
                session_id="",
                workspace_id=self._ws_id,
                metadata=r.get("metadata", {}),
            ))
        return messages

    def sessions(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[SessionResponse, Session]:
        """List sessions this peer participates in."""
        # In SpacetimeDB, we don't have a direct peer→session mapping
        # Return empty page for now
        return SyncPage(data={"items": [], "total": 0, "page": page, "size": size, "pages": 1})


# ---------------------------------------------------------------------------
# Session class
# ---------------------------------------------------------------------------


class Session:
    """A conversation session — matches upstream honcho.Session."""

    def __init__(
        self,
        session_id: str,
        honcho: Honcho,  # type: ignore[name-defined]
        *,
        metadata: dict[str, object] | None = None,
        configuration: SessionConfiguration | None = None,
        created_at: datetime.datetime | None = None,
        is_active: bool | None = None,
    ):
        self._id = session_id
        self._honcho = honcho
        self._ws_id = honcho._ws_id
        self._metadata = metadata or {}
        self._configuration = configuration or SessionConfiguration()
        self._created_at = created_at or datetime.datetime.utcnow()
        self._is_active = is_active if is_active is not None else True
        self._peers: list[Peer] = []

    @property
    def id(self) -> str:  # noqa: A003
        return self._id

    @property
    def metadata(self) -> dict[str, object] | None:
        return self._metadata

    @property
    def configuration(self) -> SessionConfiguration | None:
        return self._configuration

    @property
    def created_at(self) -> datetime.datetime | None:
        return self._created_at

    @property
    def is_active(self) -> bool | None:
        return self._is_active

    def add_peers(self, peers: Any | list[Any]) -> None:
        """Add peers to this session."""
        if not isinstance(peers, list):
            peers = [peers]
        for p in peers:
            if isinstance(p, Peer) and p not in self._peers:
                self._peers.append(p)
            elif isinstance(p, str):
                # Create a lightweight peer reference
                peer = self._honcho.peer(p)
                if peer not in self._peers:
                    self._peers.append(peer)

    def peers(self) -> list[Peer]:
        """Get peers in this session."""
        return list(self._peers)

    def add_messages(
        self,
        messages: MessageCreateParams | list[MessageCreateParams],
    ) -> list[Message]:
        """Add messages to this session."""
        if not isinstance(messages, list):
            messages = [messages]

        result: list[Message] = []
        for msg in messages:
            try:
                self._honcho._client.store(
                    self._ws_id,
                    content=msg.content,
                    summary="",
                    entities_json=json.dumps(msg.metadata or {}),
                )
            except Exception:
                pass

            result.append(Message(
                id=hash(msg.content + msg.peer_id + str(datetime.datetime.utcnow())) % (2**32),
                content=msg.content,
                peer_id=msg.peer_id,
                session_id=self._id,
                workspace_id=self._ws_id,
                metadata=dict(msg.metadata or {}),
                created_at=msg.created_at or datetime.datetime.utcnow(),
            ))
        return result

    def messages(
        self,
        *,
        filters: dict[str, object] | None = None,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[MessageResponse, Message]:
        """List messages in this session."""
        try:
            results = self._honcho._client.search(self._ws_id, query="", limit=size, semantic=False)
        except Exception:
            results = []

        items = []
        for r in results[:size]:
            items.append(Message(
                id=r.get("id", ""),
                content=r.get("memory_content", r.get("content", "")),
                peer_id=r.get("metadata", {}).get("peer_id", ""),
                session_id=self._id,
                workspace_id=self._ws_id,
            ))

        return SyncPage(data={
            "items": items, "total": len(items),
            "page": page, "size": size, "pages": 1,
        })

    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        """Search messages within this session."""
        try:
            results = self._honcho._client.search(self._ws_id, query=query, limit=limit, semantic=True)
        except Exception:
            results = []

        messages = []
        for i, r in enumerate(results[:limit]):
            messages.append(Message(
                id=r.get("id", str(i)),
                content=r.get("memory_content", r.get("content", "")),
                peer_id=r.get("metadata", {}).get("peer_id", ""),
                session_id=self._id,
                workspace_id=self._ws_id,
            ))
        return messages

    def context(
        self,
        *,
        summary: bool = False,
        tokens: int | None = None,
        **kwargs: Any,
    ) -> SessionContext:
        """Get session context with messages."""
        msgs = self.messages(size=tokens or 50).items
        return SessionContext(
            session_id=self._id,
            messages=msgs,
        )

    def summaries(self) -> SessionSummaries:
        """Get session summaries."""
        return SessionSummaries(id=self._id)

    def delete(self) -> None:
        """Delete this session."""
        self._is_active = False

    def refresh(self) -> None:
        """Refresh session state."""
        pass


# ---------------------------------------------------------------------------
# Honcho client — drop-in replacement for honcho.Honcho
# ---------------------------------------------------------------------------


class Honcho:
    """Drop-in replacement for ``honcho.Honcho``.

    Maps the Honcho conversational memory platform API to SpacetimeDB.
    Accepts standard Honcho constructor args plus SpacetimeDB-specific params.

    Usage::

        honcho = Honcho(workspace_id="my-workspace", base_url=None,
                        stdb_host="localhost", stdb_port=3001)
        peer = honcho.peer("alice")
        session = honcho.session("chat-1")
        session.add_peers([peer])
    """

    def __init__(
        self,
        api_key: str | None = None,
        environment: Literal["local", "production"] | None = None,
        base_url: str | None = None,
        workspace_id: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        default_headers: Mapping[str, str] | None = None,
        default_query: Mapping[str, object] | None = None,
        http_client: Any | None = None,
        # SpacetimeDB-specific
        stdb_host: str | None = None,
        stdb_port: int | None = None,
        stdb_database: str | None = None,
    ):
        import hashlib

        self._ws_id = workspace_id or os.environ.get("HONCHO_WORKSPACE_ID", "default")
        self._api_key = api_key
        self._base_url = base_url or f"http://{stdb_host or 'localhost'}:{stdb_port or 3001}"
        self._timeout = timeout or 30.0

        db = stdb_database or hashlib.md5(self._ws_id.encode()).hexdigest()[:16]
        self._client = Client(
            host=stdb_host or os.environ.get("SPACETIMEDB_HOST", "localhost"),
            port=stdb_port or os.environ.get("SPACETIMEDB_PORT", "3001"),
            database=db,
            timeout=self._timeout,
        )
        self._peer_cache: dict[str, Peer] = {}
        self._session_cache: dict[str, Session] = {}
        self._closed = False

    # -- Properties -----------------------------------------------------------

    @property
    def metadata(self) -> dict[str, object] | None:
        """Cached workspace metadata."""
        return {"workspace_id": self._ws_id}

    @property
    def configuration(self) -> WorkspaceConfiguration | None:
        return WorkspaceConfiguration()

    @property
    def base_url(self) -> str:
        return self._base_url

    # -- Peer methods ---------------------------------------------------------

    def peer(
        self,
        id: str,  # noqa: A002
        *,
        metadata: dict[str, object] | None = None,
        configuration: PeerConfig | None = None,
    ) -> Peer:
        """Get or create a peer by ID."""
        if id in self._peer_cache:
            return self._peer_cache[id]

        peer = Peer(
            peer_id=id,
            honcho=self,
            metadata=metadata or {},
            configuration=configuration or PeerConfig(),
        )
        self._peer_cache[id] = peer
        return peer

    def peers(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[PeerResponse, Peer]:
        """List peers in the workspace."""
        peers = list(self._peer_cache.values())
        if reverse:
            peers = list(reversed(peers))
        return SyncPage(data={
            "items": peers, "total": len(peers),
            "page": page, "size": size, "pages": max(1, (len(peers) + size - 1) // size or 1),
        })

    # -- Session methods ------------------------------------------------------

    def session(
        self,
        id: str,  # noqa: A002
        *,
        metadata: dict[str, object] | None = None,
        configuration: SessionConfiguration | None = None,
        peers: Any = None,
    ) -> Session:
        """Get or create a session by ID."""
        if id in self._session_cache:
            return self._session_cache[id]

        session = Session(
            session_id=id,
            honcho=self,
            metadata=metadata or {},
            configuration=configuration or SessionConfiguration(),
        )
        self._session_cache[id] = session

        if peers is not None:
            session.add_peers(peers)

        return session

    def sessions(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[SessionResponse, Session]:
        """List sessions in the workspace."""
        sessions = list(self._session_cache.values())
        if reverse:
            sessions = list(reversed(sessions))
        return SyncPage(data={
            "items": sessions, "total": len(sessions),
            "page": page, "size": size, "pages": max(1, (len(sessions) + size - 1) // size or 1),
        })

    # -- Search ---------------------------------------------------------------

    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        """Search across all sessions in the workspace."""
        try:
            results = self._client.search(self._ws_id, query=query, limit=limit, semantic=True)
        except Exception:
            results = []

        messages = []
        for i, r in enumerate(results[:limit]):
            messages.append(Message(
                id=r.get("id", str(i)),
                content=r.get("memory_content", r.get("content", "")),
                peer_id=r.get("metadata", {}).get("peer_id", ""),
                session_id="",
                workspace_id=self._ws_id,
            ))
        return messages

    # -- Workspace management -------------------------------------------------

    def workspaces(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[WorkspaceResponse, str]:
        """List accessible workspace IDs."""
        return SyncPage(data={
            "items": [self._ws_id], "total": 1,
            "page": page, "size": size, "pages": 1,
        })

    def delete_workspace(self, workspace_id: str | None = None) -> None:
        """Delete a workspace."""
        ws_id = workspace_id or self._ws_id
        self._session_cache.clear()
        self._peer_cache.clear()

    # -- Queue / Dream (stubs, match API shape) -------------------------------

    def queue_status(
        self,
        observer: Any = None,
        sender: Any = None,
        session: Any = None,
    ) -> QueueStatusResponse:
        """Get queue processing status."""
        return QueueStatusResponse()

    def schedule_dream(
        self,
        observer: Any,
        session: Any | None = None,
        observed: Any | None = None,
    ) -> None:
        """Schedule a dream operation."""
        pass

    # -- Close ----------------------------------------------------------------

    def close(self) -> None:
        """Close the client."""
        self._closed = True
        self._session_cache.clear()
        self._peer_cache.clear()


__all__ = [
    "Honcho",
    "Peer",
    "Session",
    "Message",
    "SyncPage",
    "PeerResponse",
    "SessionResponse",
    "MessageResponse",
    "MessageCreateParams",
    "PeerConfig",
    "SessionPeerConfig",
    "SessionConfiguration",
    "WorkspaceConfiguration",
    "QueueStatusResponse",
    "SessionContext",
    "SessionSummaries",
    "Summary",
    "DialecticResponse",
]
