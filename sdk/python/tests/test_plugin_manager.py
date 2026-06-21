"""Tests for spacetime_memory.plugin_manager — PluginManager + BasePlugin + built-in plugins."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from spacetime_memory.plugin_manager import (
    BasePlugin,
    CompressionPlugin,
    FilterPlugin,
    PluginManager,
)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


class EchoPlugin(BasePlugin):
    """A test plugin that logs calls for verification."""

    name = "echo"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.calls = []

    def on_store(self, content, metadata):
        self.calls.append(("on_store", content, metadata))
        return f"[echo] {content}", metadata

    def on_search(self, query, results):
        self.calls.append(("on_search", query, results))
        return f"[echo] {query}", results

    def on_consolidate(self, workspace_id, stats):
        self.calls.append(("on_consolidate", workspace_id, stats))
        stats["echo"] = True
        return stats

    def on_export(self, data):
        self.calls.append(("on_export", data))
        return [{"echo": True, **d} for d in data]

    def on_import(self, data):
        self.calls.append(("on_import", data))
        return [{"echo": True, **d} for d in data]


class FaultyPlugin(BasePlugin):
    """A test plugin that raises exceptions on hooks."""

    name = "faulty"
    version = "0.0.1"

    def on_store(self, content, metadata):
        raise RuntimeError("store failure")

    def on_search(self, query, results):
        raise ValueError("search failure")

    def on_consolidate(self, workspace_id, stats):
        raise RuntimeError("consolidate failure")

    def on_export(self, data):
        raise RuntimeError("export failure")

    def on_import(self, data):
        raise RuntimeError("import failure")


# ═══════════════════════════════════════════════════════════════════
# BasePlugin
# ═══════════════════════════════════════════════════════════════════


class TestBasePlugin:
    """Tests for BasePlugin default implementations."""

    def test_default_name_and_version(self):
        """BasePlugin has default name and version."""
        plugin = BasePlugin()
        assert plugin.name == "base"
        assert plugin.version == "0.1.0"

    def test_on_store_default(self):
        """Default on_store returns content and metadata unchanged."""
        plugin = BasePlugin()
        content, metadata = plugin.on_store("hello", {"key": "val"})
        assert content == "hello"
        assert metadata == {"key": "val"}

    def test_on_search_default(self):
        """Default on_search returns query and results unchanged."""
        plugin = BasePlugin()
        query, results = plugin.on_search("q", [{"a": 1}])
        assert query == "q"
        assert results == [{"a": 1}]

    def test_on_consolidate_default(self):
        """Default on_consolidate returns stats unchanged."""
        plugin = BasePlugin()
        stats = plugin.on_consolidate("ws1", {"count": 5})
        assert stats == {"count": 5}

    def test_on_export_default(self):
        """Default on_export returns data unchanged."""
        plugin = BasePlugin()
        data = plugin.on_export([{"x": 1}])
        assert data == [{"x": 1}]

    def test_on_import_default(self):
        """Default on_import returns data unchanged."""
        plugin = BasePlugin()
        data = plugin.on_import([{"y": 2}])
        assert data == [{"y": 2}]

    def test_base_plugin_is_abstract(self):
        """BasePlugin can be instantiated but is abstract (ABC)."""
        # It's technically an ABC but can be instantiated since
        # it has no abstractmethods (all hooks have defaults).
        plugin = BasePlugin()
        assert isinstance(plugin, BasePlugin)


# ═══════════════════════════════════════════════════════════════════
# CompressionPlugin
# ═══════════════════════════════════════════════════════════════════


class TestCompressionPlugin:
    """Tests for CompressionPlugin.on_store()."""

    @pytest.fixture
    def plugin(self):
        return CompressionPlugin()

    def test_short_content_not_compressed(self, plugin):
        """Content <= 500 chars is returned unchanged."""
        content = "short" * 50  # 250 chars
        result_content, result_meta = plugin.on_store(content, {})
        assert result_content == content
        assert result_meta == {}

    def test_boundary_500_not_compressed(self, plugin):
        """Content exactly 500 chars is not compressed (len > 500 is condition)."""
        content = "a" * 500
        result_content, result_meta = plugin.on_store(content, {})
        assert result_content == content
        assert "compressed" not in result_meta

    def test_long_content_compressed_with_aaak(self, plugin):
        """Content > 500 chars is compressed when AAAK is available."""
        content = "b" * 600
        # The import is `from .aaak import aaak_compress`, which resolves
        # to spacetime_memory.aaak.aaak_compress at runtime.
        with patch(
            "spacetime_memory.aaak.aaak_compress",
            return_value="COMPRESSED_DATA",
        ) as mock_compress:
            result_content, result_meta = plugin.on_store(content, {})
            mock_compress.assert_called_once_with(content)
            assert result_content == "COMPRESSED_DATA"
            assert result_meta["compressed"] is True
            assert result_meta["original_length"] == 600

    def test_long_content_aaak_import_error(self, plugin):
        """When AAAK module lacks aaak_compress, ImportError is caught and content passes through."""
        content = "c" * 600

        # Ensure aaak is imported, then temporarily remove aaak_compress from it.
        # `from .aaak import aaak_compress` will raise ImportError when the
        # attribute is missing, exercising the except ImportError: pass path.
        import spacetime_memory.aaak as aaak_mod
        original = getattr(aaak_mod, "aaak_compress", None)
        if original is not None:
            del aaak_mod.aaak_compress
        try:
            result_content, result_meta = plugin.on_store(content, {})
            assert result_content == content
            assert result_meta == {}
        finally:
            if original is not None:
                aaak_mod.aaak_compress = original

    def test_long_content_aaak_missing_module(self, plugin):
        """Simulate AAAK module being absent entirely."""
        content = "c" * 600

        # Remove aaak from sys.modules and patch import
        with patch.dict("sys.modules", {}, clear=False):
            # The module import path is ".aaak" which resolves to
            # spacetime_memory.aaak. We'll just mock the import
            # to raise ImportError.
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if ".aaak" in name or name == "aaak":
                    raise ImportError(f"No module named '{name}'")
                return real_import(name, *args, **kwargs)

            with patch.object(builtins, "__import__", mock_import):
                result_content, result_meta = plugin.on_store(content, {})
                assert result_content == content
                assert result_meta == {}


# ═══════════════════════════════════════════════════════════════════
# FilterPlugin
# ═══════════════════════════════════════════════════════════════════


class TestFilterPlugin:
    """Tests for FilterPlugin.on_store()."""

    def test_default_min_max_lengths(self):
        """Default FilterPlugin has min_length=10, max_length=50000."""
        plugin = FilterPlugin()
        assert plugin.min_length == 10
        assert plugin.max_length == 50000
        assert plugin.name == "filter"

    def test_custom_min_max_lengths(self):
        """Custom FilterPlugin with user-specified limits."""
        plugin = FilterPlugin(min_length=5, max_length=100)
        assert plugin.min_length == 5
        assert plugin.max_length == 100

    def test_content_too_short_raises_value_error(self):
        """Content below min_length raises ValueError."""
        plugin = FilterPlugin(min_length=10)
        with pytest.raises(ValueError, match="Content too short"):
            plugin.on_store("abc", {})

    def test_content_too_short_custom_min(self):
        """Content below custom min_length raises ValueError."""
        plugin = FilterPlugin(min_length=5)
        with pytest.raises(ValueError, match="Content too short"):
            plugin.on_store("ab", {})

    def test_content_exactly_min_length_passes(self):
        """Content exactly at min_length is accepted."""
        plugin = FilterPlugin(min_length=5)
        content, meta = plugin.on_store("12345", {"x": 1})
        assert content == "12345"
        assert meta == {"x": 1}

    def test_content_too_long_truncated(self):
        """Content above max_length is truncated."""
        plugin = FilterPlugin(max_length=10)
        content, meta = plugin.on_store("123456789012345", {"key": "val"})
        assert content == "1234567890"  # first 10 chars
        assert meta == {"key": "val"}

    def test_content_at_max_length_passes(self):
        """Content exactly at max_length passes through."""
        plugin = FilterPlugin(max_length=10)
        content, meta = plugin.on_store("1234567890", {"a": "b"})
        assert content == "1234567890"
        assert meta == {"a": "b"}

    def test_content_within_bounds_passes(self):
        """Content within min/max bounds passes through unchanged."""
        plugin = FilterPlugin(min_length=5, max_length=20)
        content = "hello world"  # 11 chars
        result_content, result_meta = plugin.on_store(content, {"m": 1})
        assert result_content == content
        assert result_meta == {"m": 1}

    def test_min_length_zero(self):
        """min_length=0 accepts any content (including empty)."""
        plugin = FilterPlugin(min_length=0, max_length=100)
        content, meta = plugin.on_store("", {})
        assert content == ""
        assert meta == {}


# ═══════════════════════════════════════════════════════════════════
# PluginManager — registry
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerRegistry:
    """Tests for PluginManager registry operations."""

    def test_empty_manager(self):
        """New PluginManager has no plugins."""
        pm = PluginManager()
        assert len(pm) == 0
        assert pm.list_plugins() == []

    def test_register_single(self):
        """Register a single plugin."""
        pm = PluginManager()
        plugin = EchoPlugin()
        pm.register(plugin)
        assert len(pm) == 1
        assert pm.list_plugins() == [{"name": "echo", "version": "1.0.0"}]

    def test_register_multiple(self):
        """Register multiple plugins, order preserved."""
        pm = PluginManager()
        p1 = EchoPlugin()
        p2 = FilterPlugin()
        p3 = CompressionPlugin()
        pm.register(p1)
        pm.register(p2)
        pm.register(p3)
        assert len(pm) == 3
        names = [p["name"] for p in pm.list_plugins()]
        assert names == ["echo", "filter", "compression"]

    def test_register_same_plugin_twice(self):
        """Same instance can be registered multiple times."""
        pm = PluginManager()
        plugin = EchoPlugin()
        pm.register(plugin)
        pm.register(plugin)
        assert len(pm) == 2

    def test_unregister_by_name(self):
        """Unregister removes all plugins with matching name."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        pm.register(FilterPlugin())
        pm.register(EchoPlugin())  # second echo
        assert len(pm) == 3
        pm.unregister("echo")
        assert len(pm) == 1
        assert pm.list_plugins() == [{"name": "filter", "version": "0.1.0"}]

    def test_unregister_nonexistent_name(self):
        """Unregister a name not present — no error."""
        pm = PluginManager()
        pm.register(FilterPlugin())
        pm.unregister("nonexistent")
        assert len(pm) == 1

    def test_unregister_all(self):
        """Unregister last plugin — list becomes empty."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        pm.unregister("echo")
        assert len(pm) == 0
        assert pm.list_plugins() == []

    def test_list_plugins_empty(self):
        """list_plugins on empty manager returns empty list."""
        pm = PluginManager()
        assert pm.list_plugins() == []

    def test_len_zero(self):
        pm = PluginManager()
        assert len(pm) == 0

    def test_len_nonzero(self):
        pm = PluginManager()
        pm.register(EchoPlugin())
        pm.register(FilterPlugin())
        assert len(pm) == 2


# ═══════════════════════════════════════════════════════════════════
# PluginManager — dispatch_store
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerDispatchStore:
    """Tests for PluginManager.dispatch_store()."""

    def test_empty_plugins_noop(self):
        """dispatch_store with no plugins returns input unchanged."""
        pm = PluginManager()
        content, meta = pm.dispatch_store("hello", {"x": 1})
        assert content == "hello"
        assert meta == {"x": 1}

    def test_single_plugin_transform(self):
        """A single plugin transforms content."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        content, meta = pm.dispatch_store("world", {})
        assert content == "[echo] world"
        assert meta == {}

    def test_multiple_plugins_chain(self):
        """Multiple plugins chain their transforms."""
        pm = PluginManager()
        pm.register(EchoPlugin())  # adds "[echo] "
        pm.register(EchoPlugin())  # adds another "[echo] "
        content, meta = pm.dispatch_store("x", {"a": 1})
        assert content == "[echo] [echo] x"
        assert meta == {"a": 1}

    def test_faulty_plugin_not_blocking(self):
        """A plugin that raises an exception does not block others."""
        pm = PluginManager()
        pm.register(FaultyPlugin())  # raises RuntimeError
        pm.register(EchoPlugin())    # should still run
        content, meta = pm.dispatch_store("data", {"k": "v"})
        assert content == "[echo] data"
        assert meta == {"k": "v"}

    def test_all_faulty_plugins(self):
        """All plugins failing returns original content."""
        pm = PluginManager()
        pm.register(FaultyPlugin())
        pm.register(FaultyPlugin())
        content, meta = pm.dispatch_store("original", {"m": 1})
        assert content == "original"
        assert meta == {"m": 1}

    def test_filter_plugin_truncates_then_echo(self):
        """FilterPlugin truncates, then EchoPlugin wraps."""
        pm = PluginManager()
        pm.register(FilterPlugin(max_length=10))
        pm.register(EchoPlugin())
        content, meta = pm.dispatch_store("1234567890ABCDEF", {})
        # First filter truncates to 10 chars, then echo wraps
        assert content == "[echo] 1234567890"
        assert meta == {}


