"""Tests for observability features: structured logging, request_id, Prometheus export."""
import json
import os
import types
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


class TestTracerNoOpSpan:
    """Tests for the _NoOpSpan fallback when OTel is unavailable."""

    def test_noop_span_set_attribute(self):
        from spacetime_memory.tracer import _NoOpSpan
        span = _NoOpSpan()
        span.set_attribute("key", "value")  # should not raise

    def test_noop_span_set_attributes(self):
        from spacetime_memory.tracer import _NoOpSpan
        span = _NoOpSpan()
        span.set_attributes({"a": 1})  # should not raise

    def test_noop_span_record_exception(self):
        from spacetime_memory.tracer import _NoOpSpan
        span = _NoOpSpan()
        span.record_exception(ValueError("test"))  # should not raise

    def test_noop_span_set_status(self):
        from spacetime_memory.tracer import _NoOpSpan
        span = _NoOpSpan()
        span.set_status("ok")  # should not raise

    def test_noop_span_end(self):
        from spacetime_memory.tracer import _NoOpSpan
        span = _NoOpSpan()
        span.end()  # should not raise

    def test_noop_span_context_manager(self):
        from spacetime_memory.tracer import _NoOpSpan
        with _NoOpSpan() as span:
            assert span is not None


class TestCheckOtelAvailable:
    """Tests for the _check_otel_available() cache."""

    def test_otel_not_available_on_import_error(self, monkeypatch):
        from spacetime_memory.tracer import _check_otel_available
        # Reset the cached value
        import spacetime_memory.tracer as tracer_mod
        tracer_mod._OTEL_AVAILABLE = None
        monkeypatch.setattr(tracer_mod, "import opentelemetry", None, raising=False)
        # Make the import fail
        import builtins
        orig_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "opentelemetry":
                raise ImportError("not installed")
            return orig_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _mock_import)
        assert not _check_otel_available()

    def test_otel_available_cached(self, monkeypatch):
        from spacetime_memory.tracer import _check_otel_available
        import spacetime_memory.tracer as tracer_mod
        tracer_mod._OTEL_AVAILABLE = None
        # First call caches
        monkeypatch.setattr(tracer_mod, "_OTEL_AVAILABLE", True)
        assert _check_otel_available() is True


class TestTracerInit:
    """Tests for Tracer.__init__()."""

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        monkeypatch.delenv("OTEL_SAMPLING_RATIO", raising=False)
        from spacetime_memory.tracer import Tracer
        t = Tracer()
        assert t._service_name == "spacetime-memory"
        assert t._otlp_endpoint == "http://localhost:4318"
        assert t._enabled is True
        assert t._sampling_ratio == 1.0
        assert t._tracer is None
        assert t._setup_done is False

    def test_init_env_overrides(self, monkeypatch):
        monkeypatch.setenv("OTEL_SERVICE_NAME", "my-service")
        monkeypatch.setenv("OTEL_ENABLED", "false")
        monkeypatch.setenv("OTEL_SAMPLING_RATIO", "0.5")
        from spacetime_memory.tracer import Tracer
        t = Tracer()
        assert t._service_name == "my-service"
        assert t._enabled is False
        assert t._sampling_ratio == 0.5

    def test_init_explicit_params(self, monkeypatch):
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        from spacetime_memory.tracer import Tracer
        t = Tracer(
            service_name="explicit",
            otlp_endpoint="http://custom:4318",
            enabled=True,
            sampling_ratio=0.25,
        )
        assert t._service_name == "explicit"
        assert t._otlp_endpoint == "http://custom:4318"
        assert t._enabled is True
        assert t._sampling_ratio == 0.25

    def test_init_explicit_disabled_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OTEL_ENABLED", "true")
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=False)
        assert t._enabled is False

    def test_init_default_endpoint_no_env(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        from spacetime_memory.tracer import Tracer
        t = Tracer()
        assert t._otlp_endpoint == "http://localhost:4318"


class TestTracerIsEnabled:
    """Tests for Tracer.is_enabled property."""

    def test_enabled_and_otel_available(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=True)
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)
        assert t.is_enabled is True

    def test_enabled_but_otel_not_available(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=True)
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: False)
        assert t.is_enabled is False

    def test_disabled_even_if_otel_available(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=False)
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)
        assert t.is_enabled is False


