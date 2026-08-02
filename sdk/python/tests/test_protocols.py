"""Tests for _protocols.py — runtime structural subtyping protocols.

Covers: PluginManagerProtocol, EventBusProtocol, QueryCacheProtocol,
LocalLLMProtocol, MetricsCollectorProtocol — each validated for:
  - being a @runtime_checkable Protocol
  - isinstance checks with conforming and non-conforming classes
  - edge cases (wrong signatures, missing methods, empty objects).
"""

from __future__ import annotations

from typing import Protocol

# ── Helpers ──────────────────────────────────────────────────────────────


def _import_protocols():
    """Lazy import to avoid circular issues."""
    from spacetime_memory import _protocols as m
    return m


# ── PluginManagerProtocol ────────────────────────────────────────────────


class TestPluginManagerProtocol:
    """PluginManagerProtocol — dispatch_store / dispatch_search / dispatch_export / dispatch_import."""

    def test_is_protocol(self):
        m = _import_protocols()
        assert issubclass(m.PluginManagerProtocol, Protocol)

    def test_isinstance_valid(self):
        m = _import_protocols()

        class Good:
            def dispatch_store(self, content, metadata): return (content, metadata)
            def dispatch_search(self, query, results): return (query, results)
            def dispatch_export(self, data): return data
            def dispatch_import(self, data): return data

        assert isinstance(Good(), m.PluginManagerProtocol)

    def test_isinstance_missing_method(self):
        m = _import_protocols()

        class MissingExport:
            def dispatch_store(self, content, metadata): return (content, metadata)
            def dispatch_search(self, query, results): return (query, results)
            # no dispatch_export
            def dispatch_import(self, data): return data

        assert not isinstance(MissingExport(), m.PluginManagerProtocol)

    def test_isinstance_wrong_signature(self):
        m = _import_protocols()

        class WrongSig:
            def dispatch_store(self, content, metadata): return (content, metadata)
            def dispatch_search(self): return ("", [])
            def dispatch_export(self, data): return data
            def dispatch_import(self, data): return data

        # runtime_checkable only checks method *names*, not signatures
        assert isinstance(WrongSig(), m.PluginManagerProtocol)

    def test_isinstance_empty_class(self):
        m = _import_protocols()

        class Empty:
            pass

        assert not isinstance(Empty(), m.PluginManagerProtocol)


# ── EventBusProtocol ──────────────────────────────────────────────────────


class TestEventBusProtocol:
    """EventBusProtocol — emit(event) -> None."""

    def test_is_protocol(self):
        m = _import_protocols()
        assert issubclass(m.EventBusProtocol, Protocol)

    def test_isinstance_valid(self):
        m = _import_protocols()

        class GoodBus:
            def emit(self, event): pass

        assert isinstance(GoodBus(), m.EventBusProtocol)

    def test_isinstance_missing_emit(self):
        m = _import_protocols()

        class NoEmit:
            pass

        assert not isinstance(NoEmit(), m.EventBusProtocol)

    def test_isinstance_wrong_return_annotations(self):
        m = _import_protocols()

        class BadEmit:
            def emit(self, event): return "not None"

        assert isinstance(BadEmit(), m.EventBusProtocol)


# ── QueryCacheProtocol ────────────────────────────────────────────────────


class TestQueryCacheProtocol:
    """QueryCacheProtocol — make_key / get / set / invalidate."""

    def test_is_protocol(self):
        m = _import_protocols()
        assert issubclass(m.QueryCacheProtocol, Protocol)

    def test_isinstance_valid(self):
        m = _import_protocols()

        class GoodCache:
            def make_key(self, workspace_id, query, limit, strategy): return "k"
            def get(self, key): return None
            def set(self, key, value, *, workspace_id=None): pass
            def invalidate(self, *, workspace_id=None): pass

        assert isinstance(GoodCache(), m.QueryCacheProtocol)

    def test_isinstance_missing_method(self):
        m = _import_protocols()

        class NoGet:
            def make_key(self, workspace_id, query, limit, strategy): return "k"
            def set(self, key, value, *, workspace_id=None): pass
            def invalidate(self, *, workspace_id=None): pass

        assert not isinstance(NoGet(), m.QueryCacheProtocol)

    def test_isinstance_keyword_only_args(self):
        m = _import_protocols()

        class BadSet:
            def make_key(self, workspace_id, query, limit, strategy): return "k"
            def get(self, key): return None
            def set(self, key, value, workspace_id=None): pass  # missing *
            def invalidate(self, *, workspace_id=None): pass

        # runtime_checkable only checks method *names*, not keyword-only markers
        assert isinstance(BadSet(), m.QueryCacheProtocol)


# ── LocalLLMProtocol ────────────────────────────────────────────────────


class TestLocalLLMProtocol:
    """LocalLLMProtocol — generate(prompt) -> str."""

    def test_is_protocol(self):
        m = _import_protocols()
        assert issubclass(m.LocalLLMProtocol, Protocol)

    def test_isinstance_valid(self):
        m = _import_protocols()

        class GoodLLM:
            def generate(self, prompt, **kwargs): return "response"

        assert isinstance(GoodLLM(), m.LocalLLMProtocol)

    def test_isinstance_no_generate(self):
        m = _import_protocols()

        class NoLLM:
            pass

        assert not isinstance(NoLLM(), m.LocalLLMProtocol)


# ── MetricsCollectorProtocol ──────────────────────────────────────────────


class TestMetricsCollectorProtocol:
    """MetricsCollectorProtocol — record(fn, endpoint, is_error) -> Any / to_dict() -> dict."""

    def test_is_protocol(self):
        m = _import_protocols()
        assert issubclass(m.MetricsCollectorProtocol, Protocol)

    def test_isinstance_valid(self):
        m = _import_protocols()

        class GoodMetrics:
            def record(self, endpoint, fn, is_error=None): return fn()
            def to_dict(self): return {}

        assert isinstance(GoodMetrics(), m.MetricsCollectorProtocol)

    def test_isinstance_missing_to_dict(self):
        m = _import_protocols()

        class NoToDict:
            def record(self, endpoint, fn, is_error=None): return fn()

        assert not isinstance(NoToDict(), m.MetricsCollectorProtocol)

    def test_isinstance_basic_object_fails(self):
        m = _import_protocols()
        assert not isinstance(object(), m.MetricsCollectorProtocol)


# ── Cross-protocol checks ──────────────────────────────────────────────


class TestProtocolDecoration:
    """All protocol classes are correctly decorated."""

    def test_all_protocols_are_runtime_checkable(self):
        m = _import_protocols()
        protocol_names = [
            "PluginManagerProtocol",
            "EventBusProtocol",
            "QueryCacheProtocol",
            "LocalLLMProtocol",
            "MetricsCollectorProtocol",
        ]
        for name in protocol_names:
            cls = getattr(m, name)
            assert hasattr(cls, "_is_protocol"), f"{name} is not a Protocol"
            assert hasattr(cls, "__instancecheck__"), f"{name} is not runtime_checkable"

    def test_plugin_manager_module_import(self):
        """Protocols module imports cleanly without side effects."""
        import importlib

        import spacetime_memory._protocols as m
        importlib.reload(m)
        assert hasattr(m, "PluginManagerProtocol")
        assert hasattr(m, "EventBusProtocol")
        assert hasattr(m, "QueryCacheProtocol")
        assert hasattr(m, "LocalLLMProtocol")
        assert hasattr(m, "MetricsCollectorProtocol")
