"""
Metrics collector for spacetime-memory SDK.

Provides a ``MetricsCollector`` that wraps the SDK Client to track
request counts, latencies, error rates, and memory statistics.

Usage::

    from spacetime_memory.metrics import MetricsCollector
    collector = MetricsCollector()
    client = Client(...)

    # Wrap SDK calls to record metrics
    result = collector.record("store_memory", lambda: client.store(...))

    # Export to dict for CLI/API consumption
    data = collector.to_dict()

OpenTelemetry Bridge
--------------------
``setup_otel_metrics()`` creates OTel instruments backed by the same data
and registers an ``InMemoryMetricReader`` via ``add_metric_reader()``
(OTel SDK v1.43.0+), enabling live metric collection in agent runner
environments.

Usage::

    from spacetime_memory.metrics import MetricsCollector, setup_otel_metrics
    setup_otel_metrics()                        # registers global InMemoryMetricReader
    mc = MetricsCollector()
    mc.record("store_memory", lambda: client.store(…))
    # OTel MeterProvider now tracks the same counters/histograms

Environment variables:

- ``OTEL_METRICS_ENABLED`` — set to ``false`` to skip OTel instrumentation
  (default: ``true``)
- ``OTEL_METRIC_EXPORT_INTERVAL_MS`` — export interval in milliseconds
  for periodic readers (default: ``60000``)
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("spacetime-memory")


_OTEL_INSTRUMENTS: dict[str, Any] = {}
"""Global OTel instrument references created by ``setup_otel_metrics()``."""


@dataclass
class EndpointStats:
    """Latency and error statistics for a single endpoint/reducer."""

    count: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds across all recorded calls."""
        if self.count == 0:
            return 0.0
        return round(self.total_latency_ms / self.count, 1)

    @property
    def error_rate(self) -> float:
        """Error rate as a percentage of total calls."""
        if self.count == 0:
            return 0.0
        return round(self.errors / self.count * 100, 1)

    def record(self, latency_ms: float, is_error: bool = False) -> None:
        """Record a single call's latency and error status."""
        self.count += 1
        self.total_latency_ms += latency_ms
        if latency_ms < self.min_latency_ms:
            self.min_latency_ms = latency_ms
        if latency_ms > self.max_latency_ms:
            self.max_latency_ms = latency_ms
        if is_error:
            self.errors += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-serializable)."""
        return {
            "count": self.count,
            "errors": self.errors,
            "error_rate_pct": self.error_rate,
            "latency_ms": {
                "avg": self.avg_latency_ms,
                "min": round(self.min_latency_ms, 1) if self.count > 0 else 0.0,
                "max": round(self.max_latency_ms, 1),
            },
        }


@dataclass
class MemoryStats:
    """Memory statistics per workspace or globally."""

    total: int = 0
    by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_tier: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-serializable)."""
        return {
            "total": self.total,
            "by_type": dict(self.by_type),
            "by_tier": dict(self.by_tier),
        }


