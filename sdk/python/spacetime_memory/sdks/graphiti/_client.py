"""Graphiti adapter — drop-in replacement for ``grapheti_core.graphiti.Graphiti``.

Wraps Spacetime-Memory's knowledge graph operations (kg_node, kg_edge)
behind Graphiti's API.

The implementation is split across mixin modules:
  - :mod:`_core` — init, lifecycle, helpers
  - :mod:`_episodes` — triplet, episode, retrieval
  - :mod:`_search` — hybrid search, entity edge summary
  - :mod:`_communities` — community detection, saga
  - :mod:`_edges` — temporal edge tracking
  - :mod:`_node_namespaces` — node namespace classes
  - :mod:`_edge_namespaces` — edge namespace classes
"""
from __future__ import annotations

from ._communities import GraphitiCommunities
from ._core import GraphitiCore
from ._edges import GraphitiEdges
from ._episodes import GraphitiEpisodes
from ._search import GraphitiSearch
from ._node_namespaces import (
    NodeNamespace,
    EntityNodeNamespace,
    EpisodeNodeNamespace,
    CommunityNodeNamespace,
    SagaNodeNamespace,
)

# Public re-exports consumed by tests and downstream users
__all__ = [
    "Graphiti",
    "NodeNamespace",
    "EntityNodeNamespace",
    "EpisodeNodeNamespace",
    "CommunityNodeNamespace",
    "SagaNodeNamespace",
]


class Graphiti(GraphitiCore, GraphitiEpisodes, GraphitiSearch, GraphitiCommunities, GraphitiEdges):
    """Drop-in replacement for ``grapheti_core.grapheti.Graphiti``.

    Wraps Spacetime-Memory's knowledge graph operations (kg_node,
    kg_edge) behind Graphiti's API.

    **Important differences from the real Graphiti:**

    * Our adapter is **synchronous** (Graphiti uses ``asyncio``).  All
      ``async def`` methods in the real API are ``def`` here.
    * The real Graphiti uses an **LLM** to extract entities and edges
      from raw text (``add_episode``).  This adapter includes optional
      LLM-powered extraction via ``LLMClient`` — it degrades gracefully
      (stores the episode without extracting entities) when no API key
      is configured.
    * ``group_id`` maps to a SpacetimeDB workspace **name**.  The
      adapter resolves group_id strings to actual workspace UUIDs via
      the ``_resolve_workspace`` cache.
    * ``build_communities`` delegates to the SpacetimeDB
      ``detect_communities`` reducer.
    * ``search`` returns ``EntityEdge`` objects (fact edges), matching
      the real Graphiti behaviour.
    * ``search_`` returns ``SearchResults`` with both nodes and edges,
      matching the real advanced search.

    Example::

        from spacetime_memory.sdks.graphiti import (
            Graphiti, EntityNode, EntityEdge,
        )

        g = Graphiti()
        result = g.add_triplet(
            source_node=EntityNode(name="Alice", group_id="ws1"),
            edge=EntityEdge(name="likes", fact="Alice likes pizza",
                            group_id="ws1"),
            target_node=EntityNode(name="Pizza", group_id="ws1"),
        )
        print(f"Created nodes: {[n.name for n in result.nodes]}")
        print(f"Created edges: {[e.name for e in result.edges]}")

        # Search for relevant facts
        edges = g.search("Alice food", group_ids=["ws1"])
        for e in edges:
            print(f"  {e.name}: {e.fact}")

        g.close()
    """
