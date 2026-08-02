"""Knowledge compounder — turns interactions into persistent knowledge.

Implements the "LLM Wiki" pattern from Karpathy: every query, store, and
synthesis can generate new wiki pages, update entity summaries, and grow
the knowledge base compoundingly, rather than each interaction being a
stateless query against raw memories.

Usage::

    client = Client(...)
    cp = Compounder(client)

    # Persist a search synthesis as a wiki page
    result = cp.store_answer(
        query="What's the relationship between neural nets and evolution?",
        answer="Both are optimization processes...",
        source_memory_ids=["mem_123", "mem_456"],
    )

    # Find potential links between unconnected entities
    links = cp.suggest_connections(workspace_id="ws1")

    # Auto-cross-link related memories
    stats = cp.cross_link(workspace_id="ws1")
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm import LLMClient

logger = logging.getLogger(__name__)

from .helpers import CompounderHelpers  # noqa: E402
from .workflows import CompounderWorkflows  # noqa: E402


class Compounder(CompounderWorkflows, CompounderHelpers):
    """High-level operations that make knowledge compound across interactions.

    All methods degrade gracefully when the LLM is not configured — they
    return empty/``None`` results rather than raising errors.
    """

    def __init__(
        self,
        client: Any,  # Client — forward ref to avoid circular import
        llm: LLMClient | None = None,
    ) -> None:
        self._client = client
        self._llm = llm or LLMClient()
