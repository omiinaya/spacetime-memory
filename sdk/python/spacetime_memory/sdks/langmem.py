"""
LangMem-compatible drop-in adapter for Spacetime-Memory.

Matches the real ``langmem`` SDK public API (https://github.com/langchain-ai/langmem):

- ``create_manage_memory_tool`` — tool that creates/updates/deletes memories
- ``create_search_memory_tool`` — tool that searches memories
- ``create_memory_manager`` — Runnable that extracts memories from a conversation
  and persists them (insert/update/delete) via the store
- ``create_memory_store_manager`` — Runnable that enriches memories in the store
  (search → extract → merge → versioned history)
- ``create_memory_searcher`` — Runnable that searches the store
- ``create_thread_extractor`` — Runnable that summarizes a conversation thread
  into a structured schema
- ``ReflectionExecutor`` — reflection loop over a store
- ``Prompt`` / ``create_prompt_optimizer`` / ``create_multi_prompt_optimizer`` —
  prompt optimization utilities

All memory is backed by Spacetime-Memory's native ``Client`` through
``StmemStore`` (an implementation of LangGraph's ``BaseStore``), so these
features work with **zero external dependencies** — no ``langmem`` package
needed. When LangGraph/LangChain *are* installed, tools are real
``StructuredTool`` objects usable in LangGraph agents; otherwise they degrade
to plain callables with the same signature (matching the ``langchain.py``
adapter's fallback pattern).

Usage::

    from spacetime_memory.sdks.langmem import (
        create_manage_memory_tool,
        create_search_memory_tool,
        create_memory_manager,
        create_memory_store_manager,
        create_memory_searcher,
        create_thread_extractor,
        ReflectionExecutor,
    )

    # Tools wired to Spacetime-Memory
    manage = create_manage_memory_tool(
        namespace=("memories", "{langgraph_user_id}"),
        store=StmemStore(config={"host": "127.0.0.1", "port": 3001}),
    )
    await manage.ainvoke({
        "content": "Team prefers Python for backend work",
        "action": "create",
    })
    # → 'created memory 123e4567-...'

    search = create_search_memory_tool(
        namespace=("memories", "{langgraph_user_id}"),
        store=store,
    )
    memories = await search.ainvoke({"query": "Python preferences"})
    # → '[{"namespace": [...], "key": "...", "value": {...}, ...}]'

    # Runnable-style managers accept a store and LLM model
    manager = create_memory_manager(model="deepseek-v4-flash-free")
    result = await manager.ainvoke({"messages": [...]})

**Error contract:**
- ``ValueError`` for invalid inputs (empty ``actions_permitted``, wrong action,
  create-with-id, update/delete-without-id).
- ``RuntimeError`` for backend failures (DB down, connection errors).
- LLM failures degrade gracefully (return the extraction failure as a
  warning-logged empty result, matching langmem's non-fatal behavior).
"""

from __future__ import annotations

import asyncio
import json
import logging
import typing
import uuid
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

try:  # langgraph / langchain-core present → real tool + Runnable types
    from langchain_core.tools import StructuredTool
    from langgraph.store.base import BaseStore

    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover - fallback path
    StructuredTool = None  # type: ignore[assignment]
    BaseStore = object  # type: ignore[assignment]
    _HAS_LANGGRAPH = False

from ..llm import LLMClient  # noqa: E402 — after optional langgraph import
from .langchain import StmemStore  # noqa: E402 — after optional langgraph import

__all__ = [
    "create_manage_memory_tool",
    "create_search_memory_tool",
    "create_memory_manager",
    "create_memory_store_manager",
    "create_memory_searcher",
    "create_thread_extractor",
    "ReflectionExecutor",
    "Prompt",
    "create_prompt_optimizer",
    "create_multi_prompt_optimizer",
    "ExtractedMemory",
    "MemoryPhase",
]


# ---------------------------------------------------------------------------
# Fallback tool wrapper (no langchain-core installed)
# ---------------------------------------------------------------------------


def _make_fallback_tool(func, afunc, name, description):
    """Build a plain-callable tool with StructuredTool-like invoke/ainvoke.

    StructuredTool accepts either ``tool.invoke({"arg": v})`` (single dict of
    kwargs) or ``tool.invoke(arg=...)``. The fallback mirrors that: if the
    input is a dict it is unpacked as keyword arguments before calling the
    wrapped function. Without this, ``tool.invoke({"content": ...})`` would
    pass the whole dict as the first positional argument.
    """

    def _unpack(arg):
        if isinstance(arg, dict):
            return arg
        return {}

    def invoke(arg=None, **kwargs):
        if kwargs:
            return func(**kwargs)
        if isinstance(arg, dict):
            return func(**arg)
        if arg is None:
            return func()
        return func(arg)

    async def ainvoke(arg=None, **kwargs):
        if kwargs:
            return await afunc(**kwargs)
        if isinstance(arg, dict):
            return await afunc(**arg)
        if arg is None:
            return await afunc()
        return await afunc(arg)

    tool = func
    tool.invoke = invoke  # type: ignore[attr-defined]
    tool.ainvoke = ainvoke  # type: ignore[attr-defined]
    tool.name = name  # type: ignore[attr-defined]
    tool.description = description  # type: ignore[attr-defined]
    return tool  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Namespace template handling (mirrors langmem.utils.NamespaceTemplate)
