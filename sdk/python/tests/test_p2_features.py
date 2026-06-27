"""Tests for P2 polish features: query cache, event bus, plugin manager, local LLM."""

from __future__ import annotations

import time


# ── QueryCache ──────────────────────────────────────────────────────────


def test_query_cache_basic():
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=4, ttl=30)
    key = cache.make_key("ws-1", "test query", 10, "semantic")
    cache.set(key, [{"id": "1", "score": 0.9}])
    result = cache.get(key)
    assert result is not None
    assert result[0]["id"] == "1"
    assert len(cache) == 1


def test_query_cache_lru_eviction():
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=2, ttl=60)
    for i in range(4):
        key = cache.make_key("ws-1", f"query-{i}", 10, "semantic")
        cache.set(key, [{"id": str(i)}])
    assert len(cache) == 2
    # First two should be evicted
    assert cache.get(cache.make_key("ws-1", "query-0", 10, "semantic")) is None
    assert cache.get(cache.make_key("ws-1", "query-1", 10, "semantic")) is None
    # Last two should remain
    assert cache.get(cache.make_key("ws-1", "query-2", 10, "semantic")) is not None
    assert cache.get(cache.make_key("ws-1", "query-3", 10, "semantic")) is not None


def test_query_cache_ttl_expiry():
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=4, ttl=0.01)  # 10ms TTL
    key = cache.make_key("ws-1", "test", 10, "semantic")
    cache.set(key, [{"id": "1"}])
    time.sleep(0.02)
    assert cache.get(key) is None


def test_query_cache_invalidate_workspace():
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=8, ttl=60)
    k1 = cache.make_key("ws-A", "q", 10, "semantic")
    k2 = cache.make_key("ws-B", "q", 10, "semantic")
    cache.set(k1, [{"id": "A"}], workspace_id="ws-A")
    cache.set(k2, [{"id": "B"}], workspace_id="ws-B")
    cache.invalidate(workspace_id="ws-A")
    assert cache.get(k1) is None
    assert cache.get(k2) is not None


def test_query_cache_stats():
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=4, ttl=60)
    key = cache.make_key("ws-1", "q", 10, "semantic")
    cache.get("nonexistent")  # miss
    cache.set(key, [{"id": "1"}])
    cache.get(key)  # hit
    stats = cache.stats
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_query_cache_clear():
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=4, ttl=60)
    cache.set(cache.make_key("ws-1", "q", 10, "semantic"), [{"id": "1"}])
    cache.clear()
    assert len(cache) == 0


def test_query_cache_set_existing_key():
    """set() on an existing key moves it to end (line 72) and setdefault reuses ws_keys."""
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=4, ttl=60)
    key = cache.make_key("ws-1", "q", 10, "semantic")
    cache.set(key, [{"id": "first"}], workspace_id="ws-1")
    # Set again with same key and workspace — triggers line 72 (move_to_end) and setdefault path
    cache.set(key, [{"id": "second"}], workspace_id="ws-1")
    result = cache.get(key)
    assert result[0]["id"] == "second"


def test_query_cache_invalidate_all():
    """invalidate with workspace_id=None clears everything (lines 84-85)."""
    from spacetime_memory.query_cache import QueryCache

    cache = QueryCache(maxsize=8, ttl=60)
    k1 = cache.make_key("ws-A", "q", 10, "semantic")
    k2 = cache.make_key("ws-B", "q", 10, "semantic")
    cache.set(k1, [{"id": "A"}], workspace_id="ws-A")
    cache.set(k2, [{"id": "B"}], workspace_id="ws-B")
    assert len(cache) == 2
    cache.invalidate()  # workspace_id=None → clear all
    assert len(cache) == 0
    assert cache.get(k1) is None
    assert cache.get(k2) is None


# ── EventBus ────────────────────────────────────────────────────────────


def test_event_bus_subscribe_and_emit():
    from spacetime_memory.streaming import EventBus, MemoryEvent

    received = []
    bus = EventBus()
    bus.subscribe("memory.created", lambda e: received.append(e.data))
    bus.emit(MemoryEvent("memory.created", data={"id": "mem-1"}))
    assert len(received) == 1
    assert received[0]["id"] == "mem-1"


