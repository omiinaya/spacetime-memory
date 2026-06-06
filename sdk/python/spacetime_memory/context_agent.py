"""Context agent: query the memory store and return a context-grounded answer.

Uses the SpacetimeDB ``generate_context_pack`` and ``get_delta`` reducers
to produce a scored, structured context pack for any query, then optionally
sends it to an LLM for a synthesised answer.

Example::

    from spacetime_memory import Client
    from spacetime_memory.context_agent import ContextAgent

    agent = ContextAgent(client)
    answer = agent.ask("What do we know about X?", workspace_id="...")
    print(answer)
"""

from __future__ import annotations

import json
from typing import Any


class ContextAgent:
    """Query a workspace and return structured context.

    This is a stateless agent: each call to ``ask()`` runs the full
    context-pack pipeline.  For incremental queries (avoiding re-fetching
    unchanged context), pass ``previous_pack_id`` to get a delta.
    """

    def __init__(self, client: Any):
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(
        self,
        query: str,
        workspace_id: str,
        token_budget: int = 4096,
        previous_pack_id: str = "",
    ) -> dict[str, Any]:
        """Run the context pipeline and return the result.

        Returns a dict with:
          - pack: the ``context_pack`` row
          - entries: list of ``context_entry`` rows
          - delta: (if previous_pack_id provided) list of ``context_delta`` rows
        """
        # 1. Generate the context pack
        self._client._call("generate_context_pack", [
            workspace_id, query, token_budget, "context_agent", previous_pack_id,
        ])

        # 2. Read the pack
        packs = self._client._sql(
            "SELECT * FROM context_pack WHERE "
            f"workspace_id = '{_esc(workspace_id)}' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if not packs:
            return {"error": "No context pack generated"}

        pack = packs[0]
        pack_id = pack.get("id", "")

        # 3. Read entries
        entries = self._client._sql(
            "SELECT * FROM context_entry WHERE "
            f"pack_id = '{_esc(pack_id)}' "
            "ORDER BY rank ASC"
        )

        result: dict[str, Any] = {
            "pack": pack,
            "entries": entries,
        }

        # 4. If delta was requested, compute it
        if previous_pack_id:
            self._client._call("get_delta", [previous_pack_id])
            result["delta"] = self._client._sql(
                "SELECT * FROM context_delta WHERE "
                f"previous_pack_id = '{_esc(previous_pack_id)}' "
                "ORDER BY rank ASC"
            )

        return result

    def format_context(self, entries: list[dict[str, Any]]) -> str:
        """Format context entries into a text block for an LLM prompt."""
        lines = []
        for i, entry in enumerate(entries, 1):
            content = entry.get("content", entry.get("memory_content", ""))
            score = entry.get("score", entry.get("rank", 0))
            lines.append(f"[{i}] (score={score:.3f}) {content[:500]}")
        return "\n\n".join(lines)


# ── Helper ──────────────────────────────────────────────────────────


def _esc(val: str) -> str:
    return val.replace("'", "''")
