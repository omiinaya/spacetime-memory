"""Spacetime Memory — multi-layer memory infrastructure for AI agents."""

__version__ = "1.0.0"

from .client import (
    Client,
    configure_logging,
    EmbedderUnavailableError,
    SpacetimeDBError,
    NotFoundError,
    ApiError,
)
from .compounder import Compounder
from . import sdks
from .agent_orchestrator import AgentOrchestrator
from .metrics import (
    MetricsCollector,
    setup_otel_metrics,
    collect_otel_metrics,
    remove_otel_metric_readers,
    is_otel_metrics_active,
)
from .tracer import Tracer, get_tracer, start_span

__all__ = [
    "Client",
    "Compounder",
    "sdks",
    "AgentOrchestrator",
    "MetricsCollector",
    "setup_otel_metrics",
    "collect_otel_metrics",
    "remove_otel_metric_readers",
    "is_otel_metrics_active",
    "Tracer",
    "get_tracer",
    "start_span",
    "configure_logging",
    "EmbedderUnavailableError",
    "SpacetimeDBError",
    "NotFoundError",
    "ApiError",
]
