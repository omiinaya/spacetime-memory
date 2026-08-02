"""Metrics collector for spacetime-memory SDK.

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
    mc.record("store_memory", lambda: client.store(...))
    # OTel MeterProvider now tracks the same counters/histograms

Environment variables:

- ``OTEL_METRICS_ENABLED`` — set to ``false`` to skip OTel instrumentation
  (default: ``true``)
- ``OTEL_METRIC_EXPORT_INTERVAL_MS`` — export interval in milliseconds
  for periodic readers (default: ``60000``)
"""

from __future__ import annotations

from ._collector import EndpointStats, MemoryStats, MetricsCollector
from ._otel import (
    _OTEL_INSTRUMENTS,
    collect_otel_metrics,
    is_otel_metrics_active,
    remove_otel_metric_readers,
    setup_otel_metrics,
)

__all__ = [
    "EndpointStats",
    "MemoryStats",
    "MetricsCollector",
    "collect_otel_metrics",
    "is_otel_metrics_active",
    "remove_otel_metric_readers",
    "setup_otel_metrics",
]
