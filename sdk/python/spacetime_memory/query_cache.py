"""
Query Cache — LRU cache for repeated search queries.

Caches search results keyed by (workspace_id, query, limit, strategies).
Uses an LRU eviction policy with configurable maxsize.

Thread-safe for use in multi-threaded environments (e.g., MCP servers).

Integrated into Client.search() via query_cache parameter.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any


class QueryCache:
    """LRU cache for search query results.

    Usage:
        cache = QueryCache(maxsize=128, ttl=300)
        key = cache.make_key(workspace_id, query, limit, strategies)
        results = cache.get(key)
        if results is None:
            results = client.search(...)
            cache.set(key, results)
    """

    def __init__(self, maxsize: int = 128, ttl: float = 300.0):
        """
        Args:
            maxsize: Maximum number of cached queries.
            ttl: Time-to-live in seconds (default 5 minutes).
        """
        self._cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self._ws_keys: dict[str, set[str]] = {}  # workspace_id → set of cache keys
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(workspace_id: str, query: str, limit: int, strategies: str = "") -> str:
        """Create a stable cache key from search parameters."""
        raw = f"{workspace_id}|{query}|{limit}|{strategies}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, key: str, workspace_id: str = "") -> list[dict[str, Any]] | None:
        """Retrieve cached results. Returns None on miss or expiry."""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            ts, results = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return results

    def set(self, key: str, results: list[dict[str, Any]], workspace_id: str = ""):
        """Store results in the cache."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), results)
            # Track workspace→key mapping for invalidation
            if workspace_id:
                self._ws_keys.setdefault(workspace_id, set()).add(key)
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)  # evict least recently used

    def invalidate(self, workspace_id: str | None = None):
        """Invalidate cache for a specific workspace, or all entries."""
        with self._lock:
            if workspace_id is None:
                self._cache.clear()
                self._ws_keys.clear()
            else:
                keys = self._ws_keys.pop(workspace_id, set())
                for k in keys:
                    self._cache.pop(k, None)

    def clear(self):
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()
            self._ws_keys.clear()

    @property
    def stats(self) -> dict[str, Any]:
        """Return cache hit/miss statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }

    def __len__(self) -> int:
        return len(self._cache)
