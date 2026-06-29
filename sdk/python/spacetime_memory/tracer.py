"""OpenTelemetry tracing integration for spacetime-memory.

Provides a lightweight ``Tracer`` wrapper that sets up OpenTelemetry's
``TracerProvider`` with optional OTLP export.  Everything in this module
is optional — if OpenTelemetry packages aren't installed, all calls are
no-ops.

Usage::

    from .tracer import get_tracer, start_span

    tracer = get_tracer()
    with start_span("my_operation"):
        do_work()

Environment variables:

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OTLP HTTP endpoint (default: ``http://localhost:4318``)
- ``OTEL_SERVICE_NAME`` — Override service name (default: ``spacetime-memory``)
- ``OTEL_ENABLED`` — Set to ``false`` or ``0`` to disable tracing entirely
- ``OTEL_SAMPLING_RATIO`` — Sampling ratio (0.0–1.0, default: ``1.0``)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("spacetime-memory")


def _get_version() -> str:
    """Try to read the package version from metadata, or return unknown."""
    try:
        from importlib.metadata import version

        return version("spacetime-memory")
    except Exception:
        return "unknown"


_TRACER: Any = None


def get_tracer(setup: bool = False) -> Any:
    """Get the global ``Tracer`` singleton.

    Args:
        setup: When True, initialise the tracer (one-shot).
    """
    global _TRACER
    if setup and _TRACER is None:
        _TRACER = _Tracer()
    return _TRACER


def start_span(name: str, attributes: dict[str, Any] | None = None) -> Any:
    """Start a new span.  Returns a no-op context manager if tracing
    is not available."""
    if _TRACER is not None:
        return _TRACER.start_span(name, attributes)
    from contextlib import nullcontext

    return nullcontext()


# -----------------------------------------------------------------------
# Internal
# -----------------------------------------------------------------------


class _Tracer:
    """Lazy one-shot OTel initializer."""

    def __init__(self) -> None:
        self._setup_done = False
        self._provider = None
        self._otlp_endpoint: str = (
            os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
            or "http://localhost:4318"
        )
        self._sampling_ratio = float(os.environ.get("OTEL_SAMPLING_RATIO", "1.0"))
        self._service_name = (
            os.environ.get("OTEL_SERVICE_NAME") or "spacetime-memory"
        )
        self._setup()

    def _setup(self) -> None:
        """One-shot initialisation — called once from ``__init__``."""
        if self._setup_done:
            return

        # Respect explicit disable
        otel_enabled = os.environ.get("OTEL_ENABLED", "true").lower()
        if otel_enabled in ("false", "0", "no"):
            logger.info("OpenTelemetry disabled via OTEL_ENABLED=%s", otel_enabled)
            self._setup_done = True
            return

        try:
            from opentelemetry import trace as _oteltrace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio

            resource = Resource.create(
                attributes={
                    "service.name": self._service_name,
                    "service.version": _get_version(),
                }
            )

            sampler = ParentBasedTraceIdRatio(self._sampling_ratio)

            self._provider = TracerProvider(resource=resource, sampler=sampler)
            _oteltrace.set_tracer_provider(self._provider)

            # Console exporter
            if (
                os.environ.get("OTEL_TRACES_EXPORTER", "otlp").lower()
                == "console"
            ):
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter

                span_processor = BatchSpanProcessor(ConsoleSpanExporter())
                self._provider.add_span_processor(span_processor)
                logger.info("OpenTelemetry tracing: console exporter")
            else:
                self._try_otlp_exporter()

        except ImportError:
            logger.info(
                "OpenTelemetry packages not installed. "
                "Install with: pip install 'spacetime-memory[otel]'"
            )

        self._setup_done = True

    def _try_otlp_exporter(self) -> None:
        """Try to wire up the OTLP HTTP exporter.

        This method is only called when OpenTelemetry SDK packages are
        already imported successfully.  If the collector is not reachable
        we fall through silently (info-level log) rather than logging a
        warning on every CLI invocation.
        """
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # Quick connectivity probe
            collector_reachable = False
            try:
                import httpx as _httpx

                probe = _httpx.get(
                    self._otlp_endpoint.rstrip("/v1") + "/",
                    timeout=2.0,
                )
                collector_reachable = probe.status_code < 500
            except Exception:
                pass

            if collector_reachable:
                otlp_exporter = OTLPSpanExporter(
                    endpoint=f"{self._otlp_endpoint}/v1/traces",
                )
                span_processor = BatchSpanProcessor(otlp_exporter)
                self._provider.add_span_processor(span_processor)
                logger.info(
                    "OpenTelemetry tracing: OTLP exporter -> %s",
                    self._otlp_endpoint,
                )
            else:
                logger.info(
                    "OTLP collector at %s not reachable — "
                    "skipping OTLP trace exporter. "
                    "Set OTEL_ENABLED=false to silence.",
                    self._otlp_endpoint,
                )

        except ImportError:
            logger.info(
                "OpenTelemetry OTLP exporter not installed. "
                "Install with: pip install opentelemetry-exporter-otlp-proto-http"
            )

    def start_span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> Any:
        """Start a new span if the provider is configured."""
        if self._provider is None:
            from contextlib import nullcontext

            return nullcontext()
        tracer = self._provider.get_tracer("spacetime-memory")
        return tracer.start_as_current_span(name, attributes=attributes)


# Public alias for backward compatibility
Tracer = _Tracer
