"""Supplementary tests for spacetime_memory.metrics._otel — OTel metrics bridge.

Primary tests live in test_metrics.py. This file adds coverage for
ImportError graceful degradation and edge cases using mocks instead of
real OTel SDK (to avoid dependency requirements).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestOtelMetricsMocked:
    """OTel metrics bridge tests with fully mocked imports.

    These tests do not require the opentelemetry SDK packages to be installed.
    """

    def _reset_state(self):
        """Reset the module-level globals before each test."""
        from spacetime_memory.metrics import _otel

        _otel._OTEL_METRICS_SETUP = False
        _otel._IN_MEMORY_METRIC_READER = None
        _otel._OTEL_INSTRUMENTS.clear()

    def test_setup_otel_disabled_by_env(self):
        """OTEL_METRICS_ENABLED=false prevents setup."""
        import os

        os.environ["OTEL_METRICS_ENABLED"] = "false"
        try:
            self._reset_state()
            from spacetime_memory.metrics._otel import is_otel_metrics_active, setup_otel_metrics

            result = setup_otel_metrics()
            assert result is False
            assert is_otel_metrics_active() is False
        finally:
            del os.environ["OTEL_METRICS_ENABLED"]

    def test_setup_otel_disabled_by_env_zero(self):
        """OTEL_METRICS_ENABLED=0 also disables."""
        import os

        os.environ["OTEL_METRICS_ENABLED"] = "0"
        try:
            self._reset_state()
            from spacetime_memory.metrics._otel import setup_otel_metrics

            result = setup_otel_metrics()
            assert result is False
        finally:
            del os.environ["OTEL_METRICS_ENABLED"]

    def test_setup_otel_import_error_graceful(self):
        """When OTel SDK is not installed, setup returns False."""
        self._reset_state()
        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.metrics": None,
            "opentelemetry.sdk.metrics.export": None,
        }, clear=False):
            from spacetime_memory.metrics._otel import setup_otel_metrics

            result = setup_otel_metrics()
            assert result is False

    def test_collect_otel_no_reader_returns_none(self):
        self._reset_state()
        from spacetime_memory.metrics._otel import collect_otel_metrics

        result = collect_otel_metrics()
        assert result is None

    def test_remove_metric_readers_no_reader_noop(self):
        self._reset_state()
        from spacetime_memory.metrics._otel import remove_otel_metric_readers

        # Should not raise
        remove_otel_metric_readers()

    def test_is_otel_inactive_by_default(self):
        self._reset_state()
        from spacetime_memory.metrics._otel import is_otel_metrics_active

        assert is_otel_metrics_active() is False

    def test_setup_otel_idempotent_marks_as_done(self):
        """When already set up, second call returns True."""
        from spacetime_memory.metrics import _otel

        self._reset_state()
        _otel._OTEL_METRICS_SETUP = True
        _otel._IN_MEMORY_METRIC_READER = MagicMock()

        from spacetime_memory.metrics._otel import setup_otel_metrics

        result = setup_otel_metrics()
        assert result is True

    def test_setup_with_mocked_otel_success(self):
        """Mock the full OTel setup path."""
        import spacetime_memory.metrics._otel as _otel_mod

        self._reset_state()

        mock_meter = MagicMock()
        mock_meter.create_counter.return_value = MagicMock()
        mock_meter.create_histogram.return_value = MagicMock()
        mock_meter.create_gauge.return_value = MagicMock()

        mock_mp = MagicMock()
        mock_mp.get_meter.return_value = mock_meter

        mock_reader = MagicMock()

        # OTel SDK is installed — the imports succeed naturally.
        # We pass a mock meter_provider so no real MeterProvider is created.
        with patch(
            "opentelemetry.sdk.metrics.export.InMemoryMetricReader",
            return_value=mock_reader,
        ):
            from spacetime_memory.metrics._otel import (
                is_otel_metrics_active,
                remove_otel_metric_readers,
                setup_otel_metrics,
            )

            result = setup_otel_metrics(meter_provider=mock_mp)
            assert result is True
            # is_active should be True after setup
            assert is_otel_metrics_active() is True
            assert _otel_mod._IN_MEMORY_METRIC_READER is not None

            remove_otel_metric_readers(meter_provider=mock_mp)

    def test_setup_otel_oserror_graceful(self):
        """OSError during setup returns False."""
        self._reset_state()
        # Make get_meter_provider() raise OSError when called.
        # The function imports MeterProvider inside, tries to get the
        # current provider, and that call raises OSError — caught internally.
        # To make the OSError propagate to the outer handler (which returns
        # False), also patch Resource.create() so the fallback also fails.
        with patch(
            "opentelemetry.metrics.get_meter_provider",
            side_effect=OSError("no resources"),
        ), patch(
            "opentelemetry.sdk.resources.Resource.create",
            side_effect=OSError("no resources"),
        ):
            from spacetime_memory.metrics._otel import setup_otel_metrics

            result = setup_otel_metrics()
            assert result is False

    def test_collect_otel_with_reader_empty_data(self):
        """collect_otel_metrics returns None when reader has no data."""
        self._reset_state()
        mock_reader = MagicMock()
        mock_reader.get_metrics_data.return_value = None

        from spacetime_memory.metrics import _otel

        _otel._IN_MEMORY_METRIC_READER = mock_reader

        from spacetime_memory.metrics._otel import collect_otel_metrics

        result = collect_otel_metrics()
        assert result is None

    def test_collect_otel_oserror_returns_none(self):
        """OSError during collect returns None."""
        self._reset_state()
        mock_reader = MagicMock()
        mock_reader.get_metrics_data.side_effect = OSError("read error")

        from spacetime_memory.metrics import _otel

        _otel._IN_MEMORY_METRIC_READER = mock_reader

        from spacetime_memory.metrics._otel import collect_otel_metrics

        result = collect_otel_metrics()
        assert result is None
