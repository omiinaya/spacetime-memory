"""
Letta-compatible drop-in adapter for Spacetime-Memory.

Maps the Letta memory model (https://github.com/letta-ai/letta) onto
Spacetime-Memory's native storage:

- **Core memory** — ``Block`` objects (label/value/limit, e.g. ``human`` and
  ``persona`` blocks) stored as structured memories. ``Memory`` holds the
  agent's block collection.
- **Archival memory** — ``Passage`` objects (long-term vector-searchable text)
  stored as memories in a dedicated archival workspace per agent.
- **Recall memory** — conversation ``Message`` objects (user/assistant/tool
  turns) stored as memories with session context.

Adapter class ``LettaMemory`` provides the core client surface:

- ``create_agent`` / ``get_agent`` / ``delete_agent``
- ``get_memory`` / ``update_block`` / ``add_block`` / ``delete_block``
- ``insert_archival`` / ``search_archival`` / ``delete_archival``
- ``send_message`` / ``get_messages`` (recall)
- ``list_agents``

All storage is Spacetime-Memory native (``Client``) — zero external
dependencies. Model classes match Letta's schema shapes (``Block``,
``Passage``, ``Memory``, ``Message``).

Usage::

    from spacetime_memory.sdks.letta import (
        LettaMemory, Block, Passage, Memory, Message,
    )

    lm = LettaMemory(host="127.0.0.1", port=3001)
    agent = lm.create_agent(name="assistant", persona="Helpful assistant")
    lm.update_block(agent_id=agent["id"], label="human", value="Alice, 30, likes hiking")

    # Archival memory (long-term vector searchable)
    lm.insert_archival(agent_id=agent["id"], passages=["Alice prefers coffee over tea"])
    hits = lm.search_archival(agent_id=agent["id"], query="drink preference")

    # Recall (conversation history)
    lm.send_message(agent_id=agent["id"], role="user", content="Hello!")
    messages = lm.get_messages(agent_id=agent["id"])

**Error contract:**
- ``ValueError`` for invalid inputs (empty text, missing agent).
- ``RuntimeError`` for backend failures (DB down, agent not found).
- Archival search returns ``[]`` on failure (logged), consistent with Letta
  returning empty results for missing data.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..client import Client

logger = logging.getLogger(__name__)

__all__ = [
    "LettaMemory",
    "Block",
    "Passage",
    "Memory",
    "Message",
    "CORE_MEMORY_BLOCK_CHAR_LIMIT",
]

CORE_MEMORY_BLOCK_CHAR_LIMIT = 2000


# ---------------------------------------------------------------------------
# Models — exact match to Letta's schema shapes
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


class Block(BaseModel):
    """A core-memory block (Letta ``Block``)."""

    value: str = Field(..., description="Value of the block.")
    limit: int = Field(CORE_MEMORY_BLOCK_CHAR_LIMIT, description="Character limit of the block.")
    label: Optional[str] = Field(None, description="Label (e.g. 'human', 'persona').")
    read_only: bool = Field(False, description="Whether the block is read-only.")
    description: Optional[str] = Field(None)
    metadata: Optional[dict] = Field(default_factory=dict)
    id: Optional[str] = Field(None)
    created_at: Optional[str] = Field(None)


class Passage(BaseModel):
    """An archival-memory passage (Letta ``Passage``)."""

    text: str = Field(..., description="The text of the passage.")
    id: Optional[str] = Field(None)
    archive_id: Optional[str] = Field(None)
    metadata: Optional[dict] = Field(default_factory=dict)
    tags: Optional[list[str]] = Field(None)
    embedding: Optional[list[float]] = Field(None)
    created_at: Optional[str] = Field(None)


class Message(BaseModel):
    """A conversation message in recall memory (Letta ``Message``)."""

    role: str = Field(..., description="user | assistant | tool")
    content: str = Field(..., description="Message text.")
    id: Optional[str] = Field(None)
    agent_id: Optional[str] = Field(None)
    created_at: Optional[str] = Field(None)


class Memory(BaseModel):
    """An agent's core memory — a collection of blocks (Letta ``Memory``)."""

    blocks: list[Block] = Field(default_factory=list)
    agent_id: Optional[str] = Field(None)


