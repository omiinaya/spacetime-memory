"""
Data models for the Honcho-compatible adapter.

Split from the monolithic ``honcho.py`` into a package.
"""

from __future__ import annotations

import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class ReasoningConfiguration(BaseModel):
    enabled: bool | None = None
    custom_instructions: str | None = None


class PeerCardConfiguration(BaseModel):
    use: bool | None = None
    create: bool | None = None


class SummaryConfiguration(BaseModel):
    enabled: bool | None = None
    messages_per_short_summary: int | None = None
    messages_per_long_summary: int | None = None


class DreamConfiguration(BaseModel):
    enabled: bool | None = None


class WorkspaceConfiguration(BaseModel):
    reasoning: ReasoningConfiguration | None = None
    peer_card: PeerCardConfiguration | None = None
    summary: SummaryConfiguration | None = None
    dream: DreamConfiguration | None = None


WorkspaceConfigurationResponse = WorkspaceConfiguration
SessionConfiguration = WorkspaceConfiguration
SessionConfigurationResponse = SessionConfiguration


class PeerConfig(BaseModel):
    observe_me: bool | None = None


class SessionPeerConfig(BaseModel):
    observe_others: bool | None = None
    observe_me: bool | None = None


class MessageConfiguration(BaseModel):
    reasoning: ReasoningConfiguration | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WorkspaceResponse(BaseModel):
    id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    configuration: WorkspaceConfigurationResponse = Field(
        default_factory=WorkspaceConfigurationResponse
    )
    created_at: datetime.datetime


class PeerResponse(BaseModel):
    id: str
    workspace_id: str
    created_at: datetime.datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    configuration: PeerConfig = Field(default_factory=PeerConfig)


class SessionResponse(BaseModel):
    id: str
    is_active: bool
    workspace_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    configuration: SessionConfigurationResponse = Field(
        default_factory=SessionConfigurationResponse
    )
    created_at: datetime.datetime


class MessageResponse(BaseModel):
    id: str
    content: str
    peer_id: str
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime.datetime
    workspace_id: str
    token_count: int = 0


class MessageCreateParams(BaseModel):
    content: str
    peer_id: str
    metadata: dict[str, Any] | None = None
    configuration: MessageConfiguration | None = None
    created_at: datetime.datetime | None = None


class Summary(BaseModel):
    content: str
    message_id: str
    summary_type: str
    created_at: str
    token_count: int = 0


class SessionSummaries(BaseModel):
    id: str
    short_summary: Summary | None = None
    long_summary: Summary | None = None


class SessionContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    session_id: str
    messages: list[Any] = Field(default_factory=list)
    summary: Summary | None = None
    peer_representation: str | None = None
    peer_card: list[str] | None = None

    def __len__(self) -> int:
        """Return the number of items."""
        return len(self.messages)


class PeerContextResponse(BaseModel):
    peer_id: str
    target_id: str
    representation: str | None = None
    peer_card: list[str] | None = None


class ConclusionResponse(BaseModel):
    id: str
    content: str
    observer_id: str
    observed_id: str
    session_id: str | None = None
    created_at: datetime.datetime


class ConclusionCreateParams(BaseModel):
    """Parameters for creating a conclusion — matches upstream honcho-ai."""

    content: str
    session_id: str | None = None


class SessionQueueStatus(BaseModel):
    session_id: str | None = None
    total_work_units: int = 0
    completed_work_units: int = 0
    in_progress_work_units: int = 0
    pending_work_units: int = 0


class QueueStatusResponse(BaseModel):
    total_work_units: int = 0
    completed_work_units: int = 0
    in_progress_work_units: int = 0
    pending_work_units: int = 0
    sessions: dict[str, SessionQueueStatus] | None = None


class DialecticResponse(BaseModel):
    content: str | None = None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

T = TypeVar("T")
U = TypeVar("U")