class TestTracerSetup:
    """Tests for Tracer.setup()."""

    def test_setup_already_done(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer()
        t._setup_done = True
        calls = []
        monkeypatch.setattr(t, "_enabled", True)
        # Should return immediately without checking anything
        t.setup()
        assert t._setup_done is True  # still True, not re-initialised

    def test_setup_disabled(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=False)
        t.setup()
        assert t._setup_done is True
        assert t._tracer is None

    def test_setup_otel_not_available(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=True)
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: False)
        t.setup()
        assert t._setup_done is True
        assert t._tracer is None

    def test_setup_full_path(self, monkeypatch):
        """Test the full OTel setup path with mock OTel packages."""
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=True)
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)

        # Build a mock OTel package hierarchy that behaves as a namespace package
        import contextlib

        # Use a versatile AutoMockModule for all OTel SDK imports
        class AutoMockModule(types.ModuleType):
            """A module mock that returns AutoMockModule for any attribute access,
            making sub-imports like ``from opentelemetry.sdk.resources import Resource``
            work automatically."""
            def __getattr__(self, name):
                if name.startswith("_"):
                    raise AttributeError(name)
                m = AutoMockModule(f"{self.__name__}.{name}")
                m.__package__ = m.__name__
                m.__path__ = [f"/fake/{name}"]
                setattr(self, name, m)
                return m

        mock_otel = AutoMockModule("opentelemetry")
        mock_otel.__path__ = ["/fake/opentelemetry"]
        mock_otel.__package__ = "opentelemetry"
        mock_otel.trace.set_tracer_provider = lambda p: None
        mock_otel.trace.SpanKind = type("SpanKind", (), {"INTERNAL": "INTERNAL"})
        mock_otel.trace.get_tracer = lambda *a: contextlib.nullcontext()
        _provider_obj = type("_Provider", (), {"add_span_processor": lambda s, p: None})()
        mock_otel.sdk.trace.TracerProvider = lambda **kw: _provider_obj
        mock_otel.sdk.resources.Resource = type("Resource", (), {"create": staticmethod(lambda attrs: {})})
        mock_otel.sdk.trace.export.BatchSpanProcessor = lambda *a: None
        mock_otel.sdk.trace.export.ConsoleSpanExporter = lambda: None
        mock_otel.sdk.trace.sampling.ParentBasedTraceIdRatio = lambda r: None
        mock_otel.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter = lambda **kw: None

        def _install_mock(mod, name):
            monkeypatch.setitem(sys.modules, name, mod)

        _install_mock(mock_otel, "opentelemetry")
        _install_mock(mock_otel.trace, "opentelemetry.trace")
        _install_mock(mock_otel.sdk, "opentelemetry.sdk")
        _install_mock(mock_otel.sdk.resources, "opentelemetry.sdk.resources")
        _install_mock(mock_otel.sdk.trace, "opentelemetry.sdk.trace")
        _install_mock(mock_otel.sdk.trace.export, "opentelemetry.sdk.trace.export")
        _install_mock(mock_otel.sdk.trace.sampling, "opentelemetry.sdk.trace.sampling")
        _install_mock(mock_otel.exporter, "opentelemetry.exporter")
        _install_mock(mock_otel.exporter.otlp, "opentelemetry.exporter.otlp")
        _install_mock(mock_otel.exporter.otlp.proto, "opentelemetry.exporter.otlp.proto")
        _install_mock(mock_otel.exporter.otlp.proto.http, "opentelemetry.exporter.otlp.proto.http")
        _install_mock(mock_otel.exporter.otlp.proto.http.trace_exporter,
                      "opentelemetry.exporter.otlp.proto.http.trace_exporter")

        monkeypatch.setattr("spacetime_memory.tracer._tracer", None)

        t.setup()
        assert t._setup_done is True
        assert t._tracer is not None


