"""
Zep-compatible memory adapter — backward-compatibility wrapper.

This module now re-exports everything from the ``zep`` package
(``spacetime_memory.sdks.zep``) for backward compatibility.
All code has been migrated to the package structure at
``sdk/python/spacetime_memory/sdks/zep/``.
"""

from __future__ import annotations

from .zep._async import (
    AsyncZep,
    AsyncZepClient,
)
from .zep._client import (
    Message,
    UserClient,
    Zep,
    ZepClient,
)
from .zep._models import (
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
    "ApiError",
    "AsyncZep",
    "AsyncZepClient",
    "BadRequestError",
    "ConflictError",
    "Fact",
    "FactRatingExamples",
    "FactRatingInstruction",
    "Memory",
    "MemoryMessage",
    "MemorySearchResult",
    "Message",
    "NotFoundError",
    "RoleType",
    "SearchScope",
    "SearchType",
    "Session",
    "SessionFactRatingExamples",
    "SessionFactRatingInstruction",
    "SuccessResponse",
    "Summary",
    "UserClient",
    "Zep",
    "ZepClient",
    "ZepEnvironment",
]