# ═══════════════════════════════════════════════════════════════════
# PluginManager — dispatch_search
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerDispatchSearch:
    """Tests for PluginManager.dispatch_search()."""

    def test_empty_plugins_noop(self):
        """dispatch_search with no plugins returns input unchanged."""
        pm = PluginManager()
        query, results = pm.dispatch_search("q", [{"score": 0.9}])
        assert query == "q"
        assert results == [{"score": 0.9}]

    def test_single_plugin_transform(self):
        """A single plugin transforms query."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        query, results = pm.dispatch_search("search query", [{"a": 1}])
        assert query == "[echo] search query"
        assert results == [{"a": 1}]

    def test_faulty_plugin_not_blocking(self):
        """Faulty plugin does not prevent chain execution."""
        pm = PluginManager()
        pm.register(FaultyPlugin())
        pm.register(EchoPlugin())
        query, results = pm.dispatch_search("q", [{"b": 2}])
        assert query == "[echo] q"
        assert results == [{"b": 2}]


# ═══════════════════════════════════════════════════════════════════
# PluginManager — dispatch_consolidate
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerDispatchConsolidate:
    """Tests for PluginManager.dispatch_consolidate()."""

    def test_empty_plugins_noop(self):
        """dispatch_consolidate with no plugins returns stats unchanged."""
        pm = PluginManager()
        stats = pm.dispatch_consolidate("ws1", {"count": 10})
        assert stats == {"count": 10}

    def test_single_plugin_transform(self):
        """Plugin adds data to stats."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        stats = pm.dispatch_consolidate("ws1", {"count": 10})
        assert stats == {"count": 10, "echo": True}

    def test_faulty_plugin_not_blocking(self):
        """Faulty plugin does not block chain."""
        pm = PluginManager()
        pm.register(FaultyPlugin())
        pm.register(EchoPlugin())
        stats = pm.dispatch_consolidate("ws1", {"count": 5})
        assert stats == {"count": 5, "echo": True}


