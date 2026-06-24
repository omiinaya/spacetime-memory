"""Spacetime Memory — multi-layer memory infrastructure for AI agents."""

__version__ = "1.0.0"

from .client import Client, configure_logging, EmbedderUnavailableError, SpacetimeDBError, NotFoundError, ApiError
from . import sdks
from .agent_orchestrator import AgentOrchestrator
from .metrics import MetricsCollector

__all__ = ["Client", "sdks", "AgentOrchestrator", "MetricsCollector",
           "configure_logging", "EmbedderUnavailableError",
           "SpacetimeDBError", "NotFoundError", "ApiError"]
