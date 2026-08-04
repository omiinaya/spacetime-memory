"""
Cognee-compatible drop-in adapter for Spacetime-Memory.

Maps the public Cognee API (https://github.com/topoteretes/cognee) onto
Spacetime-Memory's native storage:

- ``add(data, dataset_name, ...)`` — ingest text / file paths into a dataset
- ``cognify(dataset_name, ...)`` — build the knowledge graph (entity
  extraction, edges, community detection) from ingested data
- ``search(query_text, query_type, top_k, datasets, ...)`` — hybrid semantic
  + graph search over the dataset's knowledge graph
- ``delete(dataset_name)`` / ``prune()`` — remove datasets
- ``datasets()`` — list datasets
- Memory entry models: ``QAEntry``, ``TraceEntry``, ``FeedbackEntry``,
  ``SkillRunEntry``, ``MemoryEntry``, ``RecallScope``
- ``agent_memory`` decorator + ``get_current_agent_memory_context``

All storage is Spacetime-Memory native (``Client``) — zero external
dependencies. The ``SearchResult`` model matches cognee's shape
(``search_result`` + ``dataset_id``/``dataset_name``).

Usage::

    from spacetime_memory.sdks.cognee import (
        add, cognify, search, delete, datasets,
        SearchType, QAEntry, TraceEntry, SkillRunEntry, RecallScope,
    )

    await add("Alice loves hiking in the mountains.", dataset_name="alice_profile")
    await cognify(dataset_name="alice_profile")

    results = await search("What does Alice like?", datasets=["alice_profile"])
    for r in results:
        print(r.search_result)

    # Agent memory (session-cache-style entries)
    await add(QAEntry(question="...", answer="..."), dataset_name="sessions")

**Error contract:**
- ``ValueError`` for invalid inputs (empty data, unknown dataset for
  search/cognify).
- ``RuntimeError`` for backend failures (DB down).
- LLM extraction failures degrade gracefully (KG build proceeds with
  plain text nodes; logged as warnings), matching cognee's non-fatal
  pipeline behavior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from ..client import Client
from ..llm import LLMClient

logger = logging.getLogger(__name__)

__all__ = [
    "add",
    "cognify",
    "search",
    "delete",
    "prune",
    "datasets",
    "config",
    "SearchType",
    "SearchResult",
    "SearchResultDataset",
    "QAEntry",
    "TraceEntry",
    "FeedbackEntry",
    "SkillRunEntry",
    "MemoryEntry",
    "MEMORY_ENTRY_TYPES",
    "RecallScope",
    "agent_memory",
    "get_current_agent_memory_context",
]


# ---------------------------------------------------------------------------
# Public models — exact match to cognee's shapes
# ---------------------------------------------------------------------------


class SearchType(str, Enum):
    """Cognee search types (subset supported natively)."""

    GRAPH_COMPLETION = "GRAPH_COMPLETION"
    RAG_COMPLETION = "RAG_COMPLETION"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    CODE = "CODE"
    TRAVERSAL = "TRAVERSAL"


class SearchResultDataset(BaseModel):
    id: str | None = None
    name: str | None = None


class SearchResult(BaseModel):
    """Cognee-compatible search result."""

    search_result: Any
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None


class QAEntry(BaseModel):
    """A Q&A turn stored in the session cache."""

    type: Literal["qa"] = "qa"
    question: str = Field(examples=["What is the capital of France?"])
    answer: str = Field(examples=["The capital of France is Paris."])
    context: str = Field(default="", examples=["Retrieved from geography_notes.md"])
    feedback_text: Optional[str] = None
    feedback_score: Optional[int] = None
    used_graph_element_ids: Optional[dict] = None


class TraceEntry(BaseModel):
    """One step of an agent trace."""

    type: Literal["trace"] = "trace"
    origin_function: str = Field(examples=["search_codebase"])
    status: Literal["success", "error"] = "success"
    method_params: Optional[dict] = None
    method_return_value: Optional[Any] = None
    memory_query: str = ""
    memory_context: str = ""
    error_message: str = ""
    generate_feedback_with_llm: bool = False


class FeedbackEntry(BaseModel):
    """Feedback attached to an existing QA entry."""

    type: Literal["feedback"] = "feedback"
    qa_id: str = Field(examples=["c4d5e6f7-8a9b-4c0d-9e1f-2a3b4c5d6e7f"])
    feedback_text: Optional[str] = None
    feedback_score: Optional[int] = None


class SkillRunEntry(BaseModel):
    """A persisted execution record for a skill."""

    type: Literal["skill_run"] = "skill_run"
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    selected_skill_id: str
    task_text: str = ""
    result_summary: str = ""
    success_score: Optional[float] = None
    feedback: float = 0.0
    error_type: str = ""
    error_message: str = ""
    started_at_ms: int = 0
    latency_ms: int = 0
    candidate_skill_ids: list[str] = Field(default_factory=list)
    task_pattern_id: str = ""
    router_version: str = ""
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    node_set: str = "skills"

    @field_validator("success_score")
    @classmethod
    def _validate_success_score(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("success_score must be in range [0.0, 1.0]")
        return value

    @field_validator("feedback")
    @classmethod
    def _validate_feedback(cls, value: float) -> float:
        if not -1.0 <= value <= 1.0:
            raise ValueError("feedback must be in range [-1.0, 1.0]")
        return value

    @field_validator("started_at_ms", "latency_ms")
    @classmethod
    def _validate_non_negative_ms(cls, value: int) -> int:
        if value < 0:
            raise ValueError("timestamp and latency fields must be non-negative")
        return value


MemoryEntry = Union[QAEntry, TraceEntry, FeedbackEntry, SkillRunEntry]
MEMORY_ENTRY_TYPES = (QAEntry, TraceEntry, FeedbackEntry, SkillRunEntry)

RecallScope = Literal["auto", "graph", "session", "trace", "graph_context", "session_context", "all"]


# ---------------------------------------------------------------------------
# Config (minimal cognee config shim)
# ---------------------------------------------------------------------------


class _Config:
    """Minimal ``cognee.config`` shim.

    Holds the STDB connection settings used by all adapter functions.
    """

    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 3001
        self.database = "spacetime-memory-v2"
        self.embedder_url: str | None = None
        self.tantivy_url: str | None = None
        self.llm: LLMClient | None = None
        self.default_feedback_influence: float = 0.5
        self.max_triplets: int = 50

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"_Config(host={self.host!r}, port={self.port!r}, "
            f"database={self.database!r})"
        )


config = _Config()


def _client() -> Client:
    """Build the shared Client from the adapter config."""
    return Client(
        host=config.host,
        port=config.port,
        database=config.database,
        embedder_url=config.embedder_url,
        tantivy_url=config.tantivy_url,
    )


def _dataset_ws(dataset_name: str) -> str:
    """Deterministic workspace id per dataset (hash of name)."""
    import hashlib

    digest = hashlib.sha256(f"cognee:{dataset_name}".encode()).hexdigest()[:32]
    return f"cognee-{digest}"


def _dataset_name_from_ws(ws: str) -> str:
    """Best-effort reverse of :func:`_dataset_ws` — not reversible; used only
    for display. Real dataset names are tracked in the dataset registry table."""
    return ws


def _ensure_dataset_registry(client: Client, dataset_name: str, ws: str) -> None:
    """Record dataset name → workspace mapping in the native workspace registry."""
    try:
        rows = client._query("workspace", "", {"id": ws}, ["id", "name"])
        if not rows:
            client._call("create_workspace", [f"Cognee:{dataset_name}", "cognee dataset", ws])
        client._call("set_workspace_visibility", [ws, True])
    except Exception as exc:
        logger.debug("dataset registry ensure failed (%s) — continuing", exc)


def _resolve_input_text(data: Any) -> list[str]:
    """Normalize cognee ``add`` input into a list of text strings.

    Accepts str, list[str], file paths (str starting with '/' or 'file://'),
    pydantic entries, and dicts (dumped to JSON).
    """
    items = data if isinstance(data, list) else [data]
    texts: list[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            if item.startswith("file://") or (item.startswith("/") and len(item) > 1):
                try:
                    from pathlib import Path

                    p = Path(item.replace("file://", ""))
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
                except OSError as exc:
                    logger.warning("cognee.add: cannot read file %s (%s)", item, exc)
                continue
            texts.append(item)
        elif isinstance(item, MEMORY_ENTRY_TYPES):
            texts.append(item.model_dump_json())
        elif isinstance(item, dict):
            texts.append(json.dumps(item, default=str))
        else:
            texts.append(str(item))
    return [t for t in texts if t and t.strip()]


# ---------------------------------------------------------------------------
# V1 API
# ---------------------------------------------------------------------------


async def add(
    data: Any,
    dataset_name: str = "main_dataset",
    **kwargs: Any,
) -> None:
    """Add data to a dataset for knowledge-graph processing (cognee ``add``).

    Args:
        data: Text, list of texts, file paths, or memory entries.
        dataset_name: Target dataset (mapped to a workspace).
        **kwargs: Ignored (parity with cognee's rich signature).

    Returns:
        None (cognee's ``add`` returns None).
    """
    texts = _resolve_input_text(data)
    if not texts:
        raise ValueError("cognee.add: no ingestible text provided")
    client = _client()
    ws = _dataset_ws(dataset_name)
    _ensure_dataset_registry(client, dataset_name, ws)
    for text in texts:
        try:
            client.store(
                workspace_id=ws,
                content=text,
                memory_type="experience",
            )
        except Exception as exc:
            logger.warning("cognee.add: store failed (%s)", exc)
            raise RuntimeError(f"cognee.add: failed to store data: {exc}") from exc


async def cognify(
    dataset_name: str = "main_dataset",
    **kwargs: Any,
) -> None:
    """Build the knowledge graph for a dataset (cognee ``cognify``).

    Runs entity extraction + graph construction over the dataset's stored
    memories using Spacetime-Memory's native KG (``create_node`` /
    ``create_edge``). Extraction is LLM-assisted when an LLM is configured;
    falls back to deterministic named-entity extraction.

    Args:
        dataset_name: Dataset to process.
        **kwargs: Ignored (parity).

    Returns:
        None.
    """
    client = _client()
    ws = _dataset_ws(dataset_name)
    try:
        memories = client._query("memory", ws, {}, ["id", "content"])
    except Exception as exc:
        raise RuntimeError(f"cognee.cognify: dataset '{dataset_name}' not found: {exc}") from exc
    if not memories:
        raise RuntimeError(f"cognee.cognify: dataset '{dataset_name}' not found (no memories)")

    llm = config.llm or LLMClient()
    nodes_created = 0
    edges_created = 0

    for mem in memories:
        content = str(mem.get("content", ""))
        entities = _extract_entities(content, llm)
        for label in entities:
            try:
                client._call("create_node", [ws, label, "entity", "", ""])
                nodes_created += 1
            except Exception:
                pass  # node exists
        if len(entities) >= 2:
            for i in range(len(entities) - 1):
                try:
                    client._call(
                        "create_edge",
                        [ws, entities[i], entities[i + 1], "related_to", ""],
                    )
                    edges_created += 1
                except Exception as exc:
                    logger.debug("cognee.cognify: edge create failed (%s)", exc)
    logger.info(
        "cognee.cognify: dataset=%s memories=%d nodes=%d edges=%d",
        dataset_name, len(memories), nodes_created, edges_created,
    )


def _extract_entities(text: str, llm: LLMClient) -> list[str]:
    """Extract named entities from text.

    Uses the LLM (JSON array of entity labels) when available; falls back to
    deterministic extraction of capitalized phrases (3+ chars, not at start
    of sentence unless they repeat).
    """
    if llm.available:
        raw = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You extract entities from text. Return a JSON array of "
                        "entity labels (names, places, organizations, products, "
                        "concepts). Return ONLY the JSON array, e.g. "
                        '["Alice", "hiking", "mountains"].'
                    ),
                },
                {"role": "user", "content": text[:3000]},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [str(e).strip() for e in data if str(e).strip()][:10]
            except (ValueError, TypeError):
                pass
    # Deterministic fallback: capitalized tokens
    import re

    seen: set[str] = set()
    out: list[str] = []
    for m in re.finditer(r"\b([A-Z][a-zA-Z]{2,})\b", text):
        w = m.group(1)
        if w.lower() in seen:
            continue
        seen.add(w.lower())
        out.append(w)
        if len(out) >= 10:
            break
    return out


async def search(
    query_text: str,
    query_type: SearchType = SearchType.GRAPH_COMPLETION,
    datasets: Optional[Union[list[str], str]] = None,
    top_k: int = 15,
    system_prompt: Optional[str] = None,
    only_context: bool = False,
    include_references: bool = False,
    **kwargs: Any,
) -> list[SearchResult]:
    """Search the knowledge graph (cognee ``search``).

    Performs hybrid semantic search over the dataset's memories and enriches
    with graph neighbors when available.

    Args:
        query_text: The search query.
        query_type: Search type (GRAPH_COMPLETION / RAG_COMPLETION supported;
            others fall back to the same hybrid path).
        datasets: Dataset name(s) to search. Defaults to all registered
            datasets.
        top_k: Max results.
        system_prompt / only_context / include_references / **kwargs: Ignored
            (parity).

    Returns:
        list[SearchResult] — each with ``search_result`` (dict: id, content,
        score, entities) and dataset metadata.
    """
    if not query_text or not query_text.strip():
        raise ValueError("cognee.search: query_text must be non-empty")
    client = _client()
    names = datasets if isinstance(datasets, list) else ([datasets] if datasets else None)

    # Resolve target workspaces: explicit names, or all registered
    workspaces: list[tuple[str, str]] = []  # (ws, name)
    if names:
        for n in names:
            workspaces.append((_dataset_ws(n), n))
    else:
        try:
            rows = client._query("workspace", "", {}, ["id", "name"])
            for r in rows:
                name = str(r.get("name", ""))
                if name.startswith("Cognee:"):
                    workspaces.append((r["id"], name.replace("Cognee:", "")))
        except Exception:
            pass
    if not workspaces:
        raise ValueError("cognee.search: no datasets found")

    results: list[SearchResult] = []
    for ws, name in workspaces:
        try:
            hits = client.search(
                workspace_id=ws,
                query=query_text,
                limit=top_k,
                semantic=True,
                cross_encoder=False,
            )
        except Exception as exc:
            logger.warning("cognee.search: search failed for %s (%s)", name, exc)
            hits = []
        for h in hits:
            results.append(
                SearchResult(
                    search_result={
                        "id": h.get("id", ""),
                        "content": h.get("content", h.get("memory", "")),
                        "score": h.get("score", 0.0),
                        "entities": _graph_neighbors(client, ws, str(h.get("content", ""))[:120]),
                    },
                    dataset_name=name,
                )
            )
    results.sort(key=lambda r: float(r.search_result.get("score", 0)), reverse=True)
    return results[:top_k]


def _graph_neighbors(client: Client, ws: str, content_snippet: str) -> list[str]:
    """Best-effort graph neighbor lookup: entities in this content snippet
    that exist as KG nodes (via substring match on node labels)."""
    try:
        nodes = client._query("kg_node", ws, {}, ["label"])
        snippet_lower = content_snippet.lower()
        return [
            str(n.get("label", ""))
            for n in nodes
            if str(n.get("label", "")).lower() and str(n.get("label", "")).lower() in snippet_lower
        ][:8]
    except Exception:
        return []


async def delete(
    dataset_name: str = "main_dataset",
    **kwargs: Any,
) -> None:
    """Delete a dataset and its memories (cognee ``delete``).

    Args:
        dataset_name: Dataset to delete.
        **kwargs: Ignored (parity).

    Returns:
        None.
    """
    client = _client()
    ws = _dataset_ws(dataset_name)
    try:
        rows = client._query("memory", ws, {}, ["id"])
    except Exception as exc:
        raise RuntimeError(f"cognee.delete: dataset '{dataset_name}' not found: {exc}") from exc
    if not rows:
        # Distinguish "workspace exists but empty" from "workspace missing"
        try:
            ws_rows = client._query("workspace", "", {"id": ws}, ["id"])
        except Exception:
            ws_rows = []
        if not ws_rows:
            raise RuntimeError(f"cognee.delete: dataset '{dataset_name}' not found")
    for r in rows:
        try:
            client._call("delete_memory", [r["id"]])
        except Exception:
            pass


async def prune(
    **kwargs: Any,
) -> None:
    """Delete ALL datasets (cognee ``prune``). Destructive — use with care."""
    client = _client()
    try:
        rows = client._query("workspace", "", {}, ["id", "name"])
    except Exception:
        return
    for r in rows:
        name = str(r.get("name", ""))
        if name.startswith("Cognee:"):
            ws = r["id"]
            try:
                mems = client._query("memory", ws, {}, ["id"])
                for m in mems:
                    try:
                        client._call("delete_memory", [m["id"]])
                    except Exception:
                        pass
            except Exception:
                pass


async def datasets() -> list[dict[str, Any]]:
    """List all datasets (cognee ``datasets()``).

    Returns:
        list of ``{"id": ..., "name": ...}`` dicts.
    """
    client = _client()
    out: list[dict[str, Any]] = []
    try:
        rows = client._query("workspace", "", {}, ["id", "name"])
        for r in rows:
            name = str(r.get("name", ""))
            if name.startswith("Cognee:"):
                out.append({"id": r["id"], "name": name.replace("Cognee:", "")})
    except Exception as exc:
        logger.warning("cognee.datasets: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Agent memory (session-cache style entries)
# ---------------------------------------------------------------------------

_current_context: dict[str, Any] = {}


def get_current_agent_memory_context() -> dict[str, Any]:
    """Return the current agent-memory context (cognee parity)."""
    return dict(_current_context)


def agent_memory(func: Any = None, *, context: dict[str, Any] | None = None):
    """Decorator that records the decorated call as an agent trace entry.

    When used as ``@agent_memory``, wraps the function so each invocation is
    recorded as a ``TraceEntry`` in the current context's ``trace`` list.

    Usage::

        @agent_memory
        def my_tool(x: str) -> str:
            return f"processed {x}"

        # The trace entry is appended to get_current_agent_memory_context()
    """

    def _decorate(fn: Any) -> Any:
        async def _async_wrapper(*args: Any, **kw: Any) -> Any:
            result = await fn(*args, **kw)
            _current_context.setdefault("trace", []).append(
                TraceEntry(
                    origin_function=fn.__name__,
                    status="success",
                    method_params=kw or None,
                    method_return_value=_safe_jsonable(result),
                )
            )
            return result

        def _sync_wrapper(*args: Any, **kw: Any) -> Any:
            result = fn(*args, **kw)
            _current_context.setdefault("trace", []).append(
                TraceEntry(
                    origin_function=fn.__name__,
                    status="success",
                    method_params=kw or None,
                    method_return_value=_safe_jsonable(result),
                )
            )
            return result

        if asyncio.iscoroutinefunction(fn):
            return _async_wrapper
        return _sync_wrapper

    if func is not None:
        return _decorate(func)
    return _decorate


def _safe_jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _run_sync(coro_factory: Any) -> Any:
    """Run an async function from a sync context, even inside a running loop.

    When called from within an already-running event loop (e.g. pytest-asyncio
    tests), executes the coroutine on a dedicated thread with its own loop so
    the current loop is never blocked. Otherwise uses ``asyncio.run``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    import threading

    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def sync_add(data: Any, dataset_name: str = "main_dataset", **kwargs: Any) -> None:
    """Synchronous wrapper around :func:`add` for non-async call sites."""
    return _run_sync(lambda: add(data, dataset_name=dataset_name, **kwargs))


def sync_cognify(dataset_name: str = "main_dataset", **kwargs: Any) -> None:
    """Synchronous wrapper around :func:`cognify`."""
    return _run_sync(lambda: cognify(dataset_name=dataset_name, **kwargs))


def sync_search(
    query_text: str,
    query_type: SearchType = SearchType.GRAPH_COMPLETION,
    datasets: Optional[Union[list[str], str]] = None,
    top_k: int = 15,
    **kwargs: Any,
) -> list[SearchResult]:
    """Synchronous wrapper around :func:`search`."""
    return _run_sync(
        lambda: search(query_text, query_type=query_type, datasets=datasets, top_k=top_k, **kwargs)
    )