class SyncPage(Generic[T, U]):
    """Paginated response — matches honcho SyncPage[T, U]."""

    items: list[Any]
    total: int | None
    page: int | None
    size: int | None
    pages: int | None

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        items: list[Any] | None = None,
        total: int | None = None,
        page: int | None = None,
        size: int | None = None,
        pages: int | None = None,
    ):
        """Initialize the store/reference."""
        if data is not None:
            self.items = data.get("items", [])
            self.total = data.get("total")
            self.page = data.get("page")
            self.size = data.get("size")
            self.pages = data.get("pages")
        else:
            self.items = items or []
            self.total = total
            self.page = page
            self.size = size
            self.pages = pages

    def __iter__(self):
        """Iterate over items."""
        return iter(self.items)

    def __getitem__(self, index):
        """Get an item by index or key."""
        return self.items[index]

    def __len__(self) -> int:
        """Return the number of items."""
        return len(self.items)

    def has_next_page(self) -> bool:
        """Check if there are more results to paginate."""
        if self.page is not None and self.pages is not None:
            return self.page < self.pages
        return False


# ---------------------------------------------------------------------------
# Conclusion (plain class, not Pydantic — matches upstream)
# ---------------------------------------------------------------------------


class Conclusion:
    """A conclusion formed by an observer about an observed peer — matches upstream honcho.Conclusion."""

    def __init__(
        self,
        id: str,
        content: str,
        observer_id: str,
        observed_id: str,
        session_id: str | None = None,
        created_at: datetime.datetime | None = None,
    ):
        """Initialize the store/reference."""
        self.id = id
        self.content = content
        self.observer_id = observer_id
        self.observed_id = observed_id
        self.session_id = session_id
        self.created_at = created_at or datetime.datetime.now(datetime.UTC)

    @classmethod
    def from_api_response(cls, data: ConclusionResponse) -> Conclusion:
        """Create an instance from an API response dict."""
        return cls(
            id=data.id,
            content=data.content,
            observer_id=data.observer_id,
            observed_id=data.observed_id,
            session_id=data.session_id,
            created_at=data.created_at,
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Conclusion(id='{self.id[:8]}...', observer='{self.observer_id}', "
            f"observed='{self.observed_id}', content='{self.content[:50]}...')"
        )


# ---------------------------------------------------------------------------
# Message (plain class, not Pydantic — matches upstream)
# ---------------------------------------------------------------------------


class Message:
    """A message in a session — matches upstream honcho.Message."""

    def __init__(
        self,
        id: str,
        content: str,
        peer_id: str,
        session_id: str,
        workspace_id: str,
        metadata: dict[str, Any] | None = None,
        created_at: datetime.datetime | None = None,
        token_count: int = 0,
    ):
        """Initialize the store/reference."""
        self.id = id
        self.content = content
        self.peer_id = peer_id
        self.session_id = session_id
        self.workspace_id = workspace_id
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.datetime.now(datetime.UTC)
        self.token_count = token_count

    @classmethod
    def from_api_response(cls, data: MessageResponse) -> Message:
        """Create an instance from an API response dict."""
        return cls(
            id=data.id,
            content=data.content,
            peer_id=data.peer_id,
            session_id=data.session_id,
            workspace_id=data.workspace_id or "",
            metadata=data.metadata,
            created_at=data.created_at,
            token_count=data.token_count,
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"Message(id='{self.id[:8]}...', peer='{self.peer_id}', content='{self.content[:50]}...')"


__all__ = [
    "Conclusion",
    "ConclusionCreateParams",
    "ConclusionResponse",
    "DialecticResponse",
    "DreamConfiguration",
    "Message",
    "MessageConfiguration",
    "MessageCreateParams",
    "MessageResponse",
    "PeerCardConfiguration",
    "PeerConfig",
    "PeerContextResponse",
    "PeerResponse",
    "QueueStatusResponse",
    "ReasoningConfiguration",
    "SessionConfiguration",
    "SessionConfigurationResponse",
    "SessionContext",
    "SessionPeerConfig",
    "SessionQueueStatus",
    "SessionResponse",
    "SessionSummaries",
    "Summary",
    "SummaryConfiguration",
    "SyncPage",
    "WorkspaceConfiguration",
    "WorkspaceConfigurationResponse",
    "WorkspaceResponse",
]
