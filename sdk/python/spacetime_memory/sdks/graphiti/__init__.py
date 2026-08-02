"""Graphiti-compatible adapter — package.

See :mod:`spacetime_memory.sdks.graphiti._models` for the data types
and :mod:`spacetime_memory.sdks.graphiti._client` for the client.
"""

from __future__ import annotations

from spacetime_memory.client import Client as GraphitiClient

from ._client import (
    Graphiti,
)
from ._edge_namespaces import (
    CommunityEdgeNamespace,
    EdgeNamespace,
    EntityEdgeNamespace,
    EpisodicEdgeNamespace,
    HasEpisodeEdgeNamespace,
    NextEpisodeEdgeNamespace,
)
from ._models import (
    AddBulkEpisodeResults,
    AddEpisodeResults,
    AddTripletResults,
    CommunityEdge,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicEdge,
    EpisodicNode,
    HasEpisodeEdge,
    NextEpisodeEdge,
    RawEpisode,
    SagaNode,
    SearchResults,
)

# Namespace classes
from ._node_namespaces import (
    CommunityNodeNamespace,
    EntityNodeNamespace,
    EpisodeNodeNamespace,
    NodeNamespace,
    SagaNodeNamespace,
)
from ._utils import _esc

__all__ = [
    "AddBulkEpisodeResults",
    "AddEpisodeResults",
    "AddTripletResults",
    "CommunityEdge",
    "CommunityEdgeNamespace",
    "CommunityNode",
    "CommunityNodeNamespace",
    "EdgeNamespace",
    "EntityEdge",
    "EntityEdgeNamespace",
    "EntityNode",
    "EntityNodeNamespace",
    "EpisodeNodeNamespace",
    "EpisodicEdge",
    "EpisodicEdgeNamespace",
    "EpisodicNode",
    "Graphiti",
    "GraphitiClient",
    "HasEpisodeEdge",
    "HasEpisodeEdgeNamespace",
    "NextEpisodeEdge",
    "NextEpisodeEdgeNamespace",
    "NodeNamespace",
    "RawEpisode",
    "SagaNode",
    "SagaNodeNamespace",
    "SearchResults",
    "_esc",
]
