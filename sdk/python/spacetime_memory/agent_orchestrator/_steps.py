"""Step recording mixin for AgentOrchestrator."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StepRecordingMixin:
    """Step recording and context assembly mixin.

    Provides add_step(), add_tool_call(), and get_context() methods.
    Expects ``self._client``, ``self._workspace_id``, and ``self._sessions``
    to be set by the class that inherits this mixin.
    """

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
            raise ValueError("At least one of thought, action, or observation is required")

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
            "agent_step", filter_dict={"session_id": session_id}, columns=["id"]
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
            "agent_step",
            filter_dict={"session_id": session_id, "step_type": "tool_call"},
            columns=["id"],
        )
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        rows = rows[:1]
        if rows:
            call_step_id = rows[0]["id"]

        # Record result if provided
        if result is not None and call_step_id:
            result_str = json.dumps(result) if not isinstance(result, str) else result
            result_content = json.dumps({"name": tool, "result": result_str})
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
                steps = self._client._query("session_step_result", filter_dict={"query_hash": query_hash})
                steps.sort(key=lambda r: r.get("created_at", ""))
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
                logger.warning("Failed to get session steps for %s", session_id, exc_info=True)

        # Sort by score descending, then by position
        context.sort(key=lambda c: c.get("score", 0.0), reverse=True)
        return context[:top_k]
