"""Shared LLM client for optional LLM-powered adapter features.

Provides a thin wrapper around OpenAI-compatible chat completion APIs.
All methods gracefully degrade when no API key is configured — the
adapters continue to work, they just fall back to their non-LLM paths.

Usage::

    from spacetime_memory.llm import LLMClient

    llm = LLMClient()
    summary = llm.summarize("Long text to summarize...")
    if summary:
        print(summary)

Environment variables:

- ``OPENAI_API_KEY`` — required for LLM calls
- ``OPENAI_BASE_URL`` — API base URL (default: ``https://api.openai.com/v1``)
- ``LLM_MODEL`` — model name (default: ``gpt-4o-mini``)
"""

from __future__ import annotations

import json
import os
from typing import Any


class LLMClient:
    """Lightweight OpenAI-compatible chat completion client.

    Attributes:
        model: The model name to use (from ``LLM_MODEL`` env var).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY", "")
            or os.environ.get("LITELLM_MASTER_KEY", "")
        )
        self.base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL", "")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "un-qwen3.6-plus")

    @property
    def available(self) -> bool:
        """Whether the LLM client is configured and can make calls."""
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> str | None:
        """Call the chat completion API.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.
            response_format: Optional JSON mode config (e.g. ``{"type": "json_object"}``).
            timeout: Request timeout in seconds.

        Returns:
            The response content string, or ``None`` if not configured or on failure.
        """
        if not self.available:
            return None

        import httpx

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return None

    def summarize(self, text: str, instruction: str = "") -> str | None:
        """Summarize text using the LLM.

        Args:
            text: The text to summarize.
            instruction: Optional extra instruction for the summarization.

        Returns:
            Summary string, or ``None`` if LLM not configured or call fails.
        """
        if not self.available:
            return None

        system = "You are a precise summarization assistant. Summarize the following text concisely while preserving key facts and entities."
        if instruction:
            system += f" {instruction}"

        return self.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ])

    def extract_facts(self, text: str) -> list[str] | None:
        """Extract key facts from text as a list of strings.

        Args:
            text: The text to extract facts from.

        Returns:
            List of fact strings, or ``None`` if LLM not configured.
        """
        if not self.available:
            return None

        result = self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract key facts from the user's message as a JSON array of strings. "
                        "Each fact should be a single, atomic statement. "
                        "Return ONLY valid JSON, no markdown, no explanation."
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        if not result:
            return None
        try:
            data = json.loads(result)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # Try common keys
                for key in ("facts", "fact", "items", "statements"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
            return [str(data)]
        except (json.JSONDecodeError, TypeError):
            return None

    def summarize_community(
        self,
        community_name: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> str | None:
        """Generate a narrative summary for a knowledge-graph community.

        Args:
            community_name: Name/label of the community.
            nodes: List of node dicts with ``name`` and optionally ``summary``.
            edges: List of edge dicts with ``relation``, ``fact``,
                ``source_node``, ``target_node``.

        Returns:
            Narrative summary string, or ``None`` if LLM not configured.
        """
        if not self.available:
            return None

        node_lines = []
        for n in nodes:
            name = n.get("name", n.get("label", "?"))
            summary = n.get("summary", "")
            if summary:
                node_lines.append(f"- {name}: {summary}")
            else:
                node_lines.append(f"- {name}")

        edge_lines = []
        for e in edges:
            src = e.get("source_node", e.get("source_node_uuid", "?"))[:12]
            tgt = e.get("target_node", e.get("target_node_uuid", "?"))[:12]
            rel = e.get("relation", e.get("name", "?"))
            fact = e.get("fact", "")
            if fact:
                edge_lines.append(f"- {src} --[{rel}]--> {tgt}: {fact}")
            else:
                edge_lines.append(f"- {src} --[{rel}]--> {tgt}")

        prompt = (
            f"## Community: {community_name}\n\n"
            f"### Nodes ({len(nodes)})\n" + "\n".join(node_lines) + "\n\n"
            f"### Edges ({len(edges)})\n" + "\n".join(edge_lines) + "\n\n"
            "Write a brief narrative summary (2-4 sentences) describing what this community represents "
            "in the knowledge graph. Focus on the key entities and their relationships."
        )

        return self.summarize(prompt, instruction="Be concise. 2-4 sentences.")
