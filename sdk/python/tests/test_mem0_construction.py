"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_construction.py -v

"""

from __future__ import annotations

import os

import pytest
from mem0_shared import _uid

from spacetime_memory.sdks.mem0 import Memory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


class TestMem0Construction:
    """Construction and config."""

    def test_from_config(self, host: str, port: int) -> None:
        """Create via from_config classmethod."""
        m = Memory.from_config({"host": host, "port": port})
        assert isinstance(m, Memory)

    def test_close_is_idempotent(self, mem: Memory) -> None:
        """close is idempotent."""
        mem.close()
        mem.close()  # Should not raise

    def test_reset_clears_cache(self, mem: Memory) -> None:
        """reset clears internal state."""
        uid = _uid()
        mem.add("Reset test", user_id=uid)
        mem.reset()
        # Works fine after reset
        uid2 = _uid()
        result = mem.add("After reset", user_id=uid2)
        assert result["results"][0]["memory"] == "After reset"




class TestMem0ConfigVariants:
    """Constructor and config edge cases (lines 522-525, 542-543)."""

    def test_init_with_empty_dict(self, host: str, port: int) -> None:
        """Memory(config={}) uses defaults."""
        m = Memory(config={})
        assert isinstance(m, Memory)

    def test_init_with_pydantic_like(self, host: str, port: int) -> None:
        """Memory(config=...) with object that has model_dump()."""

        class FakeConfig:
            def model_dump(self):
                return {"host": host, "port": port}

        m = Memory(config=FakeConfig())
        assert isinstance(m, Memory)

    def test_init_with_none_config(self) -> None:
        """Memory() with no config hits else branch (line 525)."""
        m = Memory(config=None)
        assert isinstance(m, Memory)

    def test_init_with_llm_config(self, host: str, port: int) -> None:
        """Memory(config=...) with llm_config dict (lines 542-543)."""
        m = Memory(
            config={
                "host": host,
                "port": port,
                "llm_config": {"user1": {"model": "gpt-4", "api_key": "sk-test"}},
            }
        )
        assert isinstance(m, Memory)

    def test_init_llm_config_skips_non_dict(self, host: str, port: int) -> None:
        """Memory(config=...) with non-dict llm_config entries (line 542 is False)."""
        m = Memory(
            config={
                "host": host,
                "port": port,
                "llm_config": {"user1": "not-a-dict"},
            }
        )
        assert isinstance(m, Memory)




class TestMem0Unscoped:
    """Tests for unscoped (no user_id) operations."""

    def test_get_all_without_user_id(self, mem: Memory) -> None:
        """get_all() without user_id (lines 1169-1170)."""
        result = mem.get_all()
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_add_with_empty_filters(self, mem: Memory) -> None:
        """add() with empty filters dict hits _extract_ids_from_filters None path."""
        uid = _uid()
        result = mem.add("test", filters={}, user_id=uid)
        assert "results" in result




class TestMem0LLMConfig:
    """LLM config resolution tests."""

    def test_resolve_llm_for_with_override(self, mem: Memory) -> None:
        """_resolve_llm_for uses per-user override (line 599)."""
        uid = _uid()
        mem.set_llm_config(uid, {"model": "gpt-4", "api_key": "sk-test"})
        llm = mem._resolve_llm_for(uid)
        assert llm is not None

    def test_resolve_llm_with_config(self) -> None:
        """_resolve_llm with full config dict (line 486)."""
        from spacetime_memory.sdks.mem0 import _resolve_llm

        llm = _resolve_llm({"model": "gpt-4", "api_key": "sk-test", "base_url": "http://x"})
        assert llm is not None


