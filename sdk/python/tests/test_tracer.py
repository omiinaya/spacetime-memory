"""Tests for tracer.py — optional OpenTelemetry tracing wrapper.

Covers: get_tracer singleton, start_span no-op, Tracer init with env
vars, explicit disable, fallback when OTel packages missing.
"""

from __future__ import annotations

import os
from unittest.mock import ANY, MagicMock, patch

# ── get_tracer ──────────────────────────────────────────────────────────────


class TestGetTracer:
    """get_tracer() — global singleton access."""

    def test_returns_none_by_default(self):
        """Without setup=True, get_tracer() returns None."""
        import spacetime_memory.tracer as tmod

        with patch.object(tmod, "_TRACER", None):
            tracer = tmod.get_tracer(setup=False)
            assert tracer is None

    def test_setup_creates_instance(self):
        """With setup=True, get_tracer() returns an instance."""
        import spacetime_memory.tracer as tmod

        with patch.object(tmod, "_TRACER", None), patch.object(
            tmod.Tracer, "setup"
        ) as mock_setup:
            tracer = tmod.get_tracer(setup=True)
            assert tracer is not None
            mock_setup.assert_called_once()

    def test_singleton(self):
        """get_tracer() returns the same instance after setup."""
        import spacetime_memory.tracer as tmod

        with patch.object(tmod, "_TRACER", None), patch.object(tmod.Tracer, "setup"):
            t1 = tmod.get_tracer(setup=True)
            t2 = tmod.get_tracer(setup=True)
            assert t1 is t2


# ── start_span ──────────────────────────────────────────────────────────────


class TestStartSpan:
    """start_span() — no-op or real span context manager."""

    def test_noop_when_no_tracer(self):
        """Returns nullcontext() when _TRACER is None."""
        import spacetime_memory.tracer as tmod

        with patch.object(tmod, "_TRACER", None):
            cm = tmod.start_span("op")
            with cm:
                pass  # Should not raise

    def test_delegates_to_tracer_when_available(self):
        """Delegates to _TRACER.start_span when present."""
        import spacetime_memory.tracer as tmod

        mock_tracer = MagicMock()
        mock_cm = MagicMock()
        mock_tracer.start_span.return_value = mock_cm

        with patch.object(tmod, "_TRACER", mock_tracer):
            result = tmod.start_span("test_op", {"key": "val"})
            mock_tracer.start_span.assert_called_once_with(
                "test_op", {"key": "val"}
            )
            assert result is mock_cm


# ── _get_version ────────────────────────────────────────────────────────────


class TestGetVersion:
    """_get_version() — package version from metadata."""

    def test_returns_version_string(self):
        """Returns a non-empty version string."""
        from spacetime_memory.tracer import _get_version

        v = _get_version()
        assert isinstance(v, str)
        assert len(v) > 0

    def test_fallback_unknown_on_error(self):
        """Returns 'unknown' when metadata lookup fails."""
        from spacetime_memory.tracer import _get_version

        with patch(
            "importlib.metadata.version", side_effect=Exception("boom")
        ):
            assert _get_version() == "unknown"


# ── Tracer __init__ ─────────────────────────────────────────────────────────


class TestTracerInit:
    """Tracer.__init__() — environment variable parsing."""

    def test_defaults(self):
        """Default values from env vars."""
        with patch.dict(os.environ, {}, clear=True):
            from spacetime_memory.tracer import Tracer

            t = Tracer()
            assert t._otlp_endpoint == "http://localhost:4318"
            assert t._sampling_ratio == 1.0
            assert t._service_name == "spacetime-memory"

    def test_env_overrides(self):
        """Env vars override defaults."""
        env = {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel.example.com:4318",
            "OTEL_SAMPLING_RATIO": "0.5",
            "OTEL_SERVICE_NAME": "my-service",
        }
        with patch.dict(os.environ, env, clear=True):
            from spacetime_memory.tracer import Tracer

            t = Tracer()
            assert t._otlp_endpoint == "http://otel.example.com:4318"
            assert t._sampling_ratio == 0.5
            assert t._service_name == "my-service"

    def test_otel_endpoint_rstrip_slash(self):
        """Trailing slash is preserved as-is (no stripping)."""
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://example.com:4318/"},
            clear=True,
        ):
            from spacetime_memory.tracer import Tracer

            t = Tracer()
            assert t._otlp_endpoint == "http://example.com:4318/"


# ── Tracer.setup ────────────────────────────────────────────────────────────


