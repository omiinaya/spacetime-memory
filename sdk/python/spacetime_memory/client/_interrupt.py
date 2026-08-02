"""Interrupt/Resume Protocol mixin — LangGraph-parity pause/resume for agent sessions.

Built on top of the existing session + agent_step tables (no new tables).
State machine states are tracked via step types ("interrupt", "resume") and
session metadata.

States:
    running ──interrupt_session()──▸ interrupted ──resume_session()──▸ running
"""
from __future__ import annotations

import json
from typing import Any

from ._base import _tracing_span


class InterruptMixin:
    """Spacetime-Memory interrupt/resume mixin.

    Provides LangGraph-parity ``interrupt_session``, ``resume_session``, and
    ``get_session_state`` — all backed by the existing ``session`` and
    ``agent_step`` tables (no new tables).

    Inherits from ``ClientBase`` for connection infrastructure.
    """

    # ── interrupt_session ─────────────────────────────────────────────────

    def interrupt_session(
        self,
        workspace_id: str,
        session_id: str,
        reason: str,
        target_step_id: str = "",
    ) -> dict[str, Any]:
        """Pause an agent session, recording a formal interrupt point.

        Writes an ``agent_step`` with ``step_type="interrupt"`` and updates
        the session's metadata with the interrupt state.

        Args:
            workspace_id: The workspace containing the session.
            session_id: The session to interrupt.
            reason: Human-readable reason (e.g. "awaiting user input",
                "tool timeout", "max steps reached").
            target_step_id: Optional step ID where execution should resume.
                Pass ``""`` if unknown.

        Returns:
            Reducer status dict.
        """
        with _tracing_span(
            "interrupt_session",
            workspace_id=workspace_id,
            session_id=session_id,
            reason=reason,
        ):
            return self._call(
                "interrupt_session",
                [workspace_id, session_id, reason, target_step_id],
            )

    # ── resume_session ───────────────────────────────────────────────────

    def resume_session(
        self,
        workspace_id: str,
        session_id: str,
        from_step_id: str = "",
    ) -> dict[str, Any]:
        """Resume a previously interrupted session.

        Finds the interrupt step (by ID or most recent), writes a
        ``step_type="resume"`` marker, and restores the session to
        ``running`` state.

        Args:
            workspace_id: The workspace containing the session.
            session_id: The session to resume.
            from_step_id: The interrupt step ID to resume from. If ``""``,
                uses the most recent interrupt step.

        Returns:
            Reducer status dict.
        """
        with _tracing_span(
            "resume_session",
            workspace_id=workspace_id,
            session_id=session_id,
        ):
            return self._call(
                "resume_session",
                [workspace_id, session_id, from_step_id],
            )

    # ── get_session_state ────────────────────────────────────────────────

    def get_session_state(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Get the current state machine status of a session.

        Reads session metadata and the most recent significant steps to
        determine the session's interrupt state.

        Results are written to ``session_step_result`` with
        ``query_hash="state:<session_id>"``, then read back and returned as
        a dict.

        Args:
            session_id: The session to query.

        Returns:
            A dict with keys ``session_id``, ``workspace_id``, ``state``,
            ``total_steps``, ``interrupt_reason``, ``interrupt_step_id``,
            ``last_resume_step_id``, ``updated_at`` — or ``None`` if the
            reducer failed.
        """
        with _tracing_span(
            "get_session_state",
            session_id=session_id,
        ):
            try:
                result = self._call("get_session_state", [session_id])
            except RuntimeError:
                return None
            if result.get("status") != "ok":
                return None

            query_hash = f"state:{session_id}"
            rows = self._query(
                "session_step_result",
                filter_dict={"query_hash": query_hash},
            )
            if not rows:
                return None

            # Parse the info JSON from the most recent result
            rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
            content = rows[0].get("content", "{}")
            try:
                return json.loads(content) if content else None
            except (json.JSONDecodeError, TypeError):
                return None

    # ── list_interrupted_sessions ────────────────────────────────────────

    def list_interrupted_sessions(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List all sessions in the ``interrupted`` state within a workspace.

        Args:
            workspace_id: The workspace to search.

        Returns:
            A list of session dicts (with state info embedded) that are
            currently interrupted. Sorted by ``updated_at`` descending.
        """
        sessions = self._query("session", workspace_id=workspace_id)
        interrupted: list[dict[str, Any]] = []
        for sess in sessions:
            try:
                meta = json.loads(sess.get("metadata", "{}"))
            except (json.JSONDecodeError, TypeError):
                meta = {}
            if meta.get("interrupt_state") == "interrupted":
                sess["_interrupt_reason"] = meta.get("interrupt_reason", "")
                sess["_interrupt_step_id"] = meta.get("interrupt_step_id", "")
                sess["_interrupt_target_step"] = meta.get(
                    "interrupt_target_step", ""
                )
                interrupted.append(sess)

        interrupted.sort(
            key=lambda s: s.get("updated_at", 0), reverse=True
        )
        return interrupted
