"""
Mem0-compatible drop-in adapter.

Matches the real Mem0 Python SDK API (https://github.com/mem0ai/mem0):

All public method signatures (``add``, ``search``, ``get_all``, ``get``,
``delete``, ``history``, ``update``) accept the same keyword arguments
as upstream ``mem0.Memory``. Return shapes match (``{"results": [...]}``).
The ``graph`` property provides entity store access.

NOTE: Constructor differs from upstream — accepts a plain ``config`` dict
instead of a typed ``MemoryConfig`` object. The upstream also requires
an LLM provider config which our adapter doesn't need.

**Error contract:**
- ``ValueError`` for invalid inputs (empty ``text``, missing required args)
- ``RuntimeError`` / ``SpacetimeDBError`` for backend failures (DB down,
  connection errors).  These propagate from the underlying ``Client``.
- ``logger.warning`` logged for transient issues (LLM extraction, KG
  node creation failures) — the operation degrades gracefully rather
  than crashing.
- Graph search returns ``[]`` on failure (logged), consistent with
  mem0's ``get_all`` returning empty for missing data.

Usage::

    from spacetime_memory.sdks.mem0 import Memory

    m = Memory(config={"host": "127.0.0.1", "port": 3001})
    m.add("I like pizza", user_id="alice", agent_id="assistant")
    results = m.search("food preferences", user_id="alice")
    memory = m.get(memory_id=results["results"][0]["id"])
    all_mems = m.get_all(filters={"user_id": "alice"})
    m.update(memory_id=memory_id, data="I love pizza")
    m.delete(memory_id=memory_id)
    history = m.history(memory_id=memory_id)
    m.reset()
"""

from __future__ import annotations

from ._client import Memory as Memory
from ._client import _GraphStore as _GraphStore
from ._client import _resolve_llm as _resolve_llm
from ._models import _InferMergeDone as _InferMergeDone

__all__ = [
    "Memory",
    # Internal utilities (prefixed with underscore but exported for
    # advanced usage and backwards compatibility).
    "_GraphStore",
    "_resolve_llm",
    "_InferMergeDone",
]
