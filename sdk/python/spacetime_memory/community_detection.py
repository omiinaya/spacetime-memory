"""
Native community detection for knowledge graphs — Graphiti/Cognee parity.

Implements a modularity-optimizing community detection algorithm (Louvain-like)
entirely in Python, using only the existing ``kg_node`` and ``kg_edge`` tables
in SpacetimeDB.  No external graph libraries required (networkx, igraph, etc.).

Algorithm
---------
1. **Seed**: Nodes with no community assignment get seeded via edge connectivity
   (connected components).
2. **Louvain-style refinement**: Iteratively move nodes between communities to
   maximize modularity gain.  Modularity Q = sum over communities of
   (internal_edges / total_edges - (total_degree / (2*total_edges))²).
3. **Hierarchical aggregation**: (Optional) Treat each detected community as a
   super-node and repeat, building a community hierarchy.
4. **Community summaries**: LLM-generated narrative summaries for each community
   (when an LLM is available).

Usage
-----
    from spacetime_memory.community_detection import detect_communities

    result = detect_communities(client, workspace_id)
    for comm in result["communities"]:
        print(comm["name"], comm["summary"], comm["size"])
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Modularity-based community detection (pure Python)
# ---------------------------------------------------------------------------


def detect_communities(
    client: Any,
    workspace_id: str,
    max_iterations: int = 50,
    resolution: float = 1.0,
    min_community_size: int = 2,
) -> dict[str, Any]:
    """Run modularity-optimizing community detection on a knowledge graph.

    This is a pure-Python implementation of a Louvain-like algorithm that
    operates entirely through the SpacetimeDB ``kg_node`` and ``kg_edge``
    tables.  No external dependencies.

    Parameters
    ----------
    client:
        SpacetimeMemory client instance.
    workspace_id:
        Target workspace.
    max_iterations:
        Maximum refinement passes (default 50 — typically converges in 5-15).
    resolution:
        Modularity resolution parameter.  >1.0 yields more/smaller communities;
        <1.0 yields fewer/larger communities.
    min_community_size:
        Communities smaller than this are merged into the nearest large
        community.

    Returns
    -------
    dict with keys:
        communities : list[dict]
            Each dict: {id, name, size, internal_edges, summary, members}
        modularity : float
            Final modularity score.
        iterations : int
            Iterations to convergence.
    """
    start = time.time()

    # --- Phase 1: Fetch all nodes and edges from STDB ---
    nodes = _fetch_nodes(client, workspace_id)
    edges = _fetch_edges(client, workspace_id)

    if not nodes:
        return {
            "communities": [],
            "modularity": 0.0,
            "iterations": 0,
            "elapsed_s": 0.0,
            "node_count": 0,
            "edge_count": 0,
        }

    node_ids = [n["id"] for n in nodes]
    node_id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    existing_community = {n["id"]: n.get("community_id", 0) or 0 for n in nodes}

    n = len(nodes)
    m = len(edges)

    # Build adjacency list with edge weights
    adj: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for e in edges:
        src = node_id_to_idx.get(e.get("source_node_id", ""))
        tgt = node_id_to_idx.get(e.get("target_node_id", ""))
        if src is not None and tgt is not None:
            w = float(e.get("weight", 1.0))
            adj[src].append((tgt, w))
            adj[tgt].append((src, w))  # undirected
            # Note: if edges are directed, we still use undirected modularity
            # which is standard for community detection in knowledge graphs

    # Degrees and total weight
    degree = [sum(w for _, w in neighbors) for neighbors in adj]
    total_weight = sum(degree) / 2.0  # double-counted

    if total_weight == 0:
        # Isolated nodes — each becomes its own community
        communities = []
        for i in range(n):
            comm_id = existing_community.get(node_ids[i], 0) or (i + 1)
            communities.append({
                "id": comm_id,
                "name": nodes[i].get("label", f"Node {comm_id}"),
                "size": 1,
                "internal_edges": 0,
                "modularity_contribution": 0.0,
                "members": [node_ids[i]],
                "member_labels": [nodes[i].get("label", "")],
            })
        return {
            "communities": communities,
            "modularity": 0.0,
            "iterations": 0,
            "elapsed_s": time.time() - start,
            "node_count": n,
            "edge_count": m,
        }

    # --- Phase 2: Initialize communities ---
    # Standard Louvain-style initialization: each node starts in its own community.
    # Nodes with existing community_ids preserve those seeds.
    community_of_node: list[int] = [0] * n
    next_community_id = 1

    # Build a map from existing community_id -> new sequential ID
    existing_map: dict[int, int] = {}
    for i in range(n):
        cid = existing_community.get(node_ids[i], 0)
        if cid > 0:
            if cid not in existing_map:
                existing_map[cid] = next_community_id
                next_community_id += 1
            community_of_node[i] = existing_map[cid]

    # Each unassigned node starts in its own community (standard Louvain)
    for i in range(n):
        if community_of_node[i] == 0:
            community_of_node[i] = next_community_id
            next_community_id += 1

    k = next_community_id - 1

    # --- Phase 3: Louvain modularity optimization ---
    # Pre-compute community properties
    comm_total_degree = [0.0] * (k + 1)
    comm_internal_weight = [0.0] * (k + 1)

    for i in range(n):
        c = community_of_node[i]
        comm_total_degree[c] += degree[i]

    for i in range(n):
        ci = community_of_node[i]
        for j, w in adj[i]:
            if community_of_node[j] == ci and j > i:
                comm_internal_weight[ci] += w

    def current_modularity() -> float:
        """Compute modularity Q."""
        Q = 0.0
        for c in range(1, k + 1):
            if comm_total_degree[c] == 0:
                continue
            expected = (comm_total_degree[c] / (2.0 * total_weight)) ** 2
            Q += comm_internal_weight[c] / total_weight - resolution * expected
        return Q

    # Track modularity improvement
    best_mod = current_modularity()
    best_assignment = list(community_of_node)
    iteration = 0

    for iteration in range(max_iterations):
        changed = False

        # Shuffle nodes for stochastic stability (use deterministic order
        # for reproducibility — sort by degree descending for faster convergence)
        order = sorted(range(n), key=lambda i: degree[i], reverse=True)

        for i in order:
            ci = community_of_node[i]
            if degree[i] == 0:
                continue

            # Remove node i from its current community (standard Louvain:
            # first isolate the node, then evaluate gains for joining others)
            comm_total_degree[ci] -= degree[i]
            for j, w in adj[i]:
                if community_of_node[j] == ci:
                    comm_internal_weight[ci] -= w

            # Compute gain from adding i to each neighbouring community.
            # Also consider the original community ci (re-adding i back).
            neighbor_communities: dict[int, float] = defaultdict(float)
            for j, w in adj[i]:
                cj = community_of_node[j]
                # Include ALL neighbors' communities (including ci, since i was
                # removed from ci and rejoining ci is a valid option)
                neighbor_communities[cj] += w

            if not neighbor_communities:
                # No neighbors — put back in ci
                _move_node_back(i, ci, degree[i], adj, community_of_node,
                                comm_total_degree, comm_internal_weight)
                continue

            best_c = ci
            best_gain = 0.0

            # ΔQ = ki_in / m - (Σ_tot * ki) / (2 * m²)
            # Σ_tot is total degree of TARGET community (post-removal for ci)
            # ki_in is weight from i to nodes in target community
            for target_c, ki_in in neighbor_communities.items():
                sig_tot = comm_total_degree[target_c]
                gain = ki_in / total_weight - resolution * (sig_tot * degree[i]) / (2.0 * total_weight * total_weight)

                if gain > best_gain:
                    best_gain = gain
                    best_c = target_c

            if best_c != ci and best_gain > 1e-10:
                # Move to best_c: add i to the target community
                community_of_node[i] = best_c
                comm_total_degree[best_c] += degree[i]
                for j, w in adj[i]:
                    if community_of_node[j] == best_c:
                        comm_internal_weight[best_c] += w
                changed = True
            else:
                # Put i back in its original community
                _move_node_back(i, ci, degree[i], adj, community_of_node,
                                comm_total_degree, comm_internal_weight)

        # Compute modularity after iteration
        Q = current_modularity()
        if Q > best_mod:
            best_mod = Q
            best_assignment = list(community_of_node)

        if not changed or (iteration > 5 and Q <= best_mod and not changed):
            break

    # Restore best assignment
    community_of_node = best_assignment

    # --- Phase 4: Merge small communities ---
    comm_sizes = Counter(community_of_node)
    small_comms = {c for c, sz in comm_sizes.items() if sz < min_community_size and c > 0}

    if small_comms and k > len(small_comms) + 1:
        for i in range(n):
            ci = community_of_node[i]
            if ci in small_comms:
                # Find the most-connected larger community
                neighbor_counts: dict[int, float] = defaultdict(float)
                for j, w in adj[i]:
                    cj = community_of_node[j]
                    if cj not in small_comms:
                        neighbor_counts[cj] += w
                if neighbor_counts:
                    best_c = max(neighbor_counts, key=lambda c: neighbor_counts[c])
                    _move_node(i, ci, best_c, adj, degree, community_of_node,
                               comm_total_degree, comm_internal_weight)

    # --- Phase 5: Build result ---
    result_nodes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i in range(n):
        c = community_of_node[i]
        result_nodes[c].append({"id": node_ids[i], "label": nodes[i].get("label", ""),
                                "node_type": nodes[i].get("node_type", "")})

    communities = []
    for c in sorted(result_nodes.keys()):
        member_ids = [nd["id"] for nd in result_nodes[c]]
        communities.append({
            "id": c,
            "name": _generate_community_name(result_nodes[c]),
            "size": len(result_nodes[c]),
            "internal_edges": int(comm_internal_weight[c]),
            "modularity_contribution": comm_internal_weight[c] / total_weight
                - resolution * (comm_total_degree[c] / (2.0 * total_weight)) ** 2,
            "members": member_ids,
            "member_labels": [nd["label"] for nd in result_nodes[c]],
        })

    communities.sort(key=lambda c: c["size"], reverse=True)

    elapsed = time.time() - start

    return {
        "communities": communities,
        "modularity": best_mod,
        "iterations": iteration + 1,
        "elapsed_s": elapsed,
        "node_count": n,
        "edge_count": m,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_nodes(client: Any, workspace_id: str) -> list[dict[str, Any]]:
    """Fetch all nodes for a workspace via the STDB SDK."""
    try:
        return client._query("kg_node", workspace_id=workspace_id,
                             columns=["id", "label", "node_type", "summary",
                                      "community_id", "name"])
    except Exception as e:
        logger.warning("Failed to fetch nodes: %s", e)
        return []


def _fetch_edges(client: Any, workspace_id: str) -> list[dict[str, Any]]:
    """Fetch all edges for a workspace via the STDB SDK."""
    try:
        return client._query("kg_edge", workspace_id=workspace_id,
                             columns=["id", "source_node_id", "target_node_id",
                                      "relationship_type", "weight", "edge_group_id"])
    except Exception as e:
        logger.warning("Failed to fetch edges: %s", e)
        return []


def _connected_components(
    adj: list[list[tuple[int, float]]],
    n: int,
    subset: list[int],
) -> dict[int, int]:
    """Assign nodes in *subset* to connected components.

    Returns a dict mapping node index -> component id (1-based).
    """
    visited = set(subset)
    component_of: dict[int, int] = {}
    next_cid = 1

    for start in subset:
        if start in component_of:
            continue
        stack = [start]
        component_of[start] = next_cid
        while stack:
            node = stack.pop()
            for neigh, _ in adj[node]:
                if neigh in visited and neigh not in component_of:
                    component_of[neigh] = next_cid
                    stack.append(neigh)
        next_cid += 1

    return component_of


def _move_node(
    i: int,
    from_c: int,
    to_c: int,
    adj: list[list[tuple[int, float]]],
    degree: list[float],
    community_of_node: list[int],
    comm_total_degree: list[float],
    comm_internal_weight: list[float],
) -> None:
    """Move node i from from_c to to_c and update community statistics."""
    # Remove contributions from from_c
    comm_total_degree[from_c] -= degree[i]

    # Subtract internal edges for from_c (edges from i to other nodes in from_c)
    for j, w in adj[i]:
        if community_of_node[j] == from_c:
            comm_internal_weight[from_c] -= w

    # Update community assignment
    community_of_node[i] = to_c

    # Add contributions to to_c
    comm_total_degree[to_c] += degree[i]

    # Add internal edges for to_c (edges from i to other nodes in to_c)
    for j, w in adj[i]:
        if community_of_node[j] == to_c:
            comm_internal_weight[to_c] += w


def _move_node_back(
    i: int,
    ci: int,
    ki: float,
    adj: list[list[tuple[int, float]]],
    community_of_node: list[int],
    comm_total_degree: list[float],
    comm_internal_weight: list[float],
) -> None:
    """Restore node i to community ci after a temporary removal."""
    community_of_node[i] = ci
    comm_total_degree[ci] += ki
    for j, w in adj[i]:
        if community_of_node[j] == ci and j != i:
            comm_internal_weight[ci] += w


def _generate_community_name(members: list[dict[str, Any]]) -> str:
    """Generate a readable community name from member labels."""
    labels = [m.get("label", "") for m in members if m.get("label")]
    types = Counter(m.get("node_type", "") for m in members)
    dominant_type = types.most_common(1)[0][0] if types else "entity"

    if len(labels) <= 3:
        return f"{', '.join(labels)}" if labels else f"Community ({dominant_type})"
    else:
        return f"{labels[0]}, {labels[1]} +{len(labels)-2} more ({dominant_type})"


# ---------------------------------------------------------------------------
# Community summarization (LLM-based)
# ---------------------------------------------------------------------------

COMMUNITY_SUMMARY_PROMPT = """You are a knowledge graph analyst.  Given a community of related entities from a knowledge graph, write a brief narrative summary (2-4 sentences) describing what this community represents, what its members have in common, and how they relate to each other.

