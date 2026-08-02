"""Internal models and type aliases for the Mem0 adapter package."""
from __future__ import annotations

from typing import Any


# Internal signal: message-list LLM fact extraction completed via recursion.
class _InferMergeDone(BaseException):
    """Raised to signal that infer+merge completed via recursive add()."""



# --- Type aliases (for documentation and type safety) ---
MessageDict = dict[str, str]
"""A single message in a conversation: ``{"role": ..., "content": ...}``."""

FilterDict = dict[str, Any]
"""Mem0 v2 filter dict (e.g. ``{"user_id": "u1", "agent_id": "a1"}``)."""

LLMConfigDict = dict[str, Any]
"""LLM configuration dict with optional keys ``provider``, ``model``, ``api_key``, ``base_url``."""

MetadataDict = dict[str, Any]
"""Arbitrary metadata attached to a memory or entity."""

ResultDict = dict[str, Any]
"""A single result record returned by Mem0 methods."""

GraphEntityDict = dict[str, Any]
"""A graph entity record (node in the knowledge graph)."""


__all__ = [
    "FilterDict",
    "GraphEntityDict",
    "LLMConfigDict",
    "MessageDict",
    "MetadataDict",
    "ResultDict",
    "_InferMergeDone",
]
