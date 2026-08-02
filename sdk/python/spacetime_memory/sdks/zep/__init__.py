"""
Zep-compatible memory adapter.

Maps the Zep long-term memory API (https://github.com/getzep/zep-python)
to SpacetimeDB.  This is the public API surface for the package.
"""

from __future__ import annotations

from ._async import (
    AsyncZep,
    AsyncZepClient,
    _AsyncGraphClient,
    _AsyncGraphEdgeNamespace,
    _AsyncGraphEpisodeNamespace,
    _AsyncGraphNodeNamespace,
    _AsyncMemoryProxy,
    _AsyncUserProxy,
)
from ._client import (
    Message,
    UserClient,
    Zep,
    ZepClient,
    _GraphClient,
    _GraphEdgeNamespace,
    _GraphEpisodeNamespace,
    _GraphNodeNamespace,
    _MemoryProxy,
    _UserProxy,
)
from ._models import (
    ApiError,
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
    Session,
    SessionFactRatingExamples,
    SessionFactRatingInstruction,
    SuccessResponse,
    Summary,
    ZepEnvironment,
)

__all__ = [
    "Zep",
    "ZepClient",
    "AsyncZep",
    "AsyncZepClient",
    "MemoryMessage",
    "Message",
    "Memory",
    "MemorySearchResult",
    "Session",
    "Fact",
    "UserClient",
    "NotFoundError",
    "BadRequestError",
    "ApiError",
    "ConflictError",
    "Summary",
    "RoleType",
    "SearchScope",
    "SearchType",
    "ZepEnvironment",
    "SuccessResponse",
    "FactRatingExamples",
    "FactRatingInstruction",
    "SessionFactRatingExamples",
    "SessionFactRatingInstruction",
    # Internal (exported for advanced use)
    "_MemoryProxy",
    "_UserProxy",
    "_GraphClient",
    "_GraphNodeNamespace",
    "_GraphEdgeNamespace",
    "_GraphEpisodeNamespace",
    "_AsyncMemoryProxy",
    "_AsyncUserProxy",
    "_AsyncGraphClient",
    "_AsyncGraphNodeNamespace",
    "_AsyncGraphEdgeNamespace",
    "_AsyncGraphEpisodeNamespace",
]
