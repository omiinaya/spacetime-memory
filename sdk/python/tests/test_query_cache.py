"""
Unit tests for spacetime_memory.query_cache — QueryCache LRU cache.
"""
from __future__ import annotations

import time

import pytest

from spacetime_memory.query_cache import QueryCache


class TestMakeKey:
    """Tests for QueryCache.make_key()."""

    def test_basic(self):
        key = QueryCache.make_key("ws1", "hello world", 10, "bm25+vector")
        assert isinstance(key, str)
        assert len(key) == 32  # truncated sha256 hex

    def test_deterministic(self):
        k1 = QueryCache.make_key("ws1", "hello", 10, "bm25+vector")
        k2 = QueryCache.make_key("ws1", "hello", 10, "bm25+vector")
        assert k1 == k2

    def test_different_workspace(self):
        k1 = QueryCache.make_key("ws1", "hello", 10)
        k2 = QueryCache.make_key("ws2", "hello", 10)
        assert k1 != k2

    def test_different_query(self):
        k1 = QueryCache.make_key("ws1", "hello", 10)
        k2 = QueryCache.make_key("ws1", "world", 10)
        assert k1 != k2

    def test_different_limit(self):
        k1 = QueryCache.make_key("ws1", "hello", 10)
        k2 = QueryCache.make_key("ws1", "hello", 20)
        assert k1 != k2

    def test_different_strategies(self):
        k1 = QueryCache.make_key("ws1", "hello", 10, "bm25+vector")
        k2 = QueryCache.make_key("ws1", "hello", 10, "graph")
        assert k1 != k2

    def test_empty_defaults(self):
        key = QueryCache.make_key("", "", 0, "")
        assert isinstance(key, str)
        assert len(key) == 32


class TestInit:
    """Tests for QueryCache initialization."""

    def test_defaults(self):
        cache = QueryCache()
        assert cache._maxsize == 128
        assert cache._ttl == 300.0
        assert len(cache) == 0

    def test_custom_maxsize(self):
        cache = QueryCache(maxsize=50)
        assert cache._maxsize == 50

    def test_custom_ttl(self):
        cache = QueryCache(ttl=60.0)
        assert cache._ttl == 60.0


class TestGetSet:
    """Tests for get/set operations."""

    def test_set_and_get(self):
        cache = QueryCache()
        key = QueryCache.make_key("ws1", "hello", 10)
        results = [{"id": "1", "score": 0.9}]
        cache.set(key, results)
        assert cache.get(key) == results

    def test_miss_returns_none(self):
        cache = QueryCache()
        key = QueryCache.make_key("ws1", "hello", 10)
        assert cache.get(key) is None

    def test_set_multiple(self):
        cache = QueryCache()
        k1 = QueryCache.make_key("ws1", "a", 10)
        k2 = QueryCache.make_key("ws1", "b", 10)
        cache.set(k1, [{"id": "a"}])
        cache.set(k2, [{"id": "b"}])
        assert cache.get(k1) == [{"id": "a"}]
        assert cache.get(k2) == [{"id": "b"}]


class TestTTL:
    """Tests for TTL-based expiry."""

    def test_expired_returns_none(self):
        cache = QueryCache(ttl=0.01)
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "1"}])
        time.sleep(0.02)
        assert cache.get(key) is None

    def test_not_expired(self):
        cache = QueryCache(ttl=3600)
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "1"}])
        assert cache.get(key) == [{"id": "1"}]

    def test_expired_removed_from_cache(self):
        cache = QueryCache(ttl=0.01)
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "1"}])
        time.sleep(0.02)
        cache.get(key)  # triggers deletion
        assert len(cache) == 0


class TestLruEviction:
    """Tests for LRU eviction."""

    def test_eviction_when_full(self):
        cache = QueryCache(maxsize=3)
        for i in range(5):
            key = QueryCache.make_key("ws1", f"q{i}", 10)
            cache.set(key, [{"id": str(i)}])

        assert len(cache) == 3  # maxsize enforced
        # First items should be evicted
        k0 = QueryCache.make_key("ws1", "q0", 10)
        k1 = QueryCache.make_key("ws1", "q1", 10)
        assert cache.get(k0) is None
        assert cache.get(k1) is None
        # Last items should remain
        k4 = QueryCache.make_key("ws1", "q4", 10)
        assert cache.get(k4) is not None

    def test_lru_order_access_promotes(self):
        """Accessing a key promotes it, preventing eviction."""
        cache = QueryCache(maxsize=3)
        k0 = QueryCache.make_key("ws1", "q0", 10)
        k1 = QueryCache.make_key("ws1", "q1", 10)
        k2 = QueryCache.make_key("ws1", "q2", 10)
        cache.set(k0, [{"id": "0"}])
        cache.set(k1, [{"id": "1"}])
        cache.set(k2, [{"id": "2"}])

        # Access k0 to promote it
        cache.get(k0)

        # Add a new key, k1 should be evicted (least recently used: k1)
        k3 = QueryCache.make_key("ws1", "q3", 10)
        cache.set(k3, [{"id": "3"}])

        assert cache.get(k0) is not None  # promoted
        assert cache.get(k1) is None  # evicted
        assert cache.get(k2) is not None  # still there
        assert cache.get(k3) is not None  # new

    def test_set_existing_key_updates(self):
        cache = QueryCache(maxsize=3)
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "old"}])
        cache.set(key, [{"id": "new"}])
        assert cache.get(key) == [{"id": "new"}]
        assert len(cache) == 1  # no duplicate


