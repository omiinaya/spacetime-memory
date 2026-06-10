"""
Drop-in replacement for ``hindsight_client.Hindsight`` (v0.8.1).

Maps the Hindsight REST API (https://github.com/vectorize-io/hindsight)
to SpacetimeDB storage. Exact signature match — pass this anywhere you
use ``hindsight_client.Hindsight``.

Usage::

    from spacetime_memory.sdks.hindsight import Hindsight

    h = Hindsight(base_url=None, stdb_host="localhost", stdb_port=3001, stdb_database="my_db")
    result = h.retain(bank_id="alice", content="Alice loves pizza")
    response = h.recall(bank_id="alice", query="What does Alice like?")
    answer = h.reflect(bank_id="alice", query="What are Alice's interests?")

    with Hindsight(base_url=None, stdb_host="localhost") as h:
        h.retain(bank_id="bob", content="Bob likes hiking")

    # Async
    await h.aretain(bank_id="alice", content="Alice likes coffee")
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..client import Client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response types — exact match to hindsight_client_api.models (v0.8.1)
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """Token usage metrics for LLM calls."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


class ChunkData(BaseModel):
    """Chunk data for a single chunk."""
    id: str
    text: str
    chunk_index: int
    truncated: bool = False


class EntityObservationResponse(BaseModel):
    """An observation about an entity."""
    text: str
    mentioned_at: Optional[str] = None


class EntityStateResponse(BaseModel):
    """Current mental model of an entity."""
    entity_id: str
    canonical_name: str
    observations: list[EntityObservationResponse]


class RecallResult(BaseModel):
    """Single recall result item."""
    id: str
    text: str
    type: Optional[str] = None
    entities: Optional[list[str]] = None
    context: Optional[str] = None
    occurred_start: Optional[str] = None
    occurred_end: Optional[str] = None
    mentioned_at: Optional[str] = None
    document_id: Optional[str] = None
    metadata: Optional[dict[str, str]] = None
    chunk_id: Optional[str] = None
    tags: Optional[list[str]] = None
    source_fact_ids: Optional[list[str]] = None
    score: Optional[float] = None


class RetainResponse(BaseModel):
    """Response model for retain endpoint."""
    success: bool
    bank_id: str
    items_count: int
    var_async: bool = Field(default=False, alias="async")
    operation_id: Optional[str] = None
    operation_ids: Optional[list[str]] = None
    usage: Optional[TokenUsage] = None

    model_config = {"populate_by_name": True}


class RecallResponse(BaseModel):
    """Response model for recall endpoints."""
    results: list[RecallResult]
    trace: Optional[dict[str, Any]] = None
    entities: Optional[dict[str, EntityStateResponse]] = None
    chunks: Optional[dict[str, ChunkData]] = None
    source_facts: Optional[dict[str, RecallResult]] = None


class ReflectFact(BaseModel):
    """A fact used in reflect response."""
    id: Optional[str] = None
    text: str
    type: Optional[str] = None
    context: Optional[str] = None
    occurred_start: Optional[str] = None
    occurred_end: Optional[str] = None


class ReflectDirective(BaseModel):
    """A directive applied during reflect."""
    id: str
    name: str
    content: str


class ReflectMentalModel(BaseModel):
    """A mental model used during reflect."""
    id: str
    text: str
    context: Optional[str] = None


class ReflectBasedOn(BaseModel):
    """Evidence the response is based on: memories, mental models, directives."""
    memories: Optional[list[ReflectFact]] = None
    mental_models: Optional[list[ReflectMentalModel]] = None
    directives: Optional[list[ReflectDirective]] = None


class ReflectToolCall(BaseModel):
    """A tool call made during reflect agent execution."""
    tool: str = Field(description="Tool name: lookup, recall, learn, expand")
    input: dict[str, Any]
    output: Optional[dict[str, Any]] = None
    duration_ms: int = Field(description="Execution time in milliseconds")
    iteration: int = 0