class TestCheckOtelAvailableSuccess:
    """Tests for _check_otel_available() when OTel IS importable."""

    def test_otel_available_success_path(self, monkeypatch):
        """Import succeeds — _OTEL_AVAILABLE should be set to True."""
        from spacetime_memory.tracer import _check_otel_available
        import spacetime_memory.tracer as tracer_mod
        tracer_mod._OTEL_AVAILABLE = None

        # Make opentelemetry import succeed by putting a mock in sys.modules
        import types
        mock = types.ModuleType("opentelemetry")
        mock_t = types.ModuleType("opentelemetry.trace")
        mock_t.ok = True
        mock_trace = types.ModuleType("opentelemetry.sdk.trace")
        mock_trace.TracerProvider = type("tp", (), {})
        monkeypatch.setitem(sys.modules, "opentelemetry", mock)
        monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_t)
        monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", mock_trace)

        assert _check_otel_available() is True


class TestTracerSetupConsoleExporter:
    """Test the OTEL_TRACES_EXPORTER=console path in setup()."""

    def test_console_exporter_path(self, monkeypatch):
        from spacetime_memory.tracer import Tracer, _check_otel_available
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "console")

        # Build mock OTel hierarchy
        import types
        class AutoMockMod(types.ModuleType):
            def __getattr__(self, name):
                if name.startswith("_"):
                    raise AttributeError(name)
                m = AutoMockMod(f"{self.__name__}.{name}")
                m.__package__ = m.__name__
                m.__path__ = [f"/fake/{name}"]
                setattr(self, name, m)
                return m

        import contextlib
        mock_otel = AutoMockMod("opentelemetry")
        mock_otel.__path__ = ["/fake/opentelemetry"]
        mock_otel.__package__ = "opentelemetry"
        mock_otel.trace.set_tracer_provider = lambda p: None
        mock_otel.trace.SpanKind = type("SpanKind", (), {"INTERNAL": "INTERNAL"})
        mock_otel.trace.get_tracer = lambda *a: contextlib.nullcontext()
        _prov = type("_P", (), {"add_span_processor": lambda s, p: None})()
        mock_otel.sdk.trace.TracerProvider = lambda **kw: _prov
        mock_otel.sdk.resources.Resource = type("R", (), {"create": staticmethod(lambda a: {})})
        mock_otel.sdk.trace.export.BatchSpanProcessor = lambda *a: None
        mock_otel.sdk.trace.export.ConsoleSpanExporter = lambda: None
        mock_otel.sdk.trace.sampling.ParentBasedTraceIdRatio = lambda r: None
        mock_otel.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter = lambda **kw: None

        def _inst(mod, name):
            monkeypatch.setitem(sys.modules, name, mod)
        _inst(mock_otel, "opentelemetry")
        _inst(mock_otel.trace, "opentelemetry.trace")
        _inst(mock_otel.sdk, "opentelemetry.sdk")
        _inst(mock_otel.sdk.resources, "opentelemetry.sdk.resources")
        _inst(mock_otel.sdk.trace, "opentelemetry.sdk.trace")
        _inst(mock_otel.sdk.trace.export, "opentelemetry.sdk.trace.export")
        _inst(mock_otel.sdk.trace.sampling, "opentelemetry.sdk.trace.sampling")
        _inst(mock_otel.exporter, "opentelemetry.exporter")
        _inst(mock_otel.exporter.otlp, "opentelemetry.exporter.otlp")
        _inst(mock_otel.exporter.otlp.proto, "opentelemetry.exporter.otlp.proto")
        _inst(mock_otel.exporter.otlp.proto.http, "opentelemetry.exporter.otlp.proto.http")
        _inst(mock_otel.exporter.otlp.proto.http.trace_exporter,
              "opentelemetry.exporter.otlp.proto.http.trace_exporter")

        monkeypatch.setattr("spacetime_memory.tracer._tracer", None)
        t = Tracer(enabled=True)
        t.setup()
        assert t._setup_done is True