def test_event_bus_wildcard_subscriber():
    from spacetime_memory.streaming import EventBus, MemoryEvent

    received = []
    bus = EventBus()
    bus.subscribe("*", lambda e: received.append(e.event_type))
    bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
    bus.emit(MemoryEvent("search.performed", data={"q": "test"}))
    assert received == ["memory.created", "search.performed"]


def test_event_bus_unsubscribe():
    from spacetime_memory.streaming import EventBus, MemoryEvent

    received = []
    bus = EventBus()

    def handler(e):
        received.append(e.data)

    bus.subscribe("memory.created", handler)
    bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
    assert len(received) == 1

    bus.unsubscribe("memory.created", handler)
    bus.emit(MemoryEvent("memory.created", data={"id": "2"}))
    assert len(received) == 1  # unchanged


def test_event_bus_handler_exception_isolated():
    from spacetime_memory.streaming import EventBus, MemoryEvent

    received = []
    bus = EventBus()

    def crashy(e):
        raise RuntimeError("boom")

    def good(e):
        received.append(e.data)

    bus.subscribe("memory.created", crashy)
    bus.subscribe("memory.created", good)
    bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
    assert received == [{"id": "1"}]  # good handler still ran


def test_event_bus_log():
    from spacetime_memory.streaming import EventBus, MemoryEvent

    bus = EventBus()
    bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
    bus.emit(MemoryEvent("memory.deleted", data={"id": "2"}))
    log = bus.get_log()
    assert len(log) == 2
    assert log[0]["event_type"] == "memory.deleted"  # most recent first


def test_event_bus_filter_log():
    from spacetime_memory.streaming import EventBus, MemoryEvent

    bus = EventBus()
    bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
    bus.emit(MemoryEvent("search.performed", data={"q": "x"}))
    filtered = bus.get_log(event_type="memory.created")
    assert len(filtered) == 1
    assert filtered[0]["data"]["id"] == "1"


def test_event_bus_subscriber_count():
    from spacetime_memory.streaming import EventBus

    bus = EventBus()
    bus.subscribe("memory.created", lambda e: None)
    bus.subscribe("search.performed", lambda e: None)
    bus.subscribe("*", lambda e: None)
    assert bus.subscriber_count == 3


def test_event_bus_trim_log():
    """Event log trims when exceeding max_log_size (line 107)."""
    from spacetime_memory.streaming import EventBus, MemoryEvent

    bus = EventBus()
    bus._max_log_size = 5
    for i in range(10):
        bus.emit(MemoryEvent("memory.created", data={"i": i}))
    assert bus.event_count == 5
    log = bus.get_log(limit=10)
    assert log[-1]["data"]["i"] == 5  # oldest retained


def test_event_bus_clear_log():
    """clear_log empties the event log (lines 125-126)."""
    from spacetime_memory.streaming import EventBus, MemoryEvent

    bus = EventBus()
    bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
    assert bus.event_count == 1
    bus.clear_log()
    assert bus.event_count == 0
    assert bus.get_log() == []


def test_event_bus_event_count():
    """event_count property returns log length (lines 157-158)."""
    from spacetime_memory.streaming import EventBus, MemoryEvent

    bus = EventBus()
    assert bus.event_count == 0
    bus.emit(MemoryEvent("memory.created"))
    bus.emit(MemoryEvent("memory.deleted"))
    assert bus.event_count == 2


# ── PluginManager ───────────────────────────────────────────────────────


def test_plugin_manager_register_and_list():
    from spacetime_memory.plugin_manager import PluginManager, FilterPlugin

    pm = PluginManager()
    pm.register(FilterPlugin(min_length=10))
    plugins = pm.list_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "filter"


def test_plugin_manager_unregister():
    from spacetime_memory.plugin_manager import PluginManager, FilterPlugin

    pm = PluginManager()
    pm.register(FilterPlugin(min_length=10))
    pm.unregister("filter")
    assert len(pm) == 0


def test_plugin_manager_dispatch_store_filter():
    """FilterPlugin catches ValueError and logs it — content passes through."""
    from spacetime_memory.plugin_manager import PluginManager, FilterPlugin

    pm = PluginManager()
    pm.register(FilterPlugin(min_length=5))
    # Content too short — FilterPlugin raises ValueError, dispatch catches it,
    # content passes through unchanged
    content, meta = pm.dispatch_store("ab", {"x": "y"})
    assert content == "ab"  # passes through unchanged after plugin fails


