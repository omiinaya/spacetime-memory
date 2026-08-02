"""Spacetime-Memory client — composite Client class.

The ``Client`` class is composed from domain-specific mixins to
keep each module focused and maintainable.
The outer ``client.py`` module remains as an alias for backward compat.
"""
from __future__ import annotations

from ._admin import AdminMixin
from ._background import BackgroundProcessingMixin
from ._base import (
    _REDUCER_ERROR_MAP,
    _SQL_ERROR_MAP,
    _TRACER,
    ApiError,
    ClientBase,
    ClientError,
    EmbedderUnavailableError,
    JSONFormatter,
    MemoryRecord,
    NotFoundError,
    SpacetimeDBError,
    _tracing_span,
    configure_logging,
    logger,
)
from ._checkpoint import CheckpointMixin
from ._cognitive_ops import CognitiveOpMixin
from ._dreaming import DreamMixin
from ._embed import EmbedderMixin
from ._entity_resolution import EntityResolutionMixin
from ._export_import import ExportImportMixin
from ._git_versioning import GitMemoryVersioningMixin
from ._insights import InsightMixin
from ._interrupt import InterruptMixin
from ._kg import KGMixin
from ._memfs import MemfsMixin
from ._memories import MemoryMixin
from ._memories_directory import DirectoryMixin
from ._memories_docs import DocumentMixin
from ._memories_history import HistoryMixin
from ._memories_search import SearchMixin
from ._memories_stats import StatsMixin
from ._memories_tags import TagMixin
from ._memory_manager import MemoryManagerAgentMixin
from ._mental_models import (
    DIRECTIVE_TEMPLATES,
    Disposition,
    MentalModel,
    MentalModelMixin,
)
from ._new_features import NewFeaturesMixin
from ._notes import NotesMixin
from ._obs_extraction import ObservationExtractionMixin
from ._ontology import OntologyMixin
from ._pattern_detection import PatternDetectionMixin
from ._pipeline import (
    PipelineDefinition,
    PipelineMixin,
    PipelineResult,
    PipelineStage,
    StageType,
)
from ._polyphonic_recall import PolyphonicRecallMixin
from ._rbac import RBACMixin
from ._reasoning_tiers import (
    DEFAULT_REASONING_TIERS,
    ReasoningTierMixin,
)
from ._reflection_loop import ReflectionLoopMixin
from ._rerank import (
    _RERANK_PROMPT,
    RECIPE_REGISTRY,
    CrossEncoderReranker,
    FusionReranker,
    MMRReranker,
    NodeDistanceReranker,
    SearchFilter,
    SearchFilterDSL,
    SearchRecipe,
    _parse_rerank_json,
    get_reranker_for_recipe,
    list_recipes,
    llm_rerank,
    resolve_recipe,
)
from ._schemas import LLMSearchResult, _apply_return_schema
from ._session import SessionMixin
from ._session_distillation import SessionDistillationMixin
from ._skills import (
    BUILTIN_SKILL_CATALOG,
    BUILTIN_SKILL_MAP,
    MOD_MEMORY_TYPE,
    SKILL_MEMORY_TYPE,
    SkillsModsMixin,
)
from ._task_queue import TaskQueueMixin
from ._utils import _esc, _make_snippet, _parse_sql_response, _query_hash
from ._workspaces import WorkspaceMixin


class Client(ClientBase, WorkspaceMixin, SearchMixin, TagMixin, DocumentMixin, DirectoryMixin, HistoryMixin, StatsMixin, SessionMixin, NotesMixin, MemoryMixin, KGMixin, AdminMixin, EmbedderMixin, InsightMixin, NewFeaturesMixin, RBACMixin, TaskQueueMixin, ExportImportMixin, PipelineMixin, MentalModelMixin, CheckpointMixin, InterruptMixin, OntologyMixin, SkillsModsMixin, DreamMixin, PatternDetectionMixin, ReflectionLoopMixin, BackgroundProcessingMixin, ObservationExtractionMixin, SessionDistillationMixin, ReasoningTierMixin, CognitiveOpMixin, MemfsMixin, EntityResolutionMixin, MemoryManagerAgentMixin, GitMemoryVersioningMixin, PolyphonicRecallMixin):
    """Spacetime-Memory client — all-in-one interface.

    Composed from domain mixins to keep each module focused.
    See individual mixin files for method documentation.
    """
    # Typed memory row record (module-level in _base, exposed as class attr
    # for backward compatibility with ``Client.MemoryRecord.from_dict``).
    MemoryRecord = MemoryRecord

__all__ = [
    "RECIPE_REGISTRY",
    "_REDUCER_ERROR_MAP",
    "_RERANK_PROMPT",
    "_SQL_ERROR_MAP",
    "_TRACER",
    "ApiError",
    "Client",
    "ClientBase",
    "ClientError",
    "CrossEncoderReranker",
    "EmbedderUnavailableError",
    "FusionReranker",
    "JSONFormatter",
    "LLMSearchResult",
    "MMRReranker",
    "NodeDistanceReranker",
    "NotFoundError",
    "SearchFilter",
    "SearchFilterDSL",
    "SearchRecipe",
    "SpacetimeDBError",
    "_apply_return_schema",
    "_esc",
    "_make_snippet",
    "_parse_rerank_json",
    "_parse_sql_response",
    "_query_hash",
    "_tracing_span",
    "configure_logging",
    "get_reranker_for_recipe",
    "list_recipes",
    "llm_rerank",
    "logger",
    "resolve_recipe",
]
