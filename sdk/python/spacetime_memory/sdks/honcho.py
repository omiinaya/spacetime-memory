"""
Drop-in replacement for ``honcho.Honcho`` (plastic-labs/honcho SDK).

Maps the Honcho conversational memory platform API
(https://github.com/plastic-labs/honcho) to SpacetimeDB storage.

**Error contract:**
- ``RuntimeError`` / ``SpacetimeDBError`` for backend failures — these
  propagate from the underlying ``Client``.
- ``logger.warning`` logged for transient failures (search, chat).
- ``Peer.chat()`` returns ``None`` when no relevant memories are found
  (matches upstream behaviour — not an error).
- ``Peer.sessions()`` returns an empty ``SyncPage`` — SpacetimeDB has
  no direct peer→session index.
- ``Session.add_messages()`` silently skips messages that fail to store
  (logged), continues processing the rest.

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
import asyncio
import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from ..client import Client
from ..llm import LLMClient

logger = logging.getLogger(__name__)

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
    configuration: WorkspaceConfigurationResponse = Field(
        default_factory=WorkspaceConfigurationResponse
    )
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
    configuration: SessionConfigurationResponse = Field(
        default_factory=SessionConfigurationResponse
    )
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
    model_config = {"arbitrary_types_allowed": True}
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


class ConclusionCreateParams(BaseModel):
    """Parameters for creating a conclusion — matches upstream honcho-ai."""

    content: str
    session_id: str | None = None


class Conclusion:
    """A conclusion formed by an observer about an observed peer — matches upstream honcho.Conclusion."""

    def __init__(
        self,
        id: str,
        content: str,
        observer_id: str,
        observed_id: str,
        session_id: str | None = None,
        created_at: datetime.datetime | None = None,
    ):
        self.id = id
        self.content = content
        self.observer_id = observer_id
        self.observed_id = observed_id
        self.session_id = session_id
        self.created_at = created_at or datetime.datetime.utcnow()

    @classmethod
    def from_api_response(cls, data: ConclusionResponse) -> Conclusion:
        return cls(
            id=data.id,
            content=data.content,
            observer_id=data.observer_id,
            observed_id=data.observed_id,
            session_id=data.session_id,
            created_at=data.created_at,
        )

    def __repr__(self) -> str:
        return (
            f"Conclusion(id='{self.id[:8]}...', observer='{self.observer_id}', "
            f"observed='{self.observed_id}', content='{self.content[:50]}...')"
        )


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
            created_at=datetime.datetime.utcnow()
            if created_at is None
            else (
                created_at
                if isinstance(created_at, datetime.datetime)
                else datetime.datetime.fromisoformat(str(created_at))
            ),
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

        # Search relevant memories
        try:
            memories = self._honcho._client.search(
                self._ws_id, query=query, limit=10, semantic=True
            )
        except RuntimeError as exc:
            logger.warning("Peer.chat() search failed: %s", exc)
            memories = []

        mem_text = "\n".join(
            f"- {m.get('memory_content', m.get('content', ''))}" for m in memories[:5]
        )
        # Return a simple response based on memory context
        if mem_text:
            return f"Based on stored context: {mem_text[:200]}"
        return None

    def chat_stream(
        self,
        query: str,
        *,
        target: Any | None = None,
        session: Session | str | None = None,
        reasoning_level: Literal["minimal", "low", "medium", "high", "max"] | None = None,
    ):
        """Stream chat responses from peer context.

        Yields response chunks as a generator. Uses the non-streaming
        ``chat()`` path since the SpacetimeDB backend does not support
        native streaming.

        Returns:
            A generator that yields ``str`` chunks.
        """
        response = self.chat(
            query,
            target=target,
            session=session,
            reasoning_level=reasoning_level,
        )

        def _generator():
            if response:
                yield response

        return _generator()

    def get_card(self, target: str | None = None) -> dict:
        """Generate a peer card using LLM based on peer messages and behavior.

        Args:
            target: Optional target peer ID for perspective.

        Returns:
            ``{"summary": "...", "traits": [...]}`` or
            ``{"summary": "", "traits": []}`` if LLM unavailable.
        """
        llm = LLMClient()
        if not llm.available:
            return {"summary": "", "traits": []}

        # Gather peer messages
        try:
            memories = self._honcho._client.search(
                self._ws_id,
                query="",
                limit=20,
                semantic=False,
            )
        except RuntimeError:
            memories = []

        mem_text = "\n".join(
            f"- [{m.get('metadata', {}).get('peer_id', '?')}]: "
            f"{m.get('memory_content', m.get('content', ''))}"
            for m in memories[:20]
        )

        # Gather session info
        sessions = self.sessions()
        session_ids = [s.id for s in sessions]

        prompt = (
            f"Based on the following messages and context about peer {self._id}, "
            f"generate a brief peer card describing their role, interests, and "
            f"behavior patterns. Return as JSON with 'summary' and 'traits' fields.\n\n"
            f"Messages:\n{mem_text or '(none)'}\n\n"
            f"Sessions: {session_ids or '(none)'}"
        )

        result = llm.chat(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=512,
        )
        if not result:
            return {"summary": "", "traits": []}

        try:
            data = json.loads(result)
            return {
                "summary": data.get("summary", ""),
                "traits": data.get("traits", []),
            }
        except (json.JSONDecodeError, TypeError):
            return {"summary": "", "traits": []}

    def representation(
        self,
        session: Session | str | None = None,
        target: str | None = None,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> str:
        """Generate a natural-language representation of this peer.

        Uses LLM to synthesize a description from stored memories. Falls
        back to a simple memory summary when no LLM is available.

        Returns:
            A natural-language representation string.
        """
        llm = LLMClient()

        try:
            memories = self._honcho._client.search(
                self._ws_id,
                query=search_query or "",
                limit=search_top_k or 10,
                semantic=True,
            )
        except RuntimeError:
            memories = []

        mem_text = "\n".join(
            f"- {m.get('memory_content', m.get('content', ''))}"
            for m in memories[: (search_top_k or 10)]
        )

        if not llm.available:
            if memories:
                contents = [m.get("memory_content", m.get("content", "")) for m in memories[:5]]
                return f"Peer {self._id}: " + "; ".join(c[:100] for c in contents if c)
            return f"Peer {self._id} (no context available)"

        prompt = (
            f"Generate a natural language representation describing peer "
            f"'{self._id}' based on their stored memories and behavior.\n\n"
            f"Memories:\n{mem_text or '(none)'}"
        )

        result = llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        return result or f"Peer {self._id} (representation unavailable)"

    def context(
        self,
        target: str | None = None,
        *,
        peer_perspective: str | None = None,
        search_query: str | None = None,
        search_top_k: int = 10,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> PeerContextResponse:
        """Combine representation and peer card into a PeerContextResponse.

        Returns:
            ``PeerContextResponse`` with peer_id, target_id,
            representation, and peer_card.
        """
        rep = self.representation(
            target=target,
            search_query=search_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
            include_most_frequent=include_most_frequent,
            max_conclusions=max_conclusions,
        )

        card = self.get_card(target=target)

        return PeerContextResponse(
            peer_id=self._id,
            target_id=str(target) if target else "",
            representation=rep,
            peer_card=card.get("traits", []),
        )

    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        """Search messages from this peer."""
        try:
            results = self._honcho._client.search(
                self._ws_id, query=query, limit=limit, semantic=True
            )
        except RuntimeError as exc:
            logger.warning("Peer.search() failed: %s", exc)
            results = []

        messages = []
        for i, r in enumerate(results[:limit]):
            messages.append(
                Message(
                    id=r.get("id", str(i)),
                    content=r.get("memory_content", r.get("content", "")),
                    peer_id=self._id,
                    session_id="",
                    workspace_id=self._ws_id,
                    metadata=r.get("metadata", {}),
                )
            )
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
        filtered: list[Session] = []
        for session in self._honcho._session_cache.values():
            if self in session._peers:
                filtered.append(session)
        if reverse:
            filtered = list(reversed(filtered))
        total = len(filtered)
        start = (page - 1) * size
        paged = filtered[start : start + size]
        return SyncPage(
            data={
                "items": paged,
                "total": total,
                "page": page,
                "size": size,
                "pages": max(1, (total + size - 1) // size or 1),
            }
        )

    # -- Metadata / Config / Refresh ------------------------------------------

    def get_metadata(self) -> dict[str, object]:
        return self._metadata

    def set_metadata(self, metadata: dict[str, object]) -> None:
        self._metadata = metadata

    def get_configuration(self) -> PeerConfig:
        return self._configuration or PeerConfig()

    def set_configuration(self, configuration: PeerConfig) -> None:
        self._configuration = configuration

    def refresh(self) -> None:
        pass

    @property
    def aio(self) -> PeerAio:
        return PeerAio(self)

    # -- Conclusions -----------------------------------------------------------

    def conclusions(
        self,
        observer: Peer,
        observed: Peer | None = None,
    ) -> ConclusionScope:
        """Get a conclusion scope for this peer observing another peer.

        Args:
            observer: The peer forming the conclusions (typically self).
            observed: The peer being observed (defaults to self if None).

        Returns:
            ``ConclusionScope`` for managing conclusions.
        """
        observed = observed or self
        return ConclusionScope(self._honcho, observer, observed)

    def conclusions_of(self, observed: Peer | str) -> ConclusionScope:
        """Get conclusions this peer has formed about another peer.

        Args:
            observed: The peer being observed (Peer instance or peer ID string).

        Returns:
            ``ConclusionScope`` for managing conclusions about ``observed`` by this peer.
        """
        if isinstance(observed, str):
            observed = self._honcho.peer(observed)
        return ConclusionScope(self._honcho, self, observed)


class PeerAio:
    """Async wrapper for Peer — uses asyncio.to_thread for sync SpacetimeDB calls."""

    def __init__(self, peer: Peer) -> None:
        self._peer = peer

    async def message(
        self,
        content: str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: dict[str, Any] | None = None,
        created_at: datetime.datetime | str | None = None,
    ) -> MessageCreateParams:
        return await asyncio.to_thread(
            self._peer.message,
            content,
            metadata=metadata,
            configuration=configuration,
            created_at=created_at,
        )

    async def chat(
        self,
        query: str,
        *,
        target: Any | None = None,
        session: Session | str | None = None,
        reasoning_level: Literal["minimal", "low", "medium", "high", "max"] | None = None,
    ) -> str | None:
        return await asyncio.to_thread(
            self._peer.chat,
            query,
            target=target,
            session=session,
            reasoning_level=reasoning_level,
        )

    async def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        return await asyncio.to_thread(
            self._peer.search,
            query,
            filters=filters,
            limit=limit,
        )

    async def sessions(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[SessionResponse, Session]:
        return await asyncio.to_thread(
            self._peer.sessions,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def get_metadata(self) -> dict[str, object]:
        return await asyncio.to_thread(self._peer.get_metadata)

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        return await asyncio.to_thread(self._peer.set_metadata, metadata)

    async def get_configuration(self) -> PeerConfig:
        return await asyncio.to_thread(self._peer.get_configuration)

    async def set_configuration(self, configuration: PeerConfig) -> None:
        return await asyncio.to_thread(self._peer.set_configuration, configuration)

    async def refresh(self) -> None:
        return await asyncio.to_thread(self._peer.refresh)

    async def chat_stream(
        self,
        query: str,
        *,
        target: Any | None = None,
        session: Session | str | None = None,
        reasoning_level: Literal["minimal", "low", "medium", "high", "max"] | None = None,
    ):
        return await asyncio.to_thread(
            self._peer.chat_stream,
            query,
            target=target,
            session=session,
            reasoning_level=reasoning_level,
        )

    async def get_card(self, target: str | None = None) -> dict:
        return await asyncio.to_thread(self._peer.get_card, target=target)

    async def representation(
        self,
        session: Session | str | None = None,
        target: str | None = None,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._peer.representation,
            session=session,
            target=target,
            search_query=search_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
            include_most_frequent=include_most_frequent,
            max_conclusions=max_conclusions,
        )

    async def context(
        self,
        target: str | None = None,
        *,
        peer_perspective: str | None = None,
        search_query: str | None = None,
        search_top_k: int = 10,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> PeerContextResponse:
        return await asyncio.to_thread(
            self._peer.context,
            target=target,
            peer_perspective=peer_perspective,
            search_query=search_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
            include_most_frequent=include_most_frequent,
            max_conclusions=max_conclusions,
        )


# ---------------------------------------------------------------------------
# ConclusionScope — matches upstream honcho.ConclusionScope
# ---------------------------------------------------------------------------


class ConclusionScope:
    """Scope for managing conclusions about an observed peer by an observer.

    Matches upstream ``honcho.ConclusionScope``.
    """

    def __init__(self, honcho: Honcho, observer: Peer, observed: Peer) -> None:
        self._honcho = honcho
        self.observer = observer
        self.observed = observed
        self.workspace_id = honcho._ws_id

    def list(
        self,
        page: int = 1,
        size: int = 50,
        session: Session | str | None = None,
        *,
        reverse: bool = False,
    ) -> SyncPage:
        """List conclusions matching the observer/observed scope."""
        session_id = session.id if isinstance(session, Session) else session
        try:
            results = self._honcho._client.search(
                self.workspace_id,
                query="",
                limit=size * page,
                semantic=False,
            )
        except RuntimeError as exc:
            logger.warning("ConclusionScope.list() search failed: %s", exc)
            results = []

        conclusions: list[Conclusion] = []
        for r in results:
            meta = r.get("metadata", {})
            if meta.get("memory_type") != "conclusion":
                continue
            if meta.get("observer_id") != self.observer.id:
                continue
            if meta.get("observed_id") != self.observed.id:
                continue
            if session_id and meta.get("session_id") != session_id:
                continue
            conclusions.append(
                Conclusion(
                    id=r.get("id", ""),
                    content=r.get("memory_content", r.get("content", "")),
                    observer_id=meta.get("observer_id", self.observer.id),
                    observed_id=meta.get("observed_id", self.observed.id),
                    session_id=meta.get("session_id"),
                    created_at=r.get("created_at"),
                )
            )

        if reverse:
            conclusions = list(reversed(conclusions))

        start = (page - 1) * size
        paged = conclusions[start : start + size]
        return SyncPage(
            data={
                "items": paged,
                "total": len(conclusions),
                "page": page,
                "size": size,
                "pages": max(1, (len(conclusions) + size - 1) // size or 1),
            }
        )

    def query(
        self,
        query: str,
        top_k: int = 10,
        distance: float | None = None,
    ) -> list[Conclusion]:
        """Semantic search for conclusions."""
        try:
            results = self._honcho._client.search(
                self.workspace_id,
                query=query,
                limit=top_k,
                semantic=True,
            )
        except RuntimeError as exc:
            logger.warning("ConclusionScope.query() search failed: %s", exc)
            results = []

        conclusions: list[Conclusion] = []
        for r in results[:top_k]:
            meta = r.get("metadata", {})
            if meta.get("memory_type") != "conclusion":
                continue
            if meta.get("observer_id") != self.observer.id:
                continue
            if meta.get("observed_id") != self.observed.id:
                continue
            conclusions.append(
                Conclusion(
                    id=r.get("id", ""),
                    content=r.get("memory_content", r.get("content", "")),
                    observer_id=meta.get("observer_id", self.observer.id),
                    observed_id=meta.get("observed_id", self.observed.id),
                    session_id=meta.get("session_id"),
                    created_at=r.get("created_at"),
                )
            )
        return conclusions

    def delete(self, conclusion_id: str) -> None:
        """Delete a conclusion by ID."""
        try:
            self._honcho._client._call("delete_memory", [conclusion_id])
        except RuntimeError as exc:
            logger.warning("ConclusionScope.delete() failed: %s", exc)

    def create(
        self,
        conclusions: list[ConclusionCreateParams | dict],
    ) -> list[Conclusion]:
        """Store conclusions as memory records."""
        result: list[Conclusion] = []
        for item in conclusions:
            if isinstance(item, dict):
                item = ConclusionCreateParams(**item)
            meta = {
                "memory_type": "conclusion",
                "observer_id": self.observer.id,
                "observed_id": self.observed.id,
                "session_id": item.session_id or "",
            }
            try:
                self._honcho._client.store(
                    self.workspace_id,
                    content=item.content,
                    summary="",
                    entities_json=json.dumps(meta),
                )
                result.append(
                    Conclusion(
                        id="",  # client doesn't have server-generated ID
                        content=item.content,
                        observer_id=self.observer.id,
                        observed_id=self.observed.id,
                        session_id=item.session_id,
                    )
                )
            except RuntimeError as exc:
                logger.warning("ConclusionScope.create() store failed: %s", exc)
        return result

    def representation(
        self,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> str:
        """Generate an LLM representation from conclusions."""
        conclusions = self.query(
            search_query or "",
            top_k=search_top_k or max_conclusions or 10,
            distance=search_max_distance,
        )
        if not conclusions:
            return f"No conclusions about {self.observed.id} by {self.observer.id}."

        llm = LLMClient()
        if not llm.available:
            content_parts = [c.content[:100] for c in conclusions[:5]]
            return f"Conclusions about {self.observed.id} by {self.observer.id}: " + "; ".join(
                content_parts
            )

        mem_text = "\n".join(f"- {c.content}" for c in conclusions[:10])
        prompt = (
            f"Synthesize a natural language representation from these conclusions "
            f"about '{self.observed.id}' made by '{self.observer.id}':\n\n"
            f"{mem_text or '(none)'}"
        )
        result_text = llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        return result_text or f"Conclusions about {self.observed.id} by {self.observer.id}."

    @property
    def aio(self) -> ConclusionScopeAio:
        return ConclusionScopeAio(self)


class ConclusionScopeAio:
    """Async wrapper for ConclusionScope."""

    def __init__(self, scope: ConclusionScope) -> None:
        self._scope = scope

    async def list(
        self,
        page: int = 1,
        size: int = 50,
        session: Session | str | None = None,
        *,
        reverse: bool = False,
    ) -> SyncPage:
        return await asyncio.to_thread(
            self._scope.list,
            page=page,
            size=size,
            session=session,
            reverse=reverse,
        )

    async def query(
        self,
        query: str,
        top_k: int = 10,
        distance: float | None = None,
    ) -> list[Conclusion]:
        return await asyncio.to_thread(
            self._scope.query,
            query,
            top_k=top_k,
            distance=distance,
        )

    async def delete(self, conclusion_id: str) -> None:
        return await asyncio.to_thread(self._scope.delete, conclusion_id)

    async def create(
        self,
        conclusions: list[ConclusionCreateParams | dict],
    ) -> list[Conclusion]:
        return await asyncio.to_thread(self._scope.create, conclusions)

    async def representation(
        self,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._scope.representation,
            search_query=search_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
            include_most_frequent=include_most_frequent,
            max_conclusions=max_conclusions,
        )


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
        self._peer_configs: dict[str, SessionPeerConfig] = {}

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
            except RuntimeError as exc:
                logger.warning(
                    "Session.add_messages() failed to store message (peer=%s, session=%s): %s",
                    msg.peer_id,
                    self._id,
                    exc,
                )
                continue

            result.append(
                Message(
                    id=hash(msg.content + msg.peer_id + str(datetime.datetime.utcnow())) % (2**32),
                    content=msg.content,
                    peer_id=msg.peer_id,
                    session_id=self._id,
                    workspace_id=self._ws_id,
                    metadata=dict(msg.metadata or {}),
                    created_at=msg.created_at or datetime.datetime.utcnow(),
                )
            )
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
        except RuntimeError:
            results = []

        items = []
        for r in results[:size]:
            items.append(
                Message(
                    id=r.get("id", ""),
                    content=r.get("memory_content", r.get("content", "")),
                    peer_id=r.get("metadata", {}).get("peer_id", ""),
                    session_id=self._id,
                    workspace_id=self._ws_id,
                )
            )

        return SyncPage(
            data={
                "items": items,
                "total": len(items),
                "page": page,
                "size": size,
                "pages": 1,
            }
        )

    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        """Search messages within this session."""
        try:
            results = self._honcho._client.search(
                self._ws_id, query=query, limit=limit, semantic=True
            )
        except RuntimeError as exc:
            logger.warning("Session.search() failed: %s", exc)
            results = []

        messages = []
        for i, r in enumerate(results[:limit]):
            messages.append(
                Message(
                    id=r.get("id", str(i)),
                    content=r.get("memory_content", r.get("content", "")),
                    peer_id=r.get("metadata", {}).get("peer_id", ""),
                    session_id=self._id,
                    workspace_id=self._ws_id,
                )
            )
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
        """Delete this session (workspace) from SpacetimeDB."""
        try:
            if hasattr(self._honcho._client, "delete_workspace"):
                self._honcho._client.delete_workspace(self._ws_id)
            else:
                self._honcho._client._call("delete_workspace", [self._ws_id])
        except RuntimeError as exc:
            logger.warning(
                "Session.delete() failed to delete workspace %s: %s",
                self._ws_id,
                exc,
            )
        self._is_active = False

    def clone(self, *, message_id: str | None = None) -> Session:
        """Clone this session into a new session with its own workspace.

        Creates a new workspace in SpacetimeDB and copies peers and
        optionally messages from *message_id* forward.
        """
        import uuid

        new_id = uuid.uuid4().hex

        # Create new workspace in StDB
        self._honcho._client.create_workspace(name=new_id, id=new_id)

        # Create new session via the Honcho parent
        new_session = self._honcho.session(new_id)
        new_session._ws_id = new_id  # point to the new workspace

        # Copy peers
        new_session.add_peers(self._peers)

        # Optionally copy messages from message_id forward
        if message_id:
            msgs = self.messages(size=10000)
            copying = False
            for msg in msgs:
                if msg.id == message_id:
                    copying = True
                if copying:
                    new_session.add_messages(
                        [
                            MessageCreateParams(
                                content=msg.content,
                                peer_id=msg.peer_id,
                                metadata=msg.metadata,
                                created_at=msg.created_at,
                            )
                        ]
                    )

        return new_session

    def refresh(self) -> None:
        """Refresh session state."""
        pass

    # -- Metadata / Config ----------------------------------------------------

    def get_metadata(self) -> dict[str, object]:
        return self._metadata

    def set_metadata(self, metadata: dict[str, object]) -> None:
        self._metadata = metadata

    def get_configuration(self) -> SessionConfiguration:
        return self._configuration or SessionConfiguration()

    def set_configuration(self, configuration: SessionConfiguration) -> None:
        self._configuration = configuration

    # -- Peer management ------------------------------------------------------

    def set_peers(self, peers: Any | list[Any]) -> None:
        """Replace the peers list with the given peers."""
        if not isinstance(peers, list):
            peers = [peers]
        new_peers: list[Peer] = []
        for p in peers:
            if isinstance(p, Peer):
                new_peers.append(p)
            elif isinstance(p, str):
                new_peers.append(self._honcho.peer(p))
        self._peers = new_peers

    def remove_peers(self, peers: Any | list[Any]) -> None:
        """Remove peers from this session."""
        if not isinstance(peers, list):
            peers = [peers]
        remove_ids: set[str] = set()
        for p in peers:
            if isinstance(p, Peer):
                remove_ids.add(p.id)
            elif isinstance(p, str):
                remove_ids.add(p)
        self._peers = [p for p in self._peers if p.id not in remove_ids]

    def get_peer_configuration(self, peer: Peer | str) -> SessionPeerConfig:
        """Get configuration for a peer in this session."""
        peer_id = peer.id if isinstance(peer, Peer) else peer
        return self._peer_configs.get(peer_id, SessionPeerConfig())

    def set_peer_configuration(self, peer: Peer | str, config: SessionPeerConfig) -> None:
        """Set configuration for a peer in this session."""
        peer_id = peer.id if isinstance(peer, Peer) else peer
        self._peer_configs[peer_id] = config

    # -- Message access -------------------------------------------------------

    def get_message(self, message_id: str) -> Message | None:
        """Get a single message by ID."""
        try:
            results = self._honcho._client.get_memory(message_id)
        except RuntimeError:
            return None
        if not results:
            return None
        r = results[0]
        return Message(
            id=r.get("id", message_id),
            content=r.get("memory_content", r.get("content", "")),
            peer_id=r.get("peer_id", ""),
            session_id=self._id,
            workspace_id=self._ws_id,
            metadata=r.get("metadata", {}),
        )

    def update_message(self, message_id: str, metadata: dict[str, object]) -> None:
        """Update message metadata."""
        try:
            results = self._honcho._client.get_memory(message_id)
        except RuntimeError:
            return
        if not results:
            return
        r = results[0]
        content = r.get("memory_content", r.get("content", ""))
        self._honcho._client.update_memory(message_id, content=content, summary="", confidence=0.8)

    # -- File upload shell -----------------------------------------------------

    def upload_file(
        self,
        file: Any,
        peer: Peer | str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: MessageConfiguration | None = None,
        created_at: datetime.datetime | None = None,
    ) -> list[Message]:
        """Store file metadata as a message (thin shell, no actual file processing).

        Extracts a filename from the ``file`` argument and stores it as a
        message with content ``"[File: {filename}]"``.  Does NOT read or
        process the file contents — this is a compatibility shell matching
        the upstream ``honcho.Session.upload_file()`` shape.

        Args:
            file: A file-like object, tuple ``(filename, ...)``, path string,
                  or any object with a ``name`` / ``filename`` attribute.
            peer: The Peer (or peer ID) creating the file message.
            metadata: Optional metadata dict for the message.
            configuration: Optional message configuration.
            created_at: Optional timestamp.

        Returns:
            ``list[Message]`` — a single-item list containing the stored
            file-reference message.
        """
        # Extract filename
        filename = "unknown"
        if isinstance(file, str):
            import os as _os

            filename = _os.path.basename(file)
        elif isinstance(file, tuple):
            # Upload-style tuple: (filename, fileobj, ...)
            filename = str(file[0]) if file else "unknown"
        elif hasattr(file, "filename"):
            filename = str(file.filename)
        elif hasattr(file, "name"):
            filename = str(file.name)
        else:
            filename = str(file) if file else "unknown"

        peer_id = peer.id if isinstance(peer, Peer) else str(peer)
        content = f"[File: {filename}]"

        msg_params = MessageCreateParams(
            content=content,
            peer_id=peer_id,
            metadata=dict(metadata or {}),
            configuration=configuration,
            created_at=created_at or datetime.datetime.utcnow(),
        )
        return self.add_messages([msg_params])

    @property
    def aio(self) -> SessionAio:
        return SessionAio(self)


class SessionAio:
    """Async wrapper for Session — uses asyncio.to_thread for sync SpacetimeDB calls."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def add_peers(self, peers: Any | list[Any]) -> None:
        return await asyncio.to_thread(self._session.add_peers, peers)

    async def peers(self) -> list[Peer]:
        return await asyncio.to_thread(self._session.peers)

    async def add_messages(
        self,
        messages: MessageCreateParams | list[MessageCreateParams],
    ) -> list[Message]:
        return await asyncio.to_thread(self._session.add_messages, messages)

    async def messages(
        self,
        *,
        filters: dict[str, object] | None = None,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[MessageResponse, Message]:
        return await asyncio.to_thread(
            self._session.messages,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        return await asyncio.to_thread(
            self._session.search,
            query,
            filters=filters,
            limit=limit,
        )

    async def context(
        self,
        *,
        summary: bool = False,
        tokens: int | None = None,
        **kwargs: Any,
    ) -> SessionContext:
        return await asyncio.to_thread(
            self._session.context,
            summary=summary,
            tokens=tokens,
            **kwargs,
        )

    async def summaries(self) -> SessionSummaries:
        return await asyncio.to_thread(self._session.summaries)

    async def delete(self) -> None:
        return await asyncio.to_thread(self._session.delete)

    async def clone(self, *, message_id: str | None = None) -> Session:
        return await asyncio.to_thread(self._session.clone, message_id=message_id)

    async def refresh(self) -> None:
        return await asyncio.to_thread(self._session.refresh)

    async def get_metadata(self) -> dict[str, object]:
        return await asyncio.to_thread(self._session.get_metadata)

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        return await asyncio.to_thread(self._session.set_metadata, metadata)

    async def get_configuration(self) -> SessionConfiguration:
        return await asyncio.to_thread(self._session.get_configuration)

    async def set_configuration(self, configuration: SessionConfiguration) -> None:
        return await asyncio.to_thread(self._session.set_configuration, configuration)

    async def set_peers(self, peers: Any | list[Any]) -> None:
        return await asyncio.to_thread(self._session.set_peers, peers)

    async def remove_peers(self, peers: Any | list[Any]) -> None:
        return await asyncio.to_thread(self._session.remove_peers, peers)

    async def get_peer_configuration(self, peer: Peer | str) -> SessionPeerConfig:
        return await asyncio.to_thread(self._session.get_peer_configuration, peer)

    async def set_peer_configuration(self, peer: Peer | str, config: SessionPeerConfig) -> None:
        return await asyncio.to_thread(self._session.set_peer_configuration, peer, config)

    async def get_message(self, message_id: str) -> Message | None:
        return await asyncio.to_thread(self._session.get_message, message_id)

    async def update_message(self, message_id: str, metadata: dict[str, object]) -> None:
        return await asyncio.to_thread(self._session.update_message, message_id, metadata)


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
            token=api_key,
        )
        self._peer_cache: dict[str, Peer] = {}
        self._session_cache: dict[str, Session] = {}
        self._metadata: dict[str, object] = {}
        self._configuration: WorkspaceConfiguration = WorkspaceConfiguration()
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
        return SyncPage(
            data={
                "items": peers,
                "total": len(peers),
                "page": page,
                "size": size,
                "pages": max(1, (len(peers) + size - 1) // size or 1),
            }
        )

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
        return SyncPage(
            data={
                "items": sessions,
                "total": len(sessions),
                "page": page,
                "size": size,
                "pages": max(1, (len(sessions) + size - 1) // size or 1),
            }
        )

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
        except RuntimeError as exc:
            logger.warning("Honcho.search() failed: %s", exc)
            results = []

        messages = []
        for i, r in enumerate(results[:limit]):
            messages.append(
                Message(
                    id=r.get("id", str(i)),
                    content=r.get("memory_content", r.get("content", "")),
                    peer_id=r.get("metadata", {}).get("peer_id", ""),
                    session_id="",
                    workspace_id=self._ws_id,
                )
            )
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
        return SyncPage(
            data={
                "items": [self._ws_id],
                "total": 1,
                "page": page,
                "size": size,
                "pages": 1,
            }
        )

    def delete_workspace(self, workspace_id: str | None = None) -> None:
        """Delete a workspace."""
        self._session_cache.clear()
        self._peer_cache.clear()

    # -- Queue / Dream ---------------------------------------------------------

    def queue_status(
        self,
        observer: Any = None,
        sender: Any = None,
        session: Any = None,
    ) -> QueueStatusResponse:
        """Get queue processing status.

        Since the SpacetimeDB adapter processes conclusions and dreams
        synchronously (no background queue), this always reports zero
        queued / in-progress work units.  Completed work units reflects
        the number of conclusions stored.

        Args:
            observer: Optional observer peer (ID string or Peer) to scope.
            sender: Optional sender peer (ID string or Peer) to scope.
            session: Optional session (ID string or Session) to scope.

        Returns:
            ``QueueStatusResponse`` with work-unit counts.
        """
        # Count completed conclusions (they run synchronously, so
        # completed = total processed, in_progress = pending = 0)
        completed = 0
        try:
            mems = self._client.list_memories(
                workspace_id=self._ws_id,
                memory_type="conclusion",
            )
            completed = len(mems)
        except RuntimeError:
            pass  # STDB backend unavailable — completed defaults to 0, non-fatal

        return QueueStatusResponse(
            total_work_units=completed,
            completed_work_units=completed,
            in_progress_work_units=0,
            pending_work_units=0,
        )

    def schedule_dream(
        self,
        observer: Any,
        session: Any | None = None,
        observed: Any | None = None,
    ) -> None:
        """Run a dream operation synchronously.

        Dreams consolidate observations about a peer into higher-level
        insights via LLM.  Upstream Honcho queues dreams for background
        processing; the SpacetimeDB adapter runs them immediately.

        Args:
            observer: The observing peer (ID string or Peer) whose
                perspective to use.
            session: Optional session to scope the dream.
            observed: Optional observed peer.  Defaults to the observer
                (self-reflection).
        """
        # Resolve IDs
        observer_id = observer.id if hasattr(observer, "id") else str(observer)
        observed_id = observer_id
        if observed is not None:
            observed_id = observed.id if hasattr(observed, "id") else str(observed)

        session_id = None
        if session is not None:
            session_id = session.id if hasattr(session, "id") else str(session)

        # Gather existing conclusions about the observed peer
        try:
            conclusions = self._client.list_memories(
                workspace_id=self._ws_id,
                memory_type="conclusion",
            )
            # Filter to conclusions about the observed peer
            peer_conclusions = [
                c
                for c in conclusions
                if c.get("peer_id") == observed_id or str(observed_id) in c.get("content", "")
            ]
        except RuntimeError:
            peer_conclusions = []

        # Generate dream via LLM
        try:
            from ..llm import LLMClient

            llm = LLMClient()
            if llm.available:
                conclusion_text = "\n".join(
                    f"- {c.get('content', '')}"
                    for c in (peer_conclusions or [{"content": "No prior conclusions available."}])[
                        :20
                    ]
                )
                prompt = (
                    f"You are dreaming about observed peer '{observed_id}'.\n"
                    f"Observed by '{observer_id}'.\n\n"
                    f"Recent conclusions:\n{conclusion_text}\n\n"
                    f"Consolidate these observations into a single dream insight "
                    f"(2-4 sentences). Focus on patterns, personality traits, "
                    f"preferences, or behavioral predictions."
                )
                dream_content = llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "You are a dream consolidation engine. Synthesize observations into concise insights.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    max_tokens=256,
                )
                if dream_content:
                    self._client.store(
                        workspace_id=self._ws_id,
                        content=dream_content,
                        summary=f"[dream] {observer_id} about {observed_id}"[:120],
                        memory_type="dream",
                        peer_id=observer_id,
                        observer_id=observer_id,
                        source_session_id=session_id or "",
                    )
        except RuntimeError:
            pass  # LLM unavailable — dream is best-effort

    # -- Metadata / Config / Refresh ------------------------------------------

    def get_metadata(self) -> dict[str, object]:
        return self._metadata

    def set_metadata(self, metadata: dict[str, object]) -> None:
        self._metadata = metadata

    def get_configuration(self) -> WorkspaceConfiguration:
        return self._configuration

    def set_configuration(self, configuration: WorkspaceConfiguration) -> None:
        self._configuration = configuration

    def refresh(self) -> None:
        pass

    # -- Close ----------------------------------------------------------------

    def close(self) -> None:
        """Close the client."""
        self._closed = True
        self._session_cache.clear()
        self._peer_cache.clear()

    @property
    def aio(self) -> HonchoAio:
        return HonchoAio(self)


class HonchoAio:
    """Async wrapper for Honcho — uses asyncio.to_thread for sync SpacetimeDB calls."""

    def __init__(self, honcho: Honcho) -> None:
        self._honcho = honcho

    async def peer(
        self,
        id: str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: PeerConfig | None = None,
    ) -> Peer:
        return await asyncio.to_thread(
            self._honcho.peer,
            id,
            metadata=metadata,
            configuration=configuration,
        )

    async def peers(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[PeerResponse, Peer]:
        return await asyncio.to_thread(
            self._honcho.peers,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def session(
        self,
        id: str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: SessionConfiguration | None = None,
        peers: Any = None,
    ) -> Session:
        return await asyncio.to_thread(
            self._honcho.session,
            id,
            metadata=metadata,
            configuration=configuration,
            peers=peers,
        )

    async def sessions(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[SessionResponse, Session]:
        return await asyncio.to_thread(
            self._honcho.sessions,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> list[Message]:
        return await asyncio.to_thread(
            self._honcho.search,
            query,
            filters=filters,
            limit=limit,
        )

    async def workspaces(
        self,
        filters: dict[str, object] | None = None,
        *,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[WorkspaceResponse, str]:
        return await asyncio.to_thread(
            self._honcho.workspaces,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def delete_workspace(self, workspace_id: str | None = None) -> None:
        return await asyncio.to_thread(self._honcho.delete_workspace, workspace_id)

    async def queue_status(
        self,
        observer: Any = None,
        sender: Any = None,
        session: Any = None,
    ) -> QueueStatusResponse:
        return await asyncio.to_thread(
            self._honcho.queue_status,
            observer=observer,
            sender=sender,
            session=session,
        )

    async def schedule_dream(
        self,
        observer: Any,
        session: Any | None = None,
        observed: Any | None = None,
    ) -> None:
        return await asyncio.to_thread(
            self._honcho.schedule_dream,
            observer,
            session=session,
            observed=observed,
        )

    async def close(self) -> None:
        return await asyncio.to_thread(self._honcho.close)

    async def get_metadata(self) -> dict[str, object]:
        return await asyncio.to_thread(self._honcho.get_metadata)

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        return await asyncio.to_thread(self._honcho.set_metadata, metadata)

    async def get_configuration(self) -> WorkspaceConfiguration:
        return await asyncio.to_thread(self._honcho.get_configuration)

    async def set_configuration(self, configuration: WorkspaceConfiguration) -> None:
        return await asyncio.to_thread(self._honcho.set_configuration, configuration)

    async def refresh(self) -> None:
        return await asyncio.to_thread(self._honcho.refresh)


__all__ = [
    "Honcho",
    "HonchoAio",
    "Peer",
    "PeerAio",
    "Session",
    "SessionAio",
    "Message",
    "Conclusion",
    "ConclusionCreateParams",
    "ConclusionScope",
    "ConclusionScopeAio",
    "SyncPage",
    "PeerResponse",
    "ConclusionResponse",
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
