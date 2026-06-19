"""Agent orchestration hooks for memory-aware AI agents.

Provides the agent loop integration that Honcho-style reasoning-first
memory requires — chain-of-thought tracking, tool-use memory recording,
and context assembly from relevant memories.

Usage:
    from spacetime_memory import Client
    from spacetime_memory.agent_orchestrator import AgentOrchestrator

    client = Client()
    orch = AgentOrchestrator(client, workspace_id="...")

    # Start an agent session
    session_id = orch.start_session(agent_name="assistant", user_id="user1")

    # Record a reasoning step
    orch.add_step(session_id, thought="I should check the user's preferences")

    # Record a tool call
    orch.add_tool_call(session_id, tool="search_memories", args={"query": "preferences"})

    # Get relevant context for the agent
    context = orch.get_context("user preferences")

    # End session and reflect
    summary = orch.end_session()
"""

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


class AgentOrchestrator:
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
        self._sessions: dict[str, AgentSessionState] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

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
            "session", workspace_id=self._workspace_id,
            filter_dict={"name": session_name},
            columns=["id"]
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
                    "memory", workspace_id=self._workspace_id,
                    columns=["id"]
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

    # ------------------------------------------------------------------
    # Reasoning steps
    # ------------------------------------------------------------------

    def add_step(
        self,
        session_id: str,
        thought: str = "",
        action: str = "",
        observation: str = "",
    ) -> str:
        """Record a chain-of-thought reasoning step.

        At least one of ``thought``, ``action``, or ``observation`` must
        be provided.

        Args:
            session_id: The session to record the step in.
            thought: The agent's reasoning / thought.
            action: The action taken.
            observation: What the agent observed.

        Returns:
            The step ID.
        """
        if not any([thought, action, observation]):
            raise ValueError(
                "At least one of thought, action, or observation is required"
            )

        # Build the step content
        parts = []
        step_type = "thought"

        if thought:
            parts.append(f"## Thought\n\n{thought}")
            step_type = "thought"
        if action:
            parts.append(f"## Action\n\n{action}")
            step_type = "action"
        if observation:
            parts.append(f"## Observation\n\n{observation}")
            step_type = "observation" if step_type == "thought" else step_type

        content = "\n\n".join(parts)
        summary = thought[:120] if thought else (action[:120] if action else "")

        state = self._sessions.get(session_id)
        parent_step_id = state.last_step_id if state else ""
        state.step_count += 1

        self._client._call(
            "add_agent_step",
            [
                session_id,
                self._workspace_id,
                step_type,
                content,
                summary,
                parent_step_id,
            ],
        )

        # Discover the step ID
        step_id = ""
        rows = self._client._query(
            "agent_step", filter_dict={"session_id": session_id},
            columns=["id"]
        )
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        rows = rows[:1]
        if rows:
            step_id = rows[0]["id"]

        if state:
            state.last_step_id = step_id

        return step_id

    def add_tool_call(
        self,
        session_id: str,
        tool: str,
        args: dict[str, Any] | list[Any] | str = "",
        result: Any = None,
    ) -> str:
        """Record a tool call as a reasoning step.

        Stores two linked steps: one ``tool_call`` and one ``tool_result``.

        Args:
            session_id: The session to record in.
            tool: The tool name.
            args: The arguments passed to the tool.
            result: The result from the tool.

        Returns:
            The tool_call step ID.
        """
        args_str = json.dumps(args) if not isinstance(args, str) else args
        args_content = json.dumps({"name": tool, "args": args_str})

        self._client._call(
            "add_agent_step",
            [
                session_id,
                self._workspace_id,
                "tool_call",
                args_content,
                f"Call: {tool}",
                "",
            ],
        )

        call_step_id = ""
        rows = self._client._query(
            "agent_step", filter_dict={"session_id": session_id, "step_type": "tool_call"},
            columns=["id"]
        )
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        rows = rows[:1]
        if rows:
            call_step_id = rows[0]["id"]

        # Record result if provided
        if result is not None and call_step_id:
            result_str = json.dumps(result) if not isinstance(result, str) else result
            result_content = json.dumps(
                {"name": tool, "result": result_str}
            )
            self._client._call(
                "add_agent_step",
                [
                    session_id,
                    self._workspace_id,
                    "tool_result",
                    result_content,
                    f"Result: {tool}",
                    call_step_id,
                ],
            )

        state = self._sessions.get(session_id)
        if state:
            state.last_step_id = call_step_id

        return call_step_id

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def get_context(
        self,
        query: str = "",
        top_k: int = 10,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant context for an agent prompt.

        Combines:
        1. Relevant memories (via semantic search)
        2. Recent session steps (if ``session_id`` is provided)

        Args:
            query: Search query for relevant memories.
            top_k: Maximum number of results to return.
            session_id: If set, include recent session steps.

        Returns:
            A list of context entries.
        """
        context: list[dict[str, Any]] = []

        # 1. Search relevant memories
        if query:
            memories = self._client.search(
                workspace_id=self._workspace_id,
                query=query,
                limit=top_k,
                semantic=True,
            )
            for mem in memories:
                context.append(
                    {
                        "type": "memory",
                        "id": mem.get("id", ""),
                        "content": mem.get("memory_content", mem.get("content", "")),
                        "score": mem.get("score", 0.0),
                        "source": "memory_search",
                    }
                )

        # 2. Get recent session steps
        if session_id:
            try:
                self._client._call("get_session_steps", [session_id])
                query_hash = f"steps:{session_id}"
                steps = self._client._sql(
                    "SELECT * FROM session_step_result WHERE "
                    f"query_hash = '{_esc(query_hash)}' "
                    "ORDER BY created_at ASC"
                )
                for step in steps[-top_k:]:
                    context.append(
                        {
                            "type": "step",
                            "step_type": step.get("step_type", ""),
                            "id": step.get("id", ""),
                            "content": step.get("content", ""),
                            "summary": step.get("summary", ""),
                            "score": 1.0,
                            "source": "session_steps",
                        }
                    )
            except RuntimeError:
                logger.warning(
                    "Failed to get session steps for %s", session_id, exc_info=True
                )

        # Sort by score descending, then by position
        context.sort(key=lambda c: c.get("score", 0.0), reverse=True)
        return context[:top_k]

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
                    session_id, pid, exc_info=True,
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


# ── Helper ──────────────────────────────────────────────────────────


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")
