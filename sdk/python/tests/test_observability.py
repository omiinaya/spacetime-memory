"""Tests for observability features: structured logging, request_id, Prometheus export."""
import json
import os
import logging
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from spacetime_memory.client import Client, JSONFormatter, configure_logging
from spacetime_memory.metrics import MetricsCollector

DB = os.environ.get("SPACETIMEDB_DB", "c200e409f602c06527d0aa66dc2d05718a6b62c4c3317b5498951cea41782713")


class TestJSONFormatter:
    def test_basic_format(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger", level=logging.INFO,
            pathname=__file__, lineno=42, msg="hello world",
            args=(), exc_info=None,
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_logger"
        assert parsed["message"] == "hello world"
        assert "ts" in parsed

    def test_with_extra_fields(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING,
            pathname=__file__, lineno=1, msg="test message",
            args=(), exc_info=None,
        )
        record.extra_fields = {"request_id": "abc123", "endpoint": "test"}
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "abc123"
        assert parsed["endpoint"] == "test"

    def test_no_cross_contamination(self):
        """Extra fields from one record should not affect another."""
        fmt = JSONFormatter()
        r1 = logging.LogRecord("t", logging.INFO, "", 0, "msg1", (), None)
        r2 = logging.LogRecord("t", logging.INFO, "", 0, "msg2", (), None)
        r1.extra_fields = {"req": "one"}
        o1 = json.loads(fmt.format(r1))
        o2 = json.loads(fmt.format(r2))
        assert o1["req"] == "one"
        assert "req" not in o2


class TestClientRequestId:
    def test_default_request_id(self):
        c = Client(host="localhost", port="3001", database=DB)
        assert len(c.request_id) == 8  # 4 random bytes = 8 hex chars

    def test_unique_per_instance(self):
        c1 = Client(host="localhost", port="3001", database=DB)
        c2 = Client(host="localhost", port="3001", database=DB)
        assert c1.request_id != c2.request_id


class TestMetricsPrometheus:
    def test_prometheus_format(self):
        mc = MetricsCollector()
        mc.record_latency("test_endpoint", 42.5)
        mc.record_latency("test_endpoint", 10.0, is_error=True)
        mc.record_memory_stats(total=100, by_type={"experience": 60}, by_tier={"L0": 10})
        mc.record_embedder_error()

        text = mc.prometheus_text()
        assert "# HELP spacetime_memory_uptime_seconds" in text
        assert "# TYPE spacetime_memory_total_calls counter" in text
        assert 'endpoint="test_endpoint"' in text
        assert 'quantile="avg"' in text
        assert 'type="experience"' in text
        assert 'tier="L0"' in text
        assert "spacetime_memory_embedder_errors 1" in text

    def test_prometheus_empty(self):
        """Empty collector produces valid Prometheus output."""
        mc = MetricsCollector()
        text = mc.prometheus_text()
        assert text.startswith("# HELP")
        assert "spacetime_memory_uptime_seconds" in text

    def test_prometheus_latency_values(self):
        mc = MetricsCollector()
        mc.record_latency("sql", 15.0)
        mc.record_latency("reducer:store", 200.0, is_error=True)
        text = mc.prometheus_text()
        lines = text.strip().split("\n")
        latency_lines = [l for l in lines if "latency_ms" in l]
        assert any("15.0" in l or "15" in l for l in latency_lines)
        assert len(latency_lines) == 2  # one per endpoint


class TestConfigureLogging:
    def test_json_output(self, capsys):
        configure_logging(level="DEBUG", json_format=True)
        logger = logging.getLogger("spacetime_memory")
        logger.info("test json log", extra={"extra_fields": {"request_id": "r1"}})
        logger.handlers.clear()
        captured = capsys.readouterr()
        lines = [l for l in captured.err.split("\n") if l.strip()]
        assert len(lines) >= 1
        parsed = json.loads(lines[0])
        assert parsed["message"] == "test json log"
        assert parsed["request_id"] == "r1"

    def test_text_output(self, capsys):
        configure_logging(level="INFO", json_format=False)
        logger = logging.getLogger("spacetime_memory")
        logger.info("plain text log")
        logger.handlers.clear()
        captured = capsys.readouterr()
        assert "plain text log" in captured.err
