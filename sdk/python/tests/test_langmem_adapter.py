"""Tests for the LangMem-compatible adapter (``spacetime_memory.sdks.langmem``).

Unit tests use a fake ``BaseStore`` (no live STDB needed) so the tool and
manager logic is fully exercised. Integration tests (marked ``integration``)
require a live SpacetimeDB.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from spacetime_memory.sdks.langmem import (
    ExtractedMemory,
    MemoryPhase,
    Prompt,
    ReflectionExecutor,
    create_manage_memory_tool,
    create_memory_manager,
    create_memory_searcher,
    create_memory_store_manager,
    create_multi_prompt_optimizer,
    create_prompt_optimizer,
    create_search_memory_tool,
    create_thread_extractor,
)


# ---------------------------------------------------------------------------
# Fake BaseStore (records put/get/delete/search ops, no network)
# ---------------------------------------------------------------------------


@dataclass
class FakeItem:
    namespace: list[str]
    key: str
    value: dict[str, Any]
    created_at: str = ""
    updated_at: str = ""
    score: float | None = None

    def dict(self) -> dict[str, Any]:
        return {
            "namespace": list(self.namespace),
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "score": self.score,
        }


class FakeStore:
    """Minimal BaseStore-compatible in-memory store."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, ...], dict[str, FakeItem]] = {}
        self.ops: list[str] = []

    def _norm(self, namespace: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        return tuple(namespace)

    def put(self, namespace, key, value) -> None:
        ns = self._norm(namespace)
        self.items.setdefault(ns, {})[key] = FakeItem(list(ns), key, value)
        self.ops.append(f"put:{'/'.join(ns)}:{key}")

    async def aput(self, namespace, key, value) -> None:
        self.put(namespace, key, value)

    def get(self, namespace, key) -> FakeItem | None:
        return self.items.get(self._norm(namespace), {}).get(key)

    async def aget(self, namespace, key) -> FakeItem | None:
        return self.get(namespace, key)

    def delete(self, namespace, key) -> None:
        ns = self._norm(namespace)
        if key in self.items.get(ns, {}):
            del self.items[ns][key]
            self.ops.append(f"delete:{'/'.join(ns)}:{key}")

    async def adelete(self, namespace, key) -> None:
        self.delete(namespace, key)

    def search(self, namespace, *, query=None, filter=None, limit=10, offset=0) -> list[FakeItem]:
        ns = self._norm(namespace)
        # prefix match on namespace
        items = []
        for n, d in self.items.items():
            if len(n) >= len(ns) and n[: len(ns)] == ns:
                items.extend(d.values())
        return items[offset : offset + limit]

    async def asearch(self, namespace, *, query=None, filter=None, limit=10, offset=0) -> list[FakeItem]:
        return self.search(namespace, query=query, filter=filter, limit=limit, offset=offset)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


# ---------------------------------------------------------------------------
# create_manage_memory_tool
# ---------------------------------------------------------------------------


class TestManageMemoryTool:
    def test_create_action(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        result = tool.invoke({"content": "Alice likes pizza", "action": "create"})
        assert result.startswith("created memory ")
        mem_id = result.split()[-1]
        ns = ("memories", "alice")
        item = store.get(ns, mem_id)
        assert item is not None
        assert item.value["content"] == "Alice likes pizza"

    def test_create_async(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        result = asyncio.run(tool.ainvoke({"content": "sync test", "action": "create"}))
        assert result.startswith("created memory ")

    def test_update_action(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        mem_id = str(uuid.uuid4())
        store.put(("memories", "alice"), mem_id, {"content": "old"})
        result = tool.invoke({"content": "new content", "action": "update", "id": mem_id})
        assert result == f"updated memory {mem_id}"
        assert store.get(("memories", "alice"), mem_id).value["content"] == "new content"

    def test_delete_action(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        mem_id = str(uuid.uuid4())
        store.put(("memories", "alice"), mem_id, {"content": "doomed"})
        result = tool.invoke({"action": "delete", "id": mem_id})
        assert result == f"Deleted memory {mem_id}"
        assert store.get(("memories", "alice"), mem_id) is None

    def test_create_with_id_raises(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="cannot provide a MEMORY ID"):
            tool.invoke({"content": "x", "action": "create", "id": str(uuid.uuid4())})

    def test_update_without_id_raises(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="must provide a MEMORY ID"):
            tool.invoke({"content": "x", "action": "update"})

    def test_invalid_action_raises(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="Invalid action"):
            tool.invoke({"content": "x", "action": "bogus"})

    def test_empty_actions_permitted_raises(self) -> None:
        with pytest.raises(ValueError, match="actions_permitted cannot be empty"):
            create_manage_memory_tool(
                namespace=("memories",),
                actions_permitted=(),  # type: ignore[arg-type]
            )

    def test_actions_permitted_limits(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "bob"),
            actions_permitted=("create",),
            store=store,  # type: ignore[arg-type]
        )
        mem_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match="Invalid action"):
            tool.invoke({"action": "delete", "id": mem_id})

    def test_namespace_template_resolution(self, store: FakeStore) -> None:
        tool = create_manage_memory_tool(
            namespace=("memories", "{langgraph_user_id}"),
            store=store,  # type: ignore[arg-type]
        )
        result = tool.invoke(
            {"content": "team pref", "action": "create"},
            config={"configurable": {"langgraph_user_id": "user-123"}},
        )
        mem_id = result.split()[-1]
        # StructuredTool passes config through to the function when the
        # function declares a config param
        assert store.get(("memories", "user-123"), mem_id) is not None

    def test_schema_serialization(self, store: FakeStore) -> None:
        class Profile:  # pydantic-like
            def __init__(self, name: str) -> None:
                self.name = name

            def model_dump(self, mode: str = "python") -> dict[str, Any]:
                return {"name": self.name}

        tool = create_manage_memory_tool(
            namespace=("memories", "alice"),
            schema=Profile,
            store=store,  # type: ignore[arg-type]
        )
        result = tool.invoke({"content": Profile("Ada"), "action": "create"})
        mem_id = result.split()[-1]
        item = store.get(("memories", "alice"), mem_id)
        assert item.value["content"] == {"name": "Ada"}


# ---------------------------------------------------------------------------
# create_search_memory_tool
# ---------------------------------------------------------------------------


class TestSearchMemoryTool:
    def test_search_returns_json(self, store: FakeStore) -> None:
        store.put(("memories", "alice"), "m1", {"content": "likes pizza"})
        store.put(("memories", "alice"), "m2", {"content": "likes hiking"})
        tool = create_search_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        raw = tool.invoke({"query": "food", "limit": 10})
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_search_content_and_artifact(self, store: FakeStore) -> None:
        store.put(("memories", "alice"), "m1", {"content": "likes pizza"})
        tool = create_search_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
            response_format="content_and_artifact",
        )
        raw, artifacts = tool.invoke({"query": "pizza", "limit": 10})
        assert isinstance(raw, str)
        assert len(artifacts) == 1
        assert artifacts[0].key == "m1"

    def test_search_limit_offset(self, store: FakeStore) -> None:
        for i in range(5):
            store.put(("memories", "alice"), f"m{i}", {"content": f"memory {i}"})
        tool = create_search_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        data = json.loads(tool.invoke({"query": "", "limit": 2, "offset": 1}))
        assert len(data) == 2

    def test_search_async(self, store: FakeStore) -> None:
        store.put(("memories", "alice"), "m1", {"content": "async memory"})
        tool = create_search_memory_tool(
            namespace=("memories", "alice"),
            store=store,  # type: ignore[arg-type]
        )
        raw = asyncio.run(tool.ainvoke({"query": "async", "limit": 10}))
        data = json.loads(raw)
        assert len(data) == 1


# ---------------------------------------------------------------------------
# create_memory_manager / store_manager / searcher (LLM not configured → no-op)
# ---------------------------------------------------------------------------


class _NullLLM:
    """LLM stub that returns a fixed JSON extraction result."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.available = True
        self.calls = 0

    def chat(self, messages, **kwargs) -> str | None:
        self.calls += 1
        return self.payload


class TestMemoryManager:
    def test_manager_persists_extracted_memories(self, store: FakeStore) -> None:
        payload = json.dumps(
            [
                {"id": "mem-1", "kind": "insert", "content": "User loves Python"},
                {"id": "mem-2", "kind": "insert", "content": "User works at Acme"},
            ]
        )
        llm = _NullLLM(payload)
        manager = create_memory_manager("test-model", llm=llm, store=store)  # type: ignore[arg-type]
        result = manager.invoke(
            {"messages": [{"role": "user", "content": "I love Python and work at Acme"}]},
            config={"configurable": {"langgraph_user_id": "user-1"}},
        )
        assert len(result) == 2
        assert all(m.kind == "insert" for m in result)
        assert store.get(("memories", "user-1"), "mem-1") is not None
        assert store.get(("memories", "user-1"), "mem-2") is not None

    def test_manager_async(self, store: FakeStore) -> None:
        payload = json.dumps([{"id": "mem-x", "kind": "insert", "content": "async fact"}])
        llm = _NullLLM(payload)
        manager = create_memory_manager("test-model", llm=llm, store=store)  # type: ignore[arg-type]
        result = asyncio.run(
            manager.ainvoke(
                {"messages": [{"role": "user", "content": "async fact here"}]},
                config={"configurable": {"langgraph_user_id": "u2"}},
            )
        )
        assert len(result) == 1
        assert store.get(("memories", "u2"), "mem-x") is not None

    def test_manager_handles_llm_garbage(self, store: FakeStore) -> None:
        llm = _NullLLM("not json at all")
        manager = create_memory_manager("test-model", llm=llm, store=store)  # type: ignore[arg-type]
        result = manager.invoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"langgraph_user_id": "u3"}},
        )
        assert result == []

    def test_manager_no_llm_returns_empty(self, store: FakeStore) -> None:
        manager = create_memory_manager("test-model", store=store)  # no llm → not available
        result = manager.invoke({"messages": [{"role": "user", "content": "x"}]})
        assert result == []

    def test_manager_delete_operation(self, store: FakeStore) -> None:
        store.put(("memories", "u4"), "old-1", {"content": "stale"})
        payload = json.dumps([{"id": "old-1", "kind": "delete"}])
        llm = _NullLLM(payload)
        manager = create_memory_manager("test-model", llm=llm, store=store)  # type: ignore[arg-type]
        result = manager.invoke(
            {"messages": [{"role": "user", "content": "remove old fact"}]},
            config={"configurable": {"langgraph_user_id": "u4"}},
        )
        assert result[0].kind == "delete"
        assert store.get(("memories", "u4"), "old-1") is None


class TestMemoryStoreManager:
    def test_store_manager_persists_with_history(self, store: FakeStore) -> None:
        payload = json.dumps([{"id": "m-1", "kind": "insert", "content": "new fact"}])
        llm = _NullLLM(payload)
        manager = create_memory_store_manager("test-model", llm=llm, store=store)  # type: ignore[arg-type]
        result = manager.invoke(
            {"messages": [{"role": "user", "content": "new fact"}]},
            config={"configurable": {"langgraph_user_id": "u5"}},
        )
        assert len(result) == 1
        assert store.get(("memories", "u5"), "m-1") is not None
        # history namespace has the versioned copy
        assert store.get(("memories", "u5", "__history__"), "m-1") is not None

    def test_store_manager_searches_existing(self, store: FakeStore) -> None:
        store.put(("memories", "u6"), "existing-1", {"content": "existing fact"})
        payload = json.dumps([{"id": "existing-1", "kind": "update", "content": "updated fact"}])
        llm = _NullLLM(payload)
        manager = create_memory_store_manager("test-model", llm=llm, store=store)  # type: ignore[arg-type]
        result = manager.invoke(
            {"messages": [{"role": "user", "content": "updated fact"}]},
            config={"configurable": {"langgraph_user_id": "u6"}},
        )
        assert result[0].kind == "update"
        assert store.get(("memories", "u6"), "existing-1").value["content"] == "updated fact"


class TestMemorySearcher:
    def test_searcher_returns_memories(self, store: FakeStore) -> None:
        store.put(("memories", "u7"), "m1", {"content": "likes chess"})
        store.put(("memories", "u7"), "m2", {"content": "likes go"})
        searcher = create_memory_searcher("test-model", store=store)  # type: ignore[arg-type]
        result = searcher.invoke(
            {"query": "chess", "limit": 10},
            config={"configurable": {"langgraph_user_id": "u7"}},
        )
        assert len(result) == 2


# ---------------------------------------------------------------------------
# create_thread_extractor
# ---------------------------------------------------------------------------


class TestThreadExtractor:
    def test_extractor_default_schema(self) -> None:
        payload = json.dumps({"title": "Password Help", "summary": "User reset password"})
        llm = _NullLLM(payload)
        extractor = create_thread_extractor("test-model", llm=llm)  # type: ignore[arg-type]
        result = extractor.invoke(
            {
                "messages": [
                    {"role": "user", "content": "I can't reset my password"},
                    {"role": "assistant", "content": "Let me help you."},
                ]
            }
        )
        assert result["title"] == "Password Help"
        assert result["summary"] == "User reset password"

    def test_extractor_no_llm_returns_default(self) -> None:
        extractor = create_thread_extractor("test-model")  # no llm
        result = extractor.invoke({"messages": [{"role": "user", "content": "x"}]})
        assert "title" in result and "summary" in result

    def test_extractor_async(self) -> None:
        payload = json.dumps({"title": "T", "summary": "S"})
        llm = _NullLLM(payload)
        extractor = create_thread_extractor("test-model", llm=llm)  # type: ignore[arg-type]
        result = asyncio.run(
            extractor.ainvoke({"messages": [{"role": "user", "content": "hello"}]})
        )
        assert result["title"] == "T"


# ---------------------------------------------------------------------------
# Prompt optimization + ReflectionExecutor
# ---------------------------------------------------------------------------


class TestPromptOptimization:
    def test_prompt_optimize_with_llm(self) -> None:
        llm = _NullLLM("Be concise and specific when asking the user for input.")
        opt = create_prompt_optimizer("test-model", llm=llm)  # type: ignore[arg-type]
        p = Prompt("Ask the user for input.")
        improved = opt.optimize(p)
        assert "concise" in improved.string
        assert improved.version == 1

    def test_prompt_optimize_no_llm_returns_copy(self) -> None:
        opt = create_prompt_optimizer("test-model")
        p = Prompt("Keep it short.")
        improved = opt.optimize(p)
        assert improved.string == "Keep it short."

    def test_multi_prompt_optimizer(self) -> None:
        llm = _NullLLM(json.dumps(["Prompt A improved", "Prompt B improved"]))
        opt = create_multi_prompt_optimizer("test-model", llm=llm)  # type: ignore[arg-type]
        result = opt.optimize([Prompt("Prompt A"), Prompt("Prompt B")])
        assert len(result) == 2
        assert "improved" in result[0].string

    def test_prompt_str(self) -> None:
        p = Prompt("hello")
        assert str(p) == "hello"


class TestReflectionExecutor:
    def test_reflect_with_llm(self, store: FakeStore) -> None:
        payload = json.dumps([{"id": "r-1", "kind": "insert", "content": "reflected fact"}])
        llm = _NullLLM(payload)
        ex = ReflectionExecutor("test-model", llm=llm)  # type: ignore[arg-type]
        result = ex.reflect(
            [{"role": "user", "content": "remember this fact"}],
            namespace=("memories", "r1"),
            store=store,  # type: ignore[arg-type]
        )
        assert len(result) == 1
        assert store.get(("memories", "r1"), "r-1") is not None

    def test_reflect_async(self, store: FakeStore) -> None:
        payload = json.dumps([{"id": "r-2", "kind": "insert", "content": "async fact"}])
        llm = _NullLLM(payload)
        ex = ReflectionExecutor("test-model", llm=llm)  # type: ignore[arg-type]
        result = asyncio.run(
            ex.areflect(
                [{"role": "user", "content": "remember async"}],
                namespace=("memories", "r2"),
                store=store,  # type: ignore[arg-type]
            )
        )
        assert len(result) == 1
        assert store.get(("memories", "r2"), "r-2") is not None


class TestComposition:
    def test_pipe_composition(self, store: FakeStore) -> None:
        manager = create_memory_manager("test-model")
        composed = manager | (lambda result: len(result))
        # The pipe with a lambda only works via invoke on the composed object
        assert composed is not None
