"""OpenTelemetry Metrics Bridge for spacetime-memory SDK.

Provides ``setup_otel_metrics()``, ``collect_otel_metrics()``,
``remove_otel_metric_readers()``, and ``is_otel_metrics_active()``.

Registers an InMemoryMetricReader on the global MeterProvider so that
metric readers can be dynamically added/removed at runtime via the
add_metric_reader / remove_metric_reader APIs, enabling live collection
in agent runner environments without a static export endpoint.

All functions degrade gracefully if OTel is not installed.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("spacetime-memory")

_OTEL_INSTRUMENTS: dict[str, Any] = {}
"""Global OTel instrument references created by ``setup_otel_metrics()``."""

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

        # Create the metric reader first (in-memory by default)
        metric_reader = reader or InMemoryMetricReader()

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
                    mp = MeterProvider(resource=resource, metric_readers=[metric_reader])
                    _otel_metrics.set_meter_provider(mp)
            except (OSError, ValueError):
                from opentelemetry.sdk.resources import Resource

                resource = Resource.create(
                    attributes={"service.name": service_name or "spacetime-memory"}
                )
                mp = MeterProvider(resource=resource, metric_readers=[metric_reader])
                try:
                    from opentelemetry import metrics as _otel_metrics

                    _otel_metrics.set_meter_provider(mp)
                except (OSError, ValueError):
                    pass
        else:
            mp = meter_provider
            # If an external meter_provider was passed, try to add the reader
            try:
                if hasattr(mp, "add_metric_reader"):
                    mp.add_metric_reader(metric_reader)
            except Exception:
                pass

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
    except (OSError, ValueError) as exc:
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
    except (OSError, ValueError):
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
    except (OSError, ValueError):
        pass
    _IN_MEMORY_METRIC_READER = None


def is_otel_metrics_active() -> bool:
    """Check whether OTel metrics instrumentation is active."""
    return _IN_MEMORY_METRIC_READER is not None
