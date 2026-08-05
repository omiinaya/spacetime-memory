"""
OpenTelemetry tracing integration for spacetime-memory.

Provides a lightweight ``Tracer`` wrapper that sets up OpenTelemetry's
``TracerProvider`` with optional OTLP HTTP export and integrates with the
existing ``MetricsCollector``.

Usage::

    from spacetime_memory.tracer import Tracer

    tracer = Tracer(service_name="spacetime-memory")
    tracer.setup()

    with tracer.start_span("store_memory") as span:
        span.set_attribute("workspace_id", ws_id)
        result = client.store(...)

Environment variables:

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OTLP HTTP endpoint (default: ``http://localhost:4318``)
- ``OTEL_SERVICE_NAME`` — Override service name (default: ``spacetime-memory``)
- ``OTEL_ENABLED`` — Set to ``false`` or ``0`` to disable tracing entirely
- ``OTEL_SAMPLING_RATIO`` — Sampling ratio (0.0–1.0, default: ``1.0``)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — OpenTelemetry is an optional dependency
# ---------------------------------------------------------------------------

_OTEL_AVAILABLE: bool | None = None


def _get_version() -> str:
    """Get package version from importlib metadata."""
    try:
        from importlib.metadata import version
        return version("spacetime-memory")
    except Exception:
        return "unknown"


def _check_otel_available() -> bool:
    """Check if OpenTelemetry packages are importable (cached)."""
    global _OTEL_AVAILABLE
    if _OTEL_AVAILABLE is not None:
        return _OTEL_AVAILABLE
    try:
        import opentelemetry  # noqa: F401  (availability probe)
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.sdk.trace import TracerProvider  # noqa: F401

        _OTEL_AVAILABLE = True
    except ImportError:
        _OTEL_AVAILABLE = False
    return _OTEL_AVAILABLE


# ---------------------------------------------------------------------------
# Fallback no-op span (when OTel is not available)
# ---------------------------------------------------------------------------


class _NoOpSpan:
    """Drop-in no-op span that does nothing."""

    def add_event(self, name: str, attributes: dict[str, Any] | None = None, timestamp: int | None = None) -> None:
        pass

    def is_recording(self) -> bool:
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def update_name(self, name: str) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: object) -> None:
        pass


_NOOP_SPAN = _NoOpSpan()

# ---------------------------------------------------------------------------
# Tracer wrapper
# ---------------------------------------------------------------------------


class Tracer:
    """Wraps OpenTelemetry tracer with optional OTLP export.

    When OpenTelemetry packages are not installed, all methods degrade to
    no-ops without raising errors.
    """

    def __init__(
        self,
        service_name: str | None = None,
        otlp_endpoint: str | None = None,
        enabled: bool | None = None,
        sampling_ratio: float | None = None,
    ) -> None:
        self._service_name = (
            service_name or os.environ.get("OTEL_SERVICE_NAME") or "spacetime-memory"
        )
        self._otlp_endpoint = otlp_endpoint or os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
        )
        enabled_env = os.environ.get("OTEL_ENABLED", "true").lower()
        self._enabled = enabled if enabled is not None else enabled_env not in ("false", "0", "no")
        self._sampling_ratio = sampling_ratio or float(os.environ.get("OTEL_SAMPLING_RATIO", "1.0"))
        self._tracer = None
        self._provider = None
        self._setup_done = False

    @property
    def is_enabled(self) -> bool:
        # An explicitly injected tracer (dependency injection / tests)
        # overrides the environment gate — if the caller handed us a
        # tracer, honor it regardless of OTEL_ENABLED.
        if self._tracer is not None:
            return True
        return self._enabled and _check_otel_available()

    def setup(self) -> None:
        """Initialize the OpenTelemetry tracer provider and exporter.

        Safe to call multiple times — only runs once.
        """
        if self._setup_done:
            return
        if not self._enabled:
            logger.info("OpenTelemetry tracing is disabled via OTEL_ENABLED")
            self._setup_done = True
            return
        if not _check_otel_available():
            logger.warning(
                "OpenTelemetry packages not installed. "
                "Install with: pip install spacetime-memory[otel]"
            )
            self._setup_done = True
            return

        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.trace.sampling import (
            ParentBasedTraceIdRatio,
        )

        resource = Resource.create(
            {
                "service.name": self._service_name,
                "service.version": self._get_version(),
            }
        )

        sampler = ParentBasedTraceIdRatio(self._sampling_ratio)

        self._provider = TracerProvider(resource=resource, sampler=sampler)
        trace.set_tracer_provider(self._provider)

        # --- Exporters ---
        if os.environ.get("OTEL_TRACES_EXPORTER", "otlp").lower() == "console":
            span_processor = BatchSpanProcessor(ConsoleSpanExporter())
            self._provider.add_span_processor(span_processor)
            logger.info("OpenTelemetry tracing: console exporter")

        self._try_otlp_exporter()

        self._tracer = trace.get_tracer(self._service_name, self._get_version())
        self._setup_done = True
        logger.info(
            "OpenTelemetry tracing initialised for %s (sampling=%s)",
            self._service_name,
            self._sampling_ratio,
        )

    def _get_version(self) -> str:
        return _get_version()

    def _setup(self) -> None:
        """Backward-compat alias for ``setup()``."""
        self.setup()

    def _try_otlp_exporter(self) -> None:
        """Try to configure the OTLP span exporter (extracted for testability)."""
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # ── Connectivity check ──────────────────────────────────────
            _collector_reachable = False
            try:
                import httpx as _httpx

                _probe = _httpx.get(
                    self._otlp_endpoint.rstrip("/v1") + "/",
                    timeout=2.0,
                )
                _collector_reachable = _probe.status_code < 500
            except Exception:
                pass

            if not _collector_reachable:
                logger.warning(
                    "OTLP collector at %s is not reachable — "
                    "skipping OTLP trace exporter. "
                    "Set OTEL_ENABLED=false to silence this warning.",
                    self._otlp_endpoint,
                )
            else:
                otlp_exporter = OTLPSpanExporter(
                    endpoint=f"{self._otlp_endpoint}/v1/traces",
                )
                span_processor = BatchSpanProcessor(otlp_exporter)
                self._provider.add_span_processor(span_processor)
                logger.info(
                    "OpenTelemetry tracing: OTLP exporter -> %s",
                    self._otlp_endpoint,
                )
        except ImportError:
            logger.info(
                "OpenTelemetry OTLP exporter not installed. "
                "Install with: pip install opentelemetry-exporter-otlp-proto-http"
            )

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        kind: Any = None,
    ) -> Iterator[Any]:
        """Start an OpenTelemetry span. Degrades to no-op if unavailable.

        Usage::

            with tracer.start_span("store_memory", {"ws_id": "ws1"}):
                ...
        """
        if not self.is_enabled:
            yield _NOOP_SPAN
            return

        from opentelemetry import trace

        tracer = self._tracer or trace.get_tracer(self._service_name)
        kind = kind or trace.SpanKind.INTERNAL

        with tracer.start_as_current_span(name, kind=kind, attributes=attributes or {}) as span:
            yield span

    def instrument_method(
        self,
        method: Callable[..., Any],
        span_name: str | None = None,
        attr_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> Callable[..., Any]:
        """Decorator that wraps a method with an OpenTelemetry span.

        Arguments:
            method: The function/method to instrument.
            span_name: Override the span name (default: method's ``__qualname__``).
            attr_fn: Optional callable ``(*args, **kwargs) -> dict`` that
                     extracts attributes from the method's arguments.

        Returns:
            Wrapped function that captures timing and errors in a span.
        """
        span_name = span_name or method.__qualname__

        @wraps(method)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not self.is_enabled:
                return method(*args, **kwargs)

            attributes = attr_fn(*args, **kwargs) if attr_fn else {}
            with self.start_span(span_name, attributes=attributes):
                try:
                    return method(*args, **kwargs)
                except Exception:
                    # Span will be marked as error automatically
                    raise

        return wrapper


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_TRACER: Tracer | None = None
_tracer = _TRACER  # backward-compat alias
_Tracer = Tracer  # backward-compat class alias


def get_tracer(
    service_name: str | None = None,
    setup: bool = True,
) -> Tracer | None:
    """Get or create the module-level ``Tracer`` singleton.

    Arguments:
        service_name: Override the service name (only used on first call).
        setup: If True (default), call ``tracer.setup()`` automatically.
               If False and no tracer exists, returns None.

    Returns:
        The shared ``Tracer`` instance, or None if not yet created.
    """
    global _TRACER
    if _TRACER is None:
        if not setup:
            return None
        _TRACER = Tracer(service_name=service_name)
        _TRACER.setup()
        globals()["_tracer"] = _TRACER
    return _TRACER


def start_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Convenience: start a span on the module-level tracer.

    Usage::

        from spacetime_memory.tracer import start_span

        with start_span("search", {"query": q}):
            results = client.search(...)
    """
    return get_tracer().start_span(name, attributes)
