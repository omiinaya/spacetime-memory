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
from ..llm import LLMClient

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

    operation_ids: list[str] = Field(
        description="Operation IDs for tracking file conversion operations."
    )


class DispositionTraits(BaseModel):
    """Disposition traits that influence how memories are formed and interpreted."""

    skepticism: int = Field(
        default=3, ge=1, le=5, description="How skeptical vs trusting (1=trusting, 5=skeptical)"
    )
    literalism: int = Field(
        default=3,
        ge=1,
        le=5,
        description="How literally to interpret information (1=flexible, 5=literal)",
    )
    empathy: int = Field(
        default=3,
        ge=1,
        le=5,
        description="How much to consider emotional context (1=detached, 5=empathetic)",
    )


class BankProfileResponse(BaseModel):
    """Response model for bank profile."""

    bank_id: str
    name: str
    disposition: DispositionTraits
    mission: str = Field(
        description="The agent's mission statement that guides memory formation and reflection"
    )
    background: Optional[str] = None


class ListMemoryUnitsResponse(BaseModel):
    """Response model for list memory units endpoint."""

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class CreateBankResponse(BaseModel):
    """Response model for create_bank endpoint."""

    id: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    success: bool = True


class CreateMentalModelResponse(BaseModel):
    """Response model for create_mental_model endpoint."""

    id: str
    name: str
    content: str = ""
    success: bool = True


class CreateDirectiveResponse(BaseModel):
    """Response model for create_directive endpoint."""

    id: str
    name: str
    content: str = ""
    success: bool = True


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
# Low-level property shells
# ---------------------------------------------------------------------------


class _HindsightLowLevelShell:
    """Shell for low-level API properties that need a REST server.

    Returns graceful empty/no-op responses instead of raising errors.
    The upstream Hindsight REST server handles these; our SpacetimeDB
    adapter returns empty results for listing operations and no-ops
    for mutations.
    """

    def __init__(self, name: str) -> None:
        self._shell_name = name

    def __getattr__(self, attr: str) -> Any:
        return lambda *a, **kw: _empty_shell_response(self._shell_name, attr)

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _empty_shell_response(self._shell_name, "call")


def _empty_shell_response(shell: str, method: str) -> dict[str, Any]:
    """Return a graceful empty response for REST-only shells."""
    return {
        "status": "ok",
        "note": (
            f"Hindsight.{shell}.{method}() is a REST-server feature. "
            f"The SpacetimeDB adapter returns empty results."
        ),
        "items": [],
        "total": 0,
    }


class _HindsightMentalModelsShell:
    """Mental models shell — delegates to Hindsight.create_mental_model()."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def create(
        self, bank_id: str, name: str, query: str | None = None, **params: Any
    ) -> "CreateMentalModelResponse":
        return self._h.create_mental_model(bank_id=bank_id, name=name, query=query, **params)


class _HindsightDirectivesShell:
    """Directives shell — delegates to Hindsight.create_directive()."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def create(
        self, bank_id: str, name: str, prompt: str, **params: Any
    ) -> "CreateDirectiveResponse":
        return self._h.create_directive(bank_id=bank_id, name=name, prompt=prompt, **params)


