"""Session class for the Honcho-compatible adapter.

Split from the monolithic ``honcho.py`` into a package.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import TYPE_CHECKING, Any

from ._models import (
    Message,
    MessageConfiguration,
    MessageCreateParams,
    MessageResponse,
    SessionConfiguration,
    SessionContext,
    SessionPeerConfig,
    SessionSummaries,
    SyncPage,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._peer import Peer


def _peer_cls() -> type:
    """Lazily resolve the Peer class at runtime.

    Importing ``._peer`` at module top-level creates a circular import:
    ``_peer.py`` imports ``.``_session`` (module-level), so when
    ``_session.py`` does ``from ._peer import Peer`` it hits ``_peer`` while it
    is still partially initialized (the ``Peer`` class is not yet defined).
    This is order-dependent and intermittently raises "cannot import name
    'Peer' from partially initialized module" under the benchmark chain. Since
    this module has ``from __future__ import annotations``, ``Peer`` is only
    needed at runtime (``isinstance`` checks), so resolve it lazily here.
    """
    from ._peer import Peer

    return Peer


if TYPE_CHECKING:
    from ._honcho import Honcho


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
        """Initialize the store/reference."""
        self._id = session_id
        self._honcho = honcho
        self._ws_id = honcho._ws_id
        self._metadata = metadata or {}
        self._configuration = configuration or SessionConfiguration()
        self._created_at = created_at or datetime.datetime.now(datetime.UTC)
        self._is_active = is_active if is_active is not None else True
        self._peers: list[Peer] = []
        self._peer_configs: dict[str, SessionPeerConfig] = {}

    @property
    def id(self) -> str:
        """The unique identifier."""
        return self._id

    @property
    def metadata(self) -> dict[str, object] | None:
        """The resource metadata."""
        return self._metadata

    @property
    def configuration(self) -> SessionConfiguration | None:
        """Get the current configuration."""
        return self._configuration

    @property
    def created_at(self) -> datetime.datetime | None:
        """The creation timestamp."""
        return self._created_at

    @property
    def is_active(self) -> bool | None:
        """Is active."""
        return self._is_active

    def add_peers(self, peers: Any | list[Any]) -> None:
        """Add peers to this session."""
        if not isinstance(peers, list):
            peers = [peers]
        for p in peers:
            if isinstance(p, _peer_cls()) and p not in self._peers:
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
                    id=hash(msg.content + msg.peer_id + str(datetime.datetime.now(datetime.UTC))) % (2**32),
                    content=msg.content,
                    peer_id=msg.peer_id,
                    session_id=self._id,
                    workspace_id=self._ws_id,
                    metadata=dict(msg.metadata or {}),
                    created_at=msg.created_at or datetime.datetime.now(datetime.UTC),
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

    # -- Metadata / Config ----------------------------------------------------

    def get_metadata(self) -> dict[str, object]:
        """Get metadata associated with this resource."""
        return self._metadata

    def set_metadata(self, metadata: dict[str, object]) -> None:
        """Set metadata for this resource."""
        self._metadata = metadata

    def get_configuration(self) -> SessionConfiguration:
        """Get the configuration for this resource."""
        return self._configuration or SessionConfiguration()

    def set_configuration(self, configuration: SessionConfiguration) -> None:
        """Set the configuration for this resource."""
        self._configuration = configuration

    # -- Peer management ------------------------------------------------------

    def set_peers(self, peers: Any | list[Any]) -> None:
        """Replace the peers list with the given peers."""
        if not isinstance(peers, list):
            peers = [peers]
        new_peers: list[Peer] = []
        for p in peers:
            if isinstance(p, _peer_cls()):
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
            if isinstance(p, _peer_cls()):
                remove_ids.add(p.id)
            elif isinstance(p, str):
                remove_ids.add(p)
        self._peers = [p for p in self._peers if p.id not in remove_ids]

    def get_peer_configuration(self, peer: Peer | str) -> SessionPeerConfig:
        """Get configuration for a peer in this session."""
        peer_id = peer.id if isinstance(peer, _peer_cls()) else peer
        return self._peer_configs.get(peer_id, SessionPeerConfig())

    def set_peer_configuration(self, peer: Peer | str, config: SessionPeerConfig) -> None:
        """Set configuration for a peer in this session."""
        peer_id = peer.id if isinstance(peer, _peer_cls()) else peer
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

        peer_id = peer.id if isinstance(peer, _peer_cls()) else str(peer)
        content = f"[File: {filename}]"

        msg_params = MessageCreateParams(
            content=content,
            peer_id=peer_id,
            metadata=dict(metadata or {}),
            configuration=configuration,
            created_at=created_at or datetime.datetime.now(datetime.UTC),
        )
        return self.add_messages([msg_params])

    @property
    def aio(self) -> SessionAio:
        """Get the async I/O session for async operations."""
        return SessionAio(self)


class SessionAio:
    """Async wrapper for Session — uses asyncio.to_thread for sync SpacetimeDB calls."""

    def __init__(self, session: Session) -> None:
        """Initialize the store/reference."""
        self._session = session

    async def add_peers(self, peers: Any | list[Any]) -> None:
        """Add peers."""
        return await asyncio.to_thread(self._session.add_peers, peers)

    async def peers(self) -> list[Peer]:
        """Access the Peers sub-resource."""
        return await asyncio.to_thread(self._session.peers)

    async def add_messages(
        self,
        messages: MessageCreateParams | list[MessageCreateParams],
    ) -> list[Message]:
        """Add messages."""
        return await asyncio.to_thread(self._session.add_messages, messages)

    async def messages(
        self,
        *,
        filters: dict[str, object] | None = None,
        page: int = 1,
        size: int = 50,
        reverse: bool = False,
    ) -> SyncPage[MessageResponse, Message]:
        """Messages."""
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
        """Search across resources."""
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
        """Access the context sub-resource."""
        return await asyncio.to_thread(
            self._session.context,
            summary=summary,
            tokens=tokens,
            **kwargs,
        )

    async def summaries(self) -> SessionSummaries:
        """Summaries."""
        return await asyncio.to_thread(self._session.summaries)

    async def delete(self) -> None:
        """Delete this resource."""
        return await asyncio.to_thread(self._session.delete)

    async def clone(self, *, message_id: str | None = None) -> Session:
        """Clone."""
        return await asyncio.to_thread(self._session.clone, message_id=message_id)

    async def refresh(self) -> None:
        """Refresh the resource data from the server."""
        return await asyncio.to_thread(self._session.refresh)

    async def get_metadata(self) -> dict[str, object]:
        """Get metadata associated with this resource."""
        return await asyncio.to_thread(self._session.get_metadata)

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        """Set metadata for this resource."""
        return await asyncio.to_thread(self._session.set_metadata, metadata)

    async def get_configuration(self) -> SessionConfiguration:
        """Get the configuration for this resource."""
        return await asyncio.to_thread(self._session.get_configuration)

    async def set_configuration(self, configuration: SessionConfiguration) -> None:
        """Set the configuration for this resource."""
        return await asyncio.to_thread(self._session.set_configuration, configuration)

    async def set_peers(self, peers: Any | list[Any]) -> None:
        """Set peers."""
        return await asyncio.to_thread(self._session.set_peers, peers)

    async def remove_peers(self, peers: Any | list[Any]) -> None:
        """Remove peers."""
        return await asyncio.to_thread(self._session.remove_peers, peers)

    async def get_peer_configuration(self, peer: Peer | str) -> SessionPeerConfig:
        """Get peer configuration."""
        return await asyncio.to_thread(self._session.get_peer_configuration, peer)

    async def set_peer_configuration(self, peer: Peer | str, config: SessionPeerConfig) -> None:
        """Set peer configuration."""
        return await asyncio.to_thread(self._session.set_peer_configuration, peer, config)

    async def get_message(self, message_id: str) -> Message | None:
        """Get message."""
        return await asyncio.to_thread(self._session.get_message, message_id)

    async def update_message(self, message_id: str, metadata: dict[str, object]) -> None:
        """Update message."""
        return await asyncio.to_thread(self._session.update_message, message_id, metadata)


