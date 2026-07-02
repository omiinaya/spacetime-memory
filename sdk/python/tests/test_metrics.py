"""Unit tests for MetricsCollector."""

from __future__ import annotations

import pytest
from spacetime_memory.metrics import MetricsCollector, EndpointStats, MemoryStats


class TestEndpointStats:
    """Statistics tracking for a single endpoint."""

    def test_initial_state(self) -> None:
        s = EndpointStats()
        assert s.count == 0
        assert s.errors == 0
        assert s.avg_latency_ms == 0.0
        assert s.error_rate == 0.0

    def test_record_success(self) -> None:
        s = EndpointStats()
        s.record(10.0)
        assert s.count == 1
        assert s.errors == 0
        assert s.avg_latency_ms == 10.0
        assert s.max_latency_ms == 10.0
        assert s.min_latency_ms == 10.0

    def test_record_error(self) -> None:
        s = EndpointStats()
        s.record(50.0, is_error=True)
        assert s.count == 1
        assert s.errors == 1
        assert s.avg_latency_ms == 50.0

    def test_multiple_records(self) -> None:
        s = EndpointStats()
        s.record(10.0)
        s.record(20.0, is_error=True)
        s.record(30.0)
        assert s.count == 3
        assert s.errors == 1
        assert s.avg_latency_ms == 20.0
        assert s.min_latency_ms == 10.0
        assert s.max_latency_ms == 30.0
        assert pytest.approx(s.error_rate, 0.1) == 33.3


class TestMemoryStats:
    """Memory statistics aggregation."""

    def test_initial_state(self) -> None:
        m = MemoryStats()
        assert m.total == 0
        assert m.to_dict()["total"] == 0

    def test_to_dict(self) -> None:
        m = MemoryStats()
        m.total = 100
        m.by_type["experience"] = 80
        m.by_type["world_fact"] = 20
        m.by_tier["L0"] = 10
        m.by_tier["L1"] = 70
        result = m.to_dict()
        assert result["total"] == 100
        assert result["by_type"]["experience"] == 80
        assert result["by_tier"]["L0"] == 10


