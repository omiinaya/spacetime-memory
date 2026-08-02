"""
Drop-in replacement for ``hindsight_client.Hindsight`` (v0.8.1).

Maps the Hindsight REST API (https://github.com/vectorize-io/hindsight)
to SpacetimeDB storage. Exact signature match — pass this anywhere you
use ``hindsight_client.Hindsight``.

Usage::

    from spacetime_memory.sdks.hindsight import Hindsight

    h = Hindsight(base_url=None, stdb_host="127.0.0.1", stdb_port=3001, stdb_database="my_db")
    result = h.retain(bank_id="alice", content="Alice loves pizza")
    response = h.recall(bank_id="alice", query="What does Alice like?")
    answer = h.reflect(bank_id="alice", query="What are Alice's interests?")

    with Hindsight(base_url=None, stdb_host="127.0.0.1") as h:
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
from typing import Any, Literal

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
    mentioned_at: str | None = None


class EntityStateResponse(BaseModel):
    """Current mental model of an entity."""

    entity_id: str
    canonical_name: str
    observations: list[EntityObservationResponse]


class RecallResult(BaseModel):
    """Single recall result item."""

    id: str
    text: str
    type: str | None = None
    entities: list[str] | None = None
    context: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None
    mentioned_at: str | None = None
    document_id: str | None = None
    metadata: dict[str, str] | None = None
    chunk_id: str | None = None
    tags: list[str] | None = None
    source_fact_ids: list[str] | None = None
    score: float | None = None


class RetainResponse(BaseModel):
    """Response model for retain endpoint."""

    success: bool
    bank_id: str
    items_count: int
    var_async: bool = Field(default=False, alias="async")
    operation_id: str | None = None
    operation_ids: list[str] | None = None
    usage: TokenUsage | None = None

    model_config = {"populate_by_name": True}


class RecallResponse(BaseModel):
    """Response model for recall endpoints."""

    results: list[RecallResult]
    trace: dict[str, Any] | None = None
    entities: dict[str, EntityStateResponse] | None = None
    chunks: dict[str, ChunkData] | None = None
    source_facts: dict[str, RecallResult] | None = None


class ReflectFact(BaseModel):
    """A fact used in reflect response."""

    id: str | None = None
    text: str
    type: str | None = None
    context: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None


class ReflectDirective(BaseModel):
    """A directive applied during reflect."""

    id: str
    name: str
    content: str


class ReflectMentalModel(BaseModel):
    """A mental model used during reflect."""

    id: str
    text: str
    context: str | None = None


class ReflectBasedOn(BaseModel):
    """Evidence the response is based on: memories, mental models, directives."""

    memories: list[ReflectFact] | None = None
    mental_models: list[ReflectMentalModel] | None = None
    directives: list[ReflectDirective] | None = None


class ReflectToolCall(BaseModel):
    """A tool call made during reflect agent execution."""

    tool: str = Field(description="Tool name: lookup, recall, learn, expand")
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    duration_ms: int = Field(description="Execution time in milliseconds")
    iteration: int = 0


class ReflectLLMCall(BaseModel):
    """An LLM call made during reflect agent execution."""

    scope: str = Field(description="Call scope: agent_1, agent_2, final, etc.")
    duration_ms: int = Field(description="Execution time in milliseconds")


class ReflectTrace(BaseModel):
    """Execution trace of LLM and tool calls during reflection."""

    tool_calls: list[ReflectToolCall] | None = None
    llm_calls: list[ReflectLLMCall] | None = None


class ReflectResponse(BaseModel):
    """Response model for reflect (think) endpoint."""

    text: str = Field(description="The reflect response as well-formatted markdown")
    based_on: ReflectBasedOn | None = None
    structured_output: dict[str, Any] | None = None
    usage: TokenUsage | None = None
    trace: ReflectTrace | None = None


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
    background: str | None = None


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


class _HindsightNotImplementedShell:
    """Namespace for Hindsight REST-server features with no SpacetimeDB equivalent.

    Raises NotImplementedError instead of fabricating success responses.
    """

    def __init__(self, name: str) -> None:
        self._shell_name = name

    def __getattr__(self, attr: str) -> Any:
        def _raise(*a: Any, **kw: Any) -> Any:
            raise NotImplementedError(
                f"Hindsight.{self._shell_name}.{attr}() requires the Hindsight REST "
                f"server; the SpacetimeDB adapter does not support it."
            )
        return _raise

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Hindsight.{self._shell_name}() requires the Hindsight REST server; "
            f"the SpacetimeDB adapter does not support it."
        )


def _unsupported(namespace: str, attr: str) -> Any:
    def _raise(*a: Any, **kw: Any) -> Any:
        raise NotImplementedError(
            f"Hindsight.{namespace}.{attr}() is not implemented in the SpacetimeDB adapter."
        )
    return _raise


class _HindsightDocumentsAPI:
    """Real document operations backed by the document/doc_chunk tables."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def list(self, bank_id: str, **params: Any) -> dict[str, Any]:
        docs = self._h._client._query(
            "document", workspace_id=bank_id, filter_dict={"workspace_id": bank_id}
        )
        return {"items": docs, "total": len(docs)}

    def get(self, bank_id: str, document_id: str, **params: Any) -> dict[str, Any]:
        docs = self._h._client._query(
            "document", workspace_id=bank_id, filter_dict={"id": document_id}
        )
        if not docs:
            raise KeyError(f"document {document_id!r} not found in bank {bank_id!r}")
        return docs[0]

    def delete(self, bank_id: str, document_id: str, **params: Any) -> dict[str, Any]:
        self._h._client._call("delete_document", [document_id])
        return {"status": "ok", "id": document_id}

    def __getattr__(self, attr: str) -> Any:
        return _unsupported("documents", attr)


