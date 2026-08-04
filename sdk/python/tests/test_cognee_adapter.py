"""Tests for the Cognee-compatible adapter (``spacetime_memory.sdks.cognee``).

Unit tests use a fake Client (no live STDB needed) so the pipeline logic is
fully exercised. Integration tests (marked ``integration``) require a live
SpacetimeDB.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import pytest

from spacetime_memory.sdks.cognee import (
    FeedbackEntry,
    MemoryEntry,
    QAEntry,
    RecallScope,
    SearchResult,
    SearchType,
    SkillRunEntry,
    TraceEntry,
    _dataset_ws,
    _extract_entities,
    _resolve_input_text,
    add,
    agent_memory,
    cognify,
    config,
    datasets,
    delete,
    get_current_agent_memory_context,
    prune,
    search,
    sync_add,
    sync_cognify,
    sync_search,
)


# ---------------------------------------------------------------------------
# Fake Client (records store/search/query/call ops, no network)
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self) -> None:
        self.memories: dict[str, list[dict[str, Any]]] = {}  # ws -> rows
        self.nodes: dict[str, set[str]] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.stores: list[tuple[str, str]] = []
        self.calls: list[list[Any]] = []

    # -- Client surface used by the adapter --
    def store(self, workspace_id, content, memory_type="experience", **kw) -> dict[str, Any]:
        self.memories.setdefault(workspace_id, []).append(
            {"id": str(uuid.uuid4()), "content": content}
        )
        self.stores.append((workspace_id, content))
        return {"id": self.memories[workspace_id][-1]["id"]}

    def search(self, workspace_id, query, limit=15, semantic=True, cross_encoder=True, **kw):
        rows = self.memories.get(workspace_id, [])
        hits = []
        for r in rows:
            score = 0.5 if query.lower() in str(r.get("content", "")).lower() else 0.1
            hits.append({"id": r["id"], "content": r.get("content", ""), "score": score})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def _query(self, table, ws, filt=None, cols=None) -> list[dict[str, Any]]:
        filt = filt or {}
        if table == "memory":
            rows = [
                {k: r.get(k) for k in (cols or ["id", "content"])}
                for r in self.memories.get(ws, [])
            ]
            if filt.get("id"):
                rows = [r for r in rows if r.get("id") == filt["id"]]
            return rows
        if table == "workspace":
            out = []
            for wid, meta in self.workspaces.items():
                r = {"id": wid, "name": meta.get("name", "")}
                if cols:
                    r = {k: r.get(k) for k in cols}
                out.append(r)
            if filt.get("id"):
                out = [r for r in out if r.get("id") == filt["id"]]
            return out
        if table == "kg_node":
            return [{"label": l} for l in self.nodes.get(ws, set())]
        return []

    def _call(self, reducer: str, args: list[Any]) -> Any:
        self.calls.append([reducer, args])
        if reducer == "create_workspace":
            self.workspaces[args[2]] = {"name": args[0], "description": args[1]}
        elif reducer == "set_workspace_visibility":
            pass
        elif reducer == "create_node":
            ws, label = args[0], args[1]
            self.nodes.setdefault(ws, set()).add(label)
        elif reducer == "create_edge":
            pass
        elif reducer == "delete_memory":
            ws = None
            # find and remove
            for wid, rows in self.memories.items():
                for i, r in enumerate(rows):
                    if r.get("id") == args[0]:
                        del self.memories[wid][i]
                        return None
        return None


@pytest.fixture
def fake(monkeypatch) -> FakeClient:
    f = FakeClient()
    monkeypatch.setattr("spacetime_memory.sdks.cognee._client", lambda: f)
    return f


@pytest.fixture
def no_llm(monkeypatch) -> None:
    class _NoLLM:
        available = False

        def chat(self, *a, **kw):
            return None

    monkeypatch.setattr("spacetime_memory.sdks.cognee.LLMClient", lambda *a, **kw: _NoLLM())


# ---------------------------------------------------------------------------
# Input normalization
# ---------------------------------------------------------------------------


class TestResolveInputText:
    def test_plain_string(self) -> None:
        assert _resolve_input_text("hello world") == ["hello world"]

    def test_list_of_strings(self) -> None:
        assert _resolve_input_text(["a", "b"]) == ["a", "b"]

    def test_empty_list(self) -> None:
        assert _resolve_input_text([]) == []

    def test_none_skipped(self) -> None:
        assert _resolve_input_text([None, "x", None]) == ["x"]

    def test_memory_entry_dumped(self) -> None:
        qa = QAEntry(question="Q?", answer="A!")
        texts = _resolve_input_text(qa)
        assert len(texts) == 1
        parsed = json.loads(texts[0])
        assert parsed["type"] == "qa"

    def test_dict_dumped(self) -> None:
        assert _resolve_input_text({"a": 1}) == [json.dumps({"a": 1})]


# ---------------------------------------------------------------------------
# add / cognify
# ---------------------------------------------------------------------------


class TestAdd:
    async def test_add_text(self, fake: FakeClient, no_llm: None) -> None:
        await add("Alice loves hiking", dataset_name="profiles")
        ws = _dataset_ws("profiles")
        assert len(fake.memories.get(ws, [])) == 1
        assert fake.memories[ws][0]["content"] == "Alice loves hiking"

    async def test_add_list(self, fake: FakeClient, no_llm: None) -> None:
        await add(["one", "two"], dataset_name="d1")
        ws = _dataset_ws("d1")
        assert len(fake.memories[ws]) == 2

    async def test_add_empty_raises(self, fake: FakeClient, no_llm: None) -> None:
        with pytest.raises(ValueError, match="no ingestible text"):
            await add([], dataset_name="d1")

    async def test_sync_add(self, fake: FakeClient, no_llm: None) -> None:
        sync_add("sync text", dataset_name="d2")
        ws = _dataset_ws("d2")
        assert len(fake.memories.get(ws, [])) == 1

    async def test_add_registers_workspace(self, fake: FakeClient, no_llm: None) -> None:
        await add("data", dataset_name="d3")
        ws = _dataset_ws("d3")
        assert ws in fake.workspaces


class TestCognify:
    async def test_cognify_builds_nodes(self, fake: FakeClient, no_llm: None) -> None:
        await add("Alice loves hiking in the Rocky Mountains.", dataset_name="d4")
        await cognify(dataset_name="d4")
        ws = _dataset_ws("d4")
        # deterministic fallback extracts capitalized tokens
        assert "Alice" in fake.nodes.get(ws, set())

    async def test_cognify_missing_dataset(self, fake: FakeClient, no_llm: None) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            await cognify(dataset_name="missing")

    async def test_sync_cognify(self, fake: FakeClient, no_llm: None) -> None:
        await add("Bob lives in Paris.", dataset_name="d5")
        sync_cognify(dataset_name="d5")
        ws = _dataset_ws("d5")
        assert "Bob" in fake.nodes.get(ws, set())


class TestExtractEntities:
    def test_deterministic_fallback(self, no_llm: None) -> None:
        class _LLM:
            available = False

        ents = _extract_entities("Alice met Bob in Paris on Friday.", _LLM())
        assert "Alice" in ents
        assert "Bob" in ents
        assert "Paris" in ents

    def test_llm_path(self) -> None:
        class _LLM:
            available = True

            def chat(self, *a, **kw):
                return '["Alice", "Bob"]'

        ents = _extract_entities("Alice met Bob.", _LLM())
        assert ents == ["Alice", "Bob"]

    def test_llm_garbage_falls_back(self) -> None:
        class _LLM:
            available = True

            def chat(self, *a, **kw):
                return "not json"

        ents = _extract_entities("Alice met Bob.", _LLM())
        assert "Alice" in ents


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_search_returns_results(self, fake: FakeClient, no_llm: None) -> None:
        await add("Alice loves hiking", dataset_name="p1")
        await add("Bob hates hiking", dataset_name="p1")
        await cognify(dataset_name="p1")
        results = await search("hiking", datasets=["p1"], top_k=10)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)
        assert results[0].dataset_name == "p1"
        assert "hiking" in str(results[0].search_result["content"]).lower() or results[0].search_result["score"] >= 0.1

    async def test_search_empty_query_raises(self, fake: FakeClient, no_llm: None) -> None:
        with pytest.raises(ValueError, match="query_text must be non-empty"):
            await search("")

    async def test_search_no_datasets_raises(self, fake: FakeClient, no_llm: None) -> None:
        with pytest.raises(ValueError, match="no datasets found"):
            await search("hello")

    async def test_sync_search(self, fake: FakeClient, no_llm: None) -> None:
        await add("sky is blue", dataset_name="p2")
        results = sync_search("sky", datasets=["p2"])
        assert len(results) >= 1

    async def test_search_sorts_by_score(self, fake: FakeClient, no_llm: None) -> None:
        await add("Alice loves hiking in mountains", dataset_name="p3")
        await add("The weather today is fine", dataset_name="p3")
        results = await search("hiking", datasets=["p3"], top_k=10)
        assert len(results) == 2
        # exact-match content should rank first
        assert "hiking" in str(results[0].search_result["content"]).lower()


# ---------------------------------------------------------------------------
# delete / prune / datasets
# ---------------------------------------------------------------------------


class TestDatasetMgmt:
    async def test_delete_removes_memories(self, fake: FakeClient, no_llm: None) -> None:
        await add("data to delete", dataset_name="dd1")
        ws = _dataset_ws("dd1")
        assert len(fake.memories.get(ws, [])) == 1
        await delete(dataset_name="dd1")
        assert len(fake.memories.get(ws, [])) == 0

    async def test_delete_missing_raises(self, fake: FakeClient, no_llm: None) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            await delete(dataset_name="nope")

    async def test_datasets_lists_registered(self, fake: FakeClient, no_llm: None) -> None:
        await add("x", dataset_name="lst1")
        await add("y", dataset_name="lst2")
        names = [d["name"] for d in await datasets()]
        assert "lst1" in names
        assert "lst2" in names

    async def test_prune_removes_all(self, fake: FakeClient, no_llm: None) -> None:
        await add("x", dataset_name="pr1")
        await add("y", dataset_name="pr2")
        await prune()
        remaining = 0
        for rows in fake.memories.values():
            remaining += len(rows)
        assert remaining == 0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_qa_entry(self) -> None:
        qa = QAEntry(question="Q", answer="A")
        assert qa.type == "qa"
        assert qa.question == "Q"

    def test_trace_entry_defaults(self) -> None:
        t = TraceEntry(origin_function="fn")
        assert t.status == "success"
        assert t.error_message == ""

    def test_feedback_entry(self) -> None:
        f = FeedbackEntry(qa_id="abc", feedback_score=5)
        assert f.qa_id == "abc"

    def test_skill_run_entry_validation(self) -> None:
        s = SkillRunEntry(selected_skill_id="s1", success_score=0.5)
        assert s.success_score == 0.5
        with pytest.raises(ValueError):
            SkillRunEntry(selected_skill_id="s1", success_score=1.5)

    def test_memory_entry_union(self) -> None:
        m: MemoryEntry = QAEntry(question="q", answer="a")
        assert m.type == "qa"

    def test_recall_scope(self) -> None:
        scope: RecallScope = "auto"
        assert scope == "auto"

    def test_search_type_enum(self) -> None:
        assert SearchType.GRAPH_COMPLETION.value == "GRAPH_COMPLETION"

    def test_search_result_shape(self) -> None:
        r = SearchResult(search_result={"content": "x"}, dataset_name="d")
        assert r.search_result["content"] == "x"
        assert r.dataset_name == "d"


# ---------------------------------------------------------------------------
# agent_memory decorator
# ---------------------------------------------------------------------------


class TestAgentMemory:
    def test_sync_decorator_records_trace(self) -> None:
        get_current_agent_memory_context().clear()

        @agent_memory
        def my_tool(x: str) -> str:
            return f"processed {x}"

        result = my_tool("input")
        assert result == "processed input"
        ctx = get_current_agent_memory_context()
        assert "trace" in ctx
        assert ctx["trace"][-1].origin_function == "my_tool"
        assert ctx["trace"][-1].status == "success"

    async def test_async_decorator_records_trace(self) -> None:
        get_current_agent_memory_context().clear()

        @agent_memory
        async def my_async_tool(x: str) -> str:
            return x.upper()

        result = await my_async_tool("hi")
        assert result == "HI"
        ctx = get_current_agent_memory_context()
        assert ctx["trace"][-1].origin_function == "my_async_tool"

    def test_decorator_with_context_param(self) -> None:
        get_current_agent_memory_context().clear()

        @agent_memory(context={"env": "test"})
        def fn() -> str:
            return "ok"

        assert fn() == "ok"

    def test_current_context_returns_copy(self) -> None:
        get_current_agent_memory_context().clear()
        get_current_agent_memory_context()["injected"] = True  # mutating the copy
        assert "injected" not in get_current_agent_memory_context()


class TestDatasetWs:
    def test_deterministic(self) -> None:
        assert _dataset_ws("same") == _dataset_ws("same")
        assert _dataset_ws("same") != _dataset_ws("different")
        assert _dataset_ws("same").startswith("cognee-")
