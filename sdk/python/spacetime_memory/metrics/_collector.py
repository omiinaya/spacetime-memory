"""Metrics collector classes for spacetime-memory SDK.

Provides ``EndpointStats``, ``MemoryStats``, and ``MetricsCollector``
for tracking request counts, latencies, error rates, and memory statistics.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("spacetime-memory")


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
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
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
        self._embedder_error_timestamps: list[float] = []
        self._embedder_error_rate_window_secs: int = int(
            os.environ.get("STMEM_EMBEDDER_RATE_WINDOW_SECS", "300")
        )
        self._embedder_recovery_count: int = 0  # count of degraded->recovered transitions

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
        except (OSError, ValueError):
            latency = (time.monotonic() - start) * 1000
            self._endpoints[endpoint].record(latency, is_error=True)
            raise

    def record_latency(self, endpoint: str, latency_ms: float, is_error: bool = False) -> None:
        """Record a latency measurement directly (useful for wrapping)."""
        self._endpoints[endpoint].record(latency_ms, is_error)

    def record_embedder_error(self) -> None:
        """Increment embedder error counter and record the timestamp.

        Old timestamps outside the rate window are pruned on each call
        to keep the list bounded.
        """
        self._embedder_errors += 1
        now = time.monotonic()
        self._embedder_error_timestamps.append(now)
        # Prune timestamps older than the rate window
        cutoff = now - self._embedder_error_rate_window_secs
        self._embedder_error_timestamps = [
            ts for ts in self._embedder_error_timestamps if ts >= cutoff
        ]

    def record_embedder_recovery(self) -> None:
        """Record a embedder recovery event (degraded->healthy transition)."""
        self._embedder_recovery_count += 1

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

    def embedder_error_rate(self, window_secs: int | None = None) -> float:
        """Return the number of embedder errors in the current (or given) rate window.

        Args:
            window_secs: Override the default rate window (STMEM_EMBEDDER_RATE_WINDOW_SECS).
        """
        now = time.monotonic()
        window = window_secs if window_secs is not None else self._embedder_error_rate_window_secs
        cutoff = now - window
        return float(sum(1 for ts in self._embedder_error_timestamps if ts >= cutoff))

    def embedder_error_rate_pct(self) -> float:
        """Return embedder error rate as percentage of total recorded endpoint calls.

        When there are no endpoint calls, returns 0.0.
        """
        total_calls = sum(s.count for s in self._endpoints.values())
        if total_calls == 0:
            return 0.0
        return round(self._embedder_errors / total_calls * 100, 1)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all counters and timers."""
        self._endpoints.clear()
        self._memory = MemoryStats()
        self._last_reset = time.monotonic()
        self._embedder_errors = 0
        self._embedder_recovery_count = 0

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Export all metrics as a dict (JSON-serializable)."""
        uptime = self.uptime_seconds()
        total_calls = sum(s.count for s in self._endpoints.values())
        total_errors = sum(s.errors for s in self._endpoints.values())
        result: dict[str, Any] = {
            "uptime_seconds": round(uptime, 1),
            "uptime_human": self._format_duration(uptime),
            "last_reset": round(time.monotonic() - self._last_reset, 1),
            "endpoints": {name: stats.to_dict() for name, stats in sorted(self._endpoints.items())},
            "total_calls": total_calls,
            "total_errors": total_errors,
            "overall_error_rate_pct": self._overall_error_rate(),
            "embedder_errors": self._embedder_errors,
            "embedder_recovery_count": self._embedder_recovery_count,
            "embedder_error_rate_window_secs": self._embedder_error_rate_window_secs,
            "memory": self._memory.to_dict(),
        }
        # Compute embedder error rate as percentage of total calls
        # If total_calls is zero, use embedder_errors count as-is
        if total_calls > 0 and self._embedder_errors > 0:
            embedder_error_rate_pct = round(self._embedder_errors / total_calls * 100, 1)
            result["embedder_error_rate_pct"] = embedder_error_rate_pct
            if embedder_error_rate_pct > 25.0 and self._embedder_errors >= 3:
                result["degraded"] = True
                result["degradation_warning"] = (
                    f"Embedder error rate is {embedder_error_rate_pct}% "
                    f"({self._embedder_errors} errors in {total_calls} total calls) — "
                    "SDK embeddings are silently degraded. Check the embedder service."
                )
        elif self._embedder_errors > 0:
            result["embedder_error_rate_pct"] = 100.0  # All calls are errors
            if self._embedder_errors >= 3:
                result["degraded"] = True
                result["degradation_warning"] = (
                    f"Embedder has {self._embedder_errors} errors with no successful calls — "
                    "SDK embeddings are silently degraded. Check the embedder service."
                )
        return result

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

        lines.append("# HELP spacetime_memory_embedder_error_rate_pct Embedder error rate percentage")
        lines.append("# TYPE spacetime_memory_embedder_error_rate_pct gauge")
        lines.append(f"spacetime_memory_embedder_error_rate_pct {self.embedder_error_rate_pct()}")

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