def test_plugin_manager_dispatch_store_chaining():
    from spacetime_memory.plugin_manager import PluginManager, BasePlugin

    class UppercasePlugin(BasePlugin):
        name = "uppercase"

        def on_store(self, content, metadata):
            return content.upper(), metadata

    pm = PluginManager()
    pm.register(UppercasePlugin())
    content, meta = pm.dispatch_store("hello", {"k": "v"})
    assert content == "HELLO"
    assert meta == {"k": "v"}


def test_plugin_manager_dispatch_search():
    from spacetime_memory.plugin_manager import PluginManager, BasePlugin

    class SortPlugin(BasePlugin):
        name = "sorter"

        def on_search(self, query, results):
            results.sort(key=lambda r: r.get("score", 0), reverse=True)
            return query, results

    pm = PluginManager()
    pm.register(SortPlugin())
    results = [{"score": 0.1}, {"score": 0.9}, {"score": 0.5}]
    _, sorted_results = pm.dispatch_search("q", results)
    assert [r["score"] for r in sorted_results] == [0.9, 0.5, 0.1]


def test_plugin_manager_dispatch_consolidate():
    from spacetime_memory.plugin_manager import PluginManager, BasePlugin

    class StatsPlugin(BasePlugin):
        name = "stats"

        def on_consolidate(self, workspace_id, stats):
            stats["processed_by"] = "stats_plugin"
            return stats

    pm = PluginManager()
    pm.register(StatsPlugin())
    result = pm.dispatch_consolidate("ws-1", {"reinforced": 5})
    assert result["processed_by"] == "stats_plugin"
    assert result["reinforced"] == 5


def test_plugin_manager_error_isolation():
    from spacetime_memory.plugin_manager import PluginManager, BasePlugin

    class CrashyPlugin(BasePlugin):
        name = "crashy"

        def on_store(self, content, metadata):
            raise RuntimeError("boom")

    class GoodPlugin(BasePlugin):
        name = "good"

        def on_store(self, content, metadata):
            metadata["processed"] = True
            return content, metadata

    pm = PluginManager()
    pm.register(CrashyPlugin())
    pm.register(GoodPlugin())
    content, meta = pm.dispatch_store("hello", {})
    assert meta.get("processed") is True  # good plugin still ran


# ── LocalLLM unit tests (model-free) ────────────────────────────────────


def test_local_llm_auto_no_models(tmp_path):
    """When no GGUF files exist, auto() returns unavailable instance."""
    from spacetime_memory.local_llm import LocalLLM
    import os
    from pathlib import Path
    from unittest.mock import patch

    # Ensure no models in search paths
    old_env = os.environ.pop("LOCAL_LLM_MODEL_PATH", None)
    try:
        with patch.object(Path, "home", return_value=tmp_path):
            llm = LocalLLM.auto()
            assert llm.available is False
    finally:
        if old_env:
            os.environ["LOCAL_LLM_MODEL_PATH"] = old_env


def test_local_llm_unavailable_generate_raises():
    from spacetime_memory.local_llm import LocalLLM

    llm = LocalLLM(model_path=None)
    try:
        llm.generate("test")
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "No local model loaded" in str(e)


def test_local_llm_summarize_fallback():
    """Summarize should return truncated content when model unavailable."""
    from spacetime_memory.local_llm import LocalLLM

    llm = LocalLLM(model_path=None)
    result = llm.summarize("a" * 300, max_length=50)
    assert len(result) <= 53  # 50 + "..."
    assert result.endswith("...")


def test_local_llm_extract_entities_fallback():
    """extract_entities returns empty list when unavailable."""
    from spacetime_memory.local_llm import LocalLLM

    llm = LocalLLM(model_path=None)
    result = llm.extract_entities("John works at Acme.")
    assert result == []


def test_local_llm_recommended_models_keys():
    from spacetime_memory.local_llm import RECOMMENDED_MODELS

    assert "minicpm5-1b" in RECOMMENDED_MODELS
    assert "qwen2.5-0.5b" in RECOMMENDED_MODELS
    assert "url" in RECOMMENDED_MODELS["minicpm5-1b"]


def test_local_llm_download_unknown_model():
    from spacetime_memory.local_llm import LocalLLM

    result = LocalLLM.download_model("nonexistent-model")
    assert result is None