# ---------------------------------------------------------------------------
# LettaMemory client
# ---------------------------------------------------------------------------


class LettaMemory:
    """Spacetime-Memory backed implementation of Letta's memory API.

    Args:
        host: SpacetimeDB host.
        port: SpacetimeDB port.
        database: Database identity.
        embedder_url / tantivy_url: Optional sidecar URLs.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3001,
        database: str = "spacetime-memory-v2",
        embedder_url: str | None = None,
        tantivy_url: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self._client = Client(
            host=host,
            port=port,
            database=database,
            embedder_url=embedder_url,
            tantivy_url=tantivy_url,
        )

    # -- workspace helpers ---------------------------------------------------

    def _agent_ws(self, agent_id: str) -> str:
        digest = hashlib.sha256(f"letta:{agent_id}".encode()).hexdigest()[:32]
        return f"letta-{digest}"

    def _archival_ws(self, agent_id: str) -> str:
        digest = hashlib.sha256(f"letta-arch:{agent_id}".encode()).hexdigest()[:32]
        return f"letta-arch-{digest}"

    def _ensure_ws(self, ws: str, name: str) -> None:
        try:
            rows = self._client._query("workspace", "", {"id": ws}, ["id"])
            if not rows:
                self._client._call("create_workspace", [name, "letta memory", ws])
            self._client._call("set_workspace_visibility", [ws, True])
        except Exception as exc:
            logger.debug("letta _ensure_ws failed (%s)", exc)

    # -- agent lifecycle -----------------------------------------------------

    def create_agent(
        self,
        name: str,
        persona: str = "",
        human: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create an agent with initial core-memory blocks.

        Returns a dict with ``id``, ``name`` and the created blocks.
        """
        if not name or not name.strip():
            raise ValueError("letta.create_agent: name must be non-empty")
        agent_id = str(uuid.uuid4())
        ws = self._agent_ws(agent_id)
        self._ensure_ws(ws, f"Letta agent: {name}")
        blocks: list[Block] = []
        if persona:
            blocks.append(
                Block(value=persona, label="persona", id=str(uuid.uuid4()), created_at=_utc_now())
            )
        if human:
            blocks.append(
                Block(value=human, label="human", id=str(uuid.uuid4()), created_at=_utc_now())
            )
        for b in blocks:
            self._store_block(ws, agent_id, b)
        # registry memory: agent metadata
        try:
            self._client.store(
                workspace_id=ws,
                content=f"AGENT_META name={name}",
                memory_type="agent",
            )
        except Exception as exc:
            logger.warning("letta.create_agent: meta store failed (%s)", exc)
        return {"id": agent_id, "name": name, "blocks": [b.model_dump() for b in blocks]}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get an agent's metadata + core-memory blocks.

        Raises ``RuntimeError`` if the agent does not exist.
        """
        ws = self._agent_ws(agent_id)
        try:
            rows = self._client._query("workspace", "", {"id": ws}, ["id"])
        except Exception as exc:
            raise RuntimeError(f"letta.get_agent: agent not found: {exc}") from exc
        if not rows:
            raise RuntimeError(f"letta.get_agent: agent '{agent_id}' not found")
        blocks = self.get_memory(agent_id).blocks
        return {"id": agent_id, "blocks": [b.model_dump() for b in blocks]}

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent and all its memories (core + archival + recall)."""
        ws = self._agent_ws(agent_id)
        arch_ws = self._archival_ws(agent_id)
        for w in (ws, arch_ws):
            try:
                rows = self._client._query("memory", w, {}, ["id"])
                for r in rows:
                    try:
                        self._client._call("delete_memory", [r["id"]])
                    except Exception:
                        pass
            except Exception:
                pass
        return True

    def list_agents(self) -> list[dict[str, Any]]:
        """List all Letta agents (workspaces named ``Letta agent: ...``)."""
        out: list[dict[str, Any]] = []
        try:
            rows = self._client._query("workspace", "", {}, ["id", "name"])
            for r in rows:
                name = str(r.get("name", ""))
                if name.startswith("Letta agent:"):
                    out.append({"id": r["id"], "name": name.replace("Letta agent:", "").strip()})
        except Exception as exc:
            logger.warning("letta.list_agents: %s", exc)
        return out

    # -- core memory ---------------------------------------------------------

    def _store_block(self, ws: str, agent_id: str, block: Block) -> None:
        if block.id is None:
            block.id = str(uuid.uuid4())
        if block.created_at is None:
            block.created_at = _utc_now()
        self._client.store(
            workspace_id=ws,
            content=block.value,
            memory_type="block",
            summary=json_safe({"label": block.label, "limit": block.limit}),
        )

    def get_memory(self, agent_id: str) -> Memory:
        """Get an agent's core memory (blocks)."""
        ws = self._agent_ws(agent_id)
        blocks: list[Block] = []
        try:
            rows = self._client._query("memory", ws, {}, ["id", "content"])
        except Exception as exc:
            raise RuntimeError(f"letta.get_memory: agent not found: {exc}") from exc
        for r in rows:
            blocks.append(
                Block(
                    value=str(r.get("content", "")),
                    label=None,
                    id=r.get("id"),
                    created_at=_utc_now(),
                )
            )
        return Memory(blocks=blocks, agent_id=agent_id)

    def update_block(self, agent_id: str, label: str, value: str, **kwargs: Any) -> Block:
        """Update (or create) a core-memory block by label.

        Args:
            agent_id: Target agent.
            label: Block label (e.g. ``"human"`` or ``"persona"``).
            value: New block content.
        """
        if not label or not value:
            raise ValueError("letta.update_block: label and value must be non-empty")
        ws = self._agent_ws(agent_id)
        # Find existing block by label (via memory summary)
        existing_id: str | None = None
        try:
            rows = self._client._query("memory", ws, {}, ["id", "content", "summary"])
            for r in rows:
                if "block" == r.get("memory_type", ""):
                    pass
                # heuristics: match summary containing label
                try:
                    import json as _json

                    summ = _json.loads(r.get("summary") or "{}")
                    if summ.get("label") == label:
                        existing_id = r["id"]
                        break
                except Exception:
                    pass
        except Exception:
            pass
        block = Block(value=value, label=label, id=existing_id or str(uuid.uuid4()))
        if existing_id:
            try:
                self._client._call("update_memory", [existing_id, value, "", 0.5, None])
            except Exception as exc:
                logger.warning("letta.update_block: update failed (%s), re-storing", exc)
                self._store_block(ws, agent_id, block)
        else:
            self._store_block(ws, agent_id, block)
        return block

    def add_block(self, agent_id: str, label: str, value: str, **kwargs: Any) -> Block:
        """Add a new core-memory block."""
        if not label or not value:
            raise ValueError("letta.add_block: label and value must be non-empty")
        ws = self._agent_ws(agent_id)
        block = Block(value=value, label=label)
        self._store_block(ws, agent_id, block)
        return block

    def delete_block(self, agent_id: str, block_id: str) -> bool:
        """Delete a core-memory block by id."""
        ws = self._agent_ws(agent_id)
        try:
            self._client._call("delete_memory", [block_id])
            return True
        except Exception as exc:
            logger.warning("letta.delete_block: %s", exc)
            return False

    # -- archival memory -----------------------------------------------------

    def insert_archival(
        self,
        agent_id: str,
        passages: str | list[str],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Insert passages into an agent's archival (long-term) memory.

        Args:
            agent_id: Target agent.
            passages: A single text string or list of text strings.

        Returns:
            list of passage dicts (``{"id", "text", ...}``).
        """
        items = [passages] if isinstance(passages, str) else list(passages)
        if not items:
            raise ValueError("letta.insert_archival: passages must be non-empty")
        arch_ws = self._archival_ws(agent_id)
        self._ensure_ws(arch_ws, f"Letta archival: {agent_id}")
        out: list[dict[str, Any]] = []
        for text in items:
            if not text or not text.strip():
                continue
            try:
                result = self._client.store(
                    workspace_id=arch_ws,
                    content=str(text),
                    memory_type="passage",
                )
                out.append(
                    {
                        "id": result.get("id", ""),
                        "text": str(text),
                        "archive_id": agent_id,
                        "created_at": _utc_now(),
                    }
                )
            except Exception as exc:
                logger.warning("letta.insert_archival: store failed (%s)", exc)
        return out

    def search_archival(
        self,
        agent_id: str,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search an agent's archival memory.

        Args:
            agent_id: Target agent.
            query: Search query.
            limit: Max results.

        Returns:
            list of passage dicts sorted by relevance.
        """
        if not query or not query.strip():
            raise ValueError("letta.search_archival: query must be non-empty")
        arch_ws = self._archival_ws(agent_id)
        try:
            hits = self._client.search(
                workspace_id=arch_ws,
                query=query,
                limit=limit,
                semantic=True,
                cross_encoder=False,
            )
        except Exception as exc:
            logger.warning("letta.search_archival: %s", exc)
            return []
        return [
            {
                "id": h.get("id", ""),
                "text": h.get("content", h.get("memory", "")),
                "score": h.get("score", 0.0),
                "archive_id": agent_id,
            }
            for h in hits
        ]

    def delete_archival(self, agent_id: str, passage_id: str) -> bool:
        """Delete a passage from archival memory."""
        arch_ws = self._archival_ws(agent_id)
        try:
            self._client._call("delete_memory", [passage_id])
            return True
        except Exception as exc:
            logger.warning("letta.delete_archival: %s", exc)
            return False

    # -- recall memory -------------------------------------------------------

    def send_message(self, agent_id: str, role: str, content: str, **kwargs: Any) -> dict[str, Any]:
        """Record a conversation message in recall memory.

        Args:
            agent_id: Target agent.
            role: ``"user"`` | ``"assistant"`` | ``"tool"``.
            content: Message text.

        Returns:
            The created message dict.
        """
        if role not in ("user", "assistant", "tool"):
            raise ValueError(f"letta.send_message: invalid role '{role}'")
        if not content:
            raise ValueError("letta.send_message: content must be non-empty")
        ws = self._agent_ws(agent_id)
        try:
            result = self._client.store(
                workspace_id=ws,
                content=f"[{role}] {content}",
                memory_type="message",
                source_session_id=str(agent_id),
            )
            return {
                "id": result.get("id", ""),
                "role": role,
                "content": content,
                "agent_id": agent_id,
                "created_at": _utc_now(),
            }
        except Exception as exc:
            raise RuntimeError(f"letta.send_message: {exc}") from exc

    def get_messages(self, agent_id: str, limit: int = 100, **kwargs: Any) -> list[dict[str, Any]]:
        """Get an agent's recall memory (conversation messages).

        Returns:
            list of message dicts, most recent last.
        """
        ws = self._agent_ws(agent_id)
        try:
            rows = self._client._query(
                "memory", ws, {}, ["id", "content", "created_at", "memory_type"]
            )
        except Exception as exc:
            raise RuntimeError(f"letta.get_messages: agent not found: {exc}") from exc
        msgs: list[dict[str, Any]] = []
        for r in rows:
            if r.get("memory_type") not in ("message", None, ""):
                continue  # skip agent-meta and block rows
            content = str(r.get("content", ""))
            role = "message"
            if content.startswith("["):
                try:
                    role, _, rest = content[1:].partition("]")
                    content = rest.strip()
                except Exception:
                    pass
            msgs.append(
                {
                    "id": r.get("id", ""),
                    "role": role.strip(),
                    "content": content,
                    "agent_id": agent_id,
                    "created_at": r.get("created_at", ""),
                }
            )
        return msgs[-limit:]


def json_safe(value: Any) -> str:
    """Serialize a value to a JSON string for storage in summary fields."""
    import json

    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)