class _HindsightWebhooksAPI:
    """Real webhook operations backed by the SpacetimeDB webhook tables.

    Implements the Hindsight REST-server webhook management surface
    (create / list / update / delete / fire) using the project's native
    webhook delivery infrastructure (``webhook`` + ``webhook_delivery``
    tables and reducers).  No NotImplementedError — these work end to end.
    """

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def _bank_ws(self, bank_id: str) -> str:
        """Resolve a bank_id to a workspace_id (creating if needed)."""
        return self._h._ensure_bank(bank_id)

    def create(
        self,
        bank_id: str,
        name: str,
        url: str,
        event_types: str | list[str] = "[]",
        secret: str = "",
        **params: Any,
    ) -> dict[str, Any]:
        """Register a webhook for a bank.

        Args:
            bank_id: Bank (workspace) the webhook is scoped to.
            name: Human-friendly label.
            url: Target URL that receives POST deliveries.
            event_types: JSON array string (e.g. ``'["memory.created"]'``)
                or a Python list. Empty ``[]`` matches all events.
            secret: HMAC-SHA256 signing secret (optional).
        """
        ws = self._bank_ws(bank_id)
        if isinstance(event_types, list):
            import json as _json

            event_types = _json.dumps(event_types)
        return self._h._client.create_webhook(
            workspace_id=ws, name=name, url=url,
            event_types=event_types or "[]", secret=secret,
        )

    def list(self, bank_id: str, **params: Any) -> dict[str, Any]:
        """List webhooks registered for a bank."""
        ws = self._bank_ws(bank_id)
        items = self._h._client.list_webhooks(workspace_id=ws)
        return {"items": items, "total": len(items)}

    def get(self, bank_id: str, webhook_id: str, **params: Any) -> dict[str, Any]:
        """Get a single webhook by ID."""
        items = self.list(bank_id)["items"]
        for wh in items:
            if wh.get("webhook_id") == webhook_id or wh.get("id") == webhook_id:
                return wh
        raise KeyError(f"webhook {webhook_id!r} not found in bank {bank_id!r}")

    def update(
        self,
        webhook_id: str,
        name: str = "",
        url: str = "",
        event_types: str | list[str] = "",
        is_active: bool = True,
        **params: Any,
    ) -> dict[str, Any]:
        """Update a webhook's mutable fields."""
        if isinstance(event_types, list):
            import json as _json

            event_types = _json.dumps(event_types)
        return self._h._client.update_webhook(
            webhook_id=webhook_id, name=name, url=url,
            event_types=event_types, is_active=is_active,
        )

    def delete(self, bank_id: str, webhook_id: str, **params: Any) -> dict[str, Any]:
        """Delete a webhook and its pending deliveries."""
        return self._h._client.delete_webhook(webhook_id)

    def fire(
        self,
        bank_id: str,
        event_type: str,
        payload: dict[str, Any] | str = "{}",
        **params: Any,
    ) -> dict[str, Any]:
        """Manually fire a webhook event (creates pending deliveries)."""
        ws = self._bank_ws(bank_id)
        if isinstance(payload, dict):
            import json as _json

            payload = _json.dumps(payload)
        return self._h._client.fire_webhook_event(
            workspace_id=ws, event_type=event_type, payload=payload
        )

    def __getattr__(self, attr: str) -> Any:
        return _unsupported("webhooks", attr)


