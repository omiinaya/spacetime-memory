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

import datetime
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

        # 5. Ripple update — update existing entity summaries with new info
        if entities:
            for ent in entities:
                self._ripple_update_entity(
                    workspace_id, ent.get("name", ""),
                    answer, note.get("id", ""),
                )

        # 6. Log the activity
        self._log_activity(
            workspace_id, "store_answer",
            f"'{generated_title}' ({len(result['entities'])} entities, "
            f"{len(result['links'])} links)",
        )

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

    # ------------------------------------------------------------------
    # Ripple update — update entity summary with new information
    # ------------------------------------------------------------------

    def _ripple_update_entity(
        self,
        workspace_id: str,
        entity_name: str,
        new_information: str,
        source_note_id: str,
    ) -> None:
        """Find an existing KG node for *entity_name* and update its
        summary to incorporate *new_information* (if LLM available).

        Gracefully degrades when the LLM is not configured — simply
        skips the update.
        """
        if not entity_name.strip():
            return
        if not self._llm.available:
            return

        # Find the node
        nodes = self._client._query(
            "kg_node",
            workspace_id=workspace_id,
            filter_dict={"label": entity_name},
        )
        if not nodes:
            return

        node = nodes[-1]
        node_id = node.get("id", "")
        existing_summary = node.get("summary", "")

        # Use LLM to merge the new info into existing summary
        if existing_summary:
            prompt = (
                f"Existing summary: {existing_summary}\n\n"
                f"New information: {new_information[:1000]}\n\n"
                "Merge the new information into a concise updated summary "
                f"for '{entity_name}'. Keep it to 2-3 sentences."
                " Return ONLY the updated summary text, no explanation."
            )
        else:
            prompt = (
                f"Summarize this information about '{entity_name}' in "
                f"2-3 sentences:\n\n{new_information[:1000]}"
            )

        new_summary = self._llm.summarize(prompt)
        if new_summary and new_summary != existing_summary:
            try:
                self._client._call("update_node", [
                    node_id, entity_name,
                    node.get("node_type", "concept"),
                    new_summary, "{}", source_note_id,
                ])
                logger.info(
                    "Ripple-updated node '%s' (%s) with new summary",
                    entity_name, node_id[:12],
                )
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Chronological log (_log note)
    # ------------------------------------------------------------------

    def _log_activity(
        self,
        workspace_id: str,
        event_type: str,
        detail: str,
    ) -> None:
        """Append a timestamped entry to the workspace chronological log.

        Creates a ``_log`` note if one doesn't exist.  Each entry uses a
        parseable prefix: ``## [YYYY-MM-DD] event_type | detail`` so the
        log is searchable with simple tools like ``grep``.
        """
        log_title = "_log"
        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        entry = f"## [{now}] {event_type} | {detail}\n"

        existing = self._client._query(
            "note",
            workspace_id=workspace_id,
            filter_dict={"title": log_title},
        )
        if existing:
            idx_note = existing[0]
            new_content = idx_note.get("content", "") + entry
            try:
                self._client.update_note(
                    note_id=idx_note.get("id", ""),
                    title=log_title,
                    content=new_content,
                    embed=False,
                )
            except RuntimeError:
                pass
        else:
            header = "# Workspace Log\n\nChronological record of compounder activity.\n\n"
            try:
                self._client.create_note(
                    workspace_id=workspace_id,
                    title=log_title,
                    content=header + entry,
                    embed=False,
                )
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # lint_workspace — health-check the workspace wiki
    # ------------------------------------------------------------------

    def lint_workspace(
        self,
        workspace_id: str = "default",
        *,
        check_orphans: bool = True,
        check_missing_crossrefs: bool = True,
        check_contradictions: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Health-check the workspace wiki and report issues.

        Scans for:
        - **Orphan nodes** — KG nodes with zero edges (no connections to
          anything). These are candidates for cleanup or linking.
        - **Missing cross-references** — notes/memories whose content
          mentions a KG node label but have no edge to that node.
        - **Contradictions** — (requires LLM) pairs of semantically
          similar memories that express conflicting claims.

        Args:
            workspace_id: Target workspace.
            check_orphans: Find nodes with no edges.
            check_missing_crossrefs: Find content that mentions but
                doesn't link to existing KG nodes.
            check_contradictions: Use LLM to find conflicting claims
                between semantically similar memories (slower).
            limit: Max items to scan.

        Returns:
            Dict with ``orphans``, ``missing_crossrefs``,
            ``contradictions`` lists and a summary.
        """
        result: dict[str, Any] = {
            "orphans": [],
            "missing_crossrefs": [],
            "contradictions": [],
            "summary": {},
        }

        # ── Orphan detection ──
        if check_orphans:
            result["orphans"] = self._find_orphan_nodes(workspace_id)

        # ── Missing cross-references ──
        if check_missing_crossrefs:
            result["missing_crossrefs"] = self._find_missing_crossrefs(
                workspace_id, limit,
            )

        # ── Contradiction detection ──
        if check_contradictions:
            result["contradictions"] = self._find_contradictions(
                workspace_id, limit,
            )

        result["summary"] = {
            "orphan_count": len(result["orphans"]),
            "missing_crossref_count": len(result["missing_crossrefs"]),
            "contradiction_count": len(result["contradictions"]),
            "total_issues": (
                len(result["orphans"])
                + len(result["missing_crossrefs"])
                + len(result["contradictions"])
            ),
        }

        self._log_activity(
            workspace_id, "lint",
            f"{result['summary']['total_issues']} issues found "
            f"({result['summary']['orphan_count']} orphans, "
            f"{result['summary']['missing_crossref_count']} missing crossrefs, "
            f"{result['summary']['contradiction_count']} contradictions)",
        )
        return result

    def _find_orphan_nodes(self, workspace_id: str) -> list[dict[str, Any]]:
        """Find KG nodes with no edges to any other node."""
        nodes = self._client._query(
            "kg_node", workspace_id=workspace_id, filter_dict={},
        )
        edges = self._client._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={},
        )
        connected: set[str] = set()
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                connected.add(src)
            if tgt:
                connected.add(tgt)

        orphans = []
        for n in nodes:
            nid = n.get("id", "")
            if nid and nid not in connected:
                orphans.append({
                    "id": nid,
                    "label": n.get("label", nid[:12]),
                    "node_type": n.get("node_type", "unknown"),
                })
        return orphans

    def _find_missing_crossrefs(
        self, workspace_id: str, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Find notes/memories whose content mentions a KG node label
        but has no edge to that node."""
        # Get all KG nodes and their labels
        nodes = self._client._query(
            "kg_node", workspace_id=workspace_id, filter_dict={},
        )
        # Get all edges to know what's already connected
        edges = self._client._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={},
        )
        linked_labels: set[str] = set()
        # Also track which memory IDs are linked to which nodes
        mem_to_node: dict[str, set[str]] = {}
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                mem_to_node.setdefault(src, set()).add(tgt)
            if tgt:
                mem_to_node.setdefault(tgt, set()).add(src)

        # Build a map of labels → node IDs
        label_map: dict[str, str] = {}
        for n in nodes:
            label = (n.get("label", "") or "").lower().strip()
            if label:
                label_map[label] = n.get("id", "")

        if not label_map:
            return []

        # Scan memories and notes
        missing: list[dict[str, Any]] = []
        memories = self._client._query(
            "memory", workspace_id=workspace_id, filter_dict={},
        )[:limit]
        notes = self._client._query(
            "note", workspace_id=workspace_id, filter_dict={},
        )[:limit]

        for mem in memories:
            content = (mem.get("content", "") or "").lower()
            mid = mem.get("id", "")
            if not content or not mid:
                continue
            for label_lower, node_id in label_map.items():
                if label_lower in content:
                    # Check if already linked
                    if node_id not in mem_to_node.get(mid, set()):
                        missing.append({
                            "entity_id": mid,
                            "entity_type": "memory",
                            "mentioned_label": label_lower,
                            "target_node_id": node_id,
                        })

        for note in notes:
            content = (note.get("content", "") or "").lower()
            nid = note.get("id", "")
            if not content or not nid:
                continue
            for label_lower, node_id in label_map.items():
                if label_lower in content:
                    if node_id not in mem_to_node.get(nid, set()):
                        missing.append({
                            "entity_id": nid,
                            "entity_type": "note",
                            "mentioned_label": label_lower,
                            "target_node_id": node_id,
                        })

        return missing

    def _find_contradictions(
        self, workspace_id: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Use LLM to find contradictory claims between semantically
        similar memories.

        Works in pairs: groups memories by semantic similarity, then
        asks the LLM whether each pair contains contradictory claims.

        Returns:
            List of contradiction dicts with ``id_a``, ``id_b``,
            ``content_a``, ``content_b``, ``explanation``.
        """
        if not self._llm.available:
            return []

        memories = self._client._query(
            "memory", workspace_id=workspace_id, filter_dict={},
        )
        if len(memories) < 2:
            return []

        # Take the most recent N
        memories = sorted(
            memories, key=lambda r: r.get("created_at", 0), reverse=True
        )[:limit]

        contradictions: list[dict[str, Any]] = []
        checked = 0

        for i in range(min(len(memories), 10)):  # Limit pairs to avoid LLM flood
            for j in range(i + 1, min(len(memories), i + 3)):  # Adjacent pairs
                mem_a = memories[i]
                mem_b = memories[j]
                content_a = mem_a.get("content", "")
                content_b = mem_b.get("content", "")
                if not content_a or not content_b:
                    continue

                checked += 1
                prompt = (
                    f"Memory A: {content_a[:500]}\n\n"
                    f"Memory B: {content_b[:500]}\n\n"
                    "Do these two statements contain contradictory claims? "
                    "Reply with a JSON object: "
                    '{"is_contradiction": bool, "explanation": str}. '
                    "Return ONLY valid JSON, no markdown."
                )
                result = self._llm.chat(
                    [{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=256,
                )
                if not result:
                    continue
                try:
                    data = json.loads(result)
                    if data.get("is_contradiction"):
                        contradictions.append({
                            "id_a": mem_a.get("id", ""),
                            "id_b": mem_b.get("id", ""),
                            "content_a": content_a[:200],
                            "content_b": content_b[:200],
                            "explanation": data.get("explanation", ""),
                        })
                except (json.JSONDecodeError, TypeError):
                    continue

        self._log_activity(
            workspace_id, "contradiction_check",
            f"Checked {checked} pairs, found {len(contradictions)} contradictions",
        )
        return contradictions