class TestInvalidation:
    """Tests for cache invalidation."""

    def test_invalidate_workspace(self):
        cache = QueryCache()
        k1 = QueryCache.make_key("ws1", "a", 10)
        k2 = QueryCache.make_key("ws1", "b", 10)
        k3 = QueryCache.make_key("ws2", "c", 10)

        cache.set(k1, [{"id": "a"}], workspace_id="ws1")
        cache.set(k2, [{"id": "b"}], workspace_id="ws1")
        cache.set(k3, [{"id": "c"}], workspace_id="ws2")

        cache.invalidate(workspace_id="ws1")
        assert cache.get(k1) is None
        assert cache.get(k2) is None
        assert cache.get(k3) is not None  # ws2 unaffected

    def test_invalidate_all(self):
        cache = QueryCache()
        k1 = QueryCache.make_key("ws1", "a", 10)
        k2 = QueryCache.make_key("ws2", "b", 10)
        cache.set(k1, [{"id": "a"}])
        cache.set(k2, [{"id": "b"}])

        cache.invalidate(workspace_id=None)
        assert cache.get(k1) is None
        assert cache.get(k2) is None
        assert len(cache) == 0

    def test_invalidate_unknown_workspace(self):
        """Invalidating a workspace with no keys should not error."""
        cache = QueryCache()
        cache.invalidate(workspace_id="unknown")  # no error


class TestClear:
    """Tests for the clear() method."""

    def test_clear(self):
        cache = QueryCache()
        for i in range(5):
            key = QueryCache.make_key("ws1", f"q{i}", 10)
            cache.set(key, [{"id": str(i)}])
        assert len(cache) == 5
        cache.clear()
        assert len(cache) == 0

    def test_clear_resets_ws_keys(self):
        cache = QueryCache()
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "1"}], workspace_id="ws1")
        cache.clear()
        assert len(cache._ws_keys) == 0


class TestStats:
    """Tests for the stats property."""

    def test_initial_stats(self):
        cache = QueryCache()
        s = cache.stats
        assert s == {
            "size": 0,
            "maxsize": 128,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0.0,
        }

    def test_hits_and_misses(self):
        cache = QueryCache()
        k1 = QueryCache.make_key("ws1", "hello", 10)
        k2 = QueryCache.make_key("ws1", "world", 10)
        cache.set(k1, [{"id": "1"}])
        cache.set(k2, [{"id": "2"}])

        cache.get(k1)  # hit
        cache.get(k1)  # hit
        cache.get(k2)  # hit
        k3 = QueryCache.make_key("ws1", "other", 10)
        cache.get(k3)  # miss
        cache.get(k3)  # miss

        s = cache.stats
        assert s["hits"] == 3
        assert s["misses"] == 2
        assert s["hit_rate"] == 3 / 5
        assert s["size"] == 2

    def test_hit_rate_zero_divisions(self):
        """hit_rate should be 0.0 when no queries have been made."""
        cache = QueryCache()
        assert cache.stats["hit_rate"] == 0.0


class TestLen:
    """Tests for __len__."""

    def test_len_reflects_size(self):
        cache = QueryCache()
        assert len(cache) == 0
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "1"}])
        assert len(cache) == 1
        cache.clear()
        assert len(cache) == 0


class TestThreadSafety:
    """Tests for thread-safe operations."""

    def test_concurrent_sets(self):
        import threading

        cache = QueryCache(maxsize=200)

        def set_n(n):
            for i in range(n):
                key = QueryCache.make_key("ws1", f"q{i}", 10)
                cache.set(key, [{"id": str(i)}])

        t1 = threading.Thread(target=set_n, args=(50,))
        t2 = threading.Thread(target=set_n, args=(50,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(cache) > 0

    def test_concurrent_get_and_set(self):
        import threading

        cache = QueryCache(maxsize=200)
        key = QueryCache.make_key("ws1", "hello", 10)
        cache.set(key, [{"id": "shared"}])

        errors = []

        def worker():
            try:
                for _ in range(20):
                    cache.get(key)
                    cache.set(key, [{"id": "shared"}])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