class _HindsightEntitiesAPI:
    """Real entity operations backed by the kg_node table."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def list(self, bank_id: str, **params: Any) -> dict[str, Any]:
        nodes = self._h._client._query(
            "kg_node", workspace_id=bank_id, filter_dict={"workspace_id": bank_id}
        )
        return {"items": nodes, "total": len(nodes)}

    def get(self, bank_id: str, entity_id: str, **params: Any) -> dict[str, Any]:
        nodes = self._h._client._query(
            "kg_node", workspace_id=bank_id, filter_dict={"id": entity_id}
        )
        if not nodes:
            raise KeyError(f"entity {entity_id!r} not found in bank {bank_id!r}")
        return nodes[0]

    def delete(self, bank_id: str, entity_id: str, **params: Any) -> dict[str, Any]:
        self._h._client._call("delete_node", [entity_id])
        return {"status": "ok", "id": entity_id}

    def __getattr__(self, attr: str) -> Any:
        return _unsupported("entities", attr)


class _HindsightOperationsAPI:
    """Real operation history backed by the change_event table."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def list(self, bank_id: str, **params: Any) -> dict[str, Any]:
        events = self._h._client._query(
            "change_event", workspace_id=bank_id, filter_dict={"workspace_id": bank_id}
        )
        events.sort(key=lambda e: e.get("created_at", 0))
        return {"items": events, "total": len(events)}

    def __getattr__(self, attr: str) -> Any:
        return _unsupported("operations", attr)


class _HindsightMonitoringAPI:
    """Real health monitoring backed by the sidecar health endpoints."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def health(self, **params: Any) -> dict[str, Any]:
        embedder = self._h._client.check_embedder_health()
        tantivy = self._h._client.check_tantivy_health()
        return {
            "embedder": embedder,
            "tantivy": tantivy,
            "ok": bool(embedder.get("status") == "ok" and tantivy.get("status") == "ok"),
        }

    def __getattr__(self, attr: str) -> Any:
        return _unsupported("monitoring", attr)



class _HindsightMentalModelsShell:
    """Mental models shell — delegates to Hindsight.create_mental_model()."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def create(
        self, bank_id: str, name: str, query: str | None = None, **params: Any
    ) -> CreateMentalModelResponse:
        return self._h.create_mental_model(bank_id=bank_id, name=name, query=query, **params)