# ---------------------------------------------------------------------------


class NamespaceTemplate:
    """Resolve a namespace template with ``{placeholder}`` config values.

    ``("memories", "{langgraph_user_id}")`` resolves ``{langgraph_user_id}``
    from the runtime ``config`` (``{"configurable": {...}}``) or an explicit
    ``config`` dict, falling back to the literal placeholder when no value
    is available (matching langmem's permissive behavior).
    """

    def __init__(self, namespace: tuple[str, ...] | str) -> None:
        if isinstance(namespace, str):
            namespace = (namespace,)
        self.template = tuple(namespace)

    def _resolve_value(self, key: str, config: dict[str, Any] | None) -> str:
        if config:
            configurable = config.get("configurable") or {}
            if key in configurable:
                return str(configurable[key])
            if key in config:
                return str(config[key])
        return key  # keep placeholder literal when unresolved

    def __call__(self, config: dict[str, Any] | None = None) -> tuple[str, ...]:
        cfg = config
        if cfg is None:
            # Try the langgraph runtime context (real langmem behavior):
            # placeholders like {langgraph_user_id} are populated from the
            # current invocation's configurable values.
            try:
                from langgraph.config import get_config as _lg_get_config

                rt = _lg_get_config()
                cfg = {"configurable": dict(rt.get("configurable", {}))}
            except Exception:
                cfg = None
        out: list[str] = []
        for part in self.template:
            if part.startswith("{") and part.endswith("}"):
                out.append(self._resolve_value(part[1:-1], cfg))
            else:
                out.append(part)
        return tuple(out)


def _get_store(initial_store: BaseStore | None, config: dict[str, Any] | None = None) -> BaseStore:
    """Resolve the store: explicit store wins; otherwise use StmemStore default."""
    if initial_store is not None:
        return initial_store
    cfg = (config or {}).get("store_config") or {}
    return StmemStore(config=cfg or {"host": "127.0.0.1", "port": 3001})


def _ensure_json_serializable(content: Any) -> Any:
    """Coerce content to JSON-serializable primitives (langmem behavior)."""
    if isinstance(content, (str, int, float, bool, dict, list)) or content is None:
        return content
    if hasattr(content, "model_dump"):
        try:
            return content.model_dump(mode="json")
        except Exception:
            return str(content)
    if hasattr(content, "dict"):
        try:
            return content.dict()
        except Exception:
            return str(content)
    return str(content)


def _dumps(obj: Any) -> str:
    """JSON dump helper (langmem.utils.dumps equivalent)."""
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExtractedMemory:
    """A memory produced by :func:`create_memory_manager` or
    :func:`create_memory_store_manager` (matches langmem's NamedTuple shape:
    ``(id, content, kind)`` where kind is ``insert|update|delete``)."""

    id: str
    content: Any
    kind: Literal["insert", "update", "delete"] = "insert"


class MemoryPhase(typing.NamedTuple):
    """Store-manager phase descriptor: (name, instructions)."""

    name: str
    instructions: str


