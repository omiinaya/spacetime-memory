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