class TestMetricsCollector:
    """Main metrics collector."""

    def test_initial_state(self) -> None:
        mc = MetricsCollector()
        d = mc.to_dict()
        assert d["total_calls"] == 0
        assert d["total_errors"] == 0
        assert d["embedder_errors"] == 0
        assert d["uptime_seconds"] >= 0

    def test_record_success(self) -> None:
        mc = MetricsCollector()
        result = mc.record("test_fn", lambda: "hello")
        assert result == "hello"

        d = mc.to_dict()
        assert d["total_calls"] == 1
        assert d["total_errors"] == 0
        assert "test_fn" in d["endpoints"]
        assert d["endpoints"]["test_fn"]["count"] == 1

    def test_record_error(self) -> None:
        mc = MetricsCollector()

        def _fail() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            mc.record("bad_fn", _fail)

        d = mc.to_dict()
        assert d["total_calls"] == 1
        assert d["total_errors"] == 1
        assert d["endpoints"]["bad_fn"]["errors"] == 1

    def test_record_latency(self) -> None:
        mc = MetricsCollector()
        mc.record_latency("direct", 42.0)
        d = mc.to_dict()
        assert d["endpoints"]["direct"]["count"] == 1
        assert d["endpoints"]["direct"]["latency_ms"]["avg"] == 42.0

    def test_embedder_errors(self) -> None:
        mc = MetricsCollector()
        mc.record_embedder_error()
        mc.record_embedder_error()
        assert mc.to_dict()["embedder_errors"] == 2

    def test_reset(self) -> None:
        mc = MetricsCollector()
        mc.record("ep", lambda: 1)
        mc.record_embedder_error()
        mc.record_memory_stats(total=50)
        assert mc.to_dict()["total_calls"] == 1

        mc.reset()
        d = mc.to_dict()
        assert d["total_calls"] == 0
        assert d["embedder_errors"] == 0
        assert d["memory"]["total"] == 0

    def test_multiple_endpoints(self) -> None:
        mc = MetricsCollector()
        mc.record("a", lambda: 1)
        mc.record("a", lambda: 2)
        mc.record("b", lambda: 3)
        d = mc.to_dict()
        assert d["endpoints"]["a"]["count"] == 2
        assert d["endpoints"]["b"]["count"] == 1
        assert d["total_calls"] == 3

    def test_uptime(self) -> None:
        import time

        mc = MetricsCollector()
        time.sleep(0.01)
        assert mc.uptime_seconds() > 0.005
        assert "uptime_human" in mc.to_dict()

    def test_record_memory_stats(self) -> None:
        mc = MetricsCollector()
        mc.record_memory_stats(
            total=200,
            by_type={"experience": 150, "world_fact": 50},
            by_tier={"L0": 20, "L1": 180},
        )
        d = mc.to_dict()
        assert d["memory"]["total"] == 200
        assert d["memory"]["by_type"]["experience"] == 150
        assert d["memory"]["by_tier"]["L0"] == 20

    def test_endpoint_stats_nonexistent(self) -> None:
        mc = MetricsCollector()
        s = mc.endpoint_stats("does-not-exist")
        assert s.count == 0
        assert s.errors == 0

    @staticmethod
    def test_format_duration_days() -> None:
        """_format_duration includes days when >= 86400s (line 260)."""
        result = MetricsCollector._format_duration(90000)  # 1d 1h 0m 0s
        assert "1d" in result
        assert "1h" in result

    @staticmethod
    def test_format_duration_hours() -> None:
        """_format_duration includes hours when >= 3600s but < 86400s (line 262)."""
        result = MetricsCollector._format_duration(7200)  # 2h 0m 0s
        assert "2h" in result
        assert "d" not in result
        # minutes only appear when > 0, so 0m is omitted

    @staticmethod
    def test_format_duration_minutes() -> None:
        """_format_duration includes minutes when >= 60s (line 264)."""
        result = MetricsCollector._format_duration(120)  # 2m 0s
        assert "2m" in result
        assert "0s" in result

    @staticmethod
    def test_format_duration_seconds_only() -> None:
        """_format_duration shows only seconds for < 60s."""
        result = MetricsCollector._format_duration(30)
        assert result == "30s"


# ---------------------------------------------------------------------------
# OTel Metrics Bridge Tests
# ---------------------------------------------------------------------------


