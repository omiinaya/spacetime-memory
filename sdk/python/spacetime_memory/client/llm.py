"""LLM client for entity extraction — minimal stub for benchmark compatibility."""

from __future__ import annotations

from typing import Any


class LLMClient:
    """Minimal stub that reports unavailable — no LLM needed for benchmarks."""

    def __init__(self) -> None:
        self.available = False

    def extract_entities_llm(self, content: str, **kwargs: Any) -> list[dict[str, str]]:
        return []
