"""
Zep-compatible memory adapter — async client classes.

Provides AsyncZepClient, _AsyncMemoryProxy, _AsyncUserProxy,
and AsyncZep (with sub-clients).
"""

from __future__ import annotations

import asyncio
from typing import Any

from ._client import (
    UserClient,
    ZepClient,
    _GraphClient,
)
from ._models import (
    Fact,
    MemoryMessage,
    MemorySearchResult,
    Session,
)

# ---------------------------------------------------------------------------
# Async client (wraps sync ZepClient via asyncio.to_thread)
# ---------------------------------------------------------------------------


class AsyncZepClient:
    """Async wrapper around ``ZepClient`` for use in asyncio applications.

    Mirrors the full ``ZepClient`` API with async methods. Each method
    delegates to the synchronous ``ZepClient`` via ``asyncio.to_thread()``
    to avoid blocking the event loop.

    Usage::

        from spacetime_memory.sdks.zep import AsyncZepClient

        client = AsyncZepClient(host=\"127.0.0.1\", port=3001)

        async with client:
            result = await client.add_memory(
                session_id=\"my-session\",
                messages=[{\"role\": \"user\", \"content\": \"Hello\"}],
            )
            memory = await client.get_memory(session_id=\"my-session\")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        config: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> None:
        """Initialize the API resource wrapper."""
        self._sync = ZepClient(
            host=host,
            port=port,
            config=config,
            token=token,
        )

    # ------------------------------------------------------------------
    # Async Memory API
    # ------------------------------------------------------------------

    async def add_memory(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | list[MemoryMessage],
        metadata: dict[str, Any] | None = None,
        fact_instruction: str | None = None,
        summary_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Add a memory to a session."""
        return await asyncio.to_thread(
            self._sync.add_memory,
            session_id,
            messages,
            metadata=metadata,
            fact_instruction=fact_instruction,
            summary_instruction=summary_instruction,
        )

    async def get_memory(
        self,
        session_id: str,
        limit: int = 10,
        min_rating: float = 0.0,
    ) -> dict[str, Any] | None:
        """Get a memory by ID."""
        return await asyncio.to_thread(
            self._sync.get_memory, session_id, limit=limit, min_rating=min_rating
        )

    async def delete_memory(self, session_id: str) -> dict[str, Any]:
        """Delete a memory by ID."""
        return await asyncio.to_thread(self._sync.delete_memory, session_id)

    async def search_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        score_threshold: float = 0.0,
        min_score: float | None = None,
        search_type: str = "similarity",
    ) -> list[MemorySearchResult]:
        """Search memories by query."""
        return await asyncio.to_thread(
            self._sync.search_memory,
            session_id,
            query,
            limit=limit,
            score_threshold=score_threshold,
            min_score=min_score,
            search_type=search_type,
        )

    # ------------------------------------------------------------------
    # Async Facts API
    # ------------------------------------------------------------------

    async def add_fact(
        self,
        session_id: str,
        fact: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a fact to a user/session."""
        return await asyncio.to_thread(self._sync.add_fact, session_id, fact, metadata=metadata)

    async def list_facts(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[Fact]:
        """List all facts for a user."""
        return await asyncio.to_thread(self._sync.list_facts, session_id, limit=limit)

    async def delete_fact(self, fact_uuid: str, **kwargs: Any) -> dict[str, Any]:
        """Delete a fact by ID."""
        return await asyncio.to_thread(self._sync.delete_fact, fact_uuid, **kwargs)

    async def get_fact(self, fact_uuid: str) -> Fact:
        """Get a fact by ID."""
        return await asyncio.to_thread(self._sync.get_fact, fact_uuid)

    # ------------------------------------------------------------------
    # Async Memory Update
    # ------------------------------------------------------------------

    async def update_memory(
        self,
        session_id: str,
        memory_id: str,
        messages: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing memory."""
        return await asyncio.to_thread(
            self._sync.update_memory,
            session_id,
            memory_id,
            messages=messages,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Async Session message methods
    # ------------------------------------------------------------------

    async def get_session_messages(
        self,
        session_id: str,
        limit: int | None = None,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """Get messages for a session."""
        return await asyncio.to_thread(
            self._sync.get_session_messages,
            session_id,
            limit=limit,
            cursor=cursor,
        )

    async def get_session_message(
        self,
        session_id: str,
        message_uuid: str,
    ) -> dict[str, Any]:
        """Get a single message from a session."""
        return await asyncio.to_thread(self._sync.get_session_message, session_id, message_uuid)

    async def update_message_metadata(
        self,
        session_id: str,
        message_uuid: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Update metadata on a message."""
        return await asyncio.to_thread(
            self._sync.update_message_metadata,
            session_id,
            message_uuid,
            metadata,
        )

    # ------------------------------------------------------------------
    # Async Session management
    # ------------------------------------------------------------------

    async def list_sessions(
        self,
        limit: int = 100,
        offset: int = 0,
        page_number: int | None = None,
        page_size: int | None = None,
        order_by: str = "created_at",
        asc: bool = False,
    ) -> list[Session]:
        """List all sessions for a user."""
        return await asyncio.to_thread(
            self._sync.list_sessions,
            limit=limit,
            offset=offset,
            page_number=page_number,
            page_size=page_size,
            order_by=order_by,
            asc=asc,
        )

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        return await asyncio.to_thread(self._sync.get_session, session_id)

    async def add_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session."""
        return await asyncio.to_thread(self._sync.add_session, session_id, metadata=metadata)

    async def update_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
        fact_rating_instruction: str | None = None,
    ) -> Session:
        """Update session metadata."""
        return await asyncio.to_thread(
            self._sync.update_session,
            session_id,
            metadata=metadata,
            fact_rating_instruction=fact_rating_instruction,
        )

    async def search_sessions(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Session]:
        """Search sessions by criteria."""
        return await asyncio.to_thread(self._sync.search_sessions, query, limit=limit)

    async def close(self) -> None:
        """Close the client connection."""
        return await asyncio.to_thread(self._sync.close)

    async def summarize_memory(self, session_id: str) -> str | None:
        """Summarize a memory using the session context."""
        return await asyncio.to_thread(self._sync.summarize_memory, session_id)

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AsyncZepClient:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context manager."""
        await self.close()


# ---------------------------------------------------------------------------
# Async sub-client proxies (async mirror of .memory / .user)
# ---------------------------------------------------------------------------


class _AsyncMemoryProxy:
    """Async proxy for ``AsyncZep.memory``."""

    def __init__(self, client: AsyncZepClient) -> None:
        """Initialize the API resource wrapper."""
        self._c = client

    async def add(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | list[MemoryMessage],
        *,
        metadata: dict[str, Any] | None = None,
        fact_instruction: str | None = None,
        summary_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Add a new record."""
        return await self._c.add_memory(
            session_id,
            messages,
            metadata=metadata,
            fact_instruction=fact_instruction,
            summary_instruction=summary_instruction,
        )

    async def get(
        self,
        session_id: str,
        *,
        limit: int = 10,
        min_rating: float = 0.0,
    ) -> dict[str, Any] | None:
        """Get a single record by ID."""
        return await self._c.get_memory(session_id, limit=limit, min_rating=min_rating)

    async def delete(self, session_id: str) -> dict[str, Any]:
        """Delete a record by ID."""
        return await self._c.delete_memory(session_id)

    async def search(
        self,
        session_id: str,
        query: str,
        *,
        limit: int = 10,
        score_threshold: float = 0.0,
        min_score: float | None = None,
        search_type: str = "similarity",
    ) -> list[MemorySearchResult]:
        """Search memory/search results."""
        return await self._c.search_memory(
            session_id,
            query,
            limit=limit,
            score_threshold=score_threshold,
            min_score=min_score,
            search_type=search_type,
        )

    async def add_fact(
        self,
        session_id: str,
        fact: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a fact to a user/session."""
        return await self._c.add_fact(session_id, fact, metadata=metadata)

    async def get_fact(self, fact_uuid: str) -> Fact:
        """Get a fact by ID."""
        return await self._c.get_fact(fact_uuid)

    async def delete_fact(self, fact_uuid: str, **kwargs: Any) -> dict[str, Any]:
        """Delete a fact by ID."""
        return await self._c.delete_fact(fact_uuid, **kwargs)

    async def add_session(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session."""
        return await self._c.add_session(session_id, metadata=metadata)

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        return await self._c.get_session(session_id)

    async def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        page_number: int | None = None,
        page_size: int | None = None,
        order_by: str = "created_at",
        asc: bool = False,
    ) -> list[Session]:
        """List all sessions for a user."""
        return await self._c.list_sessions(
            limit=limit,
            offset=offset,
            page_number=page_number,
            page_size=page_size,
            order_by=order_by,
            asc=asc,
        )

    async def search_sessions(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[Session]:
        """Search sessions by criteria."""
        return await self._c.search_sessions(query, limit=limit)

    async def update_session(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        fact_rating_instruction: str | None = None,
    ) -> Session:
        """Update session metadata."""
        return await self._c.update_session(
            session_id,
            metadata=metadata,
            fact_rating_instruction=fact_rating_instruction,
        )

    async def get_session_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """Get messages for a session."""
        return await self._c.get_session_messages(session_id, limit=limit, cursor=cursor)

    async def get_session_message(
        self,
        session_id: str,
        message_uuid: str,
    ) -> dict[str, Any]:
        """Get a single message from a session."""
        return await self._c.get_session_message(session_id, message_uuid)

    async def update_message_metadata(
        self,
        session_id: str,
        message_uuid: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Update metadata on a message."""
        return await self._c.update_message_metadata(session_id, message_uuid, metadata)


class _AsyncUserProxy:
    """Async proxy for ``AsyncZep.user``."""

    def __init__(self, client: AsyncZepClient) -> None:
        """Initialize the API resource wrapper."""
        self._inner = UserClient(client._sync._client)

    async def add(
        self,
        *,
        user_id: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a new record."""
        return await asyncio.to_thread(
            self._inner.add,
            user_id=user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            metadata=metadata,
        )

    async def get(self, user_id: str) -> dict[str, Any]:
        """Get a single record by ID."""
        return await asyncio.to_thread(self._inner.get, user_id)

    async def update(
        self,
        user_id: str,
        *,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing record."""
        return await asyncio.to_thread(
            self._inner.update,
            user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            metadata=metadata,
        )

    async def delete(self, user_id: str) -> dict[str, Any]:
        """Delete a record by ID."""
        return await asyncio.to_thread(self._inner.delete, user_id)

    async def list_ordered(
        self,
        *,
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List items in order."""
        return await asyncio.to_thread(
            self._inner.list_ordered,
            page_number=page_number,
            page_size=page_size,
        )

    async def get_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all sessions for a user."""
        return await asyncio.to_thread(self._inner.get_sessions, user_id)


class _AsyncGraphNodeNamespace:
    def __init__(self, graph: _AsyncGraphClient) -> None:
        self._g = graph

    async def get(self, uuid: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._g._sync_graph.node.get, uuid)

    async def get_by_user_id(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._g._sync_graph.node.get_by_user_id, user_id, limit)


class _AsyncGraphEdgeNamespace:
    def __init__(self, graph: _AsyncGraphClient) -> None:
        self._g = graph

    async def get(self, uuid: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._g._sync_graph.edge.get, uuid)


class _AsyncGraphEpisodeNamespace:
    def __init__(self, graph: _AsyncGraphClient) -> None:
        self._g = graph

    async def get(self, uuid: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._g._sync_graph.episode.get, uuid)


class _AsyncGraphCommunityNamespace:
    def __init__(self, graph: _AsyncGraphClient) -> None:
        self._g = graph

    async def build(
        self,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._g._sync_graph.community.build, user_id, group_id)

    async def list(
        self,
        user_id: str | None = None,
        group_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._g._sync_graph.community.list, user_id, group_id, limit)

    async def get(
        self,
        uuid: str,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._g._sync_graph.community.get, uuid, user_id, group_id)

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        group_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._g._sync_graph.community.search, query, user_id, group_id, limit)


class _AsyncGraphClient:
    """Async mirror of :class:`_GraphClient` — delegates via asyncio.to_thread."""

    def __init__(self, async_zep: AsyncZep) -> None:
        self._sync_graph = _GraphClient(async_zep._sync)
        self.node = _AsyncGraphNodeNamespace(self)
        self.edge = _AsyncGraphEdgeNamespace(self)
        self.episode = _AsyncGraphEpisodeNamespace(self)
        self.community = _AsyncGraphCommunityNamespace(self)

    async def add(self, data: str, type: str = "text", **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync_graph.add, data, type, **kwargs)

    async def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync_graph.search, query, **kwargs)

    async def add_triplet(
        self,
        source_node_uuid: str,
        target_node_uuid: str,
        edge: str,
        workspace_id: str | None = None,
        fact: str | None = None,
        rating: float | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a triplet to the knowledge graph (async)."""
        return await asyncio.to_thread(
            self._sync_graph.add_triplet,
            source_node_uuid,
            target_node_uuid,
            edge,
            workspace_id=workspace_id,
            fact=fact,
            rating=rating,
            user_id=user_id,
            group_id=group_id,
        )


# ---------------------------------------------------------------------------
# AsyncZep — async client with .memory / .user (zep-python v2.0.2+)
# ---------------------------------------------------------------------------


class AsyncZep(AsyncZepClient):
    """Async Zep-compatible client with ``.memory`` and ``.user`` sub-clients.

    Usage::

        from spacetime_memory.sdks.zep import AsyncZep

        client = AsyncZep(host=\"127.0.0.1\", port=3001)

        async with client:
            await client.memory.add(session_id=\"s1\", messages=[...])
            mem = await client.memory.get(session_id=\"s1\")
            user = await client.user.add(email=\"a@b.com\")

    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        config: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> None:
        """Initialize the API resource wrapper."""
        super().__init__(host=host, port=port, config=config, token=token)
        self.memory = _AsyncMemoryProxy(self)
        self.user = _AsyncUserProxy(self)
        self.graph = _AsyncGraphClient(self)