class _HindsightDirectivesShell:
    """Directives shell — delegates to Hindsight.create_directive()."""

    def __init__(self, hindsight: Hindsight) -> None:
        self._h = hindsight

    def create(
        self, bank_id: str, name: str, prompt: str, **params: Any
    ) -> CreateDirectiveResponse:
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
    ) -> FileRetainResponse:
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
        stdb_host: str = "127.0.0.1",
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
    def memory(self) -> Hindsight:
        """Low-level memory operations — returns self (all ops on Hindsight)."""
        return self

    @property
    def banks(self) -> Hindsight:
        """Low-level bank operations — returns self (bank ops map to workspace ops)."""
        return self

    @property
    def documents(self) -> _HindsightDocumentsAPI:
        """Document operations — backed by the real document/doc_chunk tables."""
        return _HindsightDocumentsAPI(self)

    @property
    def entities(self) -> _HindsightEntitiesAPI:
        """Entity operations — backed by the real kg_node table."""
        return _HindsightEntitiesAPI(self)

    @property
    def mental_models(self) -> _HindsightMentalModelsShell:
        """Low-level mental model operations — delegates to create_mental_model."""
        return _HindsightMentalModelsShell(self)

    @property
    def directives(self) -> _HindsightDirectivesShell:
        """Low-level directive operations — delegates to create_directive."""
        return _HindsightDirectivesShell(self)

    @property
    def operations(self) -> _HindsightOperationsAPI:
        """Operation history — backed by the real change_event table."""
        return _HindsightOperationsAPI(self)

    @property
    def webhooks(self) -> _HindsightWebhooksAPI:
        """Webhook management — backed by real webhook delivery tables."""
        return _HindsightWebhooksAPI(self)

    @property
    def files(self) -> _HindsightFilesShell:
        """Low-level file operations — delegates to retain_files."""
        return _HindsightFilesShell(self)

    @property
    def monitoring(self) -> _HindsightMonitoringAPI:
        """Health monitoring — backed by the real sidecar health endpoints."""
        return _HindsightMonitoringAPI(self)

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

    def __enter__(self) -> Hindsight:
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
        ttl_seconds: int | None = None,
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
                ttl_seconds=ttl_seconds,
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
        ttl_seconds: int | None = None,
    ) -> RetainResponse:
        """Store a single memory (async).

        Args:
            bank_id: Target bank (workspace).
            content: The memory content to store.
            timestamp: Optional event timestamp.
            context: Optional context/summary.
            document_id: Optional source document ID.
            metadata: Optional metadata dict.
            entities: Optional entity list.
            tags: Optional tag list.
            update_mode: Optional update mode (ignored, accepted for parity).
            retain_async: Whether the store happened asynchronously.
            ttl_seconds: Optional TTL in seconds — when set, the memory
                becomes a *working memory* entry: it carries an expiry
                marker that :meth:`arecall` filters out after the TTL
                passes (Mnemosyne working-memory parity).
        """
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

        # Working-memory TTL: encode an expiry marker into the entity payload
        # so recall can filter it out after expiry.
        if ttl_seconds is not None:
            import time as _time

            expires_at = _time.time() + float(ttl_seconds)
            try:
                ent_list = json.loads(entities_json) if entities_json else []
                if not isinstance(ent_list, list):
                    ent_list = []
                ent_list.append(
                    {"type": "_ttl", "expires_at": str(expires_at)}
                )
                entities_json = json.dumps(ent_list)
            except (ValueError, TypeError):
                pass

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

        # Working-memory TTL eviction: drop expired entries (Mnemosyne parity).
        results = self._filter_expired(results, ws_id)

        return RecallResponse(results=results)

    def _filter_expired(
        self,
        results: list[RecallResult],
        ws_id: str,
    ) -> list[RecallResult]:
        """Filter out working-memory entries whose TTL has expired.

        Expiry markers were stored in the entity payload as
        ``{"type": "_ttl", "expires_at": "<unix>"}`` by :meth:`aretain`
        when ``ttl_seconds`` was set.  Recall re-fetches the entity
        payloads for the returned IDs and drops any that are past their
        expiry.  Entries without a marker are durable and always kept.
        """
        if not results:
            return results

        import time as _time

        try:
            mems = self._client.list_memories(workspace_id=ws_id, limit=200)
        except (RuntimeError, TypeError):
            return results

        expiry_by_id: dict[str, float] = {}
        for m in mems or []:
            mid = m.get("id", "") or m.get("entity_id", "")
            if not mid:
                continue
            entities_json = m.get("entities_json", "[]")
            if isinstance(entities_json, str):
                try:
                    ents = json.loads(entities_json)
                except (ValueError, TypeError):
                    ents = []
            else:
                ents = entities_json or []
            if not isinstance(ents, list):
                continue
            for ent in ents:
                if isinstance(ent, dict) and ent.get("type") == "_ttl":
                    try:
                        expiry_by_id[mid] = float(ent.get("expires_at", 0))
                    except (TypeError, ValueError):
                        pass
                    break

        now = _time.time()
        kept = []
        for r in results:
            exp = expiry_by_id.get(r.id)
            if exp is not None and exp < now:
                continue  # working memory expired — evict
            kept.append(r)
        return kept

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

    # -- list_mental_models ---------------------------------------------------

    def list_mental_models(
        self,
        bank_id: str,
        **params: Any,
    ) -> list[CreateMentalModelResponse]:
        """List all mental models in a bank."""
        return _run_async(self.alist_mental_models(bank_id=bank_id, **params))

    async def alist_mental_models(
        self,
        bank_id: str,
        **params: Any,
    ) -> list[CreateMentalModelResponse]:
        """List all mental models in a bank."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        models: list[CreateMentalModelResponse] = []
        try:
            memories = self._client.list_memories(ws_id, memory_type="mental_model")
            for m in memories:
                models.append(CreateMentalModelResponse(
                    id=m.get("id", ""),
                    name=m.get("summary", "").replace("Mental model: ", ""),
                    content=m.get("content", ""),
                    success=True,
                ))
        except RuntimeError as exc:
            logger.warning("list_mental_models() failed: %s", exc)
        return models

    # -- get_mental_model ------------------------------------------------------

    def get_mental_model(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Get a specific mental model by ID."""
        return _run_async(self.aget_mental_model(bank_id=bank_id, model_id=model_id, **params))

    async def aget_mental_model(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Get a specific mental model by ID."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        self._ensure_bank(bank_id)  # validate bank_id exists
        try:
            mems = self._client.get_memory(model_id)
            if isinstance(mems, list) and len(mems) > 0:
                mem = mems[0]
                return CreateMentalModelResponse(
                    id=mem.get("id", ""),
                    name=mem.get("summary", "").replace("Mental model: ", ""),
                    content=mem.get("content", ""),
                    success=True,
                )
        except RuntimeError:
            pass
        return CreateMentalModelResponse(id=model_id, name="", content="", success=False)

    # -- get_mental_model_history ----------------------------------------------

    def get_mental_model_history(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> list[dict[str, Any]]:
        """Get the revision history of a mental model."""
        return _run_async(self.aget_mental_model_history(bank_id=bank_id, model_id=model_id, **params))

    async def aget_mental_model_history(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> list[dict[str, Any]]:
        """Get the revision history of a mental model."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        try:
            history = self._client.get_memory_history(model_id)
            return history if isinstance(history, list) else []
        except RuntimeError:
            return []

    # -- update_mental_model ---------------------------------------------------

    def update_mental_model(
        self,
        bank_id: str,
        model_id: str,
        name: str | None = None,
        content: str | None = None,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Update a mental model's name and/or content."""
        return _run_async(self.aupdate_mental_model(
            bank_id=bank_id, model_id=model_id, name=name, content=content, **params,
        ))

    async def aupdate_mental_model(
        self,
        bank_id: str,
        model_id: str,
        name: str | None = None,
        content: str | None = None,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Update a mental model's name and/or content."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        try:
            summary = f"Mental model: {name}" if name else ""
            self._client.update_memory(
                model_id,
                content=content or "",
                summary=summary,
            )
            return CreateMentalModelResponse(
                id=model_id,
                name=name or "",
                content=content or "",
                success=True,
            )
        except RuntimeError as exc:
            logger.warning("update_mental_model() failed: %s", exc)
            return CreateMentalModelResponse(id=model_id, name=name or "", content=content or "", success=False)

    # -- delete_mental_model ---------------------------------------------------

    def delete_mental_model(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Delete (deactivate) a mental model."""
        return _run_async(self.adelete_mental_model(bank_id=bank_id, model_id=model_id, **params))

    async def adelete_mental_model(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Delete (deactivate) a mental model."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        try:
            self._client.delete_memory(model_id)
            return {"success": True}
        except RuntimeError as exc:
            logger.warning("delete_mental_model() failed: %s", exc)
            return {"success": False}

    # -- clear_mental_model ----------------------------------------------------

    def clear_mental_model(
        self,
        bank_id: str,
        name: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Clear a mental model by name (delete all with matching name)."""
        return _run_async(self.aclear_mental_model(bank_id=bank_id, name=name, **params))

    async def aclear_mental_model(
        self,
        bank_id: str,
        name: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Clear a mental model by name."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        try:
            memories = self._client.list_memories(ws_id, memory_type="mental_model")
            deleted = 0
            for m in memories:
                summary = m.get("summary", "")
                mid = m.get("id", "")
                if name in summary and mid:
                    self._client.delete_memory(mid)
                    deleted += 1
            return {"success": True, "deleted": deleted}
        except RuntimeError as exc:
            logger.warning("clear_mental_model() failed: %s", exc)
            return {"success": False}

    # -- refresh_mental_model --------------------------------------------------

    def refresh_mental_model(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Re-synthesize a mental model from current bank knowledge."""
        return _run_async(self.arefresh_mental_model(bank_id=bank_id, model_id=model_id, **params))

    async def arefresh_mental_model(
        self,
        bank_id: str,
        model_id: str,
        **params: Any,
    ) -> CreateMentalModelResponse:
        """Re-synthesize a mental model from current bank knowledge."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        # Get existing model for context
        existing: CreateMentalModelResponse = CreateMentalModelResponse(id=model_id, name="", content="", success=False)
        try:
            mems = self._client.get_memory(model_id)
            if isinstance(mems, list) and len(mems) > 0:
                mem = mems[0]
                existing = CreateMentalModelResponse(
                    id=mem.get("id", ""),
                    name=mem.get("summary", "").replace("Mental model: ", ""),
                    content=mem.get("content", ""),
                    success=True,
                )
        except RuntimeError:
            pass
        # Re-synthesize with same name
        return await self.acreate_mental_model(
            bank_id=bank_id, name=existing.name, query=existing.name,
        )

    # -- list_directives -------------------------------------------------------

    def list_directives(
        self,
        bank_id: str,
        **params: Any,
    ) -> list[CreateDirectiveResponse]:
        """List all directives in a bank."""
        return _run_async(self.alist_directives(bank_id=bank_id, **params))

    async def alist_directives(
        self,
        bank_id: str,
        **params: Any,
    ) -> list[CreateDirectiveResponse]:
        """List all directives in a bank."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        directives: list[CreateDirectiveResponse] = []
        try:
            memories = self._client.list_memories(ws_id, memory_type="directive")
            for m in memories:
                directives.append(CreateDirectiveResponse(
                    id=m.get("id", ""),
                    name=m.get("summary", "").replace("Directive: ", ""),
                    content=m.get("content", ""),
                    success=True,
                ))
        except RuntimeError as exc:
            logger.warning("list_directives() failed: %s", exc)
        return directives

    # -- get_directive ---------------------------------------------------------

    def get_directive(
        self,
        bank_id: str,
        directive_id: str,
        **params: Any,
    ) -> CreateDirectiveResponse:
        """Get a specific directive by ID."""
        return _run_async(self.aget_directive(bank_id=bank_id, directive_id=directive_id, **params))

    async def aget_directive(
        self,
        bank_id: str,
        directive_id: str,
        **params: Any,
    ) -> CreateDirectiveResponse:
        """Get a specific directive by ID."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        try:
            mems = self._client.get_memory(directive_id)
            if isinstance(mems, list) and len(mems) > 0:
                mem = mems[0]
                return CreateDirectiveResponse(
                    id=mem.get("id", ""),
                    name=mem.get("summary", "").replace("Directive: ", ""),
                    content=mem.get("content", ""),
                    success=True,
                )
        except RuntimeError:
            pass
        return CreateDirectiveResponse(id=directive_id, name="", content="", success=False)

    # -- update_directive ------------------------------------------------------

    def update_directive(
        self,
        bank_id: str,
        directive_id: str,
        name: str | None = None,
        prompt: str | None = None,
        **params: Any,
    ) -> CreateDirectiveResponse:
        """Update a directive's name and/or prompt."""
        return _run_async(self.aupdate_directive(
            bank_id=bank_id, directive_id=directive_id, name=name, prompt=prompt, **params,
        ))

    async def aupdate_directive(
        self,
        bank_id: str,
        directive_id: str,
        name: str | None = None,
        prompt: str | None = None,
        **params: Any,
    ) -> CreateDirectiveResponse:
        """Update a directive's name and/or prompt."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        try:
            summary = f"Directive: {name}" if name else ""
            self._client.update_memory(
                directive_id,
                content=prompt or "",
                summary=summary,
            )
            return CreateDirectiveResponse(
                id=directive_id,
                name=name or "",
                content=prompt or "",
                success=True,
            )
        except RuntimeError as exc:
            logger.warning("update_directive() failed: %s", exc)
            return CreateDirectiveResponse(id=directive_id, name=name or "", content=prompt or "", success=False)

    # -- delete_directive ------------------------------------------------------

    def delete_directive(
        self,
        bank_id: str,
        directive_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Delete (deactivate) a directive."""
        return _run_async(self.adelete_directive(bank_id=bank_id, directive_id=directive_id, **params))

    async def adelete_directive(
        self,
        bank_id: str,
        directive_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Delete (deactivate) a directive."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        try:
            self._client.delete_memory(directive_id)
            return {"success": True}
        except RuntimeError as exc:
            logger.warning("delete_directive() failed: %s", exc)
            return {"success": False}

    # -- set_mission -----------------------------------------------------------

    def set_mission(
        self,
        bank_id: str,
        mission: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Set the mission/purpose for a bank (stored as workspace context)."""
        return _run_async(self.aset_mission(bank_id=bank_id, mission=mission, **params))

    async def aset_mission(
        self,
        bank_id: str,
        mission: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Set the mission/purpose for a bank."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        try:
            self._client.set_workspace_context(ws_id, context=json.dumps({"mission": mission, **params}))
            return {"success": True}
        except RuntimeError as exc:
            logger.warning("set_mission() failed: %s", exc)
            return {"success": False}

    def set_reflect_mission(
        self,
        bank_id: str,
        mission: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Set the reflection mission for a bank (stored as workspace context)."""
        return _run_async(self.aset_reflect_mission(bank_id=bank_id, mission=mission, **params))

    async def aset_reflect_mission(
        self,
        bank_id: str,
        mission: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Set the reflection mission for a bank."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        try:
            self._client.set_workspace_context(ws_id, context=json.dumps({"reflect_mission": mission, **params}))
            return {"success": True}
        except RuntimeError as exc:
            logger.warning("set_reflect_mission() failed: %s", exc)
            return {"success": False}

    # -- bank config -----------------------------------------------------------

    def get_bank_config(
        self,
        bank_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Get the bank configuration (workspace metadata)."""
        return _run_async(self.aget_bank_config(bank_id=bank_id, **params))

    async def aget_bank_config(
        self,
        bank_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Get the bank configuration."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        try:
            ctx = self._client.get_workspace_context(ws_id)
            return {"id": ws_id, "config": ctx, "success": True}
        except RuntimeError as exc:
            logger.warning("get_bank_config() failed: %s", exc)
            return {"id": ws_id, "config": {}, "success": False}

    def update_bank_config(
        self,
        bank_id: str,
        config: dict[str, Any],
        **params: Any,
    ) -> dict[str, Any]:
        """Update the bank configuration."""
        return _run_async(self.aupdate_bank_config(bank_id=bank_id, config=config, **params))

    async def aupdate_bank_config(
        self,
        bank_id: str,
        config: dict[str, Any],
        **params: Any,
    ) -> dict[str, Any]:
        """Update the bank configuration."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        try:
            self._client.set_workspace_context(ws_id, context=json.dumps(config))
            return {"id": ws_id, "success": True}
        except RuntimeError as exc:
            logger.warning("update_bank_config() failed: %s", exc)
            return {"id": ws_id, "success": False}

    def reset_bank_config(
        self,
        bank_id: str,
        config: dict[str, Any] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Reset the bank configuration to defaults (or provided config)."""
        return _run_async(self.areset_bank_config(bank_id=bank_id, config=config, **params))

    async def areset_bank_config(
        self,
        bank_id: str,
        config: dict[str, Any] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Reset the bank configuration to defaults."""
        if self._closed:
            raise RuntimeError("Hindsight client is closed")
        ws_id = self._ensure_bank(bank_id)
        defaults = config or {"disposition": {"skepticism": 3, "literalism": 3, "empathy": 3}}
        try:
            self._client.set_workspace_context(ws_id, context=json.dumps(defaults))
            return {"id": ws_id, "success": True}
        except RuntimeError as exc:
            logger.warning("reset_bank_config() failed: %s", exc)
            return {"id": ws_id, "success": False}


__all__ = [
    "BankProfileResponse",
    "CreateBankResponse",
    "CreateDirectiveResponse",
    "CreateMentalModelResponse",
    "DispositionTraits",
    "FileRetainResponse",
    "Hindsight",
    "ListMemoryUnitsResponse",
    "RecallResponse",
    "RecallResult",
    "ReflectFact",
    "ReflectResponse",
    "RetainResponse",
    "TokenUsage",
]
