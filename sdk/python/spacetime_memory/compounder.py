"""Knowledge compounder — turns interactions into persistent knowledge.

Implements the "LLM Wiki" pattern from Karpathy: every query, store, and
synthesis can generate new wiki pages, update entity summaries, and grow
the knowledge base compoundingly, rather than each interaction being a
stateless query against raw memories.

Usage::

    client = Client(...)
    cp = Compounder(client)

    # Persist a search synthesis as a wiki page
    result = cp.store_answer(
        query="What's the relationship between neural nets and evolution?",
        answer="Both are optimization processes...",
        source_memory_ids=["mem_123", "mem_456"],
    )

    # Find potential links between unconnected entities
    links = cp.suggest_connections(workspace_id="ws1")

    # Auto-cross-link related memories
    stats = cp.cross_link(workspace_id="ws1")
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .llm import LLMClient

logger = logging.getLogger(__name__)


class Compounder:
    """High-level operations that make knowledge compound across interactions.

    All methods degrade gracefully when the LLM is not configured — they
    return empty/``None`` results rather than raising errors.
    """

    def __init__(
        self,
        client: Any,  # Client — forward ref to avoid circular import
        llm: LLMClient | None = None,
    ) -> None:
        self._client = client
        self._llm = llm or LLMClient()

    # ------------------------------------------------------------------
    # store_answer — persist an LLM-generated answer as a wiki page
    # ------------------------------------------------------------------

    def store_answer(
        self,
        query: str,
        answer: str,
        workspace_id: str = "default",
        source_memory_ids: list[str] | None = None,
        title: str | None = None,
        embed: bool = True,
    ) -> dict[str, Any]:
        """Persist a synthesized answer as a note + KG nodes.

        Steps:
        1. Creates a note with the answer text
        2. Extracts entities from the answer (via LLM or regex fallback)
        3. Creates KG nodes for each entity
        4. Links note to source memories via backlinks
        5. Updates the workspace index note

        Args:
            query: The question that prompted the answer.
            answer: The synthesized answer text.
            workspace_id: Target workspace.
            source_memory_ids: Optional list of memory/node IDs that
                informed this answer.
            title: Optional note title (auto-generated if omitted).
            embed: Whether to embed the note for semantic search.

        Returns:
            Dict with ``note``, ``entities``, and ``links`` keys, or
            empty dict on failure.
        """
        if not answer.strip():
            return {}

        generated_title = title or self._generate_title(query, answer)
        content = self._format_answer_page(query, answer, source_memory_ids)

        # 1. Create the note
        note = self._client.create_note(
            workspace_id=workspace_id,
            title=generated_title,
            content=content,
            embed=embed,
        )

        result: dict[str, Any] = {"note": note, "entities": [], "links": []}

        # 2. Extract entities and create KG nodes
        entities = self._llm.extract_entities_llm(answer)
        if entities:
            for ent in entities:
                try:
                    node = self._client.create_node(
                        workspace_id=workspace_id,
                        label=ent.get("name", "?"),
                        node_type=ent.get("entity_type", "concept"),
                        summary=ent.get("description", ""),
                        source_memory_id=note.get("id", ""),
                    )
                    result["entities"].append(node)
                except RuntimeError:
                    continue  # best-effort

        # 3. Link to source memories
        if source_memory_ids:
            note_id = note.get("id", "")
            for mid in source_memory_ids:
                try:
                    self._client._call("link_entities", [note_id, mid, "informed_by"])
                    result["links"].append(mid)
                except RuntimeError:
                    continue

        # 4. Update workspace index
        self._update_index(workspace_id, generated_title, note)

        logger.info(
            "Stored answer note '%s' (%d entities, %d links)",
            generated_title, len(result["entities"]), len(result["links"]),
        )
        return result

    # ------------------------------------------------------------------
    # cross_link — find and connect related but unlinked memories
    # ------------------------------------------------------------------

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

        memories = sorted(
            memories, key=lambda r: r.get("created_at", 0), reverse=True
        )[:limit]

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
                workspace_id, content, limit=5, semantic=True,
                memory_type="", tier="",
            )
            for match in similar:
                match_id = match.get("entity_id", "")
                if not match_id or match_id == mid:
                    continue

                pairs_checked += 1
                # Check if already linked
                if self._already_linked(mid, match_id):
                    continue

                score = match.get("score", 0.0)
                if score >= similarity_threshold:
                    try:
                        self._client._call(
                            "link_entities", [mid, match_id, "related_to"]
                        )
                        links_created += 1
                    except RuntimeError:
                        continue

        return {"links_created": links_created, "pairs_checked": pairs_checked}

    # ------------------------------------------------------------------
    # suggest_connections — use KG to suggest new links between nodes
    # ------------------------------------------------------------------

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
                    suggestions.append({
                        "source_id": n1,
                        "target_id": n2,
                        "source_label": s1,
                        "target_label": s2,
                        "common_neighbours": list(common)[:5],
                        "common_count": len(common),
                    })

        suggestions.sort(key=lambda s: s["common_count"], reverse=True)
        return suggestions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_title(self, query: str, answer: str) -> str:
        """Generate a concise title from the query or first line of answer."""
        # Use query if it's short enough
        if len(query) < 80:
            return query.strip().rstrip("?.")
        # Otherwise use first line of answer
        first_line = answer.strip().split("\n")[0]
        return first_line[:80].rstrip("?.")

    def _format_answer_page(
        self,
        query: str,
        answer: str,
        source_ids: list[str] | None = None,
    ) -> str:
        """Format the answer as a structured markdown page."""
        parts = [
            f"## Question\n\n{query}\n\n",
            f"## Synthesis\n\n{answer}\n\n",
        ]
        if source_ids:
            refs = "\n".join(f"- `{sid}`" for sid in source_ids)
            parts.append(f"## Sources\n\n{refs}\n")
        parts.append("---\n*Auto-generated by Compounder*")
        return "\n".join(parts)

    def _update_index(
        self,
        workspace_id: str,
        title: str,
        note: dict[str, Any],
    ) -> None:
        """Append an entry to the workspace index note (or create one)."""
        index_title = "_index"
        existing = self._client._query(
            "note",
            workspace_id=workspace_id,
            filter_dict={"title": index_title},
        )
        note_id = note.get("id", "")
        link = f"- [{title}]({note_id})  \n"

        if existing:
            # Append to existing index
            idx_note = existing[0]
            new_content = idx_note.get("content", "") + link
            try:
                self._client.update_note(
                    note_id=idx_note.get("id", ""),
                    title=index_title,
                    content=new_content,
                    embed=False,
                )
            except RuntimeError:
                pass
        else:
            # Create index note
            header = "# Workspace Index\n\nAuto-generated index of synthesis pages.\n\n"
            try:
                self._client.create_note(
                    workspace_id=workspace_id,
                    title=index_title,
                    content=header + link,
                    embed=False,
                )
            except RuntimeError:
                pass

    def _already_linked(self, id1: str, id2: str) -> bool:
        """Check whether two entities are already linked in the KG."""
        edges = self._client._query(
            "kg_edge",
            filter_dict={},
        )
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if (src == id1 and tgt == id2) or (src == id2 and tgt == id1):
                return True
        return False

    def _node_label(self, node_id: str, nodes: list[dict]) -> str:
        """Look up the label for a KG node by ID."""
        for n in nodes:
            if n.get("id") == node_id:
                return n.get("label", node_id)
        return node_id[:12]
