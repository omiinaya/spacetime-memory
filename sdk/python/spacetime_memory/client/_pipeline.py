"""Cognee-parity Pipeline system — configurable multi-stage cognitive pipelines.

Pipelines compose ordered stages:
    Search → Filter → Extract → Transform → Store

Usage::

    pipeline = client.create_pipeline(
        workspace_id,
        name="daily_summary",
        stages=[
            PipelineStage.search(query="daily updates", top_k=20),
            PipelineStage.filter(min_confidence=0.5, max_age_hours=24),
            PipelineStage.extract(type="entities"),
            PipelineStage.transform(llm_prompt="Summarize these memories"),
            PipelineStage.store(target="note", title="Daily Summary"),
        ],
        schedule="0 9 * * *",
    )
    result = pipeline.execute()
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ._base import logger

# ---------------------------------------------------------------------------
# Stage types
# ---------------------------------------------------------------------------


class StageType(str, Enum):
    """Enumeration of supported pipeline stage types."""

    SEARCH = "search"
    FILTER = "filter"
    EXTRACT = "extract"
    TRANSFORM = "transform"
    STORE = "store"
    CLASSIFY = "classify"
    RANK = "rank"


# ---------------------------------------------------------------------------
# PipelineStage — a single stage in a pipeline definition
# ---------------------------------------------------------------------------


@dataclass
class PipelineStage:
    """A single stage in a cognitive pipeline.

    Use the class-method constructors (``PipelineStage.search()``,
    ``PipelineStage.filter()``, etc.) for a clean API rather than
    instantiating this dataclass directly.
    """

    type: StageType
    """The stage type — determines which operation is performed."""

    params: dict[str, Any] = field(default_factory=dict)
    """Stage-specific keyword parameters."""

    # ── Class-method constructors ────────────────────────────────────

    @classmethod
    def search(
        cls,
        query: str,
        top_k: int = 10,
        workspace_id: str | None = None,
        **kwargs: Any,
    ) -> PipelineStage:
        """Create a Search stage.

        Args:
            query: Search query string.
            top_k: Maximum number of results to return.
            workspace_id: Optional workspace scope (defaults to pipeline's).
            **kwargs: Additional search parameters (e.g. filters, rerank).
        """
        return cls(
            type=StageType.SEARCH,
            params={"query": query, "top_k": top_k, "workspace_id": workspace_id, **kwargs},
        )

    @classmethod
    def filter(
        cls,
        min_confidence: float = 0.0,
        max_age_hours: float | None = None,
        include_types: list[str] | None = None,
        exclude_types: list[str] | None = None,
        **kwargs: Any,
    ) -> PipelineStage:
        """Create a Filter stage.

        Args:
            min_confidence: Minimum confidence score (0.0–1.0).
            max_age_hours: Maximum age in hours (None = no limit).
            include_types: Only keep results whose ``type``/``memory_type`` is in this list.
            exclude_types: Remove results whose ``type``/``memory_type`` is in this list.
            **kwargs: Additional filter parameters.
        """
        return cls(
            type=StageType.FILTER,
            params={
                "min_confidence": min_confidence,
                "max_age_hours": max_age_hours,
                "include_types": include_types,
                "exclude_types": exclude_types,
                **kwargs,
            },
        )

    @classmethod
    def extract(
        cls,
        type: str = "entities",
        fields: list[str] | None = None,
        **kwargs: Any,
    ) -> PipelineStage:
        """Create an Extract stage.

        Args:
            type: What to extract — ``"entities"``, ``"keywords"``, ``"summary"``, etc.
            fields: Source fields to extract from (default: content).
            **kwargs: Additional extraction parameters.
        """
        return cls(
            type=StageType.EXTRACT,
            params={"type": type, "fields": fields, **kwargs},
        )

    @classmethod
    def transform(
        cls,
        llm_prompt: str = "",
        model: str = "",
        temperature: float = 0.0,
        output_key: str = "transformed",
        **kwargs: Any,
    ) -> PipelineStage:
        """Create a Transform stage.

        Args:
            llm_prompt: Prompt template for LLM transformation.
            model: Model identifier (uses default if empty).
            temperature: LLM temperature.
            output_key: Key to store transformation result in stage output.
            **kwargs: Additional transform parameters.
        """
        return cls(
            type=StageType.TRANSFORM,
            params={
                "llm_prompt": llm_prompt,
                "model": model,
                "temperature": temperature,
                "output_key": output_key,
                **kwargs,
            },
        )

    @classmethod
    def store(
        cls,
        target: str = "memory",
        title: str = "",
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> PipelineStage:
        """Create a Store stage.

        Args:
            target: Storage target — ``"memory"``, ``"note"``, ``"kg_node"``.
            title: Title for the stored item.
            tags: Optional tags for the stored item.
            **kwargs: Additional store parameters.
        """
        return cls(
            type=StageType.STORE,
            params={"target": target, "title": title, "tags": tags or [], **kwargs},
        )

    @classmethod
    def classify(
        cls,
        categories: list[str] | None = None,
        output_key: str = "classification",
        **kwargs: Any,
    ) -> PipelineStage:
        """Create a Classify stage.

        Args:
            categories: Allowed classification categories (empty = auto-detect).
            output_key: Key to store classification result in stage output.
            **kwargs: Additional classification parameters.
        """
        return cls(
            type=StageType.CLASSIFY,
            params={"categories": categories or [], "output_key": output_key, **kwargs},
        )

    @classmethod
    def rank(
        cls,
        field: str = "score",
        reverse: bool = True,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> PipelineStage:
        """Create a Rank stage.

        Args:
            field: Field name to sort by.
            reverse: Sort descending (highest first) when True.
            top_k: Keep only the top K results (None = keep all).
            **kwargs: Additional ranking parameters.
        """
        return cls(
            type=StageType.RANK,
            params={"field": field, "reverse": reverse, "top_k": top_k, **kwargs},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this stage to a plain dict."""
        return {"type": self.type.value, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PipelineStage:
        """Deserialize from a dict produced by ``to_dict()``."""
        stage_type = StageType(d["type"])
        return cls(type=stage_type, params=d.get("params", {}))


# ---------------------------------------------------------------------------
# Pipeline definition — runtime representation
# ---------------------------------------------------------------------------


@dataclass
class PipelineDefinition:
    """Complete pipeline definition created via ``create_pipeline()``."""

    id: str
    """Unique pipeline identifier (auto-generated UUID)."""

    name: str
    """Human-readable pipeline name."""

    workspace_id: str
    """Workspace this pipeline belongs to."""

    stages: list[PipelineStage] = field(default_factory=list)
    """Ordered list of pipeline stages to execute."""

    schedule: str = ""
    """Optional cron expression for scheduled execution."""

    enabled: bool = True
    """Whether the pipeline is active."""

    created_at: float = 0.0
    """Unix timestamp of creation."""

    updated_at: float = 0.0
    """Unix timestamp of last update."""

    last_run_at: float = 0.0
    """Unix timestamp of last execution start."""

    last_status: str = "never_run"
    """Status of the most recent execution attempt."""

    tags: dict[str, str] = field(default_factory=dict)
    """Arbitrary user-defined tags/metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "id": self.id,
            "name": self.name,
            "workspace_id": self.workspace_id,
            "stages": [s.to_dict() for s in self.stages],
            "schedule": self.schedule,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "tags": dict(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PipelineDefinition:
        """Deserialize from a dict produced by ``to_dict()``."""
        return cls(
            id=d["id"],
            name=d["name"],
            workspace_id=d.get("workspace_id", ""),
            stages=[PipelineStage.from_dict(s) for s in d.get("stages", [])],
            schedule=d.get("schedule", ""),
            enabled=d.get("enabled", True),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            last_run_at=d.get("last_run_at", 0.0),
            last_status=d.get("last_status", "never_run"),
            tags=d.get("tags", {}),
        )


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Result of a single pipeline execution."""

    pipeline_id: str
    """The pipeline that was executed."""

    execution_id: str
    """Unique execution ID (auto-generated UUID)."""

    success: bool
    """Whether the entire pipeline completed successfully."""

    started_at: float
    """Unix timestamp of execution start."""

    finished_at: float
    """Unix timestamp of execution finish."""

    stages_output: list[dict[str, Any]] = field(default_factory=list)
    """Output from each stage in order."""

    error: str = ""
    """Error message if execution failed."""

    duration_ms: float = 0.0
    """Total execution duration in milliseconds."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "pipeline_id": self.pipeline_id,
            "execution_id": self.execution_id,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stages_output": self.stages_output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# PipelineMixin — mixin for the Client class
# ---------------------------------------------------------------------------


class PipelineMixin:
    """Spacetime-Memory pipeline mixin.

    Provides methods for creating, executing, and managing cognitive
    pipelines.  Pipelines are composed of ordered stages (search → filter
    → extract → transform → store) that process memories and knowledge.

    Pipeline definitions and execution logs are stored in-memory on the
    client instance and optionally persisted via the note/memory system.

    Usage::

        client = Client(...)

        pipeline = client.create_pipeline(
            workspace_id="ws-1",
            name="daily_summary",
            stages=[
                PipelineStage.search(query="daily updates", top_k=20),
                PipelineStage.filter(min_confidence=0.5),
                PipelineStage.extract(type="entities"),
                PipelineStage.transform(llm_prompt="Summarize these memories"),
                PipelineStage.store(target="note", title="Daily Summary"),
            ],
            schedule="0 9 * * *",
        )

        result = pipeline.execute()
        print(result.success, result.duration_ms)

        pipelines = client.list_pipelines(workspace_id="ws-1")
        status = client.get_pipeline_status(pipeline.id)
        client.delete_pipeline(pipeline.id)
    """

    # ------------------------------------------------------------------
    # Lazy storage initialisation — these dicts live on each instance so
    # tests get an independent registry.  They are created on first use
    # because ClientBase.__init__ does not call super().__init__().
    # ------------------------------------------------------------------

    def _get_registry(self) -> dict[str, PipelineDefinition]:
        """Lazy-access the pipeline definition registry."""
        if not hasattr(self, "_pipeline_registry"):
            self._pipeline_registry = {}
        return self._pipeline_registry

    def _get_logs(self) -> dict[str, list[PipelineResult]]:
        """Lazy-access the pipeline execution logs."""
        if not hasattr(self, "_pipeline_logs"):
            self._pipeline_logs = {}
        return self._pipeline_logs

    # ── CRUD operations ──────────────────────────────────────────────

    def create_pipeline(
        self,
        workspace_id: str,
        name: str,
        stages: list[PipelineStage],
        schedule: str = "",
        tags: dict[str, str] | None = None,
    ) -> PipelineDefinition:
        """Define a new cognitive pipeline.

        Args:
            workspace_id: Target workspace.
            name: Human-readable name for the pipeline.
            stages: Ordered list of ``PipelineStage`` instances.
            schedule: Optional cron expression (e.g. ``"0 9 * * *"``).
            tags: Optional metadata tags.

        Returns:
            The created ``PipelineDefinition``.
        """
        pipeline_id = str(uuid.uuid4())
        now = time.time()
        definition = PipelineDefinition(
            id=pipeline_id,
            name=name,
            workspace_id=workspace_id,
            stages=list(stages),
            schedule=schedule,
            enabled=True,
            created_at=now,
            updated_at=now,
            tags=tags or {},
        )
        self._get_registry()[pipeline_id] = definition
        self._get_logs().setdefault(pipeline_id, [])
        logger.info(
            "Created pipeline id=%s name=%r workspace=%s stages=%d",
            pipeline_id,
            name,
            workspace_id,
            len(stages),
        )
        return definition

    def delete_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        """Remove a pipeline definition.

        Args:
            pipeline_id: The pipeline ID to delete.

        Returns:
            Status dict.

        Raises:
            KeyError: If the pipeline does not exist.
        """
        if pipeline_id not in self._get_registry():
            raise KeyError(f"Pipeline '{pipeline_id}' not found")
        del self._get_registry()[pipeline_id]
        self._get_logs().pop(pipeline_id, None)
        logger.info("Deleted pipeline id=%s", pipeline_id)
        return {"status": "ok", "pipeline_id": pipeline_id}

    def list_pipelines(
        self,
        workspace_id: str | None = None,
    ) -> list[PipelineDefinition]:
        """List all defined pipelines, optionally filtered by workspace.

        Args:
            workspace_id: If provided, only return pipelines for this workspace.

        Returns:
            A list of ``PipelineDefinition`` instances.
        """
        pipelines = list(self._get_registry().values())
        if workspace_id:
            pipelines = [p for p in pipelines if p.workspace_id == workspace_id]
        return sorted(pipelines, key=lambda p: p.created_at, reverse=True)

    def get_pipeline_status(self, pipeline_id: str) -> dict[str, Any]:
        """Check the status of a pipeline.

        Args:
            pipeline_id: The pipeline ID.

        Returns:
            Dict with pipeline status info including definition and recent logs.

        Raises:
            KeyError: If the pipeline does not exist.
        """
        if pipeline_id not in self._get_registry():
            raise KeyError(f"Pipeline '{pipeline_id}' not found")
        definition = self._get_registry()[pipeline_id]
        logs = self._get_logs().get(pipeline_id, [])
        recent_logs = sorted(logs, key=lambda r: r.started_at, reverse=True)[:5]
        return {
            "id": definition.id,
            "name": definition.name,
            "workspace_id": definition.workspace_id,
            "enabled": definition.enabled,
            "schedule": definition.schedule,
            "stages": [s.to_dict() for s in definition.stages],
            "last_run_at": definition.last_run_at,
            "last_status": definition.last_status,
            "created_at": definition.created_at,
            "tags": definition.tags,
            "recent_executions": [r.to_dict() for r in recent_logs],
        }

    # ── Execution ────────────────────────────────────────────────────

    def execute_pipeline(
        self,
        pipeline_id: str,
        **overrides: Any,
    ) -> PipelineResult:
        """Run a pipeline synchronously.

        Each stage receives the output of the previous stage as its input.
        The first stage (usually Search) receives no initial input.

        Args:
            pipeline_id: The pipeline to execute.
            **overrides: Optional overrides for stage parameters (e.g. ``query``).

        Returns:
            A ``PipelineResult`` with per-stage outputs.

        Raises:
            KeyError: If the pipeline does not exist.
        """
        if pipeline_id not in self._get_registry():
            raise KeyError(f"Pipeline '{pipeline_id}' not found")

        definition = self._get_registry()[pipeline_id]
        execution_id = str(uuid.uuid4())
        started_at = time.time()

        # Mark as running
        definition.last_run_at = started_at
        definition.last_status = "running"

        stages_output: list[dict[str, Any]] = []
        current_input: Any = None  # Stages pipe data through

        try:
            for idx, stage in enumerate(definition.stages):
                logger.debug(
                    "Pipeline %s stage %d/%d: %s",
                    pipeline_id,
                    idx + 1,
                    len(definition.stages),
                    stage.type.value,
                )
                stage_start = time.time()

                # Merge overrides into stage params
                params = dict(stage.params)
                if overrides:
                    for k, v in overrides.items():
                        if k in params:
                            params[k] = v

                output = self._execute_stage(stage.type, params, current_input)
                elapsed = (time.time() - stage_start) * 1000
                stages_output.append(
                    {
                        "stage": idx,
                        "type": stage.type.value,
                        "duration_ms": round(elapsed, 1),
                        "params": params,
                        "output": output,
                    }
                )
                current_input = output

            # Update status
            definition.last_status = "success"
            finished_at = time.time()
            result = PipelineResult(
                pipeline_id=pipeline_id,
                execution_id=execution_id,
                success=True,
                started_at=started_at,
                finished_at=finished_at,
                stages_output=stages_output,
                duration_ms=round((finished_at - started_at) * 1000, 1),
            )

        except Exception as exc:
            logger.exception(
                "Pipeline %s failed at stage %d",
                pipeline_id,
                len(stages_output) + 1,
            )
            definition.last_status = "failed"
            finished_at = time.time()
            result = PipelineResult(
                pipeline_id=pipeline_id,
                execution_id=execution_id,
                success=False,
                started_at=started_at,
                finished_at=finished_at,
                stages_output=stages_output,
                error=str(exc),
                duration_ms=round((finished_at - started_at) * 1000, 1),
            )

        # Store execution log
        self._get_logs().setdefault(pipeline_id, []).append(result)
        definition.updated_at = time.time()
        return result

    # ── Internal: stage execution ────────────────────────────────────

    def _execute_stage(
        self,
        stage_type: StageType,
        params: dict[str, Any],
        current_input: Any,
    ) -> Any:
        """Execute a single pipeline stage and return its output."""
        dispatcher = {
            StageType.SEARCH: self._execute_search,
            StageType.FILTER: self._execute_filter,
            StageType.EXTRACT: self._execute_extract,
            StageType.TRANSFORM: self._execute_transform,
            StageType.STORE: self._execute_store,
            StageType.CLASSIFY: self._execute_classify,
            StageType.RANK: self._execute_rank,
        }
        handler = dispatcher.get(stage_type)
        if handler is None:
            raise ValueError(f"Unknown pipeline stage type: {stage_type}")
        return handler(params, current_input)

    def _execute_search(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> list[dict[str, Any]]:
        """Execute a Search stage — queries the search system."""
        query = params.get("query", "")
        top_k = params.get("top_k", 10)
        workspace_id = params.get("workspace_id") or ""

        # If the client has a ``search`` method (from SearchMixin), use it.
        search_fn = getattr(self, "search", None)
        if search_fn is not None and workspace_id:
            try:
                results = search_fn(
                    workspace_id=workspace_id,
                    query=query,
                    top_k=top_k,
                )
                if isinstance(results, list):
                    return results
            except Exception:
                logger.warning("search() failed, falling back to _query", exc_info=True)

        # Fallback: query the workspace memories table directly
        if workspace_id:
            try:
                rows = self._query("memory", filter_dict={"workspace_id": workspace_id})
                # Basic keyword filter on content
                query_lower = query.lower()
                matched = [r for r in rows if query_lower in str(r.get("content", "")).lower()]
                return matched[:top_k]
            except Exception:
                logger.warning("_query fallback failed", exc_info=True)

        return []

    def _execute_filter(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> list[dict[str, Any]]:
        """Execute a Filter stage — filters results by criteria."""
        if not isinstance(current_input, list):
            return []

        min_confidence = params.get("min_confidence", 0.0)
        max_age_hours = params.get("max_age_hours")
        include_types = params.get("include_types")
        exclude_types = params.get("exclude_types")
        now = time.time()

        filtered: list[dict[str, Any]] = []
        for item in current_input:
            if not isinstance(item, dict):
                filtered.append(item)
                continue

            # Confidence filter
            confidence = item.get("confidence", item.get("score", item.get("relevance", 1.0)))
            if isinstance(confidence, (int, float)) and confidence < min_confidence:
                continue

            # Age filter
            if max_age_hours is not None:
                created_at = item.get("created_at", item.get("timestamp_", 0))
                if isinstance(created_at, (int, float)) and created_at > 0:
                    age_seconds = now - created_at
                    age_hours = age_seconds / 3600
                    if age_hours > max_age_hours:
                        continue

            # Include type filter
            if include_types:
                item_type = item.get("type", item.get("memory_type", item.get("entity_type", "")))
                if item_type not in include_types:
                    continue

            # Exclude type filter
            if exclude_types:
                item_type = item.get("type", item.get("memory_type", item.get("entity_type", "")))
                if item_type in exclude_types:
                    continue

            filtered.append(item)

        return filtered

    def _execute_extract(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> list[dict[str, Any]]:
        """Execute an Extract stage — extracts entities/keywords from content."""
        if not isinstance(current_input, list):
            return []

        extraction_type = params.get("type", "entities")
        params.get("fields")

        extracted: list[dict[str, Any]] = []
        for item in current_input:
            if not isinstance(item, dict):
                continue

            item_copy = dict(item)
            content = item_copy.get("content", item_copy.get("text", item_copy.get("summary", "")))
            if not content:
                extracted.append(item_copy)
                continue

            if extraction_type == "entities":
                # Simple entity extraction: find capitalized phrases as placeholders.
                # In production this would use an NER model or LLM.
                words = str(content).split()
                entities = []
                current_phrase: list[str] = []
                for w in words:
                    clean = w.strip(".,!?;:\"'()[]{}")
                    if clean and clean[0].isupper():
                        current_phrase.append(clean)
                    else:
                        if current_phrase:
                            entities.append(" ".join(current_phrase))
                            current_phrase = []
                if current_phrase:
                    entities.append(" ".join(current_phrase))

                item_copy["extracted_entities"] = list(set(entities))
                item_copy["extraction_type"] = "entities"

            elif extraction_type == "keywords":
                # Simple keyword extraction: words longer than 5 chars
                words = str(content).split()
                keywords = [
                    w.strip(".,!?;:\"'()[]{}").lower()
                    for w in words
                    if len(w.strip(".,!?;:\"'()[]{}")) > 5
                ]
                item_copy["extracted_keywords"] = list(set(keywords))
                item_copy["extraction_type"] = "keywords"

            else:
                item_copy["extraction_type"] = extraction_type
                item_copy["extracted_content"] = content

            extracted.append(item_copy)

        return extracted

    def _execute_transform(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> Any:
        """Execute a Transform stage — applies an LLM transformation."""
        llm_prompt = params.get("llm_prompt", "")
        output_key = params.get("output_key", "transformed")

        if llm_prompt and hasattr(self, "local_llm") and self.local_llm is not None:
            try:
                input_text = ""
                if isinstance(current_input, list) or isinstance(current_input, dict):
                    input_text = json.dumps(current_input, default=str)
                elif isinstance(current_input, str):
                    input_text = current_input
                else:
                    input_text = str(current_input)

                prompt = f"{llm_prompt}\n\nInput:\n{input_text[:16000]}"
                response = self.local_llm.generate(prompt)
                if isinstance(response, str):
                    result = {output_key: response}
                elif isinstance(response, dict):
                    result = {output_key: response.get("text", str(response))}
                else:
                    result = {output_key: str(response)}
                return result
            except Exception as exc:
                logger.warning("LLM transform failed: %s", exc)

        # No LLM available — pass through with a note
        if isinstance(current_input, (list, dict)):
            result = (
                {"input": current_input, output_key: "Transform skipped (no LLM)"}
                if isinstance(current_input, dict)
                else current_input
            )
        else:
            result = {output_key: current_input or "No input"}

        return result

    def _execute_store(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> dict[str, Any]:
        """Execute a Store stage — persists the result."""
        target = params.get("target", "memory")
        title = params.get("title", "")
        tags = params.get("tags", [])
        workspace_id = params.get("workspace_id") or ""
        # Try to resolve workspace_id from the pipeline definition if not provided
        if not workspace_id:
            pipe_id = params.get("pipeline_id", "")
            if pipe_id:
                pipe_def = self._get_registry().get(pipe_id)
                if pipe_def:
                    workspace_id = pipe_def.workspace_id

        stored_refs: list[str] = []

        if target == "note":
            create_note = getattr(self, "create_note", None)
            if create_note is not None and workspace_id:
                content = ""
                if isinstance(current_input, dict) or isinstance(current_input, list):
                    content = json.dumps(current_input, default=str, indent=2)
                elif isinstance(current_input, str):
                    content = current_input
                else:
                    content = str(current_input)

                title_actual = title or f"Pipeline output {int(time.time())}"
                try:
                    result = create_note(
                        workspace_id=workspace_id,
                        title=title_actual,
                        content=content,
                        tags=tags,
                    )
                    stored_refs.append(str(result))
                    return {
                        "target": "note",
                        "title": title_actual,
                        "stored": True,
                        "refs": stored_refs,
                        "result": result,
                    }
                except Exception as exc:
                    logger.warning("create_note failed: %s", exc)

        elif target == "memory":
            store_fn = getattr(self, "store", None) or getattr(self, "create_memory", None)
            if store_fn is not None and workspace_id:
                content = (
                    current_input.get("transformed", current_input)
                    if isinstance(current_input, dict)
                    else current_input
                )
                try:
                    result = store_fn(
                        workspace_id=workspace_id,
                        content=content if isinstance(content, str) else json.dumps(content, default=str),
                        tags=tags,
                    )
                    stored_refs.append(str(result))
                    return {
                        "target": "memory",
                        "stored": True,
                        "refs": stored_refs,
                        "result": result,
                    }
                except Exception as exc:
                    logger.warning("store/memory failed: %s", exc)

        # Fallback: return data as-is
        return {
            "target": target,
            "stored": False,
            "refs": stored_refs,
            "data": current_input,
        }

    def _execute_classify(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> list[dict[str, Any]]:
        """Execute a Classify stage — categorises items based on content."""
        if not isinstance(current_input, list):
            return []

        categories = params.get("categories", [])
        output_key = params.get("output_key", "classification")

        classified: list[dict[str, Any]] = []
        for item in current_input:
            if not isinstance(item, dict):
                classified.append(item)
                continue

            item_copy = dict(item)
            content = item_copy.get("content", item_copy.get("text", item_copy.get("summary", "")))
            if not content:
                item_copy[output_key] = "unknown"
                classified.append(item_copy)
                continue

            if categories:
                # Simple tag-matching heuristic (word-boundary aware)
                content_lower = str(content).lower()
                content_words = set(content_lower.split())
                matched = [c for c in categories if c.lower() in content_words]
                item_copy[output_key] = matched[0] if matched else categories[0]
            else:
                # Auto-detect: just tag with first meaningful keyword
                words = str(content).split()
                important = [w for w in words if len(w) > 6]
                item_copy[output_key] = important[0].lower() if important else "general"

            classified.append(item_copy)

        return classified

    def _execute_rank(
        self,
        params: dict[str, Any],
        current_input: Any,
    ) -> list[dict[str, Any]]:
        """Execute a Rank stage — sorts items by a field."""
        if not isinstance(current_input, list):
            return []

        field = params.get("field", "score")
        reverse = params.get("reverse", True)
        top_k = params.get("top_k")

        def _get_sort_key(item: Any) -> float:
            if not isinstance(item, dict):
                return 0.0
            val = item.get(field, item.get("score", item.get("relevance", 0)))
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        ranked = sorted(current_input, key=_get_sort_key, reverse=reverse)
        if top_k is not None and top_k > 0:
            ranked = ranked[:top_k]
        return ranked


__all__ = [
    "PipelineDefinition",
    "PipelineMixin",
    "PipelineResult",
    "PipelineStage",
    "StageType",
]
