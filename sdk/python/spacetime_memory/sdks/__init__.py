"""Parity adapters — drop-in API compatibility with popular memory backends.

These modules provide API-compatible interfaces so apps written against
Mem0, Zep, Graphiti, Honcho, LangChain, or Hindsight can use
spacetime-memory as a backend without changing their code.

This is distinct from ``spacetime_memory.connectors``, which provides
**sync connectors** that actively poll external data sources (Discord,
GitHub, RSS, etc.) and persist events as memories or KG nodes.
"""

from .graphiti import (
    AddEpisodeResults,
    AddTripletResults,
    CommunityEdge,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicNode,
    Graphiti,
    SearchResults,
)
from .hindsight import (
    BankProfileResponse,
    DispositionTraits,
    FileRetainResponse,
    Hindsight,
    ListMemoryUnitsResponse,
    RecallResponse,
    RecallResult,
    ReflectFact,
    ReflectResponse,
    RetainResponse,
    TokenUsage,
)
from .honcho import Honcho, Message, Peer, Session, SyncPage
from .langchain import StmemMemoryStore, StmemStore
from .mem0 import Memory as Mem0Memory
from .zep import (
    ApiError,
    AsyncZep,
    AsyncZepClient,
    BadRequestError,
    ConflictError,
    Fact,
    FactRatingExamples,
    FactRatingInstruction,
    Memory,
    MemoryMessage,
    MemorySearchResult,
    NotFoundError,
    RoleType,
    SearchScope,
    SearchType,
    SessionFactRatingExamples,
    SessionFactRatingInstruction,
    SuccessResponse,
    Summary,
    UserClient,
    Zep,
    ZepClient,
    ZepEnvironment,
)
from .zep import (
    Session as ZepSession,
)

__all__ = [
    "AddEpisodeResults",
    "AddTripletResults",
    "ApiError",
    "AsyncZep",
    "AsyncZepClient",
    "BadRequestError",
    "BankProfileResponse",
    "CommunityEdge",
    "CommunityNode",
    "ConflictError",
    "DispositionTraits",
    "EntityEdge",
    "EntityNode",
    "EpisodicNode",
    "Fact",
    "FactRatingExamples",
    "FactRatingInstruction",
    "FileRetainResponse",
    "Graphiti",
    "Hindsight",
    "Honcho",
    "ListMemoryUnitsResponse",
    "Mem0Memory",
    "Memory",
    "MemoryMessage",
    "MemorySearchResult",
    "Message",
    "NotFoundError",
    "Peer",
    "RecallResponse",
    "RecallResult",
    "ReflectFact",
    "ReflectResponse",
    "RetainResponse",
    "RoleType",
    "SearchResults",
    "SearchScope",
    "SearchType",
    "Session",
    "SessionFactRatingExamples",
    "SessionFactRatingInstruction",
    "StmemMemoryStore",
    "StmemStore",
    "SuccessResponse",
    "Summary",
    "SyncPage",
    "TokenUsage",
    "UserClient",
    "Zep",
    "ZepClient",
    "ZepEnvironment",
    "ZepSession",
]
