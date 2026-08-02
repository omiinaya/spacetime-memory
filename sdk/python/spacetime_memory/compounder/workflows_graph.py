"""Compounder workflows — knowledge graph workflows."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)




class CompounderWorkflowsGraph:
    """Mixin — knowledge graph workflows."""


    def cross_link(
        self,
        workspace_id: str = "default",
        limit: int = 50,
        similarity_threshold: float = 0.7,
    ) -> dict[str, Any]:
        """Find memories/nodes that are semantically related but not yet
        linked, and create edges between them.

        Uses semantic search to find near-neighbours, then checks if
        an edge already exists before creating one.

        Args:
            workspace_id: Target workspace.
            limit: Max memories to scan.
            similarity_threshold: Min similarity to auto-link (0.0-1.0).

        Returns:
            Dict with ``links_created`` (int), ``pairs_checked`` (int).
        """
        # Fetch recent memories
        memories = self._client._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if not memories:
            return {"links_created": 0, "pairs_checked": 0}

        memories = sorted(memories, key=lambda r: r.get("created_at", 0), reverse=True)[:limit]

        links_created = 0
        pairs_checked = 0

        for i, mem in enumerate(memories):
            mid = mem.get("id", "")
            if not mid:
                continue
            content = mem.get("content", "")
            if not content or len(content) < 20:
                continue

            # Find semantically similar memories
            similar = self._client.search(
                workspace_id,
                content,
                limit=5,
                semantic=True,
                memory_type="",
                tier="",
            )
            for match in similar:
                match_id = match.get("entity_id", "")
                if not match_id or match_id == mid:
                    continue

                pairs_checked += 1
                # Check if already linked
                if self._already_linked(mid, match_id, workspace_id=workspace_id):
                    continue

                score = match.get("score", 0.0)
                if score >= similarity_threshold:
                    try:
                        self._client._call(
                            "create_edge",
                            [
                                workspace_id,
                                mid,
                                match_id,
                                "related_to",
                                score,
                                "INFERRED",
                                "{}",
                                "",
                            ],
                        )
                        links_created += 1
                    except RuntimeError:
                        continue

        return {"links_created": links_created, "pairs_checked": pairs_checked}



    def suggest_connections(
        self,
        workspace_id: str = "default",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find unconnected node pairs that should probably be linked.

        Uses a heuristic: find nodes with high centrality that share
        common neighbours but aren't directly connected.

        Args:
            workspace_id: Target workspace.
            limit: Max nodes to analyse.

        Returns:
            List of suggestion dicts with ``source_id``, ``target_id``,
            ``source_label``, ``target_label``, ``common_neighbours``.
        """
        suggestions: list[dict[str, Any]] = []

        # Get all edges in the workspace
        edges = self._client._query(
            "kg_edge",
            workspace_id=workspace_id,
            filter_dict={},
        )
        nodes = self._client._query(
            "kg_node",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if not nodes or len(nodes) < 2:
            return suggestions

        # Build adjacency map
        adj: dict[str, set[str]] = {}
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            adj.setdefault(src, set()).add(tgt)
            adj.setdefault(tgt, set()).add(src)

        # For each pair of nodes, check shared neighbours
        node_ids = [n.get("id", "") for n in nodes if n.get("id")]
        node_ids = node_ids[:limit]

        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                n1, n2 = node_ids[i], node_ids[j]

                # Skip if already connected
                if n2 in adj.get(n1, set()) or n1 in adj.get(n2, set()):
                    continue

                # Find common neighbours
                n1_neighbours = adj.get(n1, set())
                n2_neighbours = adj.get(n2, set())
                common = n1_neighbours & n2_neighbours

                if len(common) >= 1:  # Shared context suggests a link
                    s1 = self._node_label(n1, nodes)
                    s2 = self._node_label(n2, nodes)
                    suggestions.append(
                        {
                            "source_id": n1,
                            "target_id": n2,
                            "source_label": s1,
                            "target_label": s2,
                            "common_neighbours": list(common)[:5],
                            "common_count": len(common),
                        }
                    )

        suggestions.sort(key=lambda s: s["common_count"], reverse=True)
        return suggestions



    def lint_workspace(
        self,
        workspace_id: str = "default",
        *,
        check_orphans: bool = True,
        check_missing_crossrefs: bool = True,
        check_contradictions: bool = False,
        check_note_orphans: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Health-check the workspace wiki and report issues.

        Scans for:
        - **Orphan nodes** — KG nodes with zero edges (no connections to
          anything). These are candidates for cleanup or linking.
        - **Missing cross-references** — notes/memories whose content
          mentions a KG node label but have no edge to that node.
        - **Note orphans** — notes whose content mentions no known KG
          entities and have no KG edges. Entirely disconnected from the KG.
        - **Contradictions** — (requires LLM) pairs of semantically
          similar memories that express conflicting claims.

        Args:
            workspace_id: Target workspace.
            check_orphans: Find KG nodes with no edges.
            check_missing_crossrefs: Find content that mentions but
                doesn't link to existing KG nodes.
            check_contradictions: Use LLM to find conflicting claims
                between semantically similar memories (slower).
            check_note_orphans: Find notes entirely disconnected from
                the knowledge graph.
            limit: Max items to scan.

        Returns:
            Dict with ``orphans``, ``missing_crossrefs``,
            ``note_orphans``, ``contradictions`` lists and a summary.
        """
        result: dict[str, Any] = {
            "orphans": [],
            "missing_crossrefs": [],
            "note_orphans": [],
            "contradictions": [],
            "summary": {},
        }

        # ── Orphan detection ──
        if check_orphans:
            result["orphans"] = self._find_orphan_nodes(workspace_id)

        # ── Missing cross-references ──
        if check_missing_crossrefs:
            result["missing_crossrefs"] = self._find_missing_crossrefs(
                workspace_id,
                limit,
            )

        # ── Note orphan detection ──
        if check_note_orphans:
            result["note_orphans"] = self._find_note_orphans(
                workspace_id,
                limit,
            )

        # ── Contradiction detection ──
        if check_contradictions:
            result["contradictions"] = self._find_contradictions(
                workspace_id,
                limit,
            )
            # Auto-create notes for any contradictions found
            if result["contradictions"]:
                self._create_contradiction_notes(
                    workspace_id,
                    result["contradictions"],
                )

        result["summary"] = {
            "orphan_count": len(result["orphans"]),
            "missing_crossref_count": len(result["missing_crossrefs"]),
            "note_orphan_count": len(result["note_orphans"]),
            "contradiction_count": len(result["contradictions"]),
            "total_issues": (
                len(result["orphans"])
                + len(result["missing_crossrefs"])
                + len(result["note_orphans"])
                + len(result["contradictions"])
            ),
        }

        self._log_activity(
            workspace_id,
            "lint",
            f"{result['summary']['total_issues']} issues found "
            f"({result['summary']['orphan_count']} orphans, "
            f"{result['summary']['missing_crossref_count']} missing crossrefs, "
            f"{result['summary']['note_orphan_count']} note orphans, "
            f"{result['summary']['contradiction_count']} contradictions)",
        )
        return result

