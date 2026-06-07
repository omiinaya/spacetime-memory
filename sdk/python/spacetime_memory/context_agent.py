"""Context agent: query the memory store and return a context-grounded answer.

Uses the SpacetimeDB ``generate_context_pack`` and ``get_delta`` reducers
to produce a scored, structured context pack for any query, then optionally
sends it to an LLM for a synthesised answer.

LLM integration:
  - Set ``OPENAI_API_KEY`` env var to enable LLM calls
  - Set ``OPENAI_BASE_URL`` to use a different endpoint (default: OpenAI)
  - Set ``LLM_MODEL`` to override model (default: gpt-4o-mini)

Example::

    from spacetime_memory import Client
    from spacetime_memory.context_agent import ContextAgent

    agent = ContextAgent(client)
    answer = agent.ask("What do we know about X?", workspace_id="...")
    print(answer)
"""

from __future__ import annotations

import json
import os
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

        # 5. Optionally synthesize an LLM answer
        llm_answer = self._call_llm(query, entries, pack)
        if llm_answer:
            result["llm_answer"] = llm_answer

        return result

    def _call_llm(
        self,
        query: str,
        entries: list[dict[str, Any]],
        pack: dict[str, Any] | None = None,
    ) -> str | None:
        """Call an LLM with the context entries to produce a grounded answer.

        Requires OPENAI_API_KEY env var.  Falls back to None if not set.
        """
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

        context_text = self.format_context(entries)
        system_prompt = (
            "You are a memory-augmented AI assistant.  Answer the user's query "
            "based **only** on the context entries below.  If the context doesn't "
            "contain enough information, say so.  Cite the source entry numbers "
            "in brackets, e.g. [1][3]."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"## Query\n\n{query}\n\n## Context\n\n{context_text}"},
        ]

        try:
            import httpx
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            return f"[LLM call failed: {exc}]"

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