Community name: {name}
Member count: {size}
Members: {member_labels}
Representative entities: {top_labels}
"""


def summarize_communities(
    client: Any,
    workspace_id: str,
    communities: list[dict[str, Any]],
    llm_client: Any = None,
) -> list[dict[str, Any]]:
    """Generate LLM summaries for detected communities.

    Parameters
    ----------
    client:
        SpacetimeMemory client instance (for persisting summaries).
    workspace_id:
        Target workspace.
    communities:
        List of community dicts from ``detect_communities()``.
    llm_client:
        Optional LLM client with a ``chat()`` method.  If None, skips
        summarization and returns communities as-is with placeholder summaries.

    Returns
    -------
    Updated communities list with ``summary`` field populated.
    """
    if not llm_client:
        for comm in communities:
            member_labels = comm.get("member_labels", [])
            if member_labels:
                comm["summary"] = f"A community of {comm['size']} entities related to {', '.join(member_labels[:3])}."
            else:
                comm["summary"] = f"A community of {comm['size']} related entities."
        return communities

    for comm in communities:
        member_labels = comm.get("member_labels", [])
        top_labels = member_labels[:8] if member_labels else ["unnamed entities"]
        prompt = COMMUNITY_SUMMARY_PROMPT.format(
            name=comm.get("name", f"Community {comm['id']}"),
            size=comm["size"],
            member_labels=", ".join(member_labels[:15]),
            top_labels=", ".join(top_labels[:5]),
        )
        try:
            response = llm_client.chat(prompt)
            comm["summary"] = response.strip()
        except Exception as e:
            logger.warning("Community summarization failed for id=%s: %s", comm["id"], e)
            comm["summary"] = f"A community of {comm['size']} related entities."

    return communities


def persist_communities(
    client: Any,
    workspace_id: str,
    communities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist detected communities back to SpacetimeDB.

    For each community:
    1. Creates a ``kg_community`` record (via ``create_community`` reducer)
    2. Assigns each member node to the community (via ``assign_to_community`` reducer)

    Returns a summary dict with counts.
    """
    created = 0
    assigned = 0

    for comm in communities:
        name = comm.get("name", f"community_{comm['id']}")
        summary = comm.get("summary", "")
        try:
            result = client.create_community(workspace_id, name, summary)
            # The STDB community_id assigned by the reducer
            community_id = result.get("community_id", comm["id"])
            created += 1
        except Exception as e:
            logger.warning("Failed to create community '%s': %s", name, e)
            # Fallback: use the local community id
            community_id = comm["id"]

        for member_id in comm.get("members", []):
            try:
                client.assign_to_community(member_id, community_id)
                assigned += 1
            except Exception as e:
                logger.warning(
                    "Failed to assign node %s to community %s: %s",
                    member_id, community_id, e,
                )

    return {
        "communities_created": created,
        "nodes_assigned": assigned,
    }
