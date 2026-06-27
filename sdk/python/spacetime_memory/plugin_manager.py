"""
Plugin Architecture — extensible plugin system for Spacetime Memory.

Plugins hook into the memory lifecycle (store, search, consolidate)
and can transform, filter, enrich, or export memory data.

Structure:
    - PluginManager: registry + lifecycle hooks
    - BasePlugin: abstract base class for plugins
    - Built-in plugin hooks: on_store, on_search, on_consolidate, on_export

Usage:
    from spacetime_memory import Client
    from spacetime_memory.plugin_manager import PluginManager, BasePlugin

    class MyPlugin(BasePlugin):
        def on_store(self, content, metadata):
            # transform content before storage
            return content, metadata

    pm = PluginManager()
    pm.register(MyPlugin())
    client = Client(plugin_manager=pm)
"""

from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BasePlugin(abc.ABC):
    """Abstract base class for Spacetime Memory plugins.

    Override any hook method to intercept the memory lifecycle.
    All hooks return the (possibly modified) data for chaining.
    """

    name: str = "base"
    version: str = "0.1.0"

    # ── Lifecycle hooks ──────────────────────────────────────────────

    def on_store(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Called before a memory is stored. Return (content, metadata)."""
        return content, metadata

    def on_search(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Called after search results are retrieved. Return (query, results)."""
        return query, results

    def on_consolidate(
        self,
        workspace_id: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Called after consolidation completes. Return (possibly modified) stats."""
        return stats

    def on_export(
        self,
        data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Called before data export. Return (possibly filtered/transformed) data."""
        return data

    def on_import(
        self,
        data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Called before data import. Return (possibly filtered/transformed) data."""
        return data


class CompressionPlugin(BasePlugin):
    """Built-in: compresses memory content with AAAK before storage."""

    name = "compression"
    version = "0.1.0"

    def on_store(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        try:
            from .aaak import aaak_compress

            if len(content) > 500:  # only compress longer content
                compressed = aaak_compress(content)
                metadata["compressed"] = True
                metadata["original_length"] = len(content)
                return compressed, metadata
        except ImportError:
            pass
        return content, metadata


class FilterPlugin(BasePlugin):
    """Built-in: filters out low-quality or duplicate content."""

    name = "filter"
    version = "0.1.0"

    def __init__(self, min_length: int = 10, max_length: int = 50000):
        super().__init__()
        self.min_length = min_length
        self.max_length = max_length

    def on_store(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if len(content) < self.min_length:
            raise ValueError(f"Content too short (min {self.min_length} chars)")
        if len(content) > self.max_length:
            content = content[: self.max_length]
        return content, metadata


class PluginManager:
    """Registry and lifecycle manager for Spacetime Memory plugins.

    Plugins are called in registration order for each hook.
    """

    def __init__(self):
        self._plugins: list[BasePlugin] = []

    def register(self, plugin: BasePlugin):
        """Register a plugin instance."""
        self._plugins.append(plugin)
        logger.info("Plugin registered: %s v%s", plugin.name, plugin.version)

    def unregister(self, plugin_name: str):
        """Unregister a plugin by name."""
        self._plugins = [p for p in self._plugins if p.name != plugin_name]

    def list_plugins(self) -> list[dict[str, str]]:
        """List registered plugins."""
        return [{"name": p.name, "version": p.version} for p in self._plugins]

    # ── Hook dispatchers ─────────────────────────────────────────────

    def dispatch_store(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Run all on_store hooks in order."""
        for plugin in self._plugins:
            try:
                content, metadata = plugin.on_store(content, metadata)
            except Exception as e:
                logger.warning("Plugin %s.on_store failed: %s", plugin.name, e)
        return content, metadata

    def dispatch_search(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run all on_search hooks in order."""
        for plugin in self._plugins:
            try:
                query, results = plugin.on_search(query, results)
            except Exception as e:
                logger.warning("Plugin %s.on_search failed: %s", plugin.name, e)
        return query, results

    def dispatch_consolidate(
        self,
        workspace_id: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Run all on_consolidate hooks in order."""
        for plugin in self._plugins:
            try:
                stats = plugin.on_consolidate(workspace_id, stats)
            except Exception as e:
                logger.warning("Plugin %s.on_consolidate failed: %s", plugin.name, e)
        return stats

    def dispatch_export(
        self,
        data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run all on_export hooks in order."""
        for plugin in self._plugins:
            try:
                data = plugin.on_export(data)
            except Exception as e:
                logger.warning("Plugin %s.on_export failed: %s", plugin.name, e)
        return data

    def dispatch_import(
        self,
        data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run all on_import hooks in order."""
        for plugin in self._plugins:
            try:
                data = plugin.on_import(data)
            except Exception as e:
                logger.warning("Plugin %s.on_import failed: %s", plugin.name, e)
        return data

    def __len__(self) -> int:
        return len(self._plugins)