class TestTracerSetupOtlpImportError:
    """Test the OTLP exporter ImportError fallback in setup()."""

    def test_otlp_exporter_import_error(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)

        import types

        # Build mock OTel modules WITHOUT the exporter sub-package
        # Use simple ModuleType without __getattr__ so sub-imports fail
        def _make(name):
            m = types.ModuleType(name)
            m.__package__ = name
            m.__path__ = [f"/fake/{name}"]
            return m

        import contextlib

        mock_otel = _make("opentelemetry")
        mock_trace = _make("opentelemetry.trace")
        mock_trace.set_tracer_provider = lambda p: None
        mock_trace.SpanKind = type("SpanKind", (), {"INTERNAL": "INTERNAL"})
        mock_trace.get_tracer = lambda *a: contextlib.nullcontext()

        mock_sdk = _make("opentelemetry.sdk")
        mock_sdk_res = _make("opentelemetry.sdk.resources")
        mock_sdk_res.Resource = type("R", (), {"create": staticmethod(lambda a: {})})
        mock_sdk_trace = _make("opentelemetry.sdk.trace")
        mock_sdk_trace.TracerProvider = lambda **kw: type(
            "_P", (), {"add_span_processor": lambda s, p: None}
        )()
        mock_sdk_export = _make("opentelemetry.sdk.trace.export")
        mock_sdk_export.BatchSpanProcessor = lambda *a: None
        mock_sdk_export.ConsoleSpanExporter = lambda: None
        mock_sdk_sampling = _make("opentelemetry.sdk.trace.sampling")
        mock_sdk_sampling.ParentBasedTraceIdRatio = lambda r: None

        # Manually set up module hierarchy to avoid auto-creating 'exporter'
        mock_otel.trace = mock_trace
        mock_otel.sdk = mock_sdk
        mock_sdk.resources = mock_sdk_res
        mock_sdk.trace = mock_sdk_trace
        mock_sdk_trace.export = mock_sdk_export
        mock_sdk_trace.sampling = mock_sdk_sampling

        modules = {
            "opentelemetry": mock_otel,
            "opentelemetry.trace": mock_trace,
            "opentelemetry.sdk": mock_sdk,
            "opentelemetry.sdk.resources": mock_sdk_res,
            "opentelemetry.sdk.trace": mock_sdk_trace,
            "opentelemetry.sdk.trace.export": mock_sdk_export,
            "opentelemetry.sdk.trace.sampling": mock_sdk_sampling,
        }
        for name, mod in modules.items():
            monkeypatch.setitem(sys.modules, name, mod)

        monkeypatch.setattr("spacetime_memory.tracer._tracer", None)

        # Remove the real exporter module from sys.modules if present
        for key in list(sys.modules):
            if key.startswith("opentelemetry.exporter"):
                monkeypatch.setitem(sys.modules, key, None)
                del sys.modules[key]

        t = Tracer(enabled=True)
        t.setup()
        assert t._setup_done is True


