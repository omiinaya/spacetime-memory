"""Tests for ReasoningTierMixin client wrappers.

Tests the Python SDK wrappers for reasoning tier operations
by mocking the underlying HTTP/STDB calls.
"""

from __future__ import annotations

import json

from spacetime_memory.client._reasoning_tiers import (
    DEFAULT_REASONING_TIERS,
    ReasoningTierMixin,
)


class QueryCounter:
    """Rotates through _query_return entries each time _query is called."""

    def __init__(self, entries: list):
        self.entries = entries
        self.index = 0

    def next(self) -> list[dict]:
        if self.index < len(self.entries):
            val = self.entries[self.index]
            self.index += 1
            return val if isinstance(val, list) else [val]
        return []


class MockClient(ReasoningTierMixin):
    """Minimal mock client that implements the ClientBase interface methods
    needed by ReasoningTierMixin."""

    def __init__(self):
        self._call_log: list[tuple[str, list]] = []
        self._query_log: list[tuple[str, str, dict | None]] = []
        self._query_return: list[dict] = []
        self._query_counter: QueryCounter | None = None

    def _call(self, reducer: str, args: list) -> dict:
        self._call_log.append((reducer, args))
        return {"status": "ok"}

    def _query(self, table: str, workspace_id: str = "", filter_dict: dict | None = None) -> list[dict]:
        self._query_log.append((table, workspace_id, filter_dict))
        if self._query_counter:
            return self._query_counter.next()
        return self._query_return

    def _sql(self, query: str) -> list[dict]:
        return []