class ReflectLLMCall(BaseModel):
    """An LLM call made during reflect agent execution."""
    scope: str = Field(description="Call scope: agent_1, agent_2, final, etc.")
    duration_ms: int = Field(description="Execution time in milliseconds")


class ReflectTrace(BaseModel):
    """Execution trace of LLM and tool calls during reflection."""
    tool_calls: Optional[list[ReflectToolCall]] = None
    llm_calls: Optional[list[ReflectLLMCall]] = None


class ReflectResponse(BaseModel):
    """Response model for reflect (think) endpoint."""
    text: str = Field(description="The reflect response as well-formatted markdown")
    based_on: Optional[ReflectBasedOn] = None
    structured_output: Optional[dict[str, Any]] = None
    usage: Optional[TokenUsage] = None
    trace: Optional[ReflectTrace] = None


class FileRetainResponse(BaseModel):
    """Response model for file upload endpoint."""
    operation_ids: list[str] = Field(description="Operation IDs for tracking file conversion operations.")


class DispositionTraits(BaseModel):
    """Disposition traits that influence how memories are formed and interpreted."""
    skepticism: int = Field(default=3, ge=1, le=5, description="How skeptical vs trusting (1=trusting, 5=skeptical)")
    literalism: int = Field(default=3, ge=1, le=5, description="How literally to interpret information (1=flexible, 5=literal)")
    empathy: int = Field(default=3, ge=1, le=5, description="How much to consider emotional context (1=detached, 5=empathetic)")


class BankProfileResponse(BaseModel):
    """Response model for bank profile."""
    bank_id: str
    name: str
    disposition: DispositionTraits
    mission: str = Field(description="The agent's mission statement that guides memory formation and reflection")
    background: Optional[str] = None


class ListMemoryUnitsResponse(BaseModel):
    """Response model for list memory units endpoint."""
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine synchronously.

    Uses ``asyncio.run()`` when no event loop is running (safe in threads,
    sync scripts, REPL).  If an event loop IS running (Jupyter, FastAPI,
    async test), raises ``RuntimeError`` — use ``await`` on the async
    variant directly instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop running — safe to use asyncio.run()
        return asyncio.run(coro)
    raise RuntimeError(
        "Cannot call sync wrapper from async context. "
        "Use the async variant directly: await client.aretain(...)"
    )


def _make_op_id() -> str:
    """Generate a short unique operation ID."""
    import hashlib
    import os
    return hashlib.md5(os.urandom(16)).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Hindsight client — drop-in replacement for hindsight_client.Hindsight v0.8.1
# ---------------------------------------------------------------------------