class TestTracerGetVersion:
    """Tests for Tracer._get_version()."""

    def test_get_version_success(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        monkeypatch.setattr("spacetime_memory.__version__", "1.2.3", raising=False)
        t = Tracer()
        assert t._get_version() == "1.2.3"

    def test_get_version_fallback(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        monkeypatch.setattr("spacetime_memory.__version__", None, raising=False)
        # Remove __version__ to cause ImportError
        import spacetime_memory
        monkeypatch.delattr(spacetime_memory, "__version__", raising=False)
        t = Tracer()
        assert t._get_version() == "0.0.0"


class TestTracerStartSpan:
    """Tests for Tracer.start_span()."""

    def test_start_span_disabled_yields_noop(self, monkeypatch):
        from spacetime_memory.tracer import Tracer, _NOOP_SPAN
        t = Tracer(enabled=False)
        with t.start_span("test") as span:
            assert span is _NOOP_SPAN

    def test_start_span_enabled_path(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=True)
        t._enabled = True
        # is_enabled is True because OTel is now installed
        with t.start_span("test") as span:
            assert span is not None


class TestTracerInstrumentMethod:
    """Tests for Tracer.instrument_method()."""

    def test_instrument_disabled_calls_directly(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        t = Tracer(enabled=False)
        called = False

        def target():
            nonlocal called
            called = True

        wrapped = t.instrument_method(target, span_name="test")
        wrapped()
        assert called

    def test_instrument_enabled_executes(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        import contextlib
        t = Tracer(enabled=True)
        t._enabled = True
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)
        monkeypatch.setattr(t, "start_span", lambda n, attributes=None: contextlib.nullcontext())
        called = False

        def target():
            nonlocal called
            called = True

        wrapped = t.instrument_method(target, span_name="test")
        wrapped()
        assert called

    def test_instrument_with_attr_fn(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        import contextlib
        t = Tracer(enabled=True)
        t._enabled = True
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)
        monkeypatch.setattr(t, "start_span", lambda n, attributes=None: contextlib.nullcontext())
        attr_fn_called = False

        def target(x, y=1):
            return x + y

        def attr_fn(*args, **kw):
            nonlocal attr_fn_called
            attr_fn_called = True
            return {"x": args[0] if args else kw.get("x", 0)}

        wrapped = t.instrument_method(target, span_name="test", attr_fn=attr_fn)
        result = wrapped(5, y=3)
        assert result == 8
        assert attr_fn_called

    def test_instrument_raises_preserves_error(self, monkeypatch):
        from spacetime_memory.tracer import Tracer
        import contextlib
        t = Tracer(enabled=True)
        t._enabled = True
        monkeypatch.setattr("spacetime_memory.tracer._check_otel_available", lambda: True)
        monkeypatch.setattr(t, "start_span", lambda n, attributes=None: contextlib.nullcontext())

        def target():
            raise ValueError("boom")

        wrapped = t.instrument_method(target, span_name="test")
        with pytest.raises(ValueError, match="boom"):
            wrapped()


class TestGetTracer:
    """Tests for module-level get_tracer()."""

    def test_get_tracer_first_call(self, monkeypatch):
        from spacetime_memory.tracer import get_tracer, _tracer
        monkeypatch.setattr("spacetime_memory.tracer._tracer", None)
        t = get_tracer(service_name="test-svc", setup=False)
        assert t._service_name == "test-svc"
        assert t._setup_done is False

    def test_get_tracer_returns_cached(self, monkeypatch):
        from spacetime_memory.tracer import get_tracer, Tracer
        cached = Tracer(service_name="cached")
        monkeypatch.setattr("spacetime_memory.tracer._tracer", cached)
        t = get_tracer(service_name="different")
        assert t is cached
        assert t._service_name == "cached"  # cached instance, not overridden

    def test_get_tracer_auto_setup(self, monkeypatch):
        from spacetime_memory.tracer import get_tracer
        monkeypatch.setattr("spacetime_memory.tracer._tracer", None)
        calls = []
        monkeypatch.setattr("spacetime_memory.tracer.Tracer.setup", lambda s: calls.append(1))
        t = get_tracer(setup=True)
        assert len(calls) == 1


class TestStartSpanModuleLevel:
    """Tests for the module-level start_span() convenience function."""

    def test_module_start_span(self, monkeypatch):
        from spacetime_memory.tracer import start_span, Tracer
        import contextlib
        mock_tracer = Tracer(enabled=True)
        monkeypatch.setattr(mock_tracer, "start_span",
                            lambda n, attributes=None: contextlib.nullcontext())
        monkeypatch.setattr("spacetime_memory.tracer._tracer", mock_tracer)
        with start_span("test") as span:
            pass
