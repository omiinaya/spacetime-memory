"""
Drop-in replacement for ``honcho.Honcho`` — package.

Maps the Honcho conversational memory platform API
(https://github.com/plastic-labs/honcho) to SpacetimeDB storage.

See :mod:`spacetime_memory.sdks.honcho._models` for the data types
and :mod:`spacetime_memory.sdks.honcho._client` for the client.

Usage::

    from spacetime_memory.sdks import Honcho

    client = Honcho(workspace_id=\"my-workspace\", base_url=None,
                    stdb_host=\"127.0.0.1\", stdb_port=3001)

    alice = client.peer(\"alice\")
    session = client.session(\"conversation-1\")
    session.add_peers([alice])

    msg = alice.message(\"Hello, world!\")
    session.add_messages([msg])
"""

from __future__ import annotations

from ...llm import LLMClient
from ._client import (
    ConclusionScope,
    ConclusionScopeAio,
    Honcho,
    HonchoAio,
    Peer,
    PeerAio,
    Session,
    SessionAio,
)
from ._models import (
    Conclusion,
    ConclusionCreateParams,
    ConclusionResponse,
    DialecticResponse,
    DreamConfiguration,
    Message,
    MessageConfiguration,
    MessageCreateParams,
    MessageResponse,
    PeerCardConfiguration,
    PeerConfig,
    PeerContextResponse,
    PeerResponse,
    QueueStatusResponse,
    ReasoningConfiguration,
    SessionConfiguration,
    SessionConfigurationResponse,
    SessionContext,
    SessionPeerConfig,
    SessionQueueStatus,
    SessionResponse,
    SessionSummaries,
    Summary,
    SummaryConfiguration,
    SyncPage,
    WorkspaceConfiguration,
    WorkspaceConfigurationResponse,
    WorkspaceResponse,
)

__all__ = [
    "Conclusion",
    "ConclusionCreateParams",
    "ConclusionResponse",
    "ConclusionScope",
    "ConclusionScopeAio",
    "DialecticResponse",
    "DreamConfiguration",
    "Honcho",
    "HonchoAio",
    "LLMClient",
    "Message",
    "MessageConfiguration",
    "MessageCreateParams",
    "MessageResponse",
    "Peer",
    "PeerAio",
    "PeerCardConfiguration",
    "PeerConfig",
    "PeerContextResponse",
    "PeerResponse",
    "QueueStatusResponse",
    "ReasoningConfiguration",
    "Session",
    "SessionAio",
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
