"""
Zep-compatible memory adapter — data models.

Provides all data classes, error types, and stub enums matching
the zep-python v2.0.2 surface area.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Error classes (same contract as zep_python)
# ---------------------------------------------------------------------------

try:
    from zep_python import ApiError, BadRequestError, ConflictError, NotFoundError
except ImportError:
    # Fallback: define our own so imports don't break
    class NotFoundError(RuntimeError):
        pass

    class BadRequestError(RuntimeError):
        pass

    class ApiError(RuntimeError):
        def __init__(self, message="", **kwargs):
            super().__init__(message)

    class ConflictError(RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Data structures (matching zep-python shapes)
# ---------------------------------------------------------------------------


class MemoryMessage:
    """A single message in a Zep memory session.

    Mirrors ``zep_python.memory.models.MemoryMessage``.
    """

    def __init__(
        self,
        role: str = "user",
        content: str = "",
        created_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        role_type: str | None = None,
        token_count: int | None = None,
        updated_at: str | None = None,
        uuid: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.role = role
        self.content = content
        self.created_at = created_at
        self.metadata = metadata or {}
        self.role_type = role_type
        self.token_count = token_count
        self.updated_at = updated_at
        self.uuid = uuid
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the model to a plain dict."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.created_at is not None:
            d["created_at"] = self.created_at
        if self.metadata:
            d["metadata"] = self.metadata
        if self.role_type is not None:
            d["role_type"] = self.role_type
        if self.token_count is not None:
            d["token_count"] = self.token_count
        if self.updated_at is not None:
            d["updated_at"] = self.updated_at
        if self.uuid is not None:
            d["uuid"] = self.uuid
        d.update(
            {
                k: v
                for k, v in self.__dict__.items()
                if k
                not in (
                    "role",
                    "content",
                    "created_at",
                    "metadata",
                    "role_type",
                    "token_count",
                    "updated_at",
                    "uuid",
                )
            }
        )
        return d


class Memory:
    """Memory response from Zep.

    Mirrors ``zep_python.memory.models.Memory``.
    """

    def __init__(
        self,
        session_id: str = "",
        messages: list[MemoryMessage] | None = None,
        metadata: dict[str, Any] | None = None,
        facts: list[str] | None = None,
        relevant_facts: list[Fact] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.session_id = session_id
        self.messages = messages or []
        self.metadata = metadata or {}
        self.facts = facts or []
        self.relevant_facts = relevant_facts or []
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the model to a plain dict."""
        return {
            "session_id": self.session_id,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "facts": self.facts,
            "relevant_facts": [f.to_dict() for f in self.relevant_facts],
        }