class TestReasoningTierMixin:

    def test_default_tiers_constant(self):
        """Verify DEFAULT_REASONING_TIERS has all 4 expected tiers."""
        assert set(DEFAULT_REASONING_TIERS.keys()) == {"quick", "balanced", "deep", "research"}
        assert DEFAULT_REASONING_TIERS["balanced"]["is_default"] is True
        assert DEFAULT_REASONING_TIERS["quick"]["priority"] < DEFAULT_REASONING_TIERS["research"]["priority"]

    def test_create_reasoning_tier(self):
        """Test create_reasoning_tier passes correct args in correct order."""
        client = MockClient()
        result = client.create_reasoning_tier(
            "ws-123", "custom-tier", "Custom tier desc",
            max_tokens=512, temperature=0.5, top_p=0.8,
            max_context_memories=10, min_confidence=0.6,
            requires_reflection=True, requires_graph_traversal=False,
            priority=15, is_default=False,
        )
        assert result == {"status": "ok"}
        assert len(client._call_log) == 1
        reducer, args = client._call_log[0]
        assert reducer == "create_reasoning_tier"
        assert args[0] == "ws-123"        # workspace_id
        assert args[1] == ""              # peer_id (empty)
        assert args[2] == "custom-tier"   # name
        assert args[3] == "Custom tier desc"  # description
        assert args[4] == 512             # max_tokens
        assert args[5] == 0.5             # temperature
        assert args[6] == 0.8             # top_p
        assert args[7] == 10              # max_context_memories
        assert args[8] == 0.6             # min_confidence
        assert args[9] is True            # requires_reflection
        assert args[10] is False          # requires_graph_traversal
        assert args[11] == 15             # priority
        assert args[12] is False          # is_default

    def test_create_reasoning_tier_default_args(self):
        """Test create with defaults."""
        client = MockClient()
        client.create_reasoning_tier("ws-123", "quick")
        reducer, args = client._call_log[0]
        assert args[2] == "quick"           # name
        assert args[4] == 1024              # default max_tokens
        assert args[5] == 0.7               # default temperature

    def test_update_reasoning_tier(self):
        """Test update passes correct args."""
        client = MockClient()
        result = client.update_reasoning_tier(
            "ws-123", "tier-456",
            name="new-name", max_tokens=2048, is_default=True,
        )
        assert result == {"status": "ok"}
        reducer, args = client._call_log[0]
        assert reducer == "update_reasoning_tier"
        assert args[0] == "ws-123"
        assert args[1] == "tier-456"
        assert args[2] == "new-name"
        assert args[4] == 2048  # max_tokens at index 4
        assert args[12] is True  # is_default at index 12

    def test_delete_reasoning_tier(self):
        """Test delete passes correct args."""
        client = MockClient()
        result = client.delete_reasoning_tier("ws-123", "tier-456")
        assert result == {"status": "ok"}
        assert client._call_log[0] == ("delete_reasoning_tier", ["ws-123", "tier-456"])

    def test_get_reasoning_tiers(self):
        """Test get_reasoning_tiers returns parsed JSON from result table."""
        client = MockClient()
        tiers_data = [
            {"name": "quick", "priority": 10},
            {"name": "balanced", "priority": 20},
        ]
        client._query_return = [
            {"result_id": "r1", "data": json.dumps(tiers_data), "created_at": 100}
        ]
        result = client.get_reasoning_tiers("ws-123")
        assert result == tiers_data
        assert client._call_log[0] == ("get_reasoning_tiers", ["ws-123"])

    def test_get_reasoning_tiers_empty(self):
        """Test get_reasoning_tiers returns empty list on no data."""
        client = MockClient()
        client._query_return = []
        result = client.get_reasoning_tiers("ws-123")
        assert result == []

    def test_get_default_reasoning_tier(self):
        """Test get_default_reasoning_tier."""
        client = MockClient()
        tier_data = {"name": "balanced", "is_default": True}
        client._query_return = [
            {"result_id": "r1", "data": json.dumps(tier_data), "created_at": 100}
        ]
        result = client.get_default_reasoning_tier("ws-123")
        assert result == tier_data
        assert client._call_log[0] == ("get_default_reasoning_tier", ["ws-123"])

    def test_get_default_reasoning_tier_none(self):
        """Test get_default returns None when no data."""
        client = MockClient()
        client._query_return = [{"result_id": "r1", "data": "{}", "created_at": 100}]
        result = client.get_default_reasoning_tier("ws-123")
        assert result is None

    def test_set_default_tier(self):
        """Test set_default_tier passes correct args."""
        client = MockClient()
        result = client.set_default_tier("ws-123", "tier-456")
        assert result == {"status": "ok"}
        assert client._call_log[0] == ("set_default_tier", ["ws-123", "tier-456"])

    def test_apply_reasoning_tier_to_memory(self):
        """Test apply_reasoning_tier_to_memory passes correct args."""
        client = MockClient()
        result = client.apply_reasoning_tier_to_memory("ws-123", "mem-789", "tier-456")
        assert result == {"status": "ok"}
        assert client._call_log[0] == ("apply_reasoning_tier_to_memory", ["ws-123", "mem-789", "tier-456"])

    def test_get_reasoning_tier_config(self):
        """Test get_reasoning_tier_config returns dict keyed by name."""
        client = MockClient()
        tiers_data = [
            {"name": "quick", "max_tokens": 256, "priority": 10},
            {"name": "balanced", "max_tokens": 1024, "priority": 20},
        ]
        client._query_return = [
            {"result_id": "r1", "data": json.dumps(tiers_data), "created_at": 100}
        ]
        config = client.get_reasoning_tier_config("ws-123")
        assert "quick" in config
        assert "balanced" in config
        assert config["quick"]["max_tokens"] == 256
        assert config["balanced"]["max_tokens"] == 1024

    def test_select_tier_for_query_exact(self):
        """Test select_tier_for_query finds exact match."""
        client = MockClient()
        tiers_data = [
            {"name": "quick", "max_tokens": 256, "priority": 10, "is_default": False},
            {"name": "deep", "max_tokens": 4096, "priority": 30, "is_default": False},
        ]
        # set up rotating mock: first call returns tiers (list), second returns empty dict
        client._query_counter = QueryCounter([
            [{"result_id": "r1", "data": json.dumps(tiers_data), "created_at": 100}],
            [{"result_id": "r2", "data": "{}", "created_at": 200}],
        ])
        result = client.select_tier_for_query("ws-123", query_complexity="deep")
        assert result is not None
        assert result["name"] == "deep"
        assert result["max_tokens"] == 4096

    def test_select_tier_for_query_fallback(self):
        """Test select_tier_for_query falls back to default on unknown."""
        client = MockClient()
        tiers_data = [
            {"name": "balanced", "max_tokens": 1024, "is_default": True},
        ]
        # First call (get_reasoning_tier_config): returns tiers list
        # Second call (get_default_reasoning_tier): returns single tier
        client._query_counter = QueryCounter([
            [{"result_id": "r1", "data": json.dumps(tiers_data), "created_at": 100}],
            [{"result_id": "r2", "data": json.dumps({"name": "balanced"}), "created_at": 200}],
        ])
        result = client.select_tier_for_query("ws-123", query_complexity="unknown")
        assert result is not None
        assert result["name"] == "balanced"

    def test_balanced_tier_default_values(self):
        """Verify balanced tier has appropriate default values."""
        balanced = DEFAULT_REASONING_TIERS["balanced"]
        assert balanced["max_tokens"] == 1024
        assert balanced["temperature"] == 0.7
        assert balanced["is_default"] is True

    def test_research_tier_high_depth(self):
        """Verify research tier uses max depth settings."""
        research = DEFAULT_REASONING_TIERS["research"]
        assert research["max_tokens"] == 8192
        assert research["requires_reflection"] is True
        assert research["requires_graph_traversal"] is True
        assert research["temperature"] < 0.5
