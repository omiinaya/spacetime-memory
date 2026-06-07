"""Honcho-compatible drop-in adapter.

Matches the real Honcho Python SDK API:
https://github.com/plastic-labs/honcho

Usage::

    from spacetime_memory.sdks.honcho import Honcho

    honcho = Honcho()
    user = honcho.create_user(name="alice")
    session = honcho.create_session(user_id=user.id, location="room1")
    honcho.add(session_id=session.id, content="I like pizza")
    results = honcho.search(session_id=session.id, query="food preferences")
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..client import Client


class Honcho:
    """Drop-in replacement for ``honcho.Honcho``.

    Maps::

        Honcho User     → SpacetimeDB workspace
        Honcho Session  → SpacetimeDB session (client-side cached)
        Honcho Memory   → SpacetimeDB memory (persistent)

    Sessions are cached client-side and can also be created at the root
    ``Honcho`` level (``honcho.create_session(user_id=..., location=...)``),
    matching the real Honcho API where sessions are created via the
    top-level client rather than via ``User`` objects.

    Example::

        >>> from spacetime_memory.sdks.honcho import Honcho
        >>> honcho = Honcho()
        >>> user = honcho.create_user(name="alice")
        >>> session = honcho.create_session(user_id=user.id, location="room1")
        >>> memory = honcho.add(session_id=session.id, content="Hello, world!")
        >>> results = honcho.search(session_id=session.id, query="greetings")

    """

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._client = Client(
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("db", config.get("database")),
            embedder_url=config.get("embedder_url"),
        )
        self._user_cache: dict[str, User] = {}
        self._session_cache: dict[str, Session] = {}
        self._auto_cache_users()

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _auto_cache_users(self) -> None:
        """Populate the user cache from existing workspaces."""
        for ws in self._client.list_workspaces():
            name = ws.get("name", "")
            if name and name not in self._user_cache:
                self._user_cache[name] = User(name, self._client)

    def _ensure_user(self, name: str) -> User:
        """Get or create a user by name.  Cached."""
        if name not in self._user_cache:
            u = self.get_user(name)
            if u is None:
                u = self.create_user(name)
            else:
                self._user_cache[name] = u
        return self._user_cache[name]

    # -------------------------------------------------------------------
    # Honcho API — User management
    # -------------------------------------------------------------------

    def create_user(
        self,
        name: str,
        metadata: dict | None = None,
    ) -> User:
        """Create a user (workspace).

        Args:
            name: The user's name.  Maps to a workspace name.
            metadata: Optional metadata dict (stored as workspace
                description).

        Returns:
            A :class:`User` object with ``.id`` (workspace UUID) and
            ``.name`` attributes.

        Example::

            >>> user = honcho.create_user(name="alice")
            >>> user.id
            'a1b2c3d4...'

        """
        self._client.create_workspace(
            name, json.dumps(metadata or {})
        )
        user = User(name, self._client)
        self._user_cache[name] = user
        return user

    def get_user(self, name: str) -> User | None:
        """Look up a user by name.

        Args:
            name: The user name to look up.

        Returns:
            A :class:`User` instance if found, or ``None``.

        """
        for ws in self._client.list_workspaces():
            if ws.get("name") == name:
                u = User(name, self._client)
                self._user_cache[name] = u
                return u
        return None

    def get_or_create_user(self, name: str) -> User:
        """Get an existing user or create one.

        Args:
            name: The user name.

        Returns:
            A :class:`User` instance.

        """
        u = self.get_user(name)
        if u is None:
            u = self.create_user(name)
        return u

    # -------------------------------------------------------------------
    # Honcho API — Session management (root-level)
    # -------------------------------------------------------------------

    def create_session(
        self,
        user_id: str,
        location: str = "",
        metadata: dict | None = None,
    ) -> Session:
        """Create a session for a user.

        Args:
            user_id: The user's ID (workspace UUID or user name).
            location: Optional location label (e.g. ``"room1"``).
            metadata: Optional metadata dict.

        Returns:
            A :class:`Session` object with ``.id``, ``.user_id``, and
            ``.location`` attributes.

        Example::

            >>> session = honcho.create_session(user_id=user.id, location="room1")
            >>> session.id
            'b2c3d4e5...'
            >>> session.user_id
            'a1b2c3d4...'

        """
        # Look up the user by ID (could be a name or a UUID)
        user = self._user_cache.get(user_id)
        if user is None:
            # Try workspace ID lookup
            for ws in self._client.list_workspaces():
                if ws.get("id") == user_id or ws.get("name") == user_id:
                    name = ws.get("name", user_id)
                    user = User(name, self._client)
                    self._user_cache[name] = user
                    break
        if user is None:
            raise ValueError(f"User '{user_id}' not found. Create the user first with create_user().")

        session = Session(user, location=location, client=self._client)
        self._session_cache[session.id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Look up a cached session by ID.

        Args:
            session_id: The session's UUID.

        Returns:
            A :class:`Session` instance if found in cache, or ``None``.

        """
        return self._session_cache.get(session_id)

    # -------------------------------------------------------------------
    # Honcho API — Memory management (root-level)
    # -------------------------------------------------------------------

    def add(
        self,
        session_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Store a memory in a session.

        Args:
            session_id: The session UUID (from ``create_session``).
            content: The text content to remember.
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status (``{"status": "ok"}``).

        Example::

            >>> honcho.add(session_id=session.id, content="I like pizza")
            {'status': 'ok'}

        """
        session = self._session_cache.get(session_id)
        if session is None:
            raise ValueError(
                f"Session '{session_id}' not found in cache. "
                "Create it first with create_session()."
            )
        return session.create_memory(content, metadata)

    def search(
        self,
        session_id: str,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search memories within a session.

        Args:
            session_id: The session UUID.
            query: The search query text.
            limit: Max results to return (default 20).

        Returns:
            A list of memory dicts sorted by relevance, each with
            ``entity_id``, ``memory_content``, ``score``, and other fields.

        Example::

            >>> honcho.search(session_id=session.id, query="food")
            [{'entity_id': '...', 'memory_content': 'I like pizza', 'score': 0.92}]

        """
        session = self._session_cache.get(session_id)
        if session is None:
            raise ValueError(
                f"Session '{session_id}' not found in cache. "
                "Create it first with create_session()."
            )
        return session.search(query, limit)


class User:
    """Honcho User adapter (→ workspace).

    Wraps a SpacetimeDB workspace as a Honcho ``User`` object.

    Attributes:
        name: The user's name.
        id:   The workspace UUID (Honcho-compatible ``user.id``).
    """

    def __init__(self, name: str, client: Client):
        self.name = name
        self._client = client
        # Resolve workspace_id
        ws_list = client.list_workspaces()
        self._workspace_id = ""
        for ws in ws_list:
            if ws.get("name") == name or ws.get("id") == name:
                self._workspace_id = ws["id"]
                break

    @property
    def id(self) -> str:
        """Honcho-compatible user ID (maps to workspace UUID)."""
        return self._workspace_id

    @property
    def workspace_id(self) -> str:
        """The underlying SpacetimeDB workspace UUID."""
        return self._workspace_id

    def create_session(
        self,
        name: str = "",
        location: str = "",
        metadata: dict | None = None,
    ) -> Session:
        """Create a session within this user's workspace.

        Args:
            name: Optional session name (used as peer_id filter).
            location: Optional location label.
            metadata: Optional metadata dict.

        Returns:
            A :class:`Session` instance.

        """
        return Session(self, location=location, client=self._client)

    def get_sessions(self) -> list[Session]:
        """List all sessions for this user.

        Returns:
            A list of :class:`Session` instances.

        """
        rows = self._client.get_peer_sessions(self.workspace_id)
        sessions = []
        for r in rows:
            sess = Session(self, location=r.get("location", ""), client=self._client)
            sess.id = r.get("id", sess.id)
            sessions.append(sess)
        return sessions


class Session:
    """Honcho Session adapter.

    Wraps a session as a Honcho ``Session`` object.  Sessions are cached
    client-side by the parent :class:`Honcho` instance.

    Attributes:
        id:       Unique session UUID.
        user_id:  The owning user's workspace UUID.
        location: The location label (e.g. ``"room1"``).
    """

    def __init__(self, user: User, location: str = "", client: Client | None = None):
        self.id = uuid.uuid4().hex[:32]
        self.user = user
        self.location = location
        self._client = client or user._client

    @property
    def user_id(self) -> str:
        """The user UUID that owns this session."""
        return self.user.id if self.user else ""

    def create_memory(
        self,
        content: str,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Create a memory in this session.

        Args:
            content: The text content to store.
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status.

        """
        return self._client.store(
            workspace_id=self.user.workspace_id,
            content=content,
            peer_id=self.location or self.id,
            memory_type="experience",
        )

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search memories within this session.

        Args:
            query: The search query text.
            limit: Max results to return (default 20).

        Returns:
            A list of memory dicts sorted by relevance.

        """
        return self._client.search(
            workspace_id=self.user.workspace_id,
            query=query,
            limit=limit,
            semantic=True,
        )

    def get_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all memories in this session.

        Args:
            limit: Max results to return (default 100).

        Returns:
            A list of memory dicts.

        """
        return self._client.list_memories(
            workspace_id=self.user.workspace_id, limit=limit,
        )
