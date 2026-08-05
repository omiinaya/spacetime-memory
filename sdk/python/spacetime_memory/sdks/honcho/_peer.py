"""Peer class for the Honcho-compatible adapter.

Split from the monolithic ``honcho.py`` into a package.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import TYPE_CHECKING, Any, Iterator, Literal

from ...llm import LLMClient
from ._models import (
    Message,
    MessageCreateParams,
    PeerConfig,
    PeerContextResponse,
    SessionResponse,
    SyncPage,
)

logger = logging.getLogger(__name__)

from ._conclusion import ConclusionScope  # noqa: E402

if TYPE_CHECKING:
    from ._honcho import Honcho
    from ._session import Session


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
        """Initialize the store/reference."""
        self._id = peer_id
        self._honcho = honcho
        self._ws_id = honcho._ws_id
        self._metadata = metadata or {}
        self._configuration = configuration or PeerConfig()
        self._created_at = created_at or datetime.datetime.now(datetime.UTC)

    @property
    def id(self) -> str:
        """The unique identifier."""
        return self._id

    @property
    def metadata(self) -> dict[str, object] | None:
        """The resource metadata."""
        return self._metadata

    @property
    def configuration(self) -> PeerConfig | None:
        """Get the current configuration."""
        return self._configuration

    @property
    def created_at(self) -> datetime.datetime | None:
        """The creation timestamp."""
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
            created_at=datetime.datetime.now(datetime.UTC)
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
    ) -> Iterator[str]:
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
            """Generator."""
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

    def working_representation(
        self,
        session: Session | str | None = None,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
    ) -> str:
        """Working representation — this peer's representation scoped to a session.

        Matches Honcho's ``peer.working_representation(session=...)``: the
        representation derived from what the peer currently knows *in the
        context of the given session* (session messages + peer knowledge),
        as opposed to the global :meth:`representation`.

        When a session is given, its recent messages seed the semantic search
        so the representation reflects the session's current context.
        """
        scoped_query = search_query
        if scoped_query is None and session is not None:
            try:
                session_id = session.id if isinstance(session, Session) else str(session)
                msgs = self._honcho._client._query(
                    "message",
                    workspace_id=self._ws_id,
                    filter_dict={"session_id": session_id},
                )
                contents = [str(m.get("content", "")) for m in msgs if m.get("content")]
                if contents:
                    scoped_query = " ".join(contents[-5:])[:500]
            except Exception:
                scoped_query = None
        return self.representation(
            session=session,
            search_query=scoped_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
        )

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
        """List sessions this peer participates in.

        Backed by the persisted ``message`` table: messages store
        ``source_session_id`` (the session) plus ``peer_id`` in metadata, so
        sessions containing this peer are derivable across processes.
        Falls back to the in-memory session cache for sessions created in
        this process that haven't had messages persisted yet.
        """
        filtered: list[Session] = []
        seen: set[str] = set()
        from ._session import Session  # lazy — avoids circular import with _peer
        # 1. Derive sessions from persisted messages authored by this peer.
        try:
            rows = self._honcho._client._query(
                "memory",
                workspace_id=self._ws_id,
                filter_dict={},
                columns=["source_session_id", "metadata"],
            )
            for row in rows:
                meta = row.get("metadata") or {}
                if isinstance(meta, str):
                    import json as _json

                    try:
                        meta = _json.loads(meta)
                    except ValueError:
                        meta = {}
                if meta.get("peer_id") != self._id:
                    continue
                sid = row.get("source_session_id", "")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                filtered.append(
                    Session(
                        sid,
                        self._honcho,
                        metadata={"source": "persisted"},
                    )
                )
        except RuntimeError:
            pass  # fall through to cache
        # 2. Merge any sessions known only in the in-memory cache.
        for session in self._honcho._session_cache.values():
            if session.id in seen:
                continue
            if self in session._peers:
                seen.add(session.id)
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
        """Get metadata associated with this resource."""
        return self._metadata

    def set_metadata(self, metadata: dict[str, object]) -> None:
        """Set metadata for this resource."""
        self._metadata = metadata

    def get_configuration(self) -> PeerConfig:
        """Get the configuration for this resource."""
        return self._configuration or PeerConfig()

    def set_configuration(self, configuration: PeerConfig) -> None:
        """Set the configuration for this resource."""
        self._configuration = configuration

    def refresh(self) -> None:
        """Refresh the resource data from the server."""

    @property
    def aio(self) -> PeerAio:
        """Get the async I/O session for async operations."""
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
        """Initialize the store/reference."""
        self._peer = peer

    async def message(
        self,
        content: str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: dict[str, Any] | None = None,
        created_at: datetime.datetime | str | None = None,
    ) -> MessageCreateParams:
        """Access the Message sub-resource."""
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
        """Send a chat message."""
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
        """Search across resources."""
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
        """Access the Sessions sub-resource."""
        return await asyncio.to_thread(
            self._peer.sessions,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def get_metadata(self) -> dict[str, object]:
        """Get metadata associated with this resource."""
        return await asyncio.to_thread(self._peer.get_metadata)

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        """Set metadata for this resource."""
        return await asyncio.to_thread(self._peer.set_metadata, metadata)

    async def get_configuration(self) -> PeerConfig:
        """Get the configuration for this resource."""
        return await asyncio.to_thread(self._peer.get_configuration)

    async def set_configuration(self, configuration: PeerConfig) -> None:
        """Set the configuration for this resource."""
        return await asyncio.to_thread(self._peer.set_configuration, configuration)

    async def refresh(self) -> None:
        """Refresh the resource data from the server."""
        return await asyncio.to_thread(self._peer.refresh)

    async def chat_stream(
        self,
        query: str,
        *,
        target: Any | None = None,
        session: Session | str | None = None,
        reasoning_level: Literal["minimal", "low", "medium", "high", "max"] | None = None,
    ):
        """Send a chat message and stream the response."""
        return await asyncio.to_thread(
            self._peer.chat_stream,
            query,
            target=target,
            session=session,
            reasoning_level=reasoning_level,
        )

    async def get_card(self, target: str | None = None) -> dict:
        """Get the card/display info."""
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
        """Get the data representation."""
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

    async def working_representation(
        self,
        session: Session | str | None = None,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
    ) -> str:
        """Working representation scoped to a session — delegates to sync Peer."""
        return await asyncio.to_thread(
            self._peer.working_representation,
            session=session,
            search_query=search_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
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
        """Access the context sub-resource."""
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


