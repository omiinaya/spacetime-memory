"""Session management mixin for AgentOrchestrator."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentSessionState:
    """In-memory state for an active agent session."""

    session_id: str
    agent_name: str
    user_id: str
    workspace_id: str
    context: dict[str, Any] = field(default_factory=dict)
    step_count: int = 0
    last_step_id: str = ""
    collaborators: list[str] = field(default_factory=list)


class SessionManagerMixin:
    """Session lifecycle management mixin.

    Provides start_session() and end_session() methods.
    Expects ``self._client`` and ``self._workspace_id`` to be set
    by the class that inherits this mixin.
    """

    def start_session(
        self,
        agent_name: str = "assistant",
        user_id: str = "user1",
        context: str | dict[str, Any] | None = None,
    ) -> str:
        """Start a new agent session.

        Creates a session in SpacetimeDB and maintains in-memory state
        for the orchestrator.

        Args:
            agent_name: Name/type of the agent.
            user_id: Identifier for the user.
            context: Optional context dict or JSON string.

        Returns:
            The new session ID.
        """
        metadata = {}
        if context:
            if isinstance(context, str):
                try:
                    metadata = json.loads(context)
                except json.JSONDecodeError:
                    metadata = {"context": context}
            else:
                metadata = context
        metadata["agent_name"] = agent_name
        metadata["user_id"] = user_id

        metadata_json = json.dumps(metadata)
        session_name = f"{agent_name}-{user_id}"

        self._client._call(
            "create_session",
            [self._workspace_id, session_name, metadata_json],
        )

        # Discover the session we just created via SQL
        rows = self._client._query(
            "session",
            workspace_id=self._workspace_id,
            filter_dict={"name": session_name},
            columns=["id"],
        )
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        rows = rows[:1]
        if not rows:
            # Fallback: generate a deterministic ID
            session_id = str(uuid.uuid4())
        else:
            session_id = rows[0]["id"]

        state = AgentSessionState(
            session_id=session_id,
            agent_name=agent_name,
            user_id=user_id,
            workspace_id=self._workspace_id,
        )
        self._sessions[session_id] = state
        return session_id

    def end_session(
        self,
        session_id: str | None = None,
        summary: str = "",
        create_summary_memory: bool = True,
    ) -> dict[str, Any]:
        """End an agent session and optionally create a summary memory.

        Args:
            session_id: Session to end (if None, ends the most recent).
            summary: Optional summary text to write to the session.
            create_summary_memory: If True, store the summary as a memory.

        Returns:
            Dict with ``session_id`` and optional ``memory_id``.
        """
        if session_id is None:
            if not self._sessions:
                return {"error": "No active sessions"}
            # End the most recently started
            session_id = list(self._sessions.keys())[-1]

        state = self._sessions.pop(session_id, None)
        if state is None:
            # Try to find it anyway
            state = AgentSessionState(
                session_id=session_id,
                agent_name="unknown",
                user_id="unknown",
                workspace_id=self._workspace_id,
            )

        # Update session summary if provided
        if summary:
            self._client._call("update_session_summary", [session_id, summary])

        memory_id = ""
        if create_summary_memory and summary:
            result = self._client.store(
                workspace_id=self._workspace_id,
                content=summary,
                summary=f"Session summary: {session_id[:16]}...",
                memory_type="experience",
                peer_id=state.user_id,
            )
            if result and result.get("status") == "ok":
                # Try to find the stored memory
                mems = self._client._query(
                    "memory", workspace_id=self._workspace_id, columns=["id"]
                )
                mems.sort(key=lambda m: m.get("created_at", 0), reverse=True)
                mems = mems[:1]
                if mems:
                    memory_id = mems[0]["id"]

        return {
            "session_id": session_id,
            "memory_id": memory_id,
            "summary": summary,
            "step_count": state.step_count,
        }


# ── Helper ──────────────────────────────────────────────────────────


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")
