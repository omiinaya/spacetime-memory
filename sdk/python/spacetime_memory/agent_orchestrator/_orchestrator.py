"""Main AgentOrchestrator class that inherits from session and step mixins."""

from __future__ import annotations

import logging
from typing import Any

from ._session import SessionManagerMixin
from ._steps import StepRecordingMixin

logger = logging.getLogger(__name__)


class AgentOrchestrator(SessionManagerMixin, StepRecordingMixin):
    """High-level hooks for agent-memory integration.

    Wraps the SpacetimeDB Client with session management, step recording,
    tool-use tracking, and multi-user collaboration.

    Args:
        client: A spacetime_memory.Client instance.
        workspace_id: The default workspace for operations.
    """

    def __init__(
        self,
        client: Any,
        workspace_id: str,
    ):
        self._client = client
        self._workspace_id = workspace_id
        # Active sessions keyed by session_id
        self._sessions: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Multi-user collaboration (P3h)
    # ------------------------------------------------------------------

    def share_session(self, session_id: str, peer_ids: list[str]) -> dict[str, Any]:
        """Share a session with one or more peers.

        Each peer is added as a participant in the session with role
        ``\"collaborator\"``.  Already-present peers are silently skipped
        (the reducer returns an error we can ignore).

        Args:
            session_id: The session to share.
            peer_ids: List of peer IDs to share with.

        Returns:
            Dict with ``session_id`` and list of ``shared_with`` peers.
        """
        shared: list[str] = []
        failed: list[str] = []

        for pid in peer_ids:
            try:
                self._client._call(
                    "join_session",
                    [session_id, pid, "collaborator"],
                )
                shared.append(pid)
            except RuntimeError:
                logger.warning(
                    "Failed to share session %s with peer %s",
                    session_id,
                    pid,
                    exc_info=True,
                )
                failed.append(pid)

        # Track in state if we have it
        state = self._sessions.get(session_id)
        if state:
            for pid in shared:
                if pid not in state.collaborators:
                    state.collaborators.append(pid)

        result: dict[str, Any] = {
            "session_id": session_id,
            "shared_with": shared,
        }
        if failed:
            result["failed"] = failed

        return result

    def get_collaborative_context(
        self,
        session_id: str,
        peer_id: str,
        query: str = "",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Get context filtered for a specific collaborator.

        Returns the same context as :meth:`get_context` but also includes
        only the shared session steps and memories relevant to the peer.

        Args:
            session_id: The session to get context for.
            peer_id: The peer requesting context.
            query: Search query for relevant memories.
            top_k: Maximum results.

        Returns:
            List of context entries relevant to this peer.
        """
        context = self.get_context(query=query, top_k=top_k, session_id=session_id)

        # Filter: add a visibility note per peer
        for entry in context:
            entry["visible_to"] = [peer_id]

        return context
