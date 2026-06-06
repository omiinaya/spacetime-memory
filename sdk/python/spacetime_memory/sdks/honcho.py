"""Honcho-compatible drop-in adapter.

Usage::

    from spacetime_memory.sdks.honcho import Honcho

    honcho = Honcho()
    user = honcho.create_user(name="alice")
    session = user.create_session(name="chat-1")
    mem = session.create_memory(content="I like pizza")
    results = session.search("food preferences")
"""

from __future__ import annotations

import json
from typing import Any

from ..client import Client


class Honcho:
    """Drop-in replacement for ``honcho.Honcho``.

    maps:

    * Honcho ``User`` → spacetime-memory ``workspace``
    * Honcho ``Session`` → spacetime-memory ``session``
    * Honcho ``Memory`` → spacetime-memory ``memory``
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

    def create_user(
        self,
        name: str,
        metadata: dict | None = None,
    ) -> User:
        """Create a user (workspace)."""
        self._client.create_workspace(
            name, json.dumps(metadata or {})
        )
        return User(name, self._client)

    def get_user(self, name: str) -> User | None:
        """Look up a user by name."""
        for ws in self._client.list_workspaces():
            if ws.get("name") == name:
                return User(name, self._client)
        return None

    def get_or_create_user(self, name: str) -> User:
        """Get an existing user or create one."""
        u = self.get_user(name)
        if u is None:
            u = self.create_user(name)
        return u


class User:
    """Honcho User adapter (→ workspace)."""

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
    def workspace_id(self) -> str:
        return self._workspace_id

    def create_session(
        self,
        name: str,
        location: str = "",
        metadata: dict | None = None,
    ) -> Session:
        """Create a session within this user's workspace."""
        return Session(self, name, location, self._client)

    def get_sessions(self) -> list[Session]:
        """List all sessions."""
        rows = self._client.get_peer_sessions(self.workspace_id)
        return [
            Session(self, r.get("id", ""), r.get("location", ""), self._client)
            for r in rows
        ]


class Session:
    """Honcho Session adapter (→ SpacetimeDB session)."""

    def __init__(self, user: User, name: str, location: str, client: Client):
        self.user = user
        self.name = name
        self._client = client

    def create_memory(
        self,
        content: str,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Create a memory."""
        return self._client.store(
            workspace_id=self.user.workspace_id,
            content=content,
            peer_id=self.name,
            memory_type="experience",
        )

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search memories within this session."""
        return self._client.search(
            workspace_id=self.user.workspace_id,
            query=query,
            limit=limit,
            semantic=True,
        )

    def get_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all memories in this session."""
        return self._client.list_memories(
            workspace_id=self.user.workspace_id, limit=limit,
        )