# ═══════════════════════════════════════════════════════════════════
# PluginManager — dispatch_export
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerDispatchExport:
    """Tests for PluginManager.dispatch_export()."""

    def test_empty_plugins_noop(self):
        """dispatch_export with no plugins returns data unchanged."""
        pm = PluginManager()
        data = pm.dispatch_export([{"id": 1}, {"id": 2}])
        assert data == [{"id": 1}, {"id": 2}]

    def test_single_plugin_transform(self):
        """Plugin adds echo field to each record."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        data = pm.dispatch_export([{"id": 1}])
        assert data == [{"echo": True, "id": 1}]

    def test_faulty_plugin_not_blocking(self):
        """Faulty plugin does not block chain."""
        pm = PluginManager()
        pm.register(FaultyPlugin())
        pm.register(EchoPlugin())
        data = pm.dispatch_export([{"id": 1}])
        assert data == [{"echo": True, "id": 1}]


# ═══════════════════════════════════════════════════════════════════
# PluginManager — dispatch_import
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerDispatchImport:
    """Tests for PluginManager.dispatch_import()."""

    def test_empty_plugins_noop(self):
        """dispatch_import with no plugins returns data unchanged."""
        pm = PluginManager()
        data = pm.dispatch_import([{"id": 1}])
        assert data == [{"id": 1}]

    def test_single_plugin_transform(self):
        """Plugin adds echo field."""
        pm = PluginManager()
        pm.register(EchoPlugin())
        data = pm.dispatch_import([{"id": 2}])
        assert data == [{"echo": True, "id": 2}]

    def test_faulty_plugin_not_blocking(self):
        """Faulty plugin does not block chain."""
        pm = PluginManager()
        pm.register(FaultyPlugin())
        pm.register(EchoPlugin())
        data = pm.dispatch_import([{"id": 3}])
        assert data == [{"echo": True, "id": 3}]


# ═══════════════════════════════════════════════════════════════════
# Integration: all dispatch methods with mixed plugins
# ═══════════════════════════════════════════════════════════════════


class TestPluginManagerFullLifecycle:
    """Tests exercising all dispatch methods with real-ish plugin chains."""

    def test_full_lifecycle_with_plugins(self):
        """Register multiple plugins and exercise all dispatch methods."""
        pm = PluginManager()

        # Plugin that counts calls for verification
        class CountingPlugin(BasePlugin):
            name = "counter"
            version = "1.0"
            def __init__(self):
                super().__init__()
                self.count = 0
            def on_store(self, content, metadata):
                self.count += 1
                metadata["count"] = self.count
                return content, metadata
            def on_consolidate(self, workspace_id, stats):
                self.count += 1
                stats["counter_runs"] = True
                return stats

        pm.register(CountingPlugin())
        pm.register(EchoPlugin())

        # Store
        content, meta = pm.dispatch_store("test", {"initial": True})
        assert "[echo]" in content
        assert meta["initial"] is True
        assert meta["count"] == 1

        # Consolidate
        stats = pm.dispatch_consolidate("ws", {"items": 10})
        assert stats["echo"] is True
        assert stats["counter_runs"] is True

    def test_filter_then_compress_order(self):
        """Filter truncates first, then compression plugin runs."""
        pm = PluginManager()
        pm.register(FilterPlugin(max_length=501))  # longer than compression threshold
        pm.register(CompressionPlugin())           # compresses > 500 chars

        long_content = "x" * 600
        with patch(
            "spacetime_memory.aaak.aaak_compress",
            return_value="COMPRESSED",
        ):
            content, meta = pm.dispatch_store(long_content, {})
            # FilterPlugin truncates to 501 first, CompressionPlugin sees 501 > 500, compresses
            assert content == "COMPRESSED"
            assert meta["compressed"] is True
            assert meta["original_length"] == 501


class TestPluginManagerEdgeCases:
    """Edge cases for PluginManager."""

    def test_register_non_plugin(self):
        """Registering a non-BasePlugin still works (Python duck typing)."""
        pm = PluginManager()

        class FakePlugin:
            name = "fake"
            version = "0.0"
            def on_store(self, content, metadata):
                return f"fake:{content}", metadata
            def on_search(self, query, results):
                return query, results
            def on_consolidate(self, workspace_id, stats):
                return stats
            def on_export(self, data):
                return data
            def on_import(self, data):
                return data

        pm.register(FakePlugin())
        assert len(pm) == 1
        content, meta = pm.dispatch_store("hello", {})
        assert content == "fake:hello"

    def test_list_plugins_returns_dicts_with_correct_keys(self):
        """list_plugins returns dicts with 'name' and 'version' keys."""
        pm = PluginManager()
        pm.register(CompressionPlugin())
        pm.register(FilterPlugin())
        result = pm.list_plugins()
        assert len(result) == 2
        for entry in result:
            assert set(entry.keys()) == {"name", "version"}
            assert isinstance(entry["name"], str)
            assert isinstance(entry["version"], str)
