"""Plugin system for spacetime-memory.

Provides the abstract base class :class:`SpacetimePlugin` that all plugins
must subclass, and the :class:`PluginManager` that discovers, loads, and
manages plugins from a plugin directory.

Usage::

    from spacetime_memory import Client
    from spacetime_memory.plugin_manager import PluginManager

    client = Client()
    mgr = PluginManager(client, plugin_dir="plugins/")
    mgr.load_all()
    mgr.trigger("on_memory_stored", memory)
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Plugin base class
# ---------------------------------------------------------------------------


class SpacetimePlugin(ABC):
    """Abstract base class for spacetime-memory plugins.

    Subclasses **must** set ``name``, ``version``, and ``description`` at
    the class level, and implement ``on_load``.

    The remaining hook methods are optional — the manager will call them
    when triggered, but a plugin that doesn't override them simply does
    nothing.
    """

    name: str = ""
    version: str = ""
    description: str = ""

    @abstractmethod
    def on_load(self, client) -> None:
        """Called when the plugin is loaded.

        *client* is the ``spacetime_memory.Client`` instance.
        Use this to register reducers, start background tasks, etc.
        """
        ...

    def on_unload(self) -> None:
        """Called when the plugin is unloaded.

        Use this to clean up resources, stop threads, etc.
        """
        pass

    def on_memory_stored(self, memory) -> None:
        """Hook triggered after a memory is stored.

        *memory* is a dict-like representation of the stored memory.
        """
        pass

    def on_memory_retrieved(self, memory) -> None:
        """Hook triggered when a memory is retrieved."""
        pass

    def on_connector_event(self, event) -> None:
        """Hook triggered on connector events.

        *event* is a :class:`spacetime_memory.connectors.Event` instance.
        """
        pass


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class PluginManager:
    """Discovers, loads, and manages plugins.

    Args:
        client: A ``spacetime_memory.Client`` instance.
        plugin_dir: Directory to scan for plugins
            (default: ``~/.spacetime-memory/plugins``).

    Usage::

        mgr = PluginManager(client, plugin_dir="plugins/")
        mgr.load_all()
        for name, plugin in mgr.plugins.items():
            print(f"Loaded: {name} v{plugin.version}")
    """

    def __init__(
        self,
        client: Any,
        plugin_dir: str = "~/.spacetime-memory/plugins",
    ):
        self.client = client
        self.plugin_dir = os.path.abspath(os.path.expanduser(plugin_dir))
        self.plugins: dict[str, SpacetimePlugin] = {}
        self._discovered: dict[str, dict[str, Any]] = {}
        self._loaded_modules: dict[str, types.ModuleType] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[str]:
        """Scan *plugin_dir* and return names of discovered plugins.

        Discovers:
        - ``*.py`` files that define ``SpacetimePlugin`` subclasses
        - Subdirectories containing ``plugin.json`` or ``plugin.yaml``
          metadata files and a Python entry point (default ``main.py``)
        """
        self._discovered.clear()
        plugin_dir = Path(self.plugin_dir)

        if not plugin_dir.is_dir():
            return []

        for entry in sorted(plugin_dir.iterdir()):
            name = entry.name

            # Single-file plugin
            if entry.is_file() and name.endswith(".py"):
                if name.startswith("_"):
                    continue
                plugin_name = name[:-3]  # strip ``.py``
                self._discovered[plugin_name] = {
                    "type": "file",
                    "path": str(entry),
                    "metadata": {
                        "name": plugin_name,
                        "version": "0.0.0",
                        "description": "",
                    },
                }

            # Package plugin (directory with metadata)
            elif entry.is_dir() and not name.startswith("_"):
                meta = self._read_metadata(entry)
                if meta is not None:
                    plugin_name = meta.get("name", name)
                    self._discovered[plugin_name] = {
                        "type": "package",
                        "path": str(entry),
                        "metadata": meta,
                    }

        return list(self._discovered.keys())

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_metadata(dir_path: Path) -> dict[str, Any] | None:
        """Read ``plugin.json`` or ``plugin.yaml`` from a package directory.

        Requires ``__init__.py`` to exist as a package marker.
        Returns ``None`` if neither metadata file exists or both are unreadable.
        """
        init_path = dir_path / "__init__.py"
        if not init_path.is_file():
            return None  # not a valid plugin package

        json_path = dir_path / "plugin.json"
        yaml_path = dir_path / "plugin.yaml"

        if json_path.is_file():
            try:
                with open(json_path) as f:
                    meta: dict = json.load(f)
                meta.setdefault("name", dir_path.name)
                meta.setdefault("version", "0.0.0")
                meta.setdefault("description", "")
                meta.setdefault("entry_point", "main.py")
                meta.setdefault("dependencies", [])
                return meta
            except (json.JSONDecodeError, OSError) as e:
                print(
                    f"  [plugin] Warning: invalid plugin.json in {dir_path}: {e}"
                )
                return None

        if yaml_path.is_file():
            try:
                import yaml

                with open(yaml_path) as f:
                    meta_raw = yaml.safe_load(f) or {}
                # Normalise key "pip_dependencies" → "dependencies"
                if "pip_dependencies" in meta_raw:
                    meta_raw.setdefault(
                        "dependencies", meta_raw.pop("pip_dependencies")
                    )
                meta: dict = meta_raw
                meta.setdefault("name", dir_path.name)
                meta.setdefault("version", "0.0.0")
                meta.setdefault("description", "")
                meta.setdefault("entry_point", "main.py")
                meta.setdefault("dependencies", [])
                return meta
            except ImportError:
                print(
                    f"  [plugin] Warning: {yaml_path} found but PyYAML is not "
                    f"installed. Install with: pip install pyyaml"
                )
                return None
            except Exception as e:
                print(
                    f"  [plugin] Warning: invalid plugin.yaml in {dir_path}: {e}"
                )
                return None

        return None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _require_discovered(self) -> None:
        """Ensure discovery has run at least once."""
        if not self._discovered:
            self.discover()

    def load(self, name: str) -> bool:
        """Load a single plugin by name.

        Returns ``True`` on success, ``False`` if the plugin is not found
        or fails to load.
        """
        self._require_discovered()

        if name in self.plugins:
            return True  # already loaded

        info = self._discovered.get(name)
        if info is None:
            print(f"  [plugin] Plugin '{name}' not found in discovery.")
            return False

        # Resolve the module path
        if info["type"] == "file":
            module_path = info["path"]
            module_name = f"spacetime_plugin_{name}"
        else:
            pkg_path = Path(info["path"])
            entry = info["metadata"].get("entry_point", "main.py")
            candidate = pkg_path / entry
            # Fall back to __init__.py if the specified entry_point doesn't exist
            if not candidate.is_file():
                candidate = pkg_path / "__init__.py"
            if not candidate.is_file():
                print(
                    f"  [plugin] No entry point found in '{name}' "
                    f"(tried {entry}, __init__.py)"
                )
                return False
            module_path = str(candidate)
            module_name = f"spacetime_plugin_{name}"

        # Security: verify the module is within plugin_dir
        abs_module_path = os.path.abspath(module_path)
        abs_plugin_dir = os.path.abspath(self.plugin_dir)
        if not self._is_path_allowed(abs_module_path, abs_plugin_dir):
            print(
                f"  [plugin] Security: '{name}' at {abs_module_path} is "
                f"outside plugin_dir '{abs_plugin_dir}'. Skipping."
            )
            return False

        if not os.path.isfile(abs_module_path):
            print(f"  [plugin] Entry point not found: {abs_module_path}")
            return False

        # Install dependencies if requirements.txt exists
        if info["type"] == "package":
            req_path = os.path.join(info["path"], "requirements.txt")
            if os.path.isfile(req_path):
                try:
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "-r", req_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    print(f"  [plugin] Installed dependencies for '{name}'")
                except subprocess.CalledProcessError as e:
                    print(
                        f"  [plugin] Warning: failed to install deps "
                        f"for '{name}': {e}"
                    )

        # Import the module
        module = self._import_module(module_name, abs_module_path)
        if module is None:
            return False

        self._loaded_modules[name] = module

        # Find SpacetimePlugin subclass(es) in the module
        plugin_class = self._find_plugin_class(module)
        if plugin_class is None:
            print(
                f"  [plugin] No SpacetimePlugin subclass found in '{name}'"
            )
            self._cleanup_module(module_name, name)
            return False

        # Instantiate and initialise
        try:
            plugin_instance = plugin_class()
            plugin_instance.on_load(self.client)
            self.plugins[name] = plugin_instance
            print(f"  [plugin] Loaded '{name}' v{plugin_instance.version}")
            return True
        except Exception as e:
            print(f"  [plugin] Error initialising '{name}': {e}")
            import traceback

            traceback.print_exc()
            self._cleanup_module(module_name, name)
            return False

    def load_all(self) -> list[str]:
        """Discover and load all plugins.

        Returns the list of successfully loaded plugin names.
        """
        self.discover()
        loaded: list[str] = []
        for name in self._discovered:
            if self.load(name):
                loaded.append(name)
        return loaded

    def unload(self, name: str) -> bool:
        """Unload a specific plugin by name.

        Calls ``on_unload()``, removes from tracking, and cleans up the
        imported module.
        """
        plugin = self.plugins.pop(name, None)
        if plugin is None:
            return False

        try:
            plugin.on_unload()
        except Exception as e:
            print(f"  [plugin] Error during on_unload for '{name}': {e}")

        self._cleanup_module(
            getattr(self._loaded_modules.pop(name, None), "__name__", ""),
            name,
        )

        print(f"  [plugin] Unloaded '{name}'")
        return True

    def unload_all(self) -> None:
        """Unload all loaded plugins."""
        for name in list(self.plugins.keys()):
            self.unload(name)

    def get(self, name: str) -> Optional[SpacetimePlugin]:
        """Get a loaded plugin by name, or ``None`` if not loaded."""
        return self.plugins.get(name)

    def list(self) -> list[dict[str, Any]]:
        """List all discovered plugins with metadata.

        Returns a list of dicts with keys:
        ``name``, ``version``, ``description``, ``loaded``, ``type``, ``path``.
        """
        self._require_discovered()
        result: list[dict[str, Any]] = []
        for name, info in self._discovered.items():
            meta = info["metadata"]
            loaded = name in self.plugins
            plugin_ver = ""
            plugin_desc = ""
            if loaded:
                plugin_ver = self.plugins[name].version
                plugin_desc = self.plugins[name].description
            result.append({
                "name": name,
                "version": plugin_ver or meta.get("version", ""),
                "description": plugin_desc or meta.get("description", ""),
                "loaded": loaded,
                "type": info["type"],
                "path": info["path"],
            })
        return result

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def trigger(self, hook: str, *args: Any, **kwargs: Any) -> None:
        """Trigger a hook on all loaded plugins that implement it.

        Args:
            hook: Hook method name
                (e.g. ``"on_memory_stored"``, ``"on_memory_retrieved"``,
                ``"on_connector_event"``).
            *args, **kwargs: Passed to each plugin's hook method.

        .. note::
            ``on_load`` and ``on_unload`` are lifecycle hooks called
            automatically during load/unload — do **not** call them via
            ``trigger``.
        """
        for name, plugin in self.plugins.items():
            method = getattr(plugin, hook, None)
            if method is None:
                continue
            try:
                method(*args, **kwargs)
            except Exception as e:
                print(f"  [plugin] Hook '{hook}' failed in '{name}': {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_path_allowed(abs_path: str, abs_plugin_dir: str) -> bool:
        """Check that *abs_path* is within *abs_plugin_dir*."""
        norm_path = os.path.normpath(abs_path)
        norm_dir = os.path.normpath(abs_plugin_dir)
        # Allow files directly in plugin_dir or in subdirectories
        dirname = os.path.dirname(norm_path)
        return dirname == norm_dir or norm_path.startswith(norm_dir + os.sep)

    @staticmethod
    def _import_module(module_name: str, file_path: str) -> types.ModuleType | None:
        """Import a Python file as a module."""
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                print(
                    f"  [plugin] Could not create module spec for "
                    f"'{module_name}'"
                )
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            print(f"  [plugin] Import error: {e}")
            import traceback

            traceback.print_exc()
            return None

    @staticmethod
    def _find_plugin_class(module: types.ModuleType) -> type | None:
        """Find the first ``SpacetimePlugin`` subclass in *module*."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SpacetimePlugin)
                and attr is not SpacetimePlugin
            ):
                return attr
        return None

    @staticmethod
    def _cleanup_module(module_name: str, plugin_name: str) -> None:
        """Remove a dynamically imported module from ``sys.modules``."""
        if module_name and module_name in sys.modules:
            del sys.modules[module_name]
