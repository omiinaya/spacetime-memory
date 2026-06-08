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

from ..client import Client, _esc


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

        If a user with the same name already exists, returns the existing
        user instead of raising an error.

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
        # Check if user already exists first
        existing = self.get_user(name)
        if existing is not None:
            return existing

        try:
            self._client.create_workspace(
                name, json.dumps(metadata or {})
            )
        except RuntimeError as exc:
            err_msg = str(exc).lower()
            # If the error says "already exists", return the existing user
            if "already exists" in err_msg or "duplicate" in err_msg:
                existing = self.get_user(name)
                if existing is not None:
                    return existing
            # Re-raise with context if it's a different error
            raise RuntimeError(f"honcho.create_user('{name}') failed: {exc}") from exc

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
        try:
            for ws in self._client.list_workspaces():
                if ws.get("name") == name:
                    u = User(name, self._client)
                    self._user_cache[name] = u
                    return u
            return None
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"honcho.get_user('{name}') failed: {exc}") from exc

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
            try:
                for ws in self._client.list_workspaces():
                    if ws.get("id") == user_id or ws.get("name") == user_id:
                        name = ws.get("name", user_id)
                        user = User(name, self._client)
                        self._user_cache[name] = user
                        break
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"honcho.create_session(user_id='{user_id}') lookup failed: {exc}"
                ) from exc

        if user is None:
            raise ValueError(
                f"User '{user_id}' not found. Create the user first with create_user()."
            )

        session = Session(user, location=location, metadata=metadata, client=self._client)
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

    def get_or_create_session(
        self,
        user_id: str,
        location: str = "",
    ) -> Session:
        """Get an existing session for a user+location, or create one.

        Searches the session cache and the backend for a session matching
        the given user and location.  If none exists, creates a new one.

        Args:
            user_id: The user's ID (workspace UUID or user name).
            location: Optional location label (e.g. ``"room1"``).

        Returns:
            A :class:`Session` instance.

        Example::

            >>> session = honcho.get_or_create_session(user_id=user.id, location="room1")

        """
        # First check cache
        for sid, sess in self._session_cache.items():
            if sess.user_id == user_id and sess.location == location:
                return sess

        # Look up user to get workspace_id
        user = self._user_cache.get(user_id)
        if user is None:
            try:
                for ws in self._client.list_workspaces():
                    if ws.get("id") == user_id or ws.get("name") == user_id:
                        name = ws.get("name", user_id)
                        user = User(name, self._client)
                        self._user_cache[name] = user
                        break
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"honcho.get_or_create_session(user_id='{user_id}') lookup failed: {exc}"
                ) from exc

        if user is None:
            raise ValueError(
                f"User '{user_id}' not found. Create the user first with create_user()."
            )

        # Check backend for existing session with this user+location
        try:
            rows = self._client.get_peer_sessions(user.workspace_id)
            for r in rows:
                r_loc = r.get("location", "")
                if r_loc == location:
                    sess = Session(
                        user, location=location, client=self._client,
                    )
                    sess.id = r.get("id", sess.id)
                    self._session_cache[sess.id] = sess
                    return sess
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"honcho.get_or_create_session() backend lookup failed: {exc}"
            ) from exc

        # No existing session found — create one
        session = Session(user, location=location, client=self._client)
        self._session_cache[session.id] = session
        return session

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
        try:
            return session.create_memory(content, metadata)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"honcho.add(session_id='{session_id}') failed: {exc}"
            ) from exc

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
            Returns an empty list (not None) on empty results.

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
        try:
            results = session.search(query, limit)
            return results if results else []
        except RuntimeError:
            # Invalidate session cache on backend errors (stale session)
            if session_id in self._session_cache:
                del self._session_cache[session_id]
            raise
        except Exception as exc:
            # Invalidate session cache on unexpected errors
            if session_id in self._session_cache:
                del self._session_cache[session_id]
            raise RuntimeError(
                f"honcho.search(session_id='{session_id}') failed: {exc}"
            ) from exc


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
        return Session(self, location=location, metadata=metadata, client=self._client)

    def get_sessions(self) -> list[Session]:
        """List all sessions for this user.

        Returns:
            A list of :class:`Session` instances.

        """
        try:
            rows = self._client.get_peer_sessions(self.workspace_id)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"User.get_sessions() failed for user '{self.name}': {exc}"
            ) from exc
        sessions = []
        for r in rows:
            sess = Session(self, location=r.get("location", ""), client=self._client)
            sess.id = r.get("id", sess.id)
            sessions.append(sess)
        return sessions

    # -------------------------------------------------------------------
    # User metadata API (Honcho parity)
    # -------------------------------------------------------------------

    def set_metadata(self, metadata: dict) -> None:
        """Set metadata for this user (stored as workspace description).

        Args:
            metadata: A dictionary of metadata to store.
        """
        try:
            ws_id = self._workspace_id
            # Read current name from workspace
            ws_list = self._client.list_workspaces()
            current_name = self.name
            for ws in ws_list:
                if ws.get("id") == ws_id:
                    current_name = ws.get("name", self.name)
                    break
            self._client._call(
                "update_workspace",
                [ws_id, current_name, json.dumps(metadata)],
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"User.set_metadata() failed for '{self.name}': {exc}"
            ) from exc

    def get_metadata(self) -> dict:
        """Get metadata for this user.

        Returns:
            A dictionary of metadata, or an empty dict if none set.
        """
        try:
            ws_list = self._client.list_workspaces()
            for ws in ws_list:
                if ws.get("id") == self._workspace_id:
                    desc = ws.get("description", "{}")
                    if desc:
                        try:
                            return json.loads(desc) if isinstance(desc, str) else desc
                        except (json.JSONDecodeError, TypeError):
                            pass
                    return {}
            return {}
        except RuntimeError as exc:
            raise RuntimeError(
                f"User.get_metadata() failed for '{self.name}': {exc}"
            ) from exc