class TestTracerSetup:
    """Tracer.setup() — one-shot initialisation."""

    def test_skipped_when_already_done(self):
        """Second call is a no-op."""
        with patch.dict(os.environ, {}, clear=True):
            from spacetime_memory.tracer import Tracer, logger

            t = Tracer()
            t._setup_done = True
            with patch.object(logger, "info") as mock_info:
                t.setup()
                mock_info.assert_not_called()

    def test_disabled_via_env(self):
        """OTEL_ENABLED=false skips setup."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}, clear=True):
            from spacetime_memory.tracer import Tracer

            t = Tracer()
            assert t._enabled is False
            with patch("spacetime_memory.tracer.logger") as mock_log:
                t.setup()
                mock_log.info.assert_called_once()
            assert t._setup_done is True

    def test_disabled_via_env_zero(self):
        """OTEL_ENABLED=0 also disables."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "0"}, clear=True):
            from spacetime_memory.tracer import Tracer

            t = Tracer()
            t.setup()
            assert t._setup_done is True

    def test_otel_packages_not_installed(self):
        """ImportError from OTel packages is caught gracefully."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}, clear=True):
            import spacetime_memory.tracer as tmod

            t = tmod.Tracer()
            with patch.object(
                tmod, "_check_otel_available", return_value=False
            ), patch.object(tmod, "logger") as mock_log:
                t.setup()
                mock_log.warning.assert_called()
            assert t._setup_done is True

    def test_console_exporter(self):
        """OTEL_TRACES_EXPORTER=console uses ConsoleSpanExporter."""
        env = {
            "OTEL_TRACES_EXPORTER": "console",
            "OTEL_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            import spacetime_memory.tracer as tmod

            t = tmod.Tracer()
            with patch.object(
                tmod, "_check_otel_available", return_value=True
            ), patch.object(tmod, "logger") as mock_log, patch.object(
                t, "_try_otlp_exporter"
            ):
                t.setup()
                assert t._setup_done is True
                mock_log.info.assert_any_call(
                    "OpenTelemetry tracing: console exporter"
                )


# ── Tracer._try_otlp_exporter ────────────────────────────────────────────────


class TestTryOtlpExporter:
    """_try_otlp_exporter() — OTLP connectivity and setup."""

    def test_otlp_exporter_not_installed(self):
        """ImportError for OTLP exporter is caught."""
        from spacetime_memory.tracer import Tracer

        t = Tracer()
        with patch("spacetime_memory.tracer.logger") as mock_log:
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "otlp" in name.lower():
                    raise ImportError("No OTLP exporter")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                t._try_otlp_exporter()

            mock_log.info.assert_called()

    def test_collector_not_reachable(self):
        """When collector is not reachable, logs info and returns."""
        from spacetime_memory.tracer import Tracer

        t = Tracer()
        t._otlp_endpoint = "http://localhost:4318"

        with patch("spacetime_memory.tracer.logger") as mock_log, patch(
            "httpx.get",
            side_effect=Exception("connection refused"),
        ):
            t._try_otlp_exporter()
            mock_log.warning.assert_called()

    def test_otlp_setup_on_reachable(self):
        """When collector is reachable, OTLP exporter is configured."""
        from spacetime_memory.tracer import Tracer

        t = Tracer()
        t._provider = MagicMock()
        t._otlp_endpoint = "http://localhost:4318"

        with patch("spacetime_memory.tracer.logger") as mock_log, patch(
            "httpx.get"
        ) as mock_get, patch(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"
        ) as mock_exporter_cls:
            mock_get.return_value = MagicMock(status_code=200)

            t._try_otlp_exporter()

            mock_exporter_cls.assert_called_once_with(
                endpoint="http://localhost:4318/v1/traces"
            )
            mock_log.info.assert_called()

    def test_otlp_reachable_with_500(self):
        """Status code >= 500 is treated as unreachable."""
        from spacetime_memory.tracer import Tracer

        t = Tracer()
        t._provider = MagicMock()
        t._otlp_endpoint = "http://localhost:4318"

        with patch("spacetime_memory.tracer.logger"), patch(
            "httpx.get"
        ) as mock_get, patch(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"
        ) as mock_exporter:
            mock_get.return_value = MagicMock(status_code=503)
            t._try_otlp_exporter()
            mock_exporter.assert_not_called()


# ── Tracer.start_span ────────────────────────────────────────────────────────


class TestTracerStartSpan:
    """Tracer.start_span() — span creation."""

    def test_noop_when_disabled(self):
        """When is_enabled is False, returns nullcontext-style no-op span."""
        from spacetime_memory.tracer import Tracer

        t = Tracer()
        # Force _enabled to False
        t._enabled = False

        with t.start_span("op") as span:
            assert span is not None

    def test_delegates_to_tracer_when_configured(self):
        """When _tracer is set, delegates to it."""
        from spacetime_memory.tracer import Tracer

        mock_tracer = MagicMock()
        mock_span_cm = MagicMock().__enter__.return_value
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = (
            mock_span_cm
        )

        t = Tracer()
        t._tracer = mock_tracer

        with patch(
            "spacetime_memory.tracer._check_otel_available", return_value=True
        ):
            with t.start_span("my_span", {"env": "test"}):
                pass
            mock_tracer.start_as_current_span.assert_called_once_with(
                "my_span",
                kind=ANY,
                attributes={"env": "test"},
            )


# ── Module-level aliases ─────────────────────────────────────────────────────


class TestModuleLevelWrapper:
    """Tracer class alias and module-level variables."""

    def test_tracer_alias(self):
        """Tracer is an alias for _Tracer."""
        from spacetime_memory.tracer import Tracer, _Tracer

        assert Tracer is _Tracer