class MetricsCollector:
    """Collects request metrics and memory statistics.

    Thread-safe for single-thread usage. Not designed for concurrent
    access from multiple threads.

    Example::

        mc = MetricsCollector()
        client = Client(...)

        with mc.timed("store_memory"):
            client.store(workspace_id="...", content="hello", ...)

        print(mc.to_dict())

    """

    def __init__(self) -> None:
        """Initialize an empty metrics collector."""
        self._endpoints: dict[str, EndpointStats] = defaultdict(EndpointStats)
        self._memory: MemoryStats = MemoryStats()
        self._start_time: float = time.monotonic()
        self._last_reset: float = self._start_time
        self._embedder_errors: int = 0

    # ------------------------------------------------------------------
    # Recording API
    # ------------------------------------------------------------------

    def record(
        self,
        endpoint: str,
        fn: Callable[[], Any],
        is_error: bool | None = None,
    ) -> Any:
        """Call *fn* while recording latency and error status for *endpoint*.

        If *is_error* is None, the function's exception is caught and
        recorded as an error (then re-raised).
        """
        start = time.monotonic()
        try:
            result = fn()
            latency = (time.monotonic() - start) * 1000
            self._endpoints[endpoint].record(latency, is_error=False)
            return result
        except Exception:
            latency = (time.monotonic() - start) * 1000
            self._endpoints[endpoint].record(latency, is_error=True)
            raise

    def record_latency(self, endpoint: str, latency_ms: float, is_error: bool = False) -> None:
        """Record a latency measurement directly (useful for wrapping)."""
        self._endpoints[endpoint].record(latency_ms, is_error)

    def record_embedder_error(self) -> None:
        """Increment embedder error counter."""
        self._embedder_errors += 1

    def record_memory_stats(
        self,
        total: int,
        by_type: dict[str, int] | None = None,
        by_tier: dict[str, int] | None = None,
    ) -> None:
        """Record aggregate memory statistics."""
        self._memory.total = total
        if by_type:
            for k, v in by_type.items():
                self._memory.by_type[k] += v
        if by_tier:
            for k, v in by_tier.items():
                self._memory.by_tier[k] += v

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def endpoint_stats(self, endpoint: str) -> EndpointStats:
        """Get stats for a specific endpoint (or empty stats if not tracked)."""
        return self._endpoints.get(endpoint, EndpointStats())

    def uptime_seconds(self) -> float:
        """Return seconds since this collector was created."""
        return time.monotonic() - self._start_time

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all counters and timers."""
        self._endpoints.clear()
        self._memory = MemoryStats()
        self._last_reset = time.monotonic()
        self._embedder_errors = 0

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Export all metrics as a dict (JSON-serializable)."""
        uptime = self.uptime_seconds()
        return {
            "uptime_seconds": round(uptime, 1),
            "uptime_human": self._format_duration(uptime),
            "last_reset": round(time.monotonic() - self._last_reset, 1),
            "endpoints": {name: stats.to_dict() for name, stats in sorted(self._endpoints.items())},
            "total_calls": sum(s.count for s in self._endpoints.values()),
            "total_errors": sum(s.errors for s in self._endpoints.values()),
            "overall_error_rate_pct": self._overall_error_rate(),
            "embedder_errors": self._embedder_errors,
            "memory": self._memory.to_dict(),
        }

    def prometheus_text(self) -> str:
        """Export all metrics as Prometheus exposition-format text."""
        lines: list[str] = []
        uptime = self.uptime_seconds()

        lines.append("# HELP spacetime_memory_uptime_seconds Total uptime")
        lines.append("# TYPE spacetime_memory_uptime_seconds gauge")
        lines.append(f"spacetime_memory_uptime_seconds {round(uptime, 1)}")

        lines.append("# HELP spacetime_memory_total_calls Total reducer/SQL calls")
        lines.append("# TYPE spacetime_memory_total_calls counter")
        lines.append(
            f"spacetime_memory_total_calls {sum(s.count for s in self._endpoints.values())}"
        )

        lines.append("# HELP spacetime_memory_total_errors Total failed calls")
        lines.append("# TYPE spacetime_memory_total_errors counter")
        lines.append(
            f"spacetime_memory_total_errors {sum(s.errors for s in self._endpoints.values())}"
        )

        lines.append("# HELP spacetime_memory_embedder_errors Embedder error count")
        lines.append("# TYPE spacetime_memory_embedder_errors counter")
        lines.append(f"spacetime_memory_embedder_errors {self._embedder_errors}")

        lines.append("# HELP spacetime_memory_total_items Total memory items")
        lines.append("# TYPE spacetime_memory_total_items gauge")
        lines.append(f"spacetime_memory_total_items {self._memory.total}")

        for mem_type, count in self._memory.by_type.items():
            sanitized = mem_type.replace("-", "_").replace(" ", "_")
            lines.append(f'spacetime_memory_items_by_type{{type="{sanitized}"}} {count}')

        for tier, count in self._memory.by_tier.items():
            lines.append(f'spacetime_memory_items_by_tier{{tier="{tier}"}} {count}')

        lines.append("# HELP spacetime_memory_endpoint_calls Calls per endpoint")
        lines.append("# TYPE spacetime_memory_endpoint_calls counter")
        for name, stats in sorted(self._endpoints.items()):
            sanitized = name.replace("-", "_").replace(" ", "_").replace(":", "_")
            lines.append(f'spacetime_memory_endpoint_calls{{endpoint="{sanitized}"}} {stats.count}')
            lines.append(
                f'spacetime_memory_endpoint_errors{{endpoint="{sanitized}"}} {stats.errors}'
            )
            lines.append(
                f'spacetime_memory_endpoint_latency_ms{{endpoint="{sanitized}",quantile="avg"}} {stats.avg_latency_ms}'
            )

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _overall_error_rate(self) -> float:
        """Compute error rate across all endpoints as a percentage."""
        total = sum(s.count for s in self._endpoints.values())
        errors = sum(s.errors for s in self._endpoints.values())
        if total == 0:
            return 0.0
        return round(errors / total * 100, 1)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds as a human-readable duration string (e.g. '2d 3h 15m 30s')."""
        parts = []
        days, seconds = divmod(int(seconds), 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# OpenTelemetry Metrics Bridge  (OTel SDK v1.43.0+)
# ---------------------------------------------------------------------------
# Registers an InMemoryMetricReader on the global MeterProvider so that
# metric readers can be dynamically added/removed at runtime via the
# add_metric_reader / remove_metric_reader APIs, enabling live collection
# in agent runner environments without a static export endpoint.
#
# All functions degrade gracefully if OTel is not installed.
# ---------------------------------------------------------------------------

_OTEL_METRICS_SETUP: bool = False
"""Whether ``setup_otel_metrics()`` has already been called (one-shot)."""

_IN_MEMORY_METRIC_READER: Any = None
"""Hold a reference to the registered InMemoryMetricReader if active."""


def setup_otel_metrics(
    meter_provider: Any | None = None,
    service_name: str | None = None,
    reader: Any | None = None,
) -> bool:
    """Set up OTel metrics instrumentation.

    Creates counters and a histogram on the global ``MeterProvider`` and
    registers an ``InMemoryMetricReader`` so metrics are collectable at
    runtime.  Idempotent — subsequent calls are no-ops.

    Args:
        meter_provider: Override the MeterProvider (default: global SDK provider).
        service_name: Override the service name for the meter
            (default: ``spacetime-memory``).
        reader: Override the metric reader (default: ``InMemoryMetricReader``).
            Pass a custom ``PeriodicExportingMetricReader`` to export to OTLP.

    Returns:
        ``True`` if OTel instrumentation was successfully set up,
        ``False`` if OTel SDK packages are unavailable or disabled.

    .. versionadded:: 1.43.0+  Uses ``MeterProvider.add_metric_reader()``
    """
    global _OTEL_METRICS_SETUP, _IN_MEMORY_METRIC_READER

    if _OTEL_METRICS_SETUP:
        return True

    # Respect explicit disable
    otel_enabled = os.environ.get("OTEL_METRICS_ENABLED", "true").lower()
    if otel_enabled in ("false", "0", "no"):
        logger.info("OTel metrics disabled via OTEL_METRICS_ENABLED=%s", otel_enabled)
        _OTEL_METRICS_SETUP = True  # mark as done so we don't retry
        return False

    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        if meter_provider is None:
            # Try to get or create a MeterProvider
            try:
                from opentelemetry import metrics as _otel_metrics

                mp = _otel_metrics.get_meter_provider()
                if not isinstance(mp, MeterProvider):
                    from opentelemetry.sdk.resources import Resource

                    resource = Resource.create(
                        attributes={"service.name": service_name or "spacetime-memory"}
                    )
                    mp = MeterProvider(resource=resource)
                    _otel_metrics.set_meter_provider(mp)
            except Exception:
                from opentelemetry.sdk.resources import Resource

                resource = Resource.create(
                    attributes={"service.name": service_name or "spacetime-memory"}
                )
                mp = MeterProvider(resource=resource)
                try:
                    from opentelemetry import metrics as _otel_metrics

                    _otel_metrics.set_meter_provider(mp)
                except Exception:
                    pass
        else:
            mp = meter_provider

        # Create the metric reader (in-memory by default)
        metric_reader = reader or InMemoryMetricReader()
        mp.add_metric_reader(metric_reader)
        _IN_MEMORY_METRIC_READER = metric_reader

        # Create the meter and instruments
        meter = mp.get_meter("spacetime-memory", "1.0.0")

        # Counter for total calls
        _OTEL_INSTRUMENTS["calls_total"] = meter.create_counter(
            name="spacetime_memory_calls_total",
            description="Total reducer/SQL calls per endpoint",
            unit="1",
        )
        # Counter for total errors
        _OTEL_INSTRUMENTS["errors_total"] = meter.create_counter(
            name="spacetime_memory_errors_total",
            description="Total failed reducer/SQL calls per endpoint",
            unit="1",
        )
        # Histogram for latency
        _OTEL_INSTRUMENTS["latency"] = meter.create_histogram(
            name="spacetime_memory_latency_ms",
            description="Latency of reducer/SQL calls in milliseconds",
            unit="ms",
        )
        # Counter for embedder errors
        _OTEL_INSTRUMENTS["embedder_errors"] = meter.create_counter(
            name="spacetime_memory_embedder_errors",
            description="Total embedder errors",
            unit="1",
        )
        # Gauge for total items
        _OTEL_INSTRUMENTS["items_total"] = meter.create_gauge(
            name="spacetime_memory_items_total",
            description="Total memory items",
            unit="1",
        )
        # Counter for items by type
        _OTEL_INSTRUMENTS["items_by_type"] = meter.create_counter(
            name="spacetime_memory_items_by_type",
            description="Memory items grouped by type",
            unit="1",
        )

        _OTEL_METRICS_SETUP = True
        logger.info(
            "OTel metrics enabled — InMemoryMetricReader registered via add_metric_reader"
        )
        return True

    except ImportError:
        logger.info(
            "OpenTelemetry SDK not installed. "
            "Install with: pip install 'spacetime-memory[otel]'"
        )
        _OTEL_METRICS_SETUP = True  # don't retry
        return False
    except Exception as exc:
        logger.warning("OTel metrics setup failed: %s", exc)
        _OTEL_METRICS_SETUP = True
        return False


def collect_otel_metrics() -> list[dict[str, Any]] | None:
    """Collect and return metrics from the OTel InMemoryMetricReader.

    Returns:
        A list of metric data dicts (one per instrument) if a reader is
        registered, or ``None`` if OTel metrics are not set up.

    Each metric dict has::

        {
            "name": "spacetime_memory_calls_total",
            "data_points": [
                {"value": 42, "attributes": {"endpoint": "store_memory"}},
                ...
            ],
        }

    This can be scraped by a Prometheus sidecar or used in dashboards.
    """
    if _IN_MEMORY_METRIC_READER is None:
        return None
    try:
        metrics_data = _IN_MEMORY_METRIC_READER.get_metrics_data()
        if not metrics_data or not metrics_data.resource_metrics:
            return None
        result: list[dict[str, Any]] = []
        for rm in metrics_data.resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    points = []
                    for dp in metric.data.data_points:
                        attrs = {}
                        if hasattr(dp, "attributes") and dp.attributes:
                            attrs = dict(dp.attributes)
                        pt = {"value": dp.value if hasattr(dp, "value") else dp.sum}
                        if attrs:
                            pt["attributes"] = attrs
                        points.append(pt)
                    result.append({"name": metric.name, "data_points": points})
        return result
    except Exception:
        return None


def remove_otel_metric_readers(meter_provider: Any | None = None) -> None:
    """Remove all metric readers that were registered by ``setup_otel_metrics()``.

    Uses OTel SDK v1.43.0+'s ``remove_metric_reader()`` API.

    Args:
        meter_provider: The MeterProvider to remove readers from
            (default: global SDK provider).
    """
    global _IN_MEMORY_METRIC_READER
    if _IN_MEMORY_METRIC_READER is None:
        return
    try:
        from opentelemetry.sdk.metrics import MeterProvider

        if meter_provider is None:
            from opentelemetry import metrics as _otel_metrics

            mp = _otel_metrics.get_meter_provider()
            if not isinstance(mp, MeterProvider):
                return
        else:
            mp = meter_provider

        mp.remove_metric_reader(_IN_MEMORY_METRIC_READER)
    except Exception:
        pass
    _IN_MEMORY_METRIC_READER = None


def is_otel_metrics_active() -> bool:
    """Check whether OTel metrics instrumentation is active."""
    return _IN_MEMORY_METRIC_READER is not None