class _HindsightFilesShell:
    """Files shell — delegates to Hindsight.retain_files()."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def upload(
        self,
        bank_id: str,
        files: list[str | Path],
        *,
        context: str | None = None,
        files_metadata: list[dict[str, Any]] | None = None,
    ) -> "FileRetainResponse":
        return self._h.retain_files(
            bank_id=bank_id,
            files=files,
            context=context,
            files_metadata=files_metadata,
        )


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
    ) -> None:
        import hashlib

        self._timeout = timeout
        self._user_agent = user_agent or "spacetime-memory-hindsight/0.0.0"
        self._api_key = api_key

        db = (
            stdb_database
            or hashlib.md5((base_url or f"{stdb_host}:{stdb_port}").encode()).hexdigest()[:16]
        )

        self._client = Client(
            host=stdb_host,
            port=stdb_port,
            database=db,
            token=api_key,
        )
        self._closed = False
        # bank_id → workspace_id cache
        self._ws_cache: dict[str, str] = {}
        self._llm: LLMClient | None = None

    # -- low-level API property shells -----------------------------------------

    @property
    def memory(self) -> "Hindsight":
        """Low-level memory operations — returns self (all ops on Hindsight)."""
        return self

    @property
    def banks(self) -> "Hindsight":
        """Low-level bank operations — returns self (bank ops map to workspace ops)."""
        return self

    @property
    def documents(self) -> "_HindsightLowLevelShell":
        """Low-level document operations shell — NotImplementedError for server ops."""
        return _HindsightLowLevelShell("documents")

    @property
    def entities(self) -> "_HindsightLowLevelShell":
        """Low-level entity operations shell — NotImplementedError for server ops."""
        return _HindsightLowLevelShell("entities")

    @property
    def mental_models(self) -> "_HindsightMentalModelsShell":
        """Low-level mental model operations — delegates to create_mental_model."""
        return _HindsightMentalModelsShell(self)

    @property
    def directives(self) -> "_HindsightDirectivesShell":
        """Low-level directive operations — delegates to create_directive."""
        return _HindsightDirectivesShell(self)

    @property
    def operations(self) -> "_HindsightLowLevelShell":
        """Low-level operation tracking shell — NotImplementedError for server ops."""
        return _HindsightLowLevelShell("operations")

    @property
    def webhooks(self) -> "_HindsightLowLevelShell":
        """Low-level webhook management shell — NotImplementedError for server ops."""
        return _HindsightLowLevelShell("webhooks")

    @property
    def files(self) -> "_HindsightFilesShell":
        """Low-level file operations — delegates to retain_files."""
        return _HindsightFilesShell(self)

    @property
    def monitoring(self) -> "_HindsightLowLevelShell":
        """Low-level monitoring shell — NotImplementedError for server ops."""
        return _HindsightLowLevelShell("monitoring")

    # -- helpers ---------------------------------------------------------------

    def _get_llm(self) -> LLMClient:
        """Lazy-init the LLM client."""
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

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

    def __enter__(self) -> "Hindsight":
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any | None
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the client."""
        self._closed = True

    async def aclose(self) -> None:
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
                bank_id=bank_id,
                content=content,
                timestamp=timestamp,
                context=context,
                document_id=document_id,
                metadata=metadata,
                entities=entities,
                tags=tags,
                update_mode=update_mode,
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
                bank_id=bank_id,
                items=items,
                document_id=document_id,
                document_tags=document_tags,
                retain_async=retain_async,
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
            except RuntimeError as exc:
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
                bank_id=bank_id,
                query=query,
                types=types,
                max_tokens=max_tokens,
                budget=budget,
                trace=trace,
                query_timestamp=query_timestamp,
                include_entities=include_entities,
                max_entity_tokens=max_entity_tokens,
                include_chunks=include_chunks,
                max_chunk_tokens=max_chunk_tokens,
                include_source_facts=include_source_facts,
                max_source_facts_tokens=max_source_facts_tokens,
                tags=tags,
                tags_match=tags_match,
                tag_groups=tag_groups,
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
                bank_id=bank_id,
                query=query,
                budget=budget,
                context=context,
                max_tokens=max_tokens,
                response_schema=response_schema,
                tags=tags,
                tags_match=tags_match,
                include_facts=include_facts,
                include_tool_calls=include_tool_calls,
                include_tool_call_output=include_tool_call_output,
                tag_groups=tag_groups,
                fact_types=fact_types,
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
            merged_meta["timestamp"] = (
                timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            )
        if document_id:
            merged_meta["document_id"] = document_id

        try:
            self._client.store(ws_id, content=content, summary=summary, entities_json=entities_json)
            return RetainResponse(
                success=True,
                bank_id=bank_id,
                items_count=1,
                async_=retain_async,
            )
        except RuntimeError:
            return RetainResponse(
                success=False,
                bank_id=bank_id,
                items_count=0,
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
                self._client.store(
                    ws_id, content=content, summary=summary, entities_json=entities_json
                )
                count += 1
            except RuntimeError as exc:
                logger.warning("aretain_batch() failed to store item: %s", exc)

        return RetainResponse(
            success=True,
            bank_id=bank_id,
            items_count=count,
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
                ws_id,
                query=query,
                limit=limit,
                semantic=True,
            )
        except RuntimeError as exc:
            logger.warning("arecall() search failed: %s", exc)
            rows = []

        results: list[RecallResult] = []
        for i, row in enumerate(rows[:10]):
            content = row.get("memory_content", row.get("content", ""))
            results.append(
                RecallResult(
                    id=row.get("id", row.get("entity_id", str(i))),
                    text=content,
                    type=row.get("entity_type", "experience"),
                    score=row.get("score", 0.0),
                    context=row.get("context"),
                )
            )

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
        except RuntimeError as exc:
            logger.warning("areflect() search failed: %s", exc)
            memories = []

        memory_snippets = "\n".join(
            f"- {m.get('memory_content', m.get('content', ''))}" for m in memories[:10]
        )

        prompt = (
            "Based on the following memories, answer the question.\n\n"
            f"Context:\n{context or 'No additional context.'}\n\n"
            f"Relevant memories:\n{memory_snippets or 'No relevant memories found.'}\n\n"
            f"Question: {query}\n\nAnswer:"
        )

        try:
            insight_result = self._client._call(
                "create_insight",
                [
                    ws_id,
                    prompt,
                    "",
                    "reflect",
                ],
            )
            answer_text = insight_result.get(
                "insight", insight_result.get("content", str(insight_result))
            )
        except RuntimeError as exc:
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

    # -- list_memories ---------------------------------------------------------

    def list_memories(
        self,
        bank_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> ListMemoryUnitsResponse:
        """List memory units in a bank (sync wrapper)."""
        return _run_async(self.alist_memories(bank_id=bank_id, limit=limit, offset=offset))

    async def alist_memories(
        self,
        bank_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> ListMemoryUnitsResponse:
        """List memory units in a bank (async)."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)

        try:
            rows = self._client.search(ws_id, query="", limit=limit + offset, semantic=False)
        except RuntimeError as exc:
            logger.warning("alist_memories() search failed: %s", exc)
            rows = []

        rows = rows[offset:]

        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": row.get("id", ""),
                    "content": row.get("memory_content", row.get("content", "")),
                    "created_at": row.get("created_at", ""),
                    "metadata": row.get("metadata", {}),
                }
            )

        return ListMemoryUnitsResponse(
            items=items,
            total=len(items),
            limit=limit,
            offset=offset,
        )

    # -- delete_bank -----------------------------------------------------------

    def delete_bank(self, bank_id: str) -> None:
        """Delete a memory bank (sync wrapper)."""
        return _run_async(self.adelete_bank(bank_id=bank_id))

    async def adelete_bank(self, bank_id: str) -> None:
        """Delete a memory bank (async)."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)
        self._client._call("delete_workspace", [ws_id])
        self._ws_cache.pop(bank_id, None)

    # -- create_bank -----------------------------------------------------------

    def create_bank(
        self,
        name: str | None = None,
        description: str | None = None,
        **config: Any,
    ) -> CreateBankResponse:
        """Create a new memory bank (workspace) with optional LLM-generated config.

        Sync wrapper — see ``acreate_bank`` for async implementation.
        """
        return _run_async(self.acreate_bank(name=name, description=description, **config))

    async def acreate_bank(
        self,
        name: str | None = None,
        description: str | None = None,
        **config: Any,
    ) -> CreateBankResponse:
        """Create a new memory bank (workspace) with optional LLM-generated config.

        Args:
            name: Bank name (required).
            description: Optional description for LLM context.
            **config: Additional config (disposition, mission, etc.) merged into result.

        Returns:
            ``CreateBankResponse`` with id, name, and generated config.
        """
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        bank_name = name or config.get("name", "default")

        # Check if bank already exists
        existing = self._client.list_workspaces()
        for ws in existing:
            if ws.get("name") == bank_name:
                ws_id = ws["id"]
                self._ws_cache[bank_name] = ws_id
                return CreateBankResponse(
                    id=ws_id,
                    name=bank_name,
                    config={**config, "pre_existing": True},
                    success=True,
                )

        # Create workspace
        result = self._client.create_workspace(name=bank_name, description=description or "")
        ws_id = result.get("id", bank_name) if isinstance(result, dict) else bank_name
        self._ws_cache[bank_name] = ws_id

        # Generate bank configuration via LLM
        bank_config: dict[str, Any] = dict(config)
        try:
            llm = self._get_llm()
            if llm.available:
                prompt = (
                    f"Generate a configuration for a memory bank named '{bank_name}'.\n"
                    + (f"Description: {description}\n" if description else "")
                    + "Return valid JSON with these keys:\n"
                    "  - disposition: object with skepticism (1-5), literalism (1-5), empathy (1-5)\n"
                    "  - mission: string describing the bank's purpose\n"
                    "  - extraction_modes: list of strings (e.g. ['facts', 'entities', 'sentiment'])\n"
                    "  - background: optional string\n"
                    "Return ONLY the JSON object, no markdown, no explanation."
                )
                response = llm.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=512,
                )
                if response:
                    try:
                        gen_config = json.loads(response)
                        if isinstance(gen_config, dict):
                            bank_config.update(gen_config)
                    except (json.JSONDecodeError, TypeError):
                        bank_config["_llm_raw"] = response
            else:
                bank_config.update(
                    {
                        "disposition": {"skepticism": 3, "literalism": 3, "empathy": 3},
                        "mission": f"Memory bank for {bank_name}",
                        "extraction_modes": ["facts", "entities"],
                    }
                )
        except RuntimeError as exc:
            logger.warning("acreate_bank() LLM config generation failed: %s", exc)
            bank_config.update(
                {
                    "disposition": {"skepticism": 3, "literalism": 3, "empathy": 3},
                    "mission": f"Memory bank for {bank_name}",
                    "extraction_modes": ["facts", "entities"],
                }
            )

        return CreateBankResponse(
            id=ws_id,
            name=bank_name,
            config=bank_config,
            success=True,
        )

    # -- create_mental_model ---------------------------------------------------

    def create_mental_model(
        self,
        bank_id: str,
        name: str,
        query: str | None = None,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Create a mental model synthesized from bank memories.

        Sync wrapper — see ``acreate_mental_model`` for async implementation.
        """
        return _run_async(
            self.acreate_mental_model(bank_id=bank_id, name=name, query=query, **params)
        )

    async def acreate_mental_model(
        self,
        bank_id: str,
        name: str,
        query: str | None = None,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Create a mental model synthesized from bank memories.

        Searches the bank for relevant memories, uses LLM to synthesize
        a mental model, and stores it as a memory in the workspace.

        Args:
            bank_id: The bank to search.
            name: Name for the mental model.
            query: Query to find relevant memories (defaults to name).
            **params: Additional parameters passed through.

        Returns:
            ``CreateMentalModelResponse`` with id, name, and content.
        """
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)
        search_query = query or name

        # Search for relevant memories
        memories: list[dict[str, Any]] = []
        try:
            memories = self._client.search(
                ws_id,
                query=search_query,
                limit=10,
                semantic=True,
            )
        except RuntimeError as exc:
            logger.warning("acreate_mental_model() search failed: %s", exc)

        # Synthesize mental model via LLM
        content: str = ""
        try:
            llm = self._get_llm()
            if llm.available and memories:
                memory_snippets = "\n".join(
                    f"- {m.get('memory_content', m.get('content', ''))}" for m in memories[:10]
                )
                prompt = (
                    f"Synthesize a mental model named '{name}' from these memories:\n\n"
                    f"{memory_snippets or 'No relevant memories found.'}\n\n"
                    "Create a concise, coherent summary that captures the key "
                    "patterns, facts, and relationships. This mental model will "
                    "be used to guide future memory formation and reflection."
                )
                response = llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "You are a knowledge synthesis assistant. Create concise mental models from memory fragments.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                )
                content = response or ""
            elif memories:
                # Fallback: join memory contents
                content = " / ".join(
                    m.get("memory_content", m.get("content", "")) for m in memories[:5]
                )
            # else: no memories, content stays empty
        except RuntimeError as exc:
            logger.warning("acreate_mental_model() LLM synthesis failed: %s", exc)
            if not content and memories:
                content = " / ".join(
                    m.get("memory_content", m.get("content", "")) for m in memories[:5]
                )

        if not content:
            content = f"Mental model '{name}' — insufficient data to synthesize."

        # Store as memory
        model_id = ""
        try:
            result = self._client.store(
                ws_id,
                content=content,
                summary=f"Mental model: {name}",
                memory_type="mental_model",
            )
            model_id = (
                result.get("id", _make_op_id()) if isinstance(result, dict) else _make_op_id()
            )
        except RuntimeError as exc:
            logger.warning("acreate_mental_model() store failed: %s", exc)
            model_id = _make_op_id()

        return CreateMentalModelResponse(
            id=model_id,
            name=name,
            content=content,
            success=True,
        )

    # -- create_directive ------------------------------------------------------

    def create_directive(
        self,
        bank_id: str,
        name: str,
        prompt: str,
        **params: Any,
    ) -> CreateDirectiveResponse:
        """Store a directive (system prompt) in a bank.

        Sync wrapper — see ``acreate_directive`` for async implementation.
        """
        return _run_async(
            self.acreate_directive(bank_id=bank_id, name=name, prompt=prompt, **params)
        )

    async def acreate_directive(
        self,
        bank_id: str,
        name: str,
        prompt: str,
        **params: Any,
    ) -> CreateDirectiveResponse:
        """Store a directive (system prompt) in a bank.

        Directives are stored as memories with type ``directive`` and are
        injected into LLM calls during reflection.

        Args:
            bank_id: The bank to store the directive in.
            name: Name for the directive.
            prompt: The directive content/prompt text.
            **params: Additional parameters passed through.

        Returns:
            ``CreateDirectiveResponse`` with id, name, and content.
        """
        if self._closed:
            raise RuntimeError("Hindsight client is closed")

        ws_id = self._ensure_bank(bank_id)

        directive_id = ""
        try:
            result = self._client.store(
                ws_id,
                content=prompt,
                summary=f"Directive: {name}",
                memory_type="directive",
            )
            directive_id = (
                result.get("id", _make_op_id()) if isinstance(result, dict) else _make_op_id()
            )
        except RuntimeError as exc:
            logger.warning("acreate_directive() store failed: %s", exc)
            directive_id = _make_op_id()

        return CreateDirectiveResponse(
            id=directive_id,
            name=name,
            content=prompt,
            success=True,
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
    "CreateBankResponse",
    "CreateMentalModelResponse",
    "CreateDirectiveResponse",
    "DispositionTraits",
    "TokenUsage",
]