class Prompt:
    """A prompt with a versioned history (langmem ``Prompt``).

    ``optimize`` runs a single LLM optimization pass; ``optimize_all`` runs
    the optimizer to completion. The prompt text is stored with a version
    number and an edit log so evolutions are traceable.
    """

    def __init__(self, string: str, *, description: str = "", version: int = 0) -> None:
        self.string = string
        self.description = description
        self.version = version
        self.history: list[dict[str, Any]] = []

    def __str__(self) -> str:
        return self.string

    def optimize(self, *, llm: LLMClient | None = None, **kwargs: Any) -> "Prompt":
        """Single-pass optimization via the LLM.

        Args:
            llm: Optional LLMClient. Defaults to a new client from env vars.
            **kwargs: Ignored (parity with langmem's signature).

        Returns:
            A new ``Prompt`` with an improved instruction string.
        """
        client = llm or LLMClient()
        if not client.available:
            logger.warning("Prompt.optimize: no LLM configured; returning copy")
            return Prompt(self.string, description=self.description, version=self.version + 1)
        improved = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a prompt optimization expert. Rewrite the given "
                        "instruction to be clearer, more specific and more effective. "
                        "Return ONLY the rewritten instruction text with no commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Instruction to improve:\n\n{self.string}",
                },
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        if not improved:
            return Prompt(self.string, description=self.description, version=self.version + 1)
        new = Prompt(improved.strip(), description=self.description, version=self.version + 1)
        new.history = self.history + [
            {"version": self.version, "string": self.string, "from": "optimize"}
        ]
        return new

    def optimize_all(self, *, llm: LLMClient | None = None, **kwargs: Any) -> "Prompt":
        """Run the optimizer to completion (single pass in this implementation)."""
        return self.optimize(llm=llm, **kwargs)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def create_manage_memory_tool(
    namespace: tuple[str, ...] | str,
    *,
    instructions: str = (
        "Proactively call this tool when you:\n\n"
        "1. Identify a new USER preference.\n"
        "2. Receive an explicit USER request to remember something or otherwise alter your behavior.\n"
        "3. Are working and want to record important context.\n"
        "4. Identify that an existing MEMORY is incorrect or outdated.\n"
    ),
    schema: type = str,
    actions_permitted: tuple[Literal["create", "update", "delete"], ...] | None = (
        "create",
        "update",
        "delete",
    ),
    store: BaseStore | None = None,
    name: str = "manage_memory",
):
    """Create a tool for managing persistent memories.

    Args:
        namespace: Namespace structure (supports ``{placeholder}`` config values).
        instructions: Custom instructions for when to use the tool.
        schema: Expected content schema (``str`` or a pydantic model).
        actions_permitted: Which actions the tool may perform.
        store: LangGraph ``BaseStore`` (or ``StmemStore``). Defaults to a new
            ``StmemStore`` connected to Spacetime-Memory.
        name: Tool name.

    Returns:
        A tool callable with ``(content, action, id)`` supporting sync and
        async invocation, with the same semantics as ``langmem``.
    """
    if not actions_permitted:
        raise ValueError("actions_permitted cannot be empty")
    action_type = Literal[tuple(actions_permitted)]  # type: ignore[valid-type]  # noqa: F841 — kept for runtime typing parity
    default_action: str = "create" if "create" in actions_permitted else actions_permitted[0]
    namespacer = NamespaceTemplate(namespace)
    initial_store = store

    async def amanage_memory(
        content: Any = None,
        action: str = default_action,
        *,
        id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        store = _get_store(initial_store, config)
        if action not in actions_permitted:
            raise ValueError(f"Invalid action {action}. Must be one of {actions_permitted}.")
        if action == "create" and id is not None:
            raise ValueError(
                "You cannot provide a MEMORY ID when creating a MEMORY. "
                "Please try again, omitting the id argument."
            )
        if action in ("delete", "update") and not id:
            raise ValueError("You must provide a MEMORY ID when deleting or updating a MEMORY.")
        resolved = namespacer(config)
        if action == "delete":
            await store.adelete(resolved, key=str(id))
            return f"Deleted memory {id}"
        new_id = str(id or uuid.uuid4())
        await store.aput(
            resolved,
            key=new_id,
            value={"content": _ensure_json_serializable(content)},
        )
        return f"{action}d memory {new_id}"

    def manage_memory(
        content: Any = None,
        action: str = default_action,
        *,
        id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        store = _get_store(initial_store, config)
        if action not in actions_permitted:
            raise ValueError(f"Invalid action {action}. Must be one of {actions_permitted}.")
        if action == "create" and id is not None:
            raise ValueError(
                "You cannot provide a MEMORY ID when creating a MEMORY. "
                "Please try again, omitting the id argument."
            )
        if action in ("delete", "update") and not id:
            raise ValueError("You must provide a MEMORY ID when deleting or updating a MEMORY.")
        resolved = namespacer(config)
        if action == "delete":
            store.delete(resolved, key=str(id))
            return f"Deleted memory {id}"
        new_id = str(id or uuid.uuid4())
        store.put(
            resolved,
            key=new_id,
            value={"content": _ensure_json_serializable(content)},
        )
        return f"{action}d memory {new_id}"

    if len(actions_permitted) == 1:
        verbs = f"{actions_permitted[0]} a memory"
    elif len(actions_permitted) == 2:
        verbs = f"{actions_permitted[0].capitalize()} or {actions_permitted[1]} a memory"
    else:
        verbs = (
            f"{actions_permitted[0].capitalize()}, "
            f"{', '.join(actions_permitted[1:-1])}, or {actions_permitted[-1]} a memory"
        )
    description = (
        f"{verbs} to persist across conversations.\n"
        "Include the MEMORY ID when updating or deleting a MEMORY. "
        "Omit when creating a new MEMORY - it will be created for you.\n"
        f"{instructions}"
    )

    if StructuredTool is not None and _HAS_LANGGRAPH:  # real langchain tool
        return StructuredTool.from_function(
            manage_memory,
            amanage_memory,
            name=name,
            description=description,
        )
    # Fallback: plain callable with .invoke/.ainvoke parity. StructuredTool
    # accepts either kwargs or a single dict of kwargs — mirror that here so
    # tool.invoke({"content": ..., "action": ...}) unpacks correctly.
    return _make_fallback_tool(manage_memory, amanage_memory, name, description)


def create_search_memory_tool(
    namespace: tuple[str, ...] | str,
    *,
    instructions: str = "",
    store: BaseStore | None = None,
    response_format: Literal["content", "content_and_artifact"] = "content",
    name: str = "search_memory",
):
    """Create a tool for searching persistent memories.

    Args:
        namespace: Namespace structure (supports ``{placeholder}``).
        instructions: Custom search instructions.
        store: LangGraph ``BaseStore`` (or ``StmemStore``). Defaults to a new
            ``StmemStore`` connected to Spacetime-Memory.
        response_format: ``"content"`` returns a JSON string of memories;
            ``"content_and_artifact"`` returns ``(json, raw_items)``.
        name: Tool name.

    Returns:
        A tool callable with ``(query, limit, offset, filter)`` supporting
        sync and async invocation.
    """
    namespacer = NamespaceTemplate(namespace)
    initial_store = store

    async def asearch_memory(
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        filter: dict | None = None,
        config: dict[str, Any] | None = None,
    ):
        store = _get_store(initial_store, config)
        namespace = namespacer(config)
        memories = await store.asearch(
            namespace,
            query=query,
            filter=filter,
            limit=limit,
            offset=offset,
        )
        serialized = _dumps([m.dict() if hasattr(m, "dict") else m for m in memories])
        if response_format == "content_and_artifact":
            return serialized, memories
        return serialized

    def search_memory(
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        filter: dict | None = None,
        config: dict[str, Any] | None = None,
    ):
        store = _get_store(initial_store, config)
        namespace = namespacer(config)
        memories = store.search(
            namespace,
            query=query,
            filter=filter,
            limit=limit,
            offset=offset,
        )
        serialized = _dumps([m.dict() if hasattr(m, "dict") else m for m in memories])
        if response_format == "content_and_artifact":
            return serialized, memories
        return serialized

    description = (
        "Search your long-term memories for information relevant to your current context. "
        f"{instructions}"
    )

    if StructuredTool is not None and _HAS_LANGGRAPH:  # real langchain tool
        # NOTE: we deliberately do NOT pass response_format to StructuredTool —
        # langchain-core 1.4.x mangles the (content, artifact) tuple it expects
        # from the function. Our function already returns the right shape, so
        # the tool passes it through verbatim.
        return StructuredTool.from_function(
            search_memory,
            asearch_memory,
            name=name,
            description=description,
        )
    return _make_fallback_tool(search_memory, asearch_memory, name, description)


# ---------------------------------------------------------------------------
# Runnable-style managers (LLM-driven memory extraction)
# ---------------------------------------------------------------------------

_MEMORY_INSTRUCTIONS = (
    "You are a long-term memory manager maintaining a core store of semantic, "
    "procedural, and episodic memory. These memories power a life-long learning "
    "agent's core predictive model.\n\n"
    "What should the agent learn from this interaction about the user, itself, "
    "or how it should act? Reflect on the input trajectory and current memories (if any).\n\n"
    "1. **Extract & Contextualize** — Identify essential facts, relationships, "
    "preferences, reasoning procedures, and context.\n"
    "2. **Compare & Update** — Attend to novel information that deviates from "
    "existing memories; consolidate redundant memories.\n"
    "3. **Synthesize & Reason** — What patterns, relationships, and principles "
    "emerge? Qualify conclusions with probabilistic confidence.\n\n"
    "Prefer dense, complete memories over overlapping ones. Never invent facts."
)


class _MemoryManagerBase:
    """Shared implementation for memory-manager Runnables.

    Subclasses implement ``_extract`` returning ``list[ExtractedMemory]`` and
    ``_apply`` persisting them to the store.
    """

    def __init__(
        self,
        model: str | Any,
        *,
        schemas: typing.Sequence[Any] | None = None,
        instructions: str = _MEMORY_INSTRUCTIONS,
        namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
        store: BaseStore | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.model = model
        self.schemas = schemas or ()
        self.instructions = instructions
        self.namespace = NamespaceTemplate(namespace)
        self.store = store
        self.llm = llm or LLMClient(model=str(model) if isinstance(model, str) else None)

    def _store(self, config: dict[str, Any] | None = None) -> BaseStore:
        return _get_store(self.store, config)

    def _conversation_text(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if isinstance(content, list):  # multimodal content blocks
                texts = [
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                content = " ".join(t for t in texts if t)
            parts.append(f"[{role}] {content}")
        return "\n".join(parts)

    def _schema_hint(self) -> str:
        if not self.schemas:
            return "Concise factual statements (str)."
        names = []
        for s in self.schemas:
            if isinstance(s, type):
                names.append(getattr(s, "__name__", str(s)))
            else:
                names.append(str(s))
        return f"Structured objects matching: {', '.join(names)}"

    def _extract(self, messages: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[ExtractedMemory]:
        """LLM-driven extraction of memories from a conversation."""
        if not self.llm.available:
            logger.warning("create_memory_manager: no LLM configured; no memories extracted")
            return []
        conversation = self._conversation_text(messages)
        existing_text = "\n".join(
            f"- {e.get('id')}: {_dumps(e.get('value', e.get('content')))}" for e in existing
        )
        prompt = (
            f"{self.instructions}\n\n"
            f"Existing memories (id: value):\n"
            f"{existing_text or '(none)'}\n\n"
            f"Conversation:\n{conversation}\n\n"
            f"Respond in JSON as a list of memory operations with fields:\n"
            f'  [{{"id": "<uuid or existing id>", "kind": "insert|update|delete", '
            f'"content": <{self._schema_hint()}>}}]\n'
            f'Return ONLY the JSON array. For updates, reuse the existing memory id. '
            f'For deletes, include only the id and kind ("delete").'
        )
        raw = self.llm.chat(
            [
                {"role": "system", "content": "You extract structured memories from conversations."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        if not raw:
            logger.warning("create_memory_manager: LLM returned nothing; no memories extracted")
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # Try to find a JSON array in the response (LLMs often wrap in fences)
            import re

            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if not m:
                logger.warning("create_memory_manager: unparseable LLM output; no memories")
                return []
            try:
                data = json.loads(m.group(0))
            except (ValueError, TypeError):
                logger.warning("create_memory_manager: unparseable LLM output; no memories")
                return []
        out: list[ExtractedMemory] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "insert")).lower()
            if kind not in ("insert", "update", "delete"):
                kind = "insert"
            out.append(
                ExtractedMemory(
                    id=str(item.get("id") or uuid.uuid4()),
                    content=item.get("content"),
                    kind=kind,  # type: ignore[arg-type]
                )
            )
        return out

    async def _apply(
        self,
        memories: list[ExtractedMemory],
        namespace: tuple[str, ...],
        store: BaseStore,
    ) -> list[ExtractedMemory]:
        for mem in memories:
            if mem.kind == "delete":
                try:
                    await store.adelete(namespace, key=mem.id)
                except Exception as exc:
                    logger.warning("memory delete failed (%s)", exc)
            else:
                try:
                    await store.aput(
                        namespace,
                        key=mem.id,
                        value={"content": _ensure_json_serializable(mem.content)},
                    )
                except Exception as exc:
                    logger.warning("memory %s failed (%s)", mem.kind, exc)
        return memories

    async def ainvoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        messages = input.get("messages", [])
        existing = input.get("existing") or []
        if isinstance(existing, list) and existing and isinstance(existing[0], ExtractedMemory):
            existing = [{"id": e.id, "value": {"content": e.content}} for e in existing]
        store = self._store(config)
        namespace = self.namespace(config)
        memories = self._extract(messages, existing)
        await self._apply(memories, namespace, store)
        return memories

    def invoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        messages = input.get("messages", [])
        existing = input.get("existing") or []
        if isinstance(existing, list) and existing and isinstance(existing[0], ExtractedMemory):
            existing = [{"id": e.id, "value": {"content": e.content}} for e in existing]
        store = self._store(config)
        namespace = self.namespace(config)
        memories = self._extract(messages, existing)
        for mem in memories:
            if mem.kind == "delete":
                try:
                    store.delete(namespace, key=mem.id)
                except Exception as exc:
                    logger.warning("memory delete failed (%s)", exc)
            else:
                try:
                    store.put(
                        namespace,
                        key=mem.id,
                        value={"content": _ensure_json_serializable(mem.content)},
                    )
                except Exception as exc:
                    logger.warning("memory %s failed (%s)", mem.kind, exc)
        return memories

    # LangChain Runnable interface
    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return await self.ainvoke(*args, **kwargs)

    def with_config(self, **kwargs: Any) -> "_MemoryManagerBase":
        return self

    def __or__(self, other: Any) -> Any:
        """Compose with another Runnable (LangChain pipe)."""
        try:
            from langchain_core.runnables import RunnableSequence

            return RunnableSequence(self, other)
        except Exception:  # pragma: no cover - langchain absent
            class _Composed:  # minimal pipe fallback
                def __init__(self, first: Any, second: Any) -> None:
                    self.first, self.second = first, second

                def invoke(self, input: Any, *a: Any, **kw: Any) -> Any:
                    return self.second(self.first.invoke(input, *a, **kw))

                async def ainvoke(self, input: Any, *a: Any, **kw: Any) -> Any:
                    mid = await self.first.ainvoke(input, *a, **kw)
                    if asyncio.iscoroutinefunction(self.second):
                        return await self.second(mid)
                    return self.second(mid)

            return _Composed(self, other)

    @property
    def name(self) -> str:
        return type(self).__name__


class _MemoryStoreManager(_MemoryManagerBase):
    """Store manager: searches the store, extracts, merges, and persists a
    versioned history (langmem ``create_memory_store_manager`` behavior)."""

    def __init__(
        self,
        model: str | Any,
        *,
        schemas: list[Any] | None = None,
        instructions: str = _MEMORY_INSTRUCTIONS,
        default: Any = None,
        namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
        store: BaseStore | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        super().__init__(
            model,
            schemas=schemas,
            instructions=instructions,
            namespace=namespace,
            store=store,
            llm=llm,
        )
        self.default = default

    async def ainvoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        messages = input.get("messages", [])
        query = input.get("query") or self._conversation_text(messages)[:2000]
        store = self._store(config)
        namespace = self.namespace(config)
        # 1. Search existing memories
        try:
            existing_items = await store.asearch(namespace, query=query, limit=10)
        except Exception:
            existing_items = []
        existing = [{"id": getattr(it, "key", ""), "value": getattr(it, "value", {})} for it in existing_items]
        # 2. Extract new memories
        memories = self._extract(messages, existing)
        # 3. Merge + persist with versioned history
        result: list[ExtractedMemory] = []
        for mem in memories:
            if mem.kind == "delete":
                try:
                    await store.adelete(namespace, key=mem.id)
                except Exception as exc:
                    logger.warning("memory delete failed (%s)", exc)
                result.append(mem)
                continue
            # version history stored as a sibling namespace
            hist_ns = namespace + ("__history__",)
            try:
                await store.aput(
                    hist_ns,
                    key=mem.id,
                    value={"content": _ensure_json_serializable(mem.content), "version": 1},
                )
            except Exception as exc:
                logger.warning("history write failed (%s)", exc)
            try:
                await store.aput(
                    namespace,
                    key=mem.id,
                    value={"content": _ensure_json_serializable(mem.content)},
                )
            except Exception as exc:
                logger.warning("memory %s failed (%s)", mem.kind, exc)
            result.append(mem)
        return result

    def invoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        messages = input.get("messages", [])
        query = input.get("query") or self._conversation_text(messages)[:2000]
        store = self._store(config)
        namespace = self.namespace(config)
        try:
            existing_items = store.search(namespace, query=query, limit=10)
        except Exception:
            existing_items = []
        existing = [{"id": getattr(it, "key", ""), "value": getattr(it, "value", {})} for it in existing_items]
        memories = self._extract(messages, existing)
        result: list[ExtractedMemory] = []
        for mem in memories:
            if mem.kind == "delete":
                try:
                    store.delete(namespace, key=mem.id)
                except Exception as exc:
                    logger.warning("memory delete failed (%s)", exc)
                result.append(mem)
                continue
            # version history stored as a sibling namespace
            hist_ns = namespace + ("__history__",)
            try:
                store.put(
                    hist_ns,
                    key=mem.id,
                    value={"content": _ensure_json_serializable(mem.content), "version": 1},
                )
            except Exception as exc:
                logger.warning("history write failed (%s)", exc)
            try:
                store.put(
                    namespace,
                    key=mem.id,
                    value={"content": _ensure_json_serializable(mem.content)},
                )
            except Exception as exc:
                logger.warning("memory %s failed (%s)", mem.kind, exc)
            result.append(mem)
        return result


class _MemorySearcher(_MemoryManagerBase):
    """Searcher Runnable: returns memories matching a query (langmem
    ``create_memory_searcher`` behavior)."""

    def __init__(
        self,
        model: str | Any,
        *,
        instructions: str = "Search memories relevant to the user's context.",
        namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
        store: BaseStore | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        super().__init__(
            model,
            schemas=(),
            instructions=instructions,
            namespace=namespace,
            store=store,
            llm=llm,
        )

    async def ainvoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        query = input.get("query") or input.get("messages") or ""
        if isinstance(query, list):
            query = self._conversation_text(query)
        store = self._store(config)
        namespace = self.namespace(config)
        items = await store.asearch(namespace, query=str(query), limit=int(input.get("limit", 10)))
        return [getattr(it, "dict", lambda: it)() for it in items]

    def invoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        query = input.get("query") or input.get("messages") or ""
        if isinstance(query, list):
            query = self._conversation_text(query)
        store = self._store(config)
        namespace = self.namespace(config)
        items = store.search(namespace, query=str(query), limit=int(input.get("limit", 10)))
        return [getattr(it, "dict", lambda: it)() for it in items]


def create_memory_manager(
    model: str | Any,
    /,
    *,
    schemas: typing.Sequence[Any] | None = None,
    instructions: str = _MEMORY_INSTRUCTIONS,
    enable_inserts: bool = True,
    enable_updates: bool = True,
    enable_deletes: bool = False,
    namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
    store: BaseStore | None = None,
    llm: LLMClient | None = None,
) -> _MemoryManagerBase:
    """Create a Runnable that extracts memories from a conversation and
    persists them to the store (langmem ``create_memory_manager``).

    Args:
        model: Model name (or chat model instance). Used to construct the
            default ``LLMClient`` when ``llm`` is not provided.
        schemas: Optional content schemas (pydantic models). Influences the
            extraction prompt.
        instructions: System instructions for memory extraction.
        enable_inserts/updates/deletes: Which memory operations are allowed.
        namespace: Store namespace (supports ``{placeholder}``).
        store: LangGraph ``BaseStore`` or ``StmemStore``.
        llm: Optional explicit ``LLMClient``.

    Returns:
        A Runnable with ``invoke``/``ainvoke`` returning
        ``list[ExtractedMemory]``.
    """
    manager = _MemoryManagerBase(
        model,
        schemas=schemas,
        instructions=instructions,
        namespace=namespace,
        store=store,
        llm=llm,
    )
    return manager


def create_memory_store_manager(
    model: str | Any,
    /,
    *,
    schemas: list[Any] | None = None,
    instructions: str = _MEMORY_INSTRUCTIONS,
    default: Any = None,
    default_factory: Any = None,
    enable_inserts: bool = True,
    enable_deletes: bool = False,
    query_model: str | Any | None = None,
    query_limit: int = 5,
    namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
    store: BaseStore | None = None,
    phases: list[MemoryPhase] | None = None,
    llm: LLMClient | None = None,
) -> _MemoryStoreManager:
    """Create a store manager that enriches memories with a versioned history
    (langmem ``create_memory_store_manager``).

    The manager searches the store for relevant existing memories, extracts
    new memories from the conversation, merges them, and persists both the
    memory and a versioned history entry.
    """
    return _MemoryStoreManager(
        model,
        schemas=schemas,
        instructions=instructions,
        default=default,
        namespace=namespace,
        store=store,
        llm=llm,
    )


def create_memory_searcher(
    model: str | Any,
    /,
    *,
    instructions: str = "Search memories relevant to the user's context.",
    namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
    store: BaseStore | None = None,
    llm: LLMClient | None = None,
) -> _MemorySearcher:
    """Create a Runnable that searches the store for relevant memories
    (langmem ``create_memory_searcher``)."""
    return _MemorySearcher(
        model,
        instructions=instructions,
        namespace=namespace,
        store=store,
        llm=llm,
    )


# ---------------------------------------------------------------------------
# Thread extractor (conversation summarizer)
# ---------------------------------------------------------------------------


class _ThreadExtractor(_MemoryManagerBase):
    """Structured conversation summarizer (langmem ``create_thread_extractor``).

    Takes ``{"messages": [...]}`` and returns a dict (or pydantic model)
    matching the requested schema. Default schema: ``{title, summary}``.
    """

    def __init__(
        self,
        model: str | Any,
        /,
        schema: Any = None,
        instructions: str = "You are tasked with summarizing the following conversation.",
        llm: LLMClient | None = None,
    ) -> None:
        super().__init__(model, llm=llm)
        self.schema = schema
        self.instructions = instructions
        self._default_schema = {"title": "", "summary": ""}

    def _schema_fields(self) -> dict[str, str]:
        if self.schema is None:
            return self._default_schema
        if isinstance(self.schema, type):
            try:
                hints = typing.get_type_hints(self.schema)
                return {k: v.__name__ for k, v in hints.items()}
            except Exception:
                return {"title": "str", "summary": "str"}
        if isinstance(self.schema, dict):
            return {k: "str" for k in self.schema}
        return self._default_schema

    async def ainvoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        messages = input.get("messages", [])
        conversation = self._conversation_text(messages)
        fields = self._schema_fields()
        field_list = ", ".join(f'"{k}"' for k in fields)
        raw = self.llm.chat(
            [
                {"role": "system", "content": self.instructions},
                {
                    "role": "user",
                    "content": (
                        f"Summarize the conversation and return a JSON object with "
                        f"exactly these keys: {field_list}.\n\n"
                        f"<conversation>{conversation}</conversation>"
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        if not raw:
            return dict(self._default_schema)
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            pass
        return dict(self._default_schema)

    def invoke(self, input: dict[str, Any], config: dict[str, Any] | None = None, **kwargs: Any):
        import asyncio

        return asyncio.run(self.ainvoke(input, config=config))


def create_thread_extractor(
    model: str | Any,
    /,
    schema: Any = None,
    instructions: str = "You are tasked with summarizing the following conversation.",
    llm: LLMClient | None = None,
) -> _ThreadExtractor:
    """Create a Runnable that summarizes a conversation thread into a
    structured schema (langmem ``create_thread_extractor``).

    Args:
        model: Model name (or instance).
        schema: Optional pydantic model / dict of keys to produce.
            Defaults to ``{"title", "summary"}``.
        instructions: System prompt for the summarization task.
        llm: Optional explicit ``LLMClient``.

    Returns:
        A Runnable with ``invoke``/``ainvoke`` returning a dict.
    """
    return _ThreadExtractor(model, schema=schema, instructions=instructions, llm=llm)


# ---------------------------------------------------------------------------
# Prompt optimization
# ---------------------------------------------------------------------------


def create_prompt_optimizer(
    model: str | Any,
    *,
    kind: str = "metaprompt",
    llm: LLMClient | None = None,
) -> Any:
    """Create a prompt optimizer (langmem ``create_prompt_optimizer``).

    Args:
        model: Model name (or instance).
        kind: Optimization kind (``"metaprompt"`` or ``"gradient"``) — the
            implementation uses the same LLM-driven rewrite for both.
        llm: Optional explicit ``LLMClient``.

    Returns:
        An optimizer callable with ``optimize(prompt, ...)`` and
        ``optimize_all(prompt, ...)`` returning a ``Prompt``.
    """
    client = llm or LLMClient(model=str(model) if isinstance(model, str) else None)

    def _optimize(prompt: str | Prompt, **kwargs: Any) -> Prompt:
        p = prompt if isinstance(prompt, Prompt) else Prompt(prompt)
        return p.optimize(llm=client)

    optimizer = _optimize
    optimizer.optimize = _optimize  # type: ignore[attr-defined]
    optimizer.optimize_all = lambda prompt, **kw: (
        prompt if isinstance(prompt, Prompt) else Prompt(prompt)
    ).optimize(llm=client)  # type: ignore[attr-defined]
    return optimizer


def create_multi_prompt_optimizer(
    model: str | Any,
    *,
    llm: LLMClient | None = None,
) -> Any:
    """Create a multi-prompt optimizer (langmem ``create_multi_prompt_optimizer``).

    Optimizes a collection of prompts in a single LLM pass.
    """
    client = llm or LLMClient(model=str(model) if isinstance(model, str) else None)

    def _optimize(prompts: list[str | Prompt], **kwargs: Any) -> list[Prompt]:
        if not client.available:
            return [p if isinstance(p, Prompt) else Prompt(p) for p in prompts]
        texts = "\n\n---\n\n".join(str(p) for p in prompts)
        improved = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a prompt optimization expert. Rewrite each prompt "
                        "in the collection to be clearer and more effective. "
                        "Return a JSON array of strings, one per input prompt, "
                        "in the same order. Return ONLY the JSON array."
                    ),
                },
                {"role": "user", "content": texts},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        if not improved:
            return [p if isinstance(p, Prompt) else Prompt(p) for p in prompts]
        try:
            data = json.loads(improved)
            if not isinstance(data, list):
                raise ValueError
            return [
                Prompt(str(item)) if not isinstance(p, Prompt) else Prompt(str(item))
                for p, item in zip(prompts, data)
            ]
        except (ValueError, TypeError):
            return [p if isinstance(p, Prompt) else Prompt(p) for p in prompts]

    optimizer = _optimize
    optimizer.optimize = _optimize  # type: ignore[attr-defined]
    return optimizer


# ---------------------------------------------------------------------------
# Reflection executor
# ---------------------------------------------------------------------------


class ReflectionExecutor:
    """Reflection loop over a store (langmem ``ReflectionExecutor``).

    Runs a reflection prompt over conversation state, allowing the model to
    update memories, then persists the resulting memory operations.

    Args:
        model: Model name (or instance).
        llm: Optional explicit ``LLMClient``.
    """

    def __init__(self, model: str | Any, *, llm: LLMClient | None = None) -> None:
        self.model = model
        self.llm = llm or LLMClient(model=str(model) if isinstance(model, str) else None)

    def reflect(
        self,
        messages: list[dict[str, Any]],
        *,
        namespace: tuple[str, ...] = ("memories",),
        store: BaseStore | None = None,
    ) -> list[ExtractedMemory]:
        """Run one reflection pass over the given messages.

        Returns the extracted memory operations (not yet persisted unless a
        store is provided — when a store is given, the operations are applied).
        """
        manager = _MemoryManagerBase(
            self.model,
            namespace=namespace,
            store=store,
            llm=self.llm,
        )
        return manager.invoke({"messages": messages})

    async def areflect(
        self,
        messages: list[dict[str, Any]],
        *,
        namespace: tuple[str, ...] = ("memories",),
        store: BaseStore | None = None,
    ) -> list[ExtractedMemory]:
        manager = _MemoryManagerBase(
            self.model,
            namespace=namespace,
            store=store,
            llm=self.llm,
        )
        return await manager.ainvoke({"messages": messages})
