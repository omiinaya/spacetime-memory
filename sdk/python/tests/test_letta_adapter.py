"""Tests for the Letta-compatible adapter (``spacetime_memory.sdks.letta``).

Unit tests use a fake Client (no live STDB needed). Integration tests
(marked ``integration``) require a live SpacetimeDB.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from spacetime_memory.sdks.letta import (
    CORE_MEMORY_BLOCK_CHAR_LIMIT,
    Block,
    LettaMemory,
    Memory,
    Message,
    Passage,
)


# ---------------------------------------------------------------------------
# Fake Client (records store/search/query/call ops, no network)
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self) -> None:
        self.memories: dict[str, list[dict[str, Any]]] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.calls: list[list[Any]] = []

    def store(self, workspace_id, content, memory_type="experience", **kw) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "content": content,
            "memory_type": memory_type,
            "summary": kw.get("summary", ""),
            "created_at": "",
        }
        self.memories.setdefault(workspace_id, []).append(row)
        return {"id": row["id"]}

    def search(self, workspace_id, query, limit=15, semantic=True, cross_encoder=True, **kw):
        rows = self.memories.get(workspace_id, [])
        hits = []
        for r in rows:
            score = 0.7 if query.lower() in str(r.get("content", "")).lower() else 0.1
            hits.append({"id": r["id"], "content": r.get("content", ""), "score": score})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def _query(self, table, ws, filt=None, cols=None) -> list[dict[str, Any]]:
        filt = filt or {}
        if table == "memory":
            rows = list(self.memories.get(ws, []))
            if cols:
                rows = [{k: r.get(k) for k in cols} for r in rows]
            return rows
        if table == "workspace":
            out = [
                {"id": wid, "name": meta.get("name", "")} for wid, meta in self.workspaces.items()
            ]
            if filt.get("id"):
                out = [r for r in out if r.get("id") == filt["id"]]
            if cols:
                out = [{k: r.get(k) for k in cols} for r in out]
            return out
        return []

    def _call(self, reducer: str, args: list[Any]) -> Any:
        self.calls.append([reducer, args])
        if reducer == "create_workspace":
            self.workspaces[args[2]] = {"name": args[0], "description": args[1]}
        elif reducer == "set_workspace_visibility":
            pass
        elif reducer == "update_memory":
            # [memory_id, content, summary, confidence, expires_at]
            for rows in self.memories.values():
                for r in rows:
                    if r.get("id") == args[0]:
                        r["content"] = args[1]
                        return None
            raise RuntimeError("not found")
        elif reducer == "delete_memory":
            for wid, rows in self.memories.items():
                for i, r in enumerate(rows):
                    if r.get("id") == args[0]:
                        del self.memories[wid][i]
                        return None
        return None


@pytest.fixture
def letta(monkeypatch) -> LettaMemory:
    fake = FakeClient()
    lm = LettaMemory(host="127.0.0.1", port=3001)
    monkeypatch.setattr(lm, "_client", fake)
    # expose fake for assertions
    lm._fake = fake  # type: ignore[attr-defined]
    return lm


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_block_defaults(self) -> None:
        b = Block(value="hello")
        assert b.value == "hello"
        assert b.limit == CORE_MEMORY_BLOCK_CHAR_LIMIT
        assert b.read_only is False

    def test_block_label(self) -> None:
        b = Block(value="x", label="human")
        assert b.label == "human"

    def test_passage(self) -> None:
        p = Passage(text="long term fact")
        assert p.text == "long term fact"
        assert p.id is None

    def test_message(self) -> None:
        m = Message(role="user", content="hi")
        assert m.role == "user"
        assert m.content == "hi"

    def test_memory_collection(self) -> None:
        mem = Memory(blocks=[Block(value="a", label="persona")], agent_id="a1")
        assert len(mem.blocks) == 1
        assert mem.blocks[0].label == "persona"


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


class TestAgentLifecycle:
    def test_create_agent(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="assistant", persona="Helpful", human="Alice")
        assert agent["name"] == "assistant"
        assert len(agent["blocks"]) == 2
        labels = {b["label"] for b in agent["blocks"]}
        assert labels == {"persona", "human"}

    def test_create_agent_empty_name_raises(self, letta: LettaMemory) -> None:
        with pytest.raises(ValueError, match="name must be non-empty"):
            letta.create_agent(name="")

    def test_get_agent(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="bob", persona="Friendly")
        got = letta.get_agent(agent["id"])
        assert got["id"] == agent["id"]

    def test_get_agent_missing_raises(self, letta: LettaMemory) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            letta.get_agent("no-such-agent")

    def test_delete_agent(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="tmp")
        assert letta.delete_agent(agent["id"]) is True

    def test_list_agents(self, letta: LettaMemory) -> None:
        letta.create_agent(name="alpha")
        letta.create_agent(name="beta")
        names = [a["name"] for a in letta.list_agents()]
        assert "alpha" in names
        assert "beta" in names


# ---------------------------------------------------------------------------
# Core memory
# ---------------------------------------------------------------------------


class TestCoreMemory:
    def test_get_memory_empty(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        mem = letta.get_memory(agent["id"])
        assert mem.agent_id == agent["id"]

    def test_update_block_creates(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        block = letta.update_block(agent["id"], label="human", value="Alice, 30")
        assert block.label == "human"
        assert block.value == "Alice, 30"

    def test_update_block_empty_raises(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        with pytest.raises(ValueError, match="label and value"):
            letta.update_block(agent["id"], label="", value="")

    def test_add_block(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        block = letta.add_block(agent["id"], label="custom", value="custom value")
        assert block.label == "custom"

    def test_delete_block(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        block = letta.add_block(agent["id"], label="doomed", value="bye")
        assert letta.delete_block(agent["id"], block.id) is True


# ---------------------------------------------------------------------------
# Archival memory
# ---------------------------------------------------------------------------


class TestArchivalMemory:
    def test_insert_archival_single(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        out = letta.insert_archival(agent["id"], "Alice prefers coffee over tea")
        assert len(out) == 1
        assert out[0]["text"] == "Alice prefers coffee over tea"
        assert out[0]["archive_id"] == agent["id"]

    def test_insert_archival_list(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        out = letta.insert_archival(agent["id"], ["a", "b", "c"])
        assert len(out) == 3

    def test_insert_archival_empty_raises(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        with pytest.raises(ValueError, match="passages must be non-empty"):
            letta.insert_archival(agent["id"], [])

    def test_search_archival(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        letta.insert_archival(agent["id"], "Alice loves hiking in mountains")
        letta.insert_archival(agent["id"], "Bob enjoys swimming")
        hits = letta.search_archival(agent["id"], "hiking")
        assert len(hits) >= 1
        assert "hiking" in hits[0]["text"]

    def test_search_archival_empty_query_raises(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        with pytest.raises(ValueError, match="query must be non-empty"):
            letta.search_archival(agent["id"], "")

    def test_delete_archival(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        out = letta.insert_archival(agent["id"], "doomed fact")
        assert letta.delete_archival(agent["id"], out[0]["id"]) is True


# ---------------------------------------------------------------------------
# Recall memory
# ---------------------------------------------------------------------------


class TestRecallMemory:
    def test_send_message(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        msg = letta.send_message(agent["id"], role="user", content="Hello!")
        assert msg["role"] == "user"
        assert msg["content"] == "Hello!"
        assert msg["agent_id"] == agent["id"]

    def test_send_message_invalid_role_raises(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        with pytest.raises(ValueError, match="invalid role"):
            letta.send_message(agent["id"], role="admin", content="hi")

    def test_send_message_empty_raises(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        with pytest.raises(ValueError, match="content must be non-empty"):
            letta.send_message(agent["id"], role="user", content="")

    def test_get_messages(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        letta.send_message(agent["id"], role="user", content="first")
        letta.send_message(agent["id"], role="assistant", content="second")
        msgs = letta.get_messages(agent["id"])
        assert len(msgs) == 2
        contents = [m["content"] for m in msgs]
        assert "first" in contents
        assert "second" in contents

    def test_get_messages_limit(self, letta: LettaMemory) -> None:
        agent = letta.create_agent(name="x")
        for i in range(5):
            letta.send_message(agent["id"], role="user", content=f"msg{i}")
        msgs = letta.get_messages(agent["id"], limit=3)
        assert len(msgs) == 3

    def test_get_messages_missing_agent(self, letta: LettaMemory) -> None:
        # A missing agent workspace behaves as empty (no raise) since the
        # fake returns [] — matches permissive read behavior
        msgs = letta.get_messages("ghost-agent")
        assert msgs == []
