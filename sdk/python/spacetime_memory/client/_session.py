"""Session and agent step management mixin."""
from __future__ import annotations

from typing import Any


class SessionMixin:
    """Spacetime-Memory session and agent step mixin.

    Provides Client methods related to sessions, session messages,
    reasoning steps, and peer session lookups.
    Inherits from ClientBase for connection infrastructure.
    """
    def get_peer_sessions(self, peer_id: str) -> list[dict[str, Any]]:
        """List sessions a peer has participated in."""
        # Query session_participant to find session IDs, then fetch each session
        parts = self._query("session_participant", filter_dict={"peer_id": peer_id})
        rows = []
        for sp in parts:
            sessions = self._query("session", filter_dict={"id": sp.get("session_id", "")})
            for s in sessions:
                s["role"] = sp.get("role", "")
                s["joined_at"] = sp.get("joined_at", 0)
                rows.append(s)
        rows.sort(key=lambda r: r.get("joined_at", 0), reverse=True)
        return rows

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve messages for a session."""
        rows = self._query("message", filter_dict={"session_id": session_id})
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def get_session_steps(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all reasoning steps for a session.

        Calls the ``get_session_steps`` reducer which writes to the
        ``session_step_result`` table, then queries that table.

        Args:
            session_id: The session to get steps for.

        Returns:
            A list of step dicts ordered by creation time, each with keys:
            query_hash, id, session_id, workspace_id, step_type, content,
            summary, parent_step_id, created_at.
        """
        self._call("get_session_steps", [session_id])
        query_hash = f"steps:{session_id}"
        rows = self._query("session_step_result", filter_dict={"query_hash": query_hash})
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def add_agent_step(
        self,
        session_id: str,
        workspace_id: str,
        step_type: str,
        content: str,
        summary: str = "",
        parent_step_id: str = "",
    ) -> dict[str, Any]:
        """Record an agent reasoning step (thought, action, tool_call, etc.).

        Calls the ``add_agent_step`` reducer to append a reasoning step to a
        session's chain of thought.

        Args:
            session_id: The session to attach the step to.
            workspace_id: The workspace containing the session.
            step_type: One of ``"thought"``, ``"action"``, ``"observation"``,
                ``"tool_call"``, or ``"tool_result"``.
            content: The step content (text or JSON).
            summary: Optional short summary of the step.
            parent_step_id: Optional parent step ID for chain-of-thought
                linking.

        Returns:
            The reducer status dict. On success the calling tool can extract
            the created step id from the ``"id"`` key.
        """
        return self._call(
            "add_agent_step",
            [session_id, workspace_id, step_type, content, summary, parent_step_id],
        )

    def create_session(
        self,
        workspace_id: str,
        session_id: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """Create a new session.

        Args:
            workspace_id: The workspace to create the session in.
            session_id: Optional session name/ID (auto-generated if empty).
            metadata: Optional metadata dict.

        Returns:
            The reducer status dict.
        """
        import json
        metadata_json = json.dumps(metadata or {})
        return self._call(
            "create_session",
            [workspace_id, session_id, metadata_json],
        )

    def join_session(self, session_id: str) -> dict:
        """Join an existing session.

        Args:
            session_id: The session ID to join.

        Returns:
            The reducer status dict.
        """
        return self._call("join_session", [session_id])

    def leave_session(self, session_id: str) -> dict:
        """Leave a session.

        Args:
            session_id: The session ID to leave.

        Returns:
            The reducer status dict.
        """
        return self._call("leave_session", [session_id])

    def send_message(
        self,
        session_id: str,
        sender_id: str,
        content: str,
        content_type: str = "text",
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Call send_message reducer to send a message in a session."""
        return self._call("send_message", [session_id, sender_id, content, content_type, metadata_json])

    def delete_message(self, message_id: str) -> dict[str, Any]:
        """Call delete_message reducer to delete a message."""
        return self._call("delete_message", [message_id])

    def delete_session_steps(self, session_id: str) -> dict[str, Any]:
        """Call delete_session_steps reducer to delete all agent steps for a session."""
        return self._call("delete_session_steps", [session_id])
