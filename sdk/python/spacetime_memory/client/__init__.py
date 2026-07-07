"""Spacetime-Memory client — composite Client class.

The ``Client`` class is composed from domain-specific mixins to
keep each module focused and maintainable.
The outer ``client.py`` module remains as an alias for backward compat.
"""
from __future__ import annotations

from ._base import (
    ClientBase,
    JSONFormatter,
    configure_logging,
    EmbedderUnavailableError,
    SpacetimeDBError,
    NotFoundError,
    ApiError,
    _SQL_ERROR_MAP,
    _REDUCER_ERROR_MAP,
    logger,
    _TRACER,
    _tracing_span,
)
from ._workspaces import WorkspaceMixin
from ._memories import MemoryMixin
from ._kg import KGMixin
from ._admin import AdminMixin
from ._utils import _esc, _query_hash, _parse_sql_response, _make_snippet
from ._rerank import _parse_rerank_json, llm_rerank, _RERANK_PROMPT


class Client(ClientBase, WorkspaceMixin, MemoryMixin, KGMixin, AdminMixin):
    """Spacetime-Memory client — all-in-one interface.

    Composed from domain mixins to keep each module focused.
    See individual mixin files for method documentation.
    """
    pass


__all__ = [
    "Client",
    "ClientBase",
    "JSONFormatter",
    "configure_logging",
    "EmbedderUnavailableError",
    "SpacetimeDBError",
    "NotFoundError",
    "ApiError",
    "_SQL_ERROR_MAP",
    "_REDUCER_ERROR_MAP",
    "logger",
    "_TRACER",
    "_tracing_span",
    "_esc",
    "_query_hash",
    "_parse_sql_response",
    "_make_snippet",
    "_parse_rerank_json",
    "llm_rerank",
    "_RERANK_PROMPT",
]
