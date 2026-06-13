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
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


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
            workspace_id, query, token_budget, "", previous_pack_id,
        ])

        # 2. Read the pack
        packs = self._client._query(
            "context_pack", workspace_id=workspace_id
        )
        # Take most recent (server returns unsorted)
        packs.sort(key=lambda p: p.get("created_at", 0), reverse=True)
        packs = packs[:1]
        if not packs:
            return {"error": "No context pack generated"}

        pack = packs[0]
        pack_id = pack.get("id", "")

        # 3. Read entries from the pack's serialized JSON
        try:
            pack_json = json.loads(pack.get("pack_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            pack_json = []

        if isinstance(pack_json, list):
            entries = pack_json
        elif isinstance(pack_json, dict):
            entries = pack_json.get("entries", pack_json.get("memories", []))
        else:
            entries = []

        entries.sort(key=lambda e: e.get("rank", e.get("score", 0)), reverse=True)

        result: dict[str, Any] = {
            "pack": pack,
            "entries": entries,
        }

        # 4. If delta was requested, compute it
        if previous_pack_id:
            self._client._call("get_delta", [previous_pack_id])
            result["delta"] = self._client._query(
                "context_delta", filter_dict={"previous_pack_id": previous_pack_id}
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
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_MASTER_KEY", "")
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

    def synthesize(
        self,
        query: str,
        workspace_id: str,
        token_budget: int = 4096,
    ) -> dict[str, Any]:
        """Synthesize an answer with gap analysis — GBrain-style.

        Runs the context pipeline, then calls the LLM with a structured prompt
        that asks for both a grounded answer AND identification of knowledge gaps.

        Returns a dict with:
          - answer: synthesised answer text
          - gaps: list of identified knowledge gaps
          - sources: list of source entry indices used
          - confidence: float 0.0-1.0
          - pack: the context_pack row
        """
        # Run context pipeline (same as ask())
        self._client._call("generate_context_pack", [
            workspace_id, query, token_budget, "", "",
        ])
        packs = self._client._query("context_pack", workspace_id=workspace_id)
        packs.sort(key=lambda p: p.get("created_at", 0), reverse=True)
        packs = packs[:1]
        if not packs:
            return {"error": "No context pack generated", "answer": None, "gaps": []}

        pack = packs[0]
        entries: list[dict[str, Any]] = []
        try:
            pack_json_data = json.loads(pack.get("pack_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            pack_json_data = []
        if isinstance(pack_json_data, list):
            entries = pack_json_data
        elif isinstance(pack_json_data, dict):
            entries = pack_json_data.get("entries", pack_json_data.get("memories", []))
        entries.sort(key=lambda e: e.get("rank", e.get("score", 0)), reverse=True)

        result: dict[str, Any] = {"pack": pack}

        # LLM call with gap analysis prompt
        llm_result = self._call_llm_with_gaps(query, entries, pack)
        if llm_result:
            result.update(llm_result)
        else:
            result["answer"] = None
            result["gaps"] = []
            result["sources"] = []
            result["confidence"] = 0.0

        return result

    def _call_llm_with_gaps(
        self,
        query: str,
        entries: list[dict[str, Any]],
        pack: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Call LLM with a structured gap-analysis prompt.

        Returns parsed JSON dict with answer, gaps, sources, confidence, or None.
        """
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_MASTER_KEY", "")
        if not api_key:
            return None

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        context_text = self.format_context(entries)

        system_prompt = (
            "You are a knowledge synthesis engine with gap analysis and citation tracking. "
            "Answer the query based only on the context entries below. "
            "For every factual claim in your answer, cite the source entry number in brackets [1][3]. "
            "Then identify what the knowledge base does NOT contain — "
            "specific questions, entities, or topics that are missing. "
            "Return ONLY valid JSON with no markdown, no explanation, per this schema:\n"
            '{"answer": "synthesised answer with [citations]", '
            '"citations": [{"source": 1, "text": "quoted excerpt", "claim": "what claim this supports"}], '
            '"gaps": ["gap 1", "gap 2"], '
            '"sources": [1, 3], "confidence": 0.85}'
        )

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
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": (
                            f"## Query\n{query}\n\n"
                            f"## Context\n{context_text}\n\n"
                            "Synthesize an answer and identify what's missing. "
                            "Return JSON only."
                        )},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            import json as _json
            return _json.loads(content)
        except Exception as exc:
            logger.warning("LLM gap analysis call failed: %s", exc)
            return None

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