class TestOtelMetricsBridge:
    """Test suite for the OTel metrics bridge using real MeterProvider."""

    def test_setup_otel_metrics_default(self) -> None:
        """setup_otel_metrics() creates an InMemoryMetricReader."""
        from opentelemetry.sdk.metrics import MeterProvider
        from spacetime_memory.metrics import (
            setup_otel_metrics,
            is_otel_metrics_active,
            collect_otel_metrics,
            remove_otel_metric_readers,
        )

        # Reset global state for test
        import spacetime_memory.metrics as _m

        _m._OTEL_METRICS_SETUP = False
        _m._IN_MEMORY_METRIC_READER = None

        try:
            result = setup_otel_metrics(service_name="spacetime-memory-test")
            assert result is True
            assert is_otel_metrics_active() is True
        finally:
            remove_otel_metric_readers()
            _m._OTEL_METRICS_SETUP = False
            _m._IN_MEMORY_METRIC_READER = None

    def test_setup_otel_metrics_idempotent(self) -> None:
        """Calling setup_otel_metrics() twice is a no-op."""
        from spacetime_memory.metrics import (
            setup_otel_metrics,
            remove_otel_metric_readers,
        )

        import spacetime_memory.metrics as _m

        _m._OTEL_METRICS_SETUP = False
        _m._IN_MEMORY_METRIC_READER = None

        try:
            result1 = setup_otel_metrics(service_name="spacetime-memory-idem")
            result2 = setup_otel_metrics(service_name="spacetime-memory-idem")
            assert result1 is True
            assert result2 is True  # idempotent — second returns True silently
        finally:
            remove_otel_metric_readers()
            _m._OTEL_METRICS_SETUP = False
            _m._IN_MEMORY_METRIC_READER = None

    def test_setup_otel_metrics_creates_instruments(self) -> None:
        """After setup, the OTel instruments are in _OTEL_INSTRUMENTS."""
        from spacetime_memory.metrics import (
            setup_otel_metrics,
            remove_otel_metric_readers,
            _OTEL_INSTRUMENTS,
        )

        import spacetime_memory.metrics as _m

        _m._OTEL_METRICS_SETUP = False
        _m._IN_MEMORY_METRIC_READER = False
        _OTEL_INSTRUMENTS.clear()

        try:
            setup_otel_metrics(service_name="spacetime-memory-instr")
            # Check expected keys exist
            for key in ("calls_total", "errors_total", "latency", "embedder_errors", "items_total", "items_by_type"):
                assert key in _m._OTEL_INSTRUMENTS, f"Missing instrument: {key}"
        finally:
            remove_otel_metric_readers()
            _m._OTEL_METRICS_SETUP = False
            _m._IN_MEMORY_METRIC_READER = None
            _OTEL_INSTRUMENTS.clear()

    def test_collect_otel_metrics_with_custom_reader(self) -> None:
        """collect_otel_metrics() returns data after recording to instruments."""
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from opentelemetry.sdk.resources import Resource
        from spacetime_memory.metrics import (
            setup_otel_metrics,
            collect_otel_metrics,
            remove_otel_metric_readers,
            _OTEL_INSTRUMENTS,
        )

        import spacetime_memory.metrics as _m

        _m._OTEL_METRICS_SETUP = False
        _m._IN_MEMORY_METRIC_READER = None
        _OTEL_INSTRUMENTS.clear()

        reader = InMemoryMetricReader()
        resource = Resource.create(attributes={"service.name": "test-collect"})
        mp = MeterProvider(resource=resource)

        try:
            setup_otel_metrics(meter_provider=mp, reader=reader)
            assert _m._IN_MEMORY_METRIC_READER is reader

            # Record a call via the OTel counter
            counter = _OTEL_INSTRUMENTS["calls_total"]
            counter.add(1, {"endpoint": "test_fn"})

            # Flush and collect
            mp.force_flush()
            result = collect_otel_metrics()
            assert result is not None

            # Find the calls_total metric
            calls_metric = [m for m in result if m["name"] == "spacetime_memory_calls_total"]
            assert len(calls_metric) > 0
            assert len(calls_metric[0]["data_points"]) == 1
            assert calls_metric[0]["data_points"][0]["value"] == 1
            attr = calls_metric[0]["data_points"][0]["attributes"]
            assert attr.get("endpoint") == "test_fn"
        finally:
            remove_otel_metric_readers(meter_provider=mp)
            mp.shutdown()
            _m._OTEL_METRICS_SETUP = False
            _m._IN_MEMORY_METRIC_READER = None
            _OTEL_INSTRUMENTS.clear()

    def test_remove_otel_metric_readers(self) -> None:
        """After remove, is_otel_metrics_active() returns False."""
        from spacetime_memory.metrics import (
            setup_otel_metrics,
            is_otel_metrics_active,
            remove_otel_metric_readers,
        )

        import spacetime_memory.metrics as _m

        _m._OTEL_METRICS_SETUP = False
        _m._IN_MEMORY_METRIC_READER = None

        try:
            setup_otel_metrics(service_name="spacetime-memory-remove-test")
            assert is_otel_metrics_active() is True
            remove_otel_metric_readers()
            assert is_otel_metrics_active() is False
        finally:
            _m._OTEL_METRICS_SETUP = False
            _m._IN_MEMORY_METRIC_READER = None

    def test_otel_disabled_by_env(self) -> None:
        """Setting OTEL_METRICS_ENABLED=false prevents setup."""
        import os

        os.environ["OTEL_METRICS_ENABLED"] = "false"
        from spacetime_memory.metrics import setup_otel_metrics, is_otel_metrics_active

        import spacetime_memory.metrics as _m

        _m._OTEL_METRICS_SETUP = False
        _m._IN_MEMORY_METRIC_READER = None

        try:
            result = setup_otel_metrics()
            assert result is False
            assert is_otel_metrics_active() is False
        finally:
            del os.environ["OTEL_METRICS_ENABLED"]
            _m._OTEL_METRICS_SETUP = False
            _m._IN_MEMORY_METRIC_READER = None
