"""
Runtime Protocols for the spacetime-memory Python SDK.

Replaces ambiguous ``Any`` type annotations in the ``Client`` constructor with
typed structural subtyping protocols, giving type checkers and IDEs actionable
signatures without requiring concrete import dependencies.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ── PluginManagerProtocol ────────────────────────────────────────────────

@runtime_checkable
class PluginManagerProtocol(Protocol):
    """Minimal interface used by ``Client`` for plugin hook dispatches."""

    def dispatch_store(
        self, content: str, metadata: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Run all registered ``on_store`` hooks, returning (content, metadata)."""
        ...

    def dispatch_search(
        self, query: str, results: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run all registered ``on_search`` hooks, returning (query, results)."""
        ...

    def dispatch_export(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run all registered ``on_export`` hooks, returning filtered *data*."""
        ...

    def dispatch_import(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run all registered ``on_import`` hooks, returning filtered *data*."""
        ...


# ── EventBusProtocol ────────────────────────────────────────────────────

@runtime_checkable
class EventBusProtocol(Protocol):
    """Minimal interface used by ``Client`` for publishing lifecycle events."""

    def emit(self, event: Any) -> None:
        """Emit a *MemoryEvent* (or duck-typed equivalent) to all subscribers."""
        ...


# ── QueryCacheProtocol ──────────────────────────────────────────────────

@runtime_checkable
class QueryCacheProtocol(Protocol):
    """Minimal interface used by ``Client`` for caching search results."""

    def make_key(
        self,
        workspace_id: str,
        query: str,
        limit: int,
        strategy: str,
    ) -> str:
        """Build a deterministic cache key from the query parameters."""
        ...

    def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` if missing/expired."""
        ...

    def set(
        self,
        key: str,
        value: Any,
        *,
        workspace_id: str | None = None,
    ) -> None:
        """Store *value* under *key* with optional workspace-scoped TTL tracking."""
        ...

    def invalidate(self, *, workspace_id: str | None = None) -> None:
        """Invalidate cache entries, optionally scoped to a single workspace."""
        ...


# ── LocalLLMProtocol ────────────────────────────────────────────────────

@runtime_checkable
class LocalLLMProtocol(Protocol):
    """Minimal interface for a local LLM instance.

    Currently unused by the ``Client`` core, but provided for type safety
    so consumers that set ``local_llm`` get proper type checking.
    """

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from *prompt*."""
        ...


# ── MetricsCollectorProtocol ────────────────────────────────────────────

@runtime_checkable
class MetricsCollectorProtocol(Protocol):
    """Minimal interface used by ``Client`` for recording endpoint metrics."""

    def record(
        self,
        endpoint: str,
        fn: Any,
        is_error: bool | None = None,
    ) -> Any:
        """Call *fn* while recording latency / error stats for *endpoint*."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Export all collected metrics as a plain dict."""
        ...