class Hindsight:
    """Drop-in replacement for ``hindsight_client.Hindsight`` (v0.8.1).

    Accepts standard Hindsight constructor args (``base_url``, ``api_key``)
    for compatibility, plus SpacetimeDB-specific params via ``stdb_*``.

    When ``stdb_database`` is omitted, it's derived from ``base_url`` or
    ``stdb_host:stdb_port`` to provide a stable default.

    **Error contract:**
    - Return types are typed Pydantic models with ``success`` flags
      (e.g. ``RetainResponse(success=True/False)``).  This matches the
      upstream ``hindsight_client`` design — errors are in the response,
      not raised as exceptions.
    - ``RuntimeError`` raised for network-level failures (connection
      refused, timeout after retries) via the underlying ``Client``.
    - ``RuntimeError`` raised when calling sync wrappers (``retain``,
      ``recall``, ``reflect``) in an async context — use ``await``
      variants instead.
    - ``RuntimeError`` raised when using a closed client.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 300.0,
        user_agent: str | None = None,
        # SpacetimeDB-specific params (used when base_url is None)
        stdb_host: str = "localhost",
        stdb_port: int = 3001,
        stdb_database: str | None = None,
    ):
        import hashlib

        self._timeout = timeout
        self._user_agent = user_agent or "spacetime-memory-hindsight/0.0.0"
        self._api_key = api_key

        db = stdb_database or hashlib.md5(
            (base_url or f"{stdb_host}:{stdb_port}").encode()
        ).hexdigest()[:16]

        self._client = Client(
            host=stdb_host,
            port=stdb_port,
            database=db,
            token=api_key,
        )
        self._closed = False
        # bank_id → workspace_id cache
        self._ws_cache: dict[str, str] = {}

    # -- helpers ---------------------------------------------------------------

    def _ensure_bank(self, bank_id: str) -> str:
        """Resolve a bank_id to a SpacetimeDB workspace_id, creating if needed."""
        if bank_id in self._ws_cache:
            return self._ws_cache[bank_id]

        existing = self._client.list_workspaces()
        for ws in existing:
            if ws.get("name") == bank_id:
                self._ws_cache[bank_id] = ws["id"]
                return ws["id"]

        result = self._client.create_workspace(name=bank_id)
        ws_id = result.get("id", bank_id)
        self._ws_cache[bank_id] = ws_id
        return ws_id

    # -- context manager -------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the client."""
        self._closed = True

    async def aclose(self):
        """Close the client (async version)."""
        self._closed = True

    # -- retain ----------------------------------------------------------------

    def retain(
        self,
        bank_id: str,
        content: str,
        *,
        timestamp: datetime.datetime | None = None,
        context: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, str] | None = None,
        entities: list[dict[str, str]] | None = None,
        tags: list[str] | None = None,
        update_mode: str | None = None,
        retain_async: bool = False,
    ) -> RetainResponse:
        """Store a single memory (sync wrapper)."""
        return _run_async(
            self.aretain(
                bank_id=bank_id, content=content, timestamp=timestamp,
                context=context, document_id=document_id, metadata=metadata,
                entities=entities, tags=tags, update_mode=update_mode,
                retain_async=retain_async,
            )
        )

    def retain_batch(
        self,
        bank_id: str,
        items: list[dict[str, Any]],
        *,
        document_id: str | None = None,
        document_tags: list[str] | None = None,
        retain_async: bool = False,
    ) -> RetainResponse:
        """Store multiple memories in batch (sync wrapper)."""
        return _run_async(
            self.aretain_batch(
                bank_id=bank_id, items=items, document_id=document_id,
                document_tags=document_tags, retain_async=retain_async,
            )
        )

    def retain_files(
        self,
        bank_id: str,
        files: list[str | Path],
        *,
        context: str | None = None,
        files_metadata: list[dict[str, Any]] | None = None,
    ) -> FileRetainResponse:
        """Upload files and retain their contents as memories."""
        meta = files_metadata or [{"context": context} if context else {} for _ in files]
        operation_ids: list[str] = []

        for i, file_path in enumerate(files):
            path = Path(file_path)
            text = path.read_bytes().decode("utf-8", errors="replace")
            op_id = _make_op_id()
            operation_ids.append(op_id)
            m = meta[i] if i < len(meta) else {}
            merged = {**m, "bank_id": bank_id, "document_id": m.get("document_id", "")}

            ws_id = self._ensure_bank(bank_id)
            try:
                self._client.store(ws_id, content=text, summary=merged.get("context", ""))
            except Exception as exc:
                logger.warning("retain_files() failed to store %s: %s", file_path, exc)

        return FileRetainResponse(operation_ids=operation_ids)

    # -- recall ----------------------------------------------------------------

    def recall(
        self,
        bank_id: str,
        query: str,
        *,
        types: list[str] | None = None,
        max_tokens: int = 4096,
        budget: str = "mid",
        trace: bool = False,
        query_timestamp: str | None = None,
        include_entities: bool = False,
        max_entity_tokens: int = 500,
        include_chunks: bool = False,
        max_chunk_tokens: int = 8192,
        include_source_facts: bool = False,
        max_source_facts_tokens: int = 4096,
        tags: list[str] | None = None,
        tags_match: Literal["any", "all", "any_strict", "all_strict"] = "any",
        tag_groups: list[dict[str, Any]] | None = None,
    ) -> RecallResponse:
        """Recall memories using semantic similarity (sync wrapper)."""
        return _run_async(
            self.arecall(
                bank_id=bank_id, query=query, types=types,
                max_tokens=max_tokens, budget=budget, trace=trace,
                query_timestamp=query_timestamp, include_entities=include_entities,
                max_entity_tokens=max_entity_tokens, include_chunks=include_chunks,
                max_chunk_tokens=max_chunk_tokens, include_source_facts=include_source_facts,
                max_source_facts_tokens=max_source_facts_tokens,
                tags=tags, tags_match=tags_match, tag_groups=tag_groups,
            )
        )

    # -- reflect ---------------------------------------------------------------

    def reflect(
        self,
        bank_id: str,
        query: str,
        *,
        budget: str = "low",
        context: str | None = None,
        max_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        tags_match: Literal["any", "all", "any_strict", "all_strict"] = "any",
        include_facts: bool = False,
        include_tool_calls: bool = False,
        include_tool_call_output: bool = True,
        tag_groups: list[dict[str, Any]] | None = None,
        fact_types: list[str] | None = None,
        exclude_mental_models: bool = False,
        exclude_mental_model_ids: list[str] | None = None,
    ) -> ReflectResponse:
        """Generate a contextual answer based on bank identity and memories (sync wrapper)."""
        return _run_async(
            self.areflect(
                bank_id=bank_id, query=query, budget=budget,
                context=context, max_tokens=max_tokens,
                response_schema=response_schema, tags=tags,
                tags_match=tags_match, include_facts=include_facts,
                include_tool_calls=include_tool_calls,
                include_tool_call_output=include_tool_call_output,
                tag_groups=tag_groups, fact_types=fact_types,
                exclude_mental_models=exclude_mental_models,
                exclude_mental_model_ids=exclude_mental_model_ids,
            )
        )

    # -- Async implementations -------------------------------------------------

    async def aretain(
        self,
        bank_id: str,
        content: str,
        *,
        timestamp: datetime.datetime | None = None,
        context: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, str] | None = None,
        entities: list[dict[str, str]] | None = None,
        tags: list[str] | None = None,
        update_mode: str | None = None,
        retain_async: bool = False,
    ) -> RetainResponse:
        """Store a single memory (async)."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)
        summary = context or ""
        entities_json = json.dumps(entities or [])
        merged_meta = dict(metadata or {})
        if tags:
            merged_meta["tags"] = json.dumps(tags)
        if timestamp:
            merged_meta["timestamp"] = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
        if document_id:
            merged_meta["document_id"] = document_id

        try:
            self._client.store(ws_id, content=content, summary=summary,
                               entities_json=entities_json)
            return RetainResponse(
                success=True, bank_id=bank_id, items_count=1,
                async_=retain_async,
            )
        except Exception:
            return RetainResponse(
                success=False, bank_id=bank_id, items_count=0,
                async_=retain_async,
            )

    async def aretain_batch(
        self,
        bank_id: str,
        items: list[dict[str, Any]],
        *,
        document_id: str | None = None,
        document_tags: list[str] | None = None,
        retain_async: bool = False,
    ) -> RetainResponse:
        """Store multiple memories in batch (async)."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)
        count = 0
        for item in items:
            content = item.get("content", "")
            if not content:
                continue
            summary = item.get("context", "")
            entities_json = json.dumps(item.get("entities", []))
            try:
                self._client.store(ws_id, content=content, summary=summary,
                                   entities_json=entities_json)
                count += 1
            except Exception as exc:
                logger.warning("aretain_batch() failed to store item: %s", exc)

        return RetainResponse(
            success=True, bank_id=bank_id, items_count=count,
            async_=retain_async,
        )

    async def arecall(
        self,
        bank_id: str,
        query: str,
        *,
        types: list[str] | None = None,
        max_tokens: int = 4096,
        budget: str = "mid",
        trace: bool = False,
        query_timestamp: str | None = None,
        include_entities: bool = False,
        max_entity_tokens: int = 500,
        include_chunks: bool = False,
        max_chunk_tokens: int = 8192,
        include_source_facts: bool = False,
        max_source_facts_tokens: int = 4096,
        tags: list[str] | None = None,
        tags_match: Literal["any", "all", "any_strict", "all_strict"] = "any",
        tag_groups: list[dict[str, Any]] | None = None,
    ) -> RecallResponse:
        """Recall memories using semantic similarity (async)."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)
        limit = min(max_tokens // 200, 100) or 20

        try:
            rows = self._client.search(
                ws_id, query=query, limit=limit, semantic=True,
            )
        except Exception as exc:
            logger.warning("arecall() search failed: %s", exc)
            rows = []

        results: list[RecallResult] = []
        for i, row in enumerate(rows[:10]):
            content = row.get("memory_content", row.get("content", ""))
            results.append(RecallResult(
                id=row.get("id", row.get("entity_id", str(i))),
                text=content,
                type=row.get("entity_type", "experience"),
                score=row.get("score", 0.0),
                context=row.get("context"),
            ))

        return RecallResponse(results=results)

    async def areflect(
        self,
        bank_id: str,
        query: str,
        *,
        budget: str = "low",
        context: str | None = None,
        max_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        tags_match: Literal["any", "all", "any_strict", "all_strict"] = "any",
        include_facts: bool = False,
        include_tool_calls: bool = False,
        include_tool_call_output: bool = True,
        tag_groups: list[dict[str, Any]] | None = None,
        fact_types: list[str] | None = None,
        exclude_mental_models: bool = False,
        exclude_mental_model_ids: list[str] | None = None,
    ) -> ReflectResponse:
        """Generate a contextual answer based on bank identity and memories (async).

        Uses the Spacetime-Memory LLM pathway (``create_insight`` reducer) to
        answer questions based on stored memories.
        """
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)

        # Retrieve relevant context
        try:
            memories = self._client.search(ws_id, query=query, limit=20, semantic=True)
        except Exception as exc:
            logger.warning("areflect() search failed: %s", exc)
            memories = []

        memory_snippets = "\n".join(
            f"- {m.get('memory_content', m.get('content', ''))}"
            for m in memories[:10]
        )

        prompt = (
            "Based on the following memories, answer the question.\n\n"
            f"Context:\n{context or 'No additional context.'}\n\n"
            f"Relevant memories:\n{memory_snippets or 'No relevant memories found.'}\n\n"
            f"Question: {query}\n\nAnswer:"
        )

        try:
            insight_result = self._client._call("create_insight", [
                ws_id, prompt, "", "reflect",
            ])
            answer_text = insight_result.get("insight", insight_result.get("content", str(insight_result)))
        except Exception as exc:
            logger.warning("areflect() LLM insight failed: %s", exc)
            answer_text = (
                "I don't have enough information to answer that based on "
                f"the stored memories for '{bank_id}'."
            )

        # Build optional based_on
        facts = None
        if include_facts and memories:
            facts = [
                ReflectFact(id=m.get("id"), text=m.get("memory_content", m.get("content", "")))
                for m in memories[:5]
            ]

        based_on = ReflectBasedOn(memories=facts) if facts else None

        # Try structured output
        structured = None
        if response_schema:
            try:
                structured = json.loads(answer_text)
            except (json.JSONDecodeError, TypeError):
                structured = {"answer": answer_text}

        return ReflectResponse(
            text=answer_text,
            based_on=based_on,
            structured_output=structured,
            usage=TokenUsage(
                input_tokens=len(prompt) // 4,
                output_tokens=len(answer_text) // 4,
            ),
        )


__all__ = [
    "Hindsight",
    "RetainResponse",
    "RecallResponse",
    "RecallResult",
    "ReflectResponse",
    "ReflectFact",
    "FileRetainResponse",
    "BankProfileResponse",
    "ListMemoryUnitsResponse",
    "DispositionTraits",
    "TokenUsage",
]
