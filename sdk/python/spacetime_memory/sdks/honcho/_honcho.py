"""Honcho class for the Honcho-compatible adapter.

Split from the monolithic ``honcho.py`` into a package.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Any, Literal

from ...client import Client
from ...llm import LLMClient
from ._models import (
    Message,
    PeerConfig,
    PeerResponse,
    QueueStatusResponse,
    SessionConfiguration,
    SessionResponse,
    SyncPage,
    WorkspaceConfiguration,
    WorkspaceResponse,
)

logger = logging.getLogger(__name__)

from ._peer import Peer  # noqa: E402
from ._session import Session  # noqa: E402


class Honcho:
    """Drop-in replacement for ``honcho.Honcho``.

    Maps the Honcho conversational memory platform API to SpacetimeDB.
    Accepts standard Honcho constructor args plus SpacetimeDB-specific params.

    Usage::

        honcho = Honcho(workspace_id=\"my-workspace\", base_url=None,
                        stdb_host=\"127.0.0.1\", stdb_port=3001)
        peer = honcho.peer(\"alice\")
        session = honcho.session(\"chat-1\")
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
        """Initialize the store/reference."""
        import hashlib

        self._ws_id = workspace_id or os.environ.get("HONCHO_WORKSPACE_ID", "default")
        self._api_key = api_key
        self._base_url = base_url or f"http://{stdb_host or '127.0.0.1'}:{stdb_port or 3001}"
        self._timeout = timeout or 30.0

        db = stdb_database or hashlib.md5(self._ws_id.encode()).hexdigest()[:16]
        self._client = Client(
            host=stdb_host or os.environ.get("SPACETIMEDB_HOST", "127.0.0.1"),
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
        """Get the current configuration."""
        return WorkspaceConfiguration()

    @property
    def base_url(self) -> str:
        """Base url."""
        return self._base_url

    # -- Peer methods ---------------------------------------------------------

    def peer(
        self,
        id: str,
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
        id: str,
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
        """Get metadata associated with this resource."""
        return self._metadata

    def set_metadata(self, metadata: dict[str, object]) -> None:
        """Set metadata for this resource."""
        self._metadata = metadata

    def get_configuration(self) -> WorkspaceConfiguration:
        """Get the configuration for this resource."""
        return self._configuration

    def set_configuration(self, configuration: WorkspaceConfiguration) -> None:
        """Set the configuration for this resource."""
        self._configuration = configuration

    def refresh(self) -> None:
        """Refresh the resource data from the server."""

    # -- Close ----------------------------------------------------------------

    def close(self) -> None:
        """Close the client."""
        self._closed = True
        self._session_cache.clear()
        self._peer_cache.clear()

    @property
    def aio(self) -> HonchoAio:
        """Get the async I/O session for async operations."""
        return HonchoAio(self)


class HonchoAio:
    """Async wrapper for Honcho — uses asyncio.to_thread for sync SpacetimeDB calls."""

    def __init__(self, honcho: Honcho) -> None:
        """Initialize the store/reference."""
        self._honcho = honcho

    async def peer(
        self,
        id: str,
        *,
        metadata: dict[str, object] | None = None,
        configuration: PeerConfig | None = None,
    ) -> Peer:
        """Peer."""
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
        """Access the Peers sub-resource."""
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
        """Session."""
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
        """Access the Sessions sub-resource."""
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
        """Search across resources."""
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
        """Workspaces."""
        return await asyncio.to_thread(
            self._honcho.workspaces,
            filters=filters,
            page=page,
            size=size,
            reverse=reverse,
        )

    async def delete_workspace(self, workspace_id: str | None = None) -> None:
        """Delete workspace."""
        return await asyncio.to_thread(self._honcho.delete_workspace, workspace_id)

    async def queue_status(
        self,
        observer: Any = None,
        sender: Any = None,
        session: Any = None,
    ) -> QueueStatusResponse:
        """Queue status."""
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
        """Schedule dream."""
        return await asyncio.to_thread(
            self._honcho.schedule_dream,
            observer,
            session=session,
            observed=observed,
        )

    async def close(self) -> None:
        """Close the connection and release resources."""
        return await asyncio.to_thread(self._honcho.close)

    async def get_metadata(self) -> dict[str, object]:
        """Get metadata associated with this resource."""
        return await asyncio.to_thread(self._honcho.get_metadata)

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        """Set metadata for this resource."""
        return await asyncio.to_thread(self._honcho.set_metadata, metadata)

    async def get_configuration(self) -> WorkspaceConfiguration:
        """Get the configuration for this resource."""
        return await asyncio.to_thread(self._honcho.get_configuration)

    async def set_configuration(self, configuration: WorkspaceConfiguration) -> None:
        """Set the configuration for this resource."""
        return await asyncio.to_thread(self._honcho.set_configuration, configuration)

    async def refresh(self) -> None:
        """Refresh the resource data from the server."""
        return await asyncio.to_thread(self._honcho.refresh)