class Session:
    """A Zep session.

    Mirrors ``zep_python.memory.models.Session``.
    """

    def __init__(
        self,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        classifications: list[str] | None = None,
        deleted_at: str | None = None,
        ended_at: str | None = None,
        fact_rating_instruction: dict | None = None,
        facts: list[str] | None = None,
        project_uuid: str | None = None,
        user_id: str | None = None,
        uuid: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.session_id = session_id
        self.metadata = metadata or {}
        self.created_at = created_at or ""
        self.updated_at = updated_at or ""
        self.classifications = classifications or []
        self.deleted_at = deleted_at
        self.ended_at = ended_at
        self.fact_rating_instruction = fact_rating_instruction
        self.facts = facts or []
        self.project_uuid = project_uuid
        self.user_id = user_id
        self.uuid = uuid
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the model to a plain dict."""
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.classifications:
            d["classifications"] = self.classifications
        if self.deleted_at is not None:
            d["deleted_at"] = self.deleted_at
        if self.ended_at is not None:
            d["ended_at"] = self.ended_at
        if self.fact_rating_instruction is not None:
            d["fact_rating_instruction"] = self.fact_rating_instruction
        if self.facts:
            d["facts"] = self.facts
        if self.project_uuid is not None:
            d["project_uuid"] = self.project_uuid
        if self.user_id is not None:
            d["user_id"] = self.user_id
        if self.uuid is not None:
            d["uuid"] = self.uuid
        d.update(
            {
                k: v
                for k, v in self.__dict__.items()
                if k
                not in (
                    "session_id",
                    "metadata",
                    "created_at",
                    "updated_at",
                    "classifications",
                    "deleted_at",
                    "ended_at",
                    "fact_rating_instruction",
                    "facts",
                    "project_uuid",
                    "user_id",
                    "uuid",
                )
            }
        )
        return d


class MemorySearchResult:
    """A single search result from Zep memory search.

    Mirrors ``zep_python.memory.models.MemorySearchResult``.
    """

    def __init__(
        self,
        message: MemoryMessage | None = None,
        score: float = 0.0,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.message = message
        self.score = score
        self.metadata = metadata or {}
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the model to a plain dict."""
        return {
            "message": self.message.to_dict() if self.message else None,
            "score": self.score,
            "metadata": self.metadata,
        }


class Fact:
    """A single fact in a Zep session.

    Mirrors ``zep_python.types.Fact``.

    Stores a factual statement about the user, extracted from conversation.
    """

    def __init__(
        self,
        uuid: str = "",
        fact: str = "",
        created_at: str | None = None,
        rating: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.uuid = uuid
        self.fact = fact
        self.created_at = created_at or ""
        self.rating = rating
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the model to a plain dict."""
        d: dict[str, Any] = {
            "uuid": self.uuid,
            "fact": self.fact,
            "created_at": self.created_at,
        }
        if self.rating is not None:
            d["rating"] = self.rating
        d.update(
            {
                k: v
                for k, v in self.__dict__.items()
                if k not in ("uuid", "fact", "created_at", "rating")
            }
        )
        return d


# ---------------------------------------------------------------------------
# Stub type exports (zep-python v2.0.2 surface area)
# ---------------------------------------------------------------------------


class Summary:
    """Stub for ``zep_python.types.Summary``.

    Represents an LLM-generated session summary.  Currently a placeholder
    because SpacetimeDB does not run Zep's LLM summarisation pipeline.
    """

    def __init__(
        self,
        uuid: str = "",
        created_at: str = "",
        content: str = "",
        token_count: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.uuid = uuid
        self.created_at = created_at
        self.content = content
        self.token_count = token_count
        self.__dict__.update(kwargs)


class RoleType:
    """Stub for ``zep_python.types.RoleType`` enum.

    Maps to role strings used by Zep: ``"user"``, ``"assistant"``,
    ``"system"``, ``"function"``, ``"tool"``.
    """

    UserRole = "user"
    AssistantRole = "assistant"
    SystemRole = "system"
    FunctionRole = "function"
    ToolRole = "tool"


class SearchScope:
    """Stub for ``zep_python.types.SearchScope`` enum.

    ``MESSAGES`` — search message content.
    ``FACTS`` — search factual statements.
    ``SUMMARY`` — search session summaries.
    """

    MESSAGES = "messages"
    FACTS = "facts"
    SUMMARY = "summary"


class SearchType:
    """Stub for ``zep_python.types.SearchType`` enum.

    ``SIMILARITY`` — vector / semantic search.
    ``MMR`` — max-marginal-relevance search (uses MMR λ=0.7 reranking).
    """

    SIMILARITY = "similarity"
    MMR = "mmr"


class ZepEnvironment:
    """Stub for ``zep_python.types.ZepEnvironment`` enum.

    ``CLOUD`` — Zep Cloud API.
    ``SELF_HOSTED`` — on-premise / self-hosted Zep instance.
    """

    CLOUD = "cloud"
    SELF_HOSTED = "self_hosted"


class SuccessResponse:
    """Stub for ``zep_python.types.SuccessResponse``.

    Generic success envelope returned by many Zep API endpoints.
    """

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        """Initialize the API resource wrapper."""
        self.message = message
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# Fact-rating instruction stubs (zep-python v2.0.2)
# ---------------------------------------------------------------------------


class FactRatingExamples:
    """Stub for ``zep_python.types.FactRatingExamples``.

    Example fact-rating pairs used to steer Zep's LLM fact extraction.
    """

    def __init__(
        self,
        high: str = "",
        medium: str = "",
        low: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.high = high
        self.medium = medium
        self.low = low
        self.__dict__.update(kwargs)


class FactRatingInstruction:
    """Stub for ``zep_python.types.FactRatingInstruction``.

    Instruction template for the fact-rating LLM prompt.
    """

    def __init__(
        self,
        instruction: str = "",
        examples: FactRatingExamples | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.instruction = instruction
        self.examples = examples
        self.__dict__.update(kwargs)


class SessionFactRatingExamples:
    """Stub for ``zep_python.types.SessionFactRatingExamples``.

    Session-level fact-rating example pairs.
    """

    def __init__(
        self,
        high: str = "",
        medium: str = "",
        low: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.high = high
        self.medium = medium
        self.low = low
        self.__dict__.update(kwargs)


class SessionFactRatingInstruction:
    """Stub for ``zep_python.types.SessionFactRatingInstruction``.

    Per-session instruction template for the fact-rating LLM prompt.
    """

    def __init__(
        self,
        instruction: str = "",
        examples: SessionFactRatingExamples | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the API resource wrapper."""
        self.instruction = instruction
        self.examples = examples
        self.__dict__.update(kwargs)