class Session:
    """Honcho Session adapter.

    Wraps a session as a Honcho ``Session`` object.  Sessions are cached
    client-side by the parent :class:`Honcho` instance.

    Attributes:
        id:       Unique session UUID.
        user_id:  The owning user's workspace UUID.
        location: The location label (e.g. ``"room1"``).
    """

    def __init__(self, user: User, location: str = "", metadata: dict | None = None, client: Client | None = None):
        self.id = uuid.uuid4().hex[:32]
        self.user = user
        self.location = location
        self._metadata = metadata or {}
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
        try:
            return self._client.store(
                workspace_id=self.user.workspace_id,
                content=content,
                peer_id=self.location or self.id,
                memory_type="experience",
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Session.create_memory() failed in session '{self.id}': {exc}"
            ) from exc

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
            A list of memory dicts sorted by relevance.  Empty list if
            no results.

        """
        try:
            results = self._client.search(
                workspace_id=self.user.workspace_id,
                query=query,
                limit=limit,
                semantic=True,
            )
            return results if results else []
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Session.search() failed in session '{self.id}': {exc}"
            ) from exc

    def get_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all memories in this session.

        Args:
            limit: Max results to return (default 100).

        Returns:
            A list of memory dicts.

        """
        try:
            return self._client.list_memories(
                workspace_id=self.user.workspace_id, limit=limit,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Session.get_memories() failed in session '{self.id}': {exc}"
            ) from exc

    # -------------------------------------------------------------------
    # Session metadata API (Honcho parity)
    # -------------------------------------------------------------------

    def get_metadata(self) -> dict:
        """Get metadata for this session.

        Returns the locally cached metadata dict.  Call :meth:`refresh` to
        re-fetch from the backend.

        Returns:
            A dictionary of metadata, or an empty dict if none set.
        """
        return self._metadata

    def set_metadata(self, metadata: dict) -> None:
        """Set metadata for this session (persisted as a memory record).

        Stores the metadata dict as a memory record with
        ``memory_type="session_metadata"`` and
        ``source_session_id`` set to this session's ID.

        Args:
            metadata: A dictionary of metadata to store.
        """
        try:
            self._client.store(
                workspace_id=self.user.workspace_id,
                content=json.dumps(metadata),
                memory_type="session_metadata",
                peer_id=self.location or self.id,
                source_session_id=self.id,
            )
            self._metadata = metadata
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Session.set_metadata() failed in session '{self.id}': {exc}"
            ) from exc

    def refresh(self) -> None:
        """Re-fetch session metadata from the backend.

        Queries the memory table for the most recent ``session_metadata``
        record tied to this session's ID and updates the local cache.
        """
        try:
            rows = self._client._sql(
                "SELECT content FROM memory WHERE "
                f"workspace_id = '{_esc(self.user.workspace_id)}' AND "
                f"source_session_id = '{_esc(self.id)}' AND "
                f"memory_type = 'session_metadata' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if rows:
                content = rows[0].get("content", "{}")
                try:
                    self._metadata = (
                        json.loads(content) if isinstance(content, str) else content
                    )
                except (json.JSONDecodeError, TypeError):
                    self._metadata = {}
            else:
                self._metadata = {}
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Session.refresh() failed in session '{self.id}': {exc}"
            ) from exc
