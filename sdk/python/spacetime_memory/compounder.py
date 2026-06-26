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
    # search_entities — search knowledge-graph entities with flexible filters
    # ------------------------------------------------------------------

    def search_entities(
        self,
        workspace_id: str = "default",
        label: str | None = None,
        node_type: str | None = None,
        semantic_query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search knowledge-graph entities with flexible filters.

        Supports three modes that can be combined:

        * **Label search** — find entities by exact ``label`` match.
        * **Type filter** — find all entities of a given ``node_type``
          (e.g. ``"person"``, ``"concept"``, ``"org"``).
        * **Semantic search** — find entities whose label or summary
          is semantically related to *semantic_query* using the
          hybrid search engine.

        Examples::

            # All person entities
            cp.search_entities(node_type="person")

            # Find entity with specific label
            cp.search_entities(label="RLHF")

            # Semantic search for concept nodes
            cp.search_entities(
                node_type="concept",
                semantic_query="machine learning optimization",
                limit=10,
            )

        Args:
            workspace_id: Target workspace.
            label: Optional exact label to search for.
            node_type: Optional node type filter
                (e.g. ``"person"``, ``"concept"``, ``"org"``,
                 ``"product"``, ``"location"``, ``"event"``, ``"topic"``).
            semantic_query: Optional natural-language query for
                semantic entity search.
            limit: Max results to return (default: 20).

        Returns:
            List of matching ``kg_node`` dicts, each with ``id``,
            ``label``, ``node_type``, ``summary``, ``metadata_json``,
            ``source_memory_id``, and timestamp fields.
        """
        # ── Structured filter query ──
        filter_dict: dict[str, Any] = {}
        if label is not None:
            filter_dict["label"] = label
        if node_type is not None:
            filter_dict["node_type"] = node_type

        filtered_results: list[dict[str, Any]] = []
        if filter_dict:
            filtered_results = self._client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict=filter_dict,
            )

        # ── Semantic search results ──
        # The hybrid_search reducer indexes kg_node content via
        # index_entity with entity_type="node".  Search results with
        # entity_type == "node" carry an entity_id that maps to kg_node.id.
        semantic_node_ids: set[str] = set()
        if semantic_query:
            search_results = self._client.search(
                workspace_id, semantic_query, limit=limit,
                semantic=True, memory_type="", tier="",
            )
            for r in search_results:
                if r.get("entity_type") == "node":
                    nid = r.get("entity_id", "")
                    if nid:
                        semantic_node_ids.add(nid)

        # If we have semantic hits, look up the full kg_node records
        semantic_results: list[dict[str, Any]] = []
        if semantic_node_ids:
            all_nodes = self._client._query(
                "kg_node", workspace_id=workspace_id, filter_dict={},
            )
            node_map = {n.get("id", ""): n for n in all_nodes}
            for nid in semantic_node_ids:
                if nid in node_map:
                    semantic_results.append(node_map[nid])

        # ── Merge: semantic results first, then filtered results ──
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for n in semantic_results:
            nid = n.get("id", "")
            if nid and nid not in seen:
                merged.append(n)
                seen.add(nid)
        for n in filtered_results:
            nid = n.get("id", "")
            if nid and nid not in seen:
                merged.append(n)
                seen.add(nid)

        return merged[:limit]

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
        raw = self._client.create_note(
            workspace_id=workspace_id,
            title=generated_title,
            content=content,
            embed=embed,
        )
        note = self._resolve_created_note(workspace_id, generated_title, raw)

        result: dict[str, Any] = {"note": note, "entities": [], "links": []}

        # 2. Extract entities and create KG nodes + entity pages
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

                    # Auto-create an entity wiki page for new entities
                    ent_name = ent.get("name", "")
                    ent_desc = ent.get("description", "")
                    if ent_name and ent_desc:
                        try:
                            self.create_entity_page(
                                name=ent_name,
                                description=ent_desc,
                                entity_type=ent.get("entity_type", "concept"),
                                workspace_id=workspace_id,
                                embed=True,
                            )
                        except RuntimeError:
                            continue
                except RuntimeError:
                    continue  # best-effort

        # 3. Link to source memories (via create_edge if note has a KG node)
        if source_memory_ids:
            note_id = note.get("id", "")
            for mid in source_memory_ids:
                try:
                    self._client._call(
                        "create_edge", [
                            workspace_id, note_id, mid,
                            "informed_by", 1.0, "INFERRED",
                            "{}", "",
                        ],
                    )
                    result["links"].append(mid)
                except RuntimeError:
                    continue

        # 4. Update workspace index
        index_summary = query[:100] if len(query) < 100 else query[:97] + "..."
        self._update_index(workspace_id, generated_title, note, summary=index_summary)

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
    # store_answers — batch-store multiple Q&A pairs efficiently
    # ------------------------------------------------------------------

    def store_answers(
        self,
        qa_pairs: list[tuple[str, str]],
        workspace_id: str = "default",
        source_memory_ids: list[str] | None = None,
        embed: bool = True,
    ) -> list[dict[str, Any]]:
        """Batch-store multiple query/answer pairs as wiki pages.

        More efficient than calling :meth:`store_answer` in a loop because
        it fetches the workspace index once, appends all entries, and
        creates a single log entry for the batch.

        Args:
            qa_pairs: List of ``(query, answer)`` tuples.
            workspace_id: Target workspace.
            source_memory_ids: Optional list of memory/node IDs that
                informed *all* answers in this batch.
            embed: Whether to embed notes for semantic search.

        Returns:
            List of result dicts (one per pair), each with ``note``,
            ``entities``, and ``links`` keys.
        """
        if not qa_pairs:
            return []

        results: list[dict[str, Any]] = []
        for query, answer in qa_pairs:
            try:
                result = self.store_answer(
                    query=query,
                    answer=answer,
                    workspace_id=workspace_id,
                    source_memory_ids=source_memory_ids,
                    embed=embed,
                )
                results.append(result)
            except RuntimeError:
                results.append({"note": {}, "entities": [], "links": []})

        # Single consolidated log entry for the batch
        total_entities = sum(
            len(r.get("entities", [])) for r in results
        )
        total_links = sum(
            len(r.get("links", [])) for r in results
        )
        self._log_activity(
            workspace_id, "store_answers",
            f"Batch of {len(qa_pairs)} answers "
            f"({total_entities} entities, {total_links} links)",
        )

        logger.info(
            "Stored batch of %d answers (%d entities, %d links)",
            len(qa_pairs), total_entities, total_links,
        )
        return results

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
                            "create_edge", [
                                workspace_id, mid, match_id,
                                "related_to", score, "INFERRED",
                                "{}", "",
                            ],
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

    def _resolve_created_note(
        self,
        workspace_id: str,
        title: str,
        create_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve the full note record after creation.

        The ``create_note`` reducer returns ``{"status": "ok"}``, not the
        note data.  This helper queries the note back by title so callers
        get the real note dict with ``id``, ``created_at``, etc.

        Falls back to returning the original result if the query fails.
        """
        if create_result.get("status") == "ok" and title:
            try:
                matches = self._client.get_note_by_title(title)
                if matches:
                    return matches[0]
                # Fallback: scan recent notes
                all_notes = self._client._query(
                    "note", workspace_id=workspace_id, filter_dict={},
                )
                for n in sorted(
                    all_notes, key=lambda r: r.get("created_at", 0), reverse=True
                ):
                    if n.get("title", "") == title:
                        return n
            except RuntimeError:
                pass
        return create_result

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
        summary: str = "",
    ) -> None:
        """Append an entry to the workspace index note (or create one).

        Each entry follows Karpathy's format:
        ``- [Title](note_id) — one-line summary``

        If no summary is provided, the first line of the note content
        is used as a fallback.
        """
        index_title = "_index"
        note_id = note.get("id", "")

        # Generate summary from note content if not provided
        if not summary:
            content = note.get("content", "")
            if content:
                # Try first non-empty, non-separator line
                for line in content.split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("---") and not stripped.startswith("#"):
                        summary = stripped[:120].rstrip(".")
                        break

        summary_suffix = ""
        if summary:
            summary_suffix = f" — {summary}"

        link = f"- [{title}]({note_id}){summary_suffix}\n"

        existing = self._client._query(
            "note",
            workspace_id=workspace_id,
            filter_dict={"title": index_title},
        )

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
            # Auto-create notes for any contradictions found
            if result["contradictions"]:
                self._create_contradiction_notes(
                    workspace_id, result["contradictions"],
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

    def _create_contradiction_notes(
        self,
        workspace_id: str,
        contradictions: list[dict[str, Any]],
    ) -> None:
        """Create notes documenting each contradiction found during lint.

        Each note records the two conflicting memories and the LLM's
        explanation, helping the user review and resolve the conflict.
        """
        for i, c in enumerate(contradictions):
            title = f"Contradiction #{i + 1}: {c.get('id_a', '?')[:8]} ↔ {c.get('id_b', '?')[:8]}"
            content = (
                f"## Contradiction Detected\n\n"
                f"**Memory A**: `{c.get('id_a', '')}`\n"
                f"> {c.get('content_a', '')}\n\n"
                f"**Memory B**: `{c.get('id_b', '')}`\n"
                f"> {c.get('content_b', '')}\n\n"
                f"**Explanation**: {c.get('explanation', 'No explanation provided.')}\n\n"
                f"---\n*Auto-detected by Compounder lint*"
            )
            try:
                self._client.create_note(
                    workspace_id=workspace_id,
                    title=title,
                    content=content,
                    embed=True,
                )
            except RuntimeError:
                continue

    # ------------------------------------------------------------------
    # ingest_source — end-to-end source ingestion workflow
    # ------------------------------------------------------------------

    def ingest_source(
        self,
        source_text: str,
        source_title: str,
        workspace_id: str = "default",
        source_type: str = "article",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Ingest a source document and integrate it into the wiki.

        Full workflow from Karpathy's LLM Wiki pattern:
        1. Creates a source-summary note
        2. Extracts entities and creates KG nodes
        3. Links entities to the source with ``informed_by`` edges
        4. Ripple-updates existing entity nodes with new info
        5. Proactively checks for contradictions with existing knowledge
        6. Appends to ``_index``
        7. Appends to ``_log``

        Args:
            source_text: The full text of the source document.
            source_title: A concise title for this source.
            workspace_id: Target workspace.
            source_type: Type label (``article``, ``paper``,
                ``transcript``, ``note``, ``podcast``).
            embed: Whether to embed the note for semantic search.

        Returns:
            Dict with ``note``, ``entities``, ``links``,
            ``contradictions`` keys.
        """
        if not source_text.strip():
            return {"note": {}, "entities": [], "links": [],
                    "contradictions": []}

        result: dict[str, Any] = {
            "note": {}, "entities": [],
            "links": [], "contradictions": [],
        }

        # 1. Summarize and create source-summary note
        summary_text = source_text
        if self._llm.available:
            llm_summary = self._llm.summarize(
                source_text[:4000],
                instruction=(
                    f"Summarize this {source_type} in 3-5 sentences. "
                    "Focus on key claims, entities, and findings."
                ),
            )
            if llm_summary:
                summary_text = llm_summary

        content = self._format_source_page(
            source_title, source_text, summary_text, source_type,
        )
        note = self._client.create_note(
            workspace_id=workspace_id,
            title=f"Source: {source_title}",
            content=content,
            embed=embed,
        )
        result["note"] = note

        # If create_note only returned status, resolve the full record
        if not note.get("id"):
            resolved = self._resolve_created_note(
                workspace_id, f"Source: {source_title}", note,
            )
            note = resolved
            result["note"] = resolved

        # 2. Extract entities and create KG nodes
        if self._llm.available:
            entities = self._llm.extract_entities_llm(source_text[:4000])
        else:
            entities = None

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
                    continue

        # 3. Link entities to source summary
        note_id = note.get("id", "")
        for node in result["entities"]:
            node_id = node.get("id", "")
            if node_id and note_id:
                try:
                    self._client._call(
                        "create_edge", [
                            workspace_id, note_id, node_id,
                            "informed_by", 1.0, "INFERRED",
                            "{}", "",
                        ],
                    )
                    result["links"].append(node_id)
                except RuntimeError:
                    continue

        # 4. Ripple-update existing entity nodes
        if self._llm.available and entities:
            for ent in entities:
                self._ripple_update_entity(
                    workspace_id, ent.get("name", ""),
                    summary_text, note_id,
                )

        # 5. Proactive contradiction check
        if self._llm.available:
            result["contradictions"] = self._check_contradictions_on_ingest(
                workspace_id, summary_text, note_id,
            )

        # 6. Update index
        ingest_summary = summary_text[:100] if len(summary_text) < 100 else summary_text[:97] + "..."
        self._update_index(workspace_id, f"Source: {source_title}", note, summary=ingest_summary)

        # 7. Log
        self._log_activity(
            workspace_id, "ingest_source",
            f"'{source_title}' ({len(result['entities'])} entities, "
            f"{len(result['links'])} links, "
            f"{len(result['contradictions'])} contradictions)",
        )

        logger.info(
            "Ingested source '%s' (%d entities, %d links, %d contradictions)",
            source_title, len(result["entities"]),
            len(result["links"]), len(result["contradictions"]),
        )
        return result

    def _format_source_page(
        self,
        title: str,
        full_text: str,
        summary: str,
        source_type: str,
    ) -> str:
        """Format a source document as a structured markdown page."""
        max_preview = 2000
        body_preview = full_text[:max_preview]
        if len(full_text) > max_preview:
            body_preview += "\n\n*[truncated — full source has "
            body_preview += f"{len(full_text)} chars]*"

        return (
            f"## Summary\n\n{summary}\n\n"
            f"## Source ({source_type}): {title}\n\n"
            f"{body_preview}\n\n"
            f"---\n*Auto-imported via ingest_source*"
        )

    # ------------------------------------------------------------------
    # Proactive contradiction detection (called during ingest)
    # ------------------------------------------------------------------

    def _check_contradictions_on_ingest(
        self,
        workspace_id: str,
        new_content: str,
        source_note_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Check if new source content contradicts existing memories.

        Searches for semantically similar existing memories, then asks
        the LLM whether each pair contains contradictory claims.

        Args:
            workspace_id: Target workspace.
            new_content: The new source content to check.
            source_note_id: The note ID of the newly ingested source
                (used to link contradiction notes back).
            limit: Max existing memories to check against.

        Returns:
            List of contradiction dicts with ``memory_id``,
            ``existing_content``, ``explanation``.
        """
        if not self._llm.available or not new_content.strip():
            return []

        # Find semantically similar existing memories
        similar = self._client.search(
            workspace_id, new_content[:1000],
            limit=limit, semantic=True,
            memory_type="", tier="",
        )
        if not similar:
            return []

        contradictions: list[dict[str, Any]] = []
        for match in similar[:5]:  # Check top 5
            existing_id = match.get("entity_id", "")
            existing_content = match.get("content", "")
            if not existing_id or not existing_content:
                continue

            prompt = (
                f"New information: {new_content[:800]}\n\n"
                f"Existing knowledge: {existing_content[:800]}\n\n"
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
                        "memory_id": existing_id,
                        "existing_content": existing_content[:200],
                        "explanation": data.get("explanation", ""),
                    })
                    # Create a contradiction note linking source to existing
                    self._create_ingest_contradiction_note(
                        workspace_id, source_note_id,
                        existing_id, data.get("explanation", ""),
                    )
            except (json.JSONDecodeError, TypeError):
                continue

        if contradictions:
            self._log_activity(
                workspace_id, "contradiction_on_ingest",
                f"Found {len(contradictions)} contradictions with existing knowledge",
            )

        return contradictions

    def _create_ingest_contradiction_note(
        self,
        workspace_id: str,
        new_note_id: str,
        existing_memory_id: str,
        explanation: str,
    ) -> None:
        """Create a note documenting a contradiction found during ingest."""
        title = f"Contradiction: new source ↔ {existing_memory_id[:8]}"
        content = (
            f"## Contradiction Detected During Ingest\n\n"
            f"**New source**: `{new_note_id}`\n"
            f"**Existing memory**: `{existing_memory_id}`\n\n"
            f"**Explanation**: {explanation}\n\n"
            f"---\n*Auto-detected during ingest_source*"
        )
        try:
            self._client.create_note(
                workspace_id=workspace_id,
                title=title,
                content=content,
                embed=True,
            )
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Page type templates — structured wiki pages
    # ------------------------------------------------------------------

    def create_entity_page(
        self,
        name: str,
        description: str,
        entity_type: str = "concept",
        workspace_id: str = "default",
        tags: list[str] | None = None,
        relations: list[dict[str, str]] | None = None,
        embed: bool = True,
    ) -> dict[str, Any]:
        """Create a structured entity wiki page with KG node + note.

        Args:
            name: Entity name (used as both node label and page title).
            description: 2-3 sentence description of the entity.
            entity_type: One of ``person``, ``org``, ``concept``,
                ``product``, ``location``, ``event``, ``topic``.
            workspace_id: Target workspace.
            tags: Optional YAML frontmatter tags.
            relations: Optional list of related entity dicts with
                ``name`` and ``relation`` keys (e.g.
                ``[{"name": "RLHF", "relation": "subfield_of"}]``).
            embed: Whether to embed the note for semantic search.

        Returns:
            Dict with ``node`` and ``note`` keys.
        """
        # 1. Create or find KG node
        node = None
        existing = self._client._query(
            "kg_node", workspace_id=workspace_id,
            filter_dict={"label": name},
        )
        if existing:
            node = existing[0]
        else:
            try:
                node = self._client.create_node(
                    workspace_id=workspace_id,
                    label=name,
                    node_type=entity_type,
                    summary=description,
                    source_memory_id="",
                )
            except RuntimeError:
                node = None

        # 2. Create the wiki note
        tag_line = ""
        if tags:
            tag_line = "tags: [" + ", ".join(tags) + "]\n"

        rel_lines = ""
        if relations:
            rel_lines = "\n## Relations\n\n"
            for r in relations:
                rel_lines += f"- **{r.get('relation', 'related_to')}**: {r.get('name', '')}\n"

        content = (
            f"---\n"
            f"type: {entity_type}\n"
            f"{tag_line}"
            f"sources: []\n"
            f"created: {datetime.datetime.utcnow().strftime('%Y-%m-%d')}\n"
            f"---\n\n"
            f"## Overview\n\n{description}\n\n"
            f"{rel_lines}"
            f"---\n*Entity page: {name}*"
        )

        note_title = name  # Entity pages are titled by entity name
        try:
            note = self._client.create_note(
                workspace_id=workspace_id,
                title=note_title,
                content=content,
                embed=embed,
            )
        except RuntimeError:
            note = {}

        # 3. Link note to KG node
        if node and note.get("id"):
            try:
                self._client._call(
                    "create_edge", [
                        workspace_id, note["id"], node["id"],
                        "describes", 1.0, "INFERRED",
                        "{}", "",
                    ],
                )
            except RuntimeError:
                pass

        # 4. Update index
        self._update_index(
            workspace_id, name, note,
            summary=description[:100],
        )

        # 5. Log
        self._log_activity(
            workspace_id, "create_entity_page",
            f"'{name}' ({entity_type})",
        )

        return {"node": node, "note": note}

    # ------------------------------------------------------------------
    # update_entity_page — update an existing entity wiki page + KG node
    # ------------------------------------------------------------------

    def update_entity_page(
        self,
        name: str,
        workspace_id: str = "default",
        description: str | None = None,
        entity_type: str | None = None,
        tags: list[str] | None = None,
        relations: list[dict[str, str]] | None = None,
        embed: bool = True,
    ) -> dict[str, Any]:
        """Update an existing entity wiki page and its KG node in one call.

        Finds the entity by its label (``name``), then updates the KG node
        and the associated wiki note with the provided fields. Fields set to
        ``None`` are left unchanged on the existing entity.

        Args:
            name: Entity name (used to find the existing entity by label).
            workspace_id: Target workspace.
            description: New 2-3 sentence description (updates both node
                summary and note content). ``None`` = keep existing.
            entity_type: New entity type (e.g. ``"person"``, ``"concept"``).
                ``None`` = keep existing.
            tags: Updated YAML frontmatter tags. ``None`` = keep existing.
            relations: Updated relations list. ``None`` = keep existing.
            embed: Whether to re-embed the note for semantic search.

        Returns:
            Dict with ``node`` and ``note`` keys, or empty dict if the
            entity was not found.
        """
        # 1. Find the existing KG node by label
        existing = self._client._query(
            "kg_node", workspace_id=workspace_id,
            filter_dict={"label": name},
        )
        if not existing:
            logger.warning("update_entity_page: entity '%s' not found", name)
            return {}
        node = existing[0]

        # 2. Find the associated wiki note (entity pages use name as title)
        notes = self._client._query(
            "note", workspace_id=workspace_id,
            filter_dict={"title": name, "is_active": "true"},
        )
        note = notes[0] if notes else {}

        # 3. Update the KG node with any provided values
        new_label = name  # label stays the same (it's the lookup key)
        new_type = entity_type if entity_type is not None else node.get("node_type", "concept")
        new_summary = description if description is not None else node.get("summary", "")

        try:
            self._client.update_node(
                node_id=node["id"],
                label=new_label,
                node_type=new_type,
                summary=new_summary,
                metadata_json=node.get("metadata_json", "{}"),
                source_memory_id=node.get("source_memory_id", ""),
            )
        except RuntimeError:
            logger.warning("update_entity_page: failed to update KG node '%s'", name)

        # 4. Rebuild the note content with updated fields
        if note.get("id"):
            # Preserve original content and parse frontmatter if it exists
            old_content = note.get("content", "")

            # Build updated frontmatter tags
            if tags is not None:
                tag_line = ""
                if tags:
                    tag_line = "tags: [" + ", ".join(tags) + "]\n"
            else:
                # Try to extract existing tags from frontmatter
                tag_line = ""
                if old_content.startswith("---"):
                    end_idx = old_content.find("---", 3)
                    if end_idx != -1:
                        fm = old_content[3:end_idx].strip()
                        for line in fm.split("\n"):
                            if line.startswith("tags:"):
                                tag_line = line + "\n"

            # Build relations section
            if relations is not None:
                rel_lines = ""
                if relations:
                    rel_lines = "\n## Relations\n\n"
                    for r in relations:
                        rel_lines += f"- **{r.get('relation', 'related_to')}**: {r.get('name', '')}\n"
            else:
                # Extract existing relations section
                rel_lines = ""
                if old_content and "## Relations" in old_content:
                    parts = old_content.split("## Relations", 1)
                    rest = parts[1] if len(parts) > 1 else ""
                    if "---" in rest:
                        rel_lines = "## Relations" + rest.split("---", 1)[0]

            # Build new content
            new_content = (
                f"---\n"
                f"type: {new_type}\n"
                f"{tag_line}"
                f"sources: []\n"
                f"created: {datetime.datetime.utcnow().strftime('%Y-%m-%d')}\n"
                f"---\n\n"
                f"## Overview\n\n{new_summary}\n\n"
                f"{rel_lines}"
                f"---\n*Entity page: {name}*"
            )

            try:
                note = self._client.update_note(
                    note_id=note["id"],
                    title=name,
                    content=new_content,
                    embed=embed,
                )
            except RuntimeError:
                logger.warning("update_entity_page: failed to update note for '%s'", name)

        # 5. Update the index entry
        self._update_index(
            workspace_id, name, note,
            summary=(description or node.get("summary", ""))[:100],
        )

        # 6. Log
        self._log_activity(
            workspace_id, "update_entity_page",
            f"'{name}' ({new_type})",
        )

        return {"node": node, "note": note}

    def create_concept_page(
        self,
        concept: str,
        definition: str,
        workspace_id: str = "default",
        related_concepts: list[str] | None = None,
        embed: bool = True,
    ) -> dict[str, Any]:
        """Create a concept wiki page with definition and cross-references.

        Args:
            concept: The concept name.
            definition: Clear definition text.
            workspace_id: Target workspace.
            related_concepts: List of related concept names to
                cross-reference.
            embed: Whether to embed the note.

        Returns:
            Dict with ``node`` and ``note`` keys.
        """
        rel_lines = ""
        if related_concepts:
            rel_lines = "\n## Related Concepts\n\n"
            for rc in related_concepts:
                rel_lines += f"- [[{rc}]]\n"

        content = (
            f"---\n"
            f"type: concept\n"
            f"tags: [concept]\n"
            f"created: {datetime.datetime.utcnow().strftime('%Y-%m-%d')}\n"
            f"---\n\n"
            f"## Definition\n\n{definition}\n\n"
            f"{rel_lines}"
            f"---\n*Concept page: {concept}*"
        )

        note = self._client.create_note(
            workspace_id=workspace_id,
            title=f"Concept: {concept}",
            content=content,
            embed=embed,
        )

        # Create KG node for the concept
        node = None
        try:
            node = self._client.create_node(
                workspace_id=workspace_id,
                label=concept,
                node_type="concept",
                summary=definition[:300],
                source_memory_id="",
            )
        except RuntimeError:
            pass

        if node and note.get("id"):
            try:
                self._client._call(
                    "create_edge", [
                        workspace_id, note["id"], node["id"],
                        "describes", 1.0, "INFERRED",
                        "{}", "",
                    ],
                )
            except RuntimeError:
                pass

        # Update index
        self._update_index(
            workspace_id, f"Concept: {concept}", note,
            summary=definition[:100],
        )

        self._log_activity(
            workspace_id, "create_concept_page", concept,
        )
        return {"node": node, "note": note}

    def create_comparison_page(
        self,
        title: str,
        items: list[dict[str, str]] | list[str],
        workspace_id: str = "default",
        embed: bool = True,
        criteria: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a comparison table wiki page.

        Args:
            title: Comparison title (e.g. "RLHF vs DPO").
            items: List of item dicts. Each has a ``name`` key and
                arbitrary attribute keys. Example::

                    [
                        {"name": "RLHF", "type": "reward-based",
                         "complexity": "High", "stability": "High"},
                        {"name": "DPO", "type": "direct preference",
                         "complexity": "Low", "stability": "Medium"},
                    ]

                Can also be a flat list of item name strings, in which case
                ``criteria`` is used to add column headers (with empty cells).
            workspace_id: Target workspace.
            embed: Whether to embed the note.
            criteria: List of criteria names for the comparison columns.
                Only used when ``items`` is a list of strings.

        Returns:
            Dict with ``note`` key.
        """
        if not items:
            return {"note": {}}

        # Normalise: convert list[str] to list[dict] with optional criteria cols
        if items and isinstance(items[0], str):
            str_items: list[str] = items  # type: ignore[assignment]
            items = [{"name": s} for s in str_items]
            if criteria:
                for item in items:
                    for c in criteria:
                        item[c] = ""

        # After normalisation, items is always list[dict[str, str]]
        dict_items: list[dict[str, str]] = items  # type: ignore[assignment]

        # Build a markdown table
        all_keys = ["name"]
        for item in dict_items:
            for k in item:
                if k != "name" and k not in all_keys:
                    all_keys.append(k)

        header = "| " + " | ".join(k.capitalize() for k in all_keys) + " |"
        sep = "| " + " | ".join("---" for _ in all_keys) + " |"
        rows = []
        for item in dict_items:
            row = "| " + " | ".join(
                item.get(k, "") for k in all_keys
            ) + " |"
            rows.append(row)

        table = "\n".join([header, sep] + rows)

        content = (
            f"---\n"
            f"type: comparison\n"
            f"tags: [comparison]\n"
            f"created: {datetime.datetime.utcnow().strftime('%Y-%m-%d')}\n"
            f"---\n\n"
            f"## {title}\n\n"
            f"{table}\n\n"
            f"---\n*Comparison page: {title}*"
        )

        note = self._client.create_note(
            workspace_id=workspace_id,
            title=f"Comparison: {title}",
            content=content,
            embed=embed,
        )

        # Update index
        item_names = ", ".join(
            i.get("name", "") for i in dict_items[:5]
        )
        self._update_index(
            workspace_id, f"Comparison: {title}", note,
            summary=item_names[:100],
        )

        self._log_activity(
            workspace_id, "create_comparison_page", title,
        )
        return {"note": note}

    # ------------------------------------------------------------------
    # export_workspace — export wiki notes as markdown files
    # ------------------------------------------------------------------

    def export_workspace(
        self,
        output_dir: str,
        workspace_id: str = "default",
        *,
        include_kg: bool = False,
        include_system_notes: bool = False,
    ) -> dict[str, Any]:
        """Export all notes in a workspace as markdown files with
        YAML frontmatter, ready for Obsidian or git-based wiki browsing.

        Generates one ``.md`` file per note, using the note title as
        the filename.  YAML frontmatter includes ``id``, ``type``,
        ``created``, ``updated``, ``tags``, and ``backlinks``.

        Args:
            output_dir: Directory to write markdown files into.
            workspace_id: Target workspace.
            include_kg: Also export KG node summaries as markdown.
            include_system_notes: Include ``_index`` and ``_log`` notes.

        Returns:
            Dict with ``files_written``, ``output_dir``, ``errors``.
        """
        import os
        import pathlib
        from datetime import datetime as dt

        out = pathlib.Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        result: dict[str, Any] = {
            "files_written": 0,
            "output_dir": str(out),
            "errors": [],
        }

        # Fetch all notes
        notes = self._client._query(
            "note", workspace_id=workspace_id, filter_dict={},
        )
        if not notes and not include_kg:
            return result

        # Build backlink map (memory → list of notes that reference it)
        backlink_map: dict[str, list[str]] = {}
        edges = self._client._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={},
        )
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                backlink_map.setdefault(tgt, []).append(src)
            if tgt:
                backlink_map.setdefault(src, []).append(tgt)

        for note in notes:
            note_id = note.get("id", "")
            title = note.get("title", "untitled")
            content = note.get("content", "")
            created = note.get("created_at", "")
            updated = note.get("updated_at", "")

            # Skip system notes unless asked
            if not include_system_notes and title.startswith("_"):
                continue

            # Build frontmatter
            backlinks = backlink_map.get(note_id, [])
            bl_lines = "\n".join(
                f"    - \"{b}\"" for b in backlinks[:20]
            )

            frontmatter = (
                "---\n"
                f"id: \"{note_id}\"\n"
                f"title: \"{title}\"\n"
                f"created: {created}\n"
                f"updated: {updated}\n"
                f"backlinks:\n{bl_lines}\n"
                "---\n\n"
            )

            # Sanitize filename
            safe_title = "".join(
                c if c.isalnum() or c in " -_" else "_"
                for c in title
            ).strip()
            if not safe_title:
                safe_title = note_id[:12]
            filename = out / f"{safe_title[:100]}.md"

            try:
                filename.write_text(frontmatter + content, encoding="utf-8")
                result["files_written"] += 1
            except OSError as e:
                result["errors"].append(
                    f"{safe_title}: {e}"
                )

        # Optionally export KG nodes as markdown entity pages
        if include_kg:
            kg_dir = out / "_kg_nodes"
            kg_dir.mkdir(exist_ok=True)
            nodes = self._client._query(
                "kg_node", workspace_id=workspace_id, filter_dict={},
            )
            for node in nodes:
                label = node.get("label", "unknown")
                summary = node.get("summary", "")
                ntype = node.get("node_type", "concept")
                node_id = node.get("id", "")
                kg_content = (
                    "---\n"
                    f"id: \"{node_id}\"\n"
                    f"type: kg_node\n"
                    f"node_type: {ntype}\n"
                    f"label: \"{label}\"\n"
                    "---\n\n"
                    f"## {label}\n\n"
                    f"**Type:** {ntype}\n\n"
                    f"{summary}\n"
                )
                safe_label = "".join(
                    c if c.isalnum() or c in " -_" else "_"
                    for c in label
                ).strip()
                try:
                    (kg_dir / f"{safe_label[:100]}.md").write_text(
                        kg_content, encoding="utf-8"
                    )
                    result["files_written"] += 1
                except OSError as e:
                    result["errors"].append(f"kg_{label}: {e}")

        return result

    # ------------------------------------------------------------------
    # generate_overview_page — workspace synthesis/overview
    # ------------------------------------------------------------------

    def generate_overview_page(
        self,
        workspace_id: str = "default",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Generate a high-level overview/synthesis page for the
        workspace, summarizing its contents.

        Scans all notes, KG nodes, and edges to produce a markdown
        overview with entity tables, connections map, and stats.
        Uses LLM to write the synthesis if available; falls back
        to a structured data-driven summary.

        Returns:
            Dict with ``note`` key if created, or empty dict if
            the workspace is empty.
        """
        notes = self._client._query(
            "note", workspace_id=workspace_id, filter_dict={},
        ) or []
        nodes = self._client._query(
            "kg_node", workspace_id=workspace_id, filter_dict={},
        ) or []
        edges = self._client._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={},
        ) or []

        if not notes and not nodes:
            return {"note": {}}

        # Count by note type from frontmatter (best-effort)
        entity_notes = [n for n in notes
                        if "type: person" in n.get("content", "")
                        or "type: organization" in n.get("content", "")]
        concept_notes = [n for n in notes
                         if "type: concept" in n.get("content", "")]
        source_notes = [n for n in notes
                        if n.get("title", "").startswith("Source:")]
        comparison_notes = [n for n in notes
                            if n.get("title", "").startswith("Comparison:")]
        regular_notes = [n for n in notes
                         if not n.get("title", "").startswith("_")
                         and n not in entity_notes
                         and n not in concept_notes
                         and n not in source_notes
                         and n not in comparison_notes]

        # Count node types
        node_types: dict[str, int] = {}
        for nd in nodes:
            nt = nd.get("node_type", "unknown")
            node_types[nt] = node_types.get(nt, 0) + 1

        # Count edge types
        edge_types: dict[str, int] = {}
        for e in edges:
            rt = e.get("relation_type", "unknown")
            edge_types[rt] = edge_types.get(rt, 0) + 1

        # Count orphan nodes (no edges)
        connected_ids: set[str] = set()
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                connected_ids.add(src)
            if tgt:
                connected_ids.add(tgt)
        orphan_count = sum(
            1 for nd in nodes
            if nd.get("id", "") not in connected_ids
        )

        # Top entities table
        entity_rows = ""
        top_nodes = sorted(
            nodes, key=lambda n: len(n.get("summary", "")),
            reverse=True,
        )[:10]
        if top_nodes:
            entity_rows = "| Entity | Type | Summary |\n|--------|------|---------|\n"
            for nd in top_nodes:
                label = nd.get("label", "?")[:30]
                ntype = nd.get("node_type", "?")[:15]
                summary = nd.get("summary", "")[:80]
                entity_rows += f"| {label} | {ntype} | {summary} |\n"

        # Recent activity from _log
        recent_items = ""
        log_notes = [n for n in notes if n.get("title") == "_log"]
        if log_notes:
            log_content = log_notes[-1].get("content", "")
            log_lines = [
                l for l in log_content.split("\n")
                if l.startswith("## [")
            ][-5:]
            if log_lines:
                recent_items = "\n".join(f"- {l.strip('# ')}" for l in log_lines)

        type_table = ""
        if node_types:
            type_table = "| Type | Count |\n|------|:-----:|\n"
            for nt, count in sorted(node_types.items(), key=lambda x: -x[1]):
                type_table += f"| {nt} | {count} |\n"

        # Build the overview page
        lines = [
            "---",
            "type: overview",
            "tags: [overview, synthesis]",
            f"created: {datetime.datetime.utcnow().strftime('%Y-%m-%d')}",
            "---",
            "",
            "## Workspace Overview",
            "",
            f"**{len(notes)}** notes · **{len(nodes)}** KG nodes · "
            f"**{len(edges)}** edges · **{orphan_count}** orphans",
            "",
        ]

        # LLM synthesis if available
        if self._llm.available:
            summary_prompt = (
                f"Workspace '{workspace_id}' has {len(notes)} notes, "
                f"{len(nodes)} KG nodes ({node_types}), and {len(edges)} edges. "
                f"Top entities: {[n.get('label','') for n in top_nodes[:5]]}. "
                "Write a 3-5 sentence synthesis of what this workspace "
                "contains. Focus on the main themes and knowledge domains."
            )
            llm_synthesis = self._llm.summarize(
                summary_prompt,
                instruction="Write a concise workspace synthesis.",
            )
            if llm_synthesis:
                lines.append("### AI Synthesis\n")
                lines.append(llm_synthesis)
                lines.append("")

        # Stats sections
        lines.append("### Notes by Category\n")
        lines.append(f"| Category | Count |")
        lines.append(f"|----------|:-----:|")
        lines.append(f"| Sources | {len(source_notes)} |")
        lines.append(f"| Entity pages | {len(entity_notes)} |")
        lines.append(f"| Concept pages | {len(concept_notes)} |")
        lines.append(f"| Comparisons | {len(comparison_notes)} |")
        lines.append(f"| Other | {len(regular_notes)} |")
        lines.append(f"| System (_index, _log) | "
                     f"{sum(1 for n in notes if n.get('title','').startswith('_'))} |")
        lines.append("")

        if type_table:
            lines.append("### Knowledge Graph Entity Types\n")
            lines.append(type_table)
            lines.append("")

        if entity_rows:
            lines.append("### Top Entities\n")
            lines.append(entity_rows)
            lines.append("")

        if orphan_count > 0:
            lines.append(
                f"> ⚠ **{orphan_count} orphan nodes** — KG nodes with "
                f"no edges. Consider linking them or running `lint()`."
            )
            lines.append("")

        if recent_items:
            lines.append("### Recent Activity\n")
            lines.append(recent_items)
            lines.append("")

        if edge_types:
            edge_lines = "| Relation Type | Count |\n|------|:-----:|\n"
            for rt, count in sorted(edge_types.items(), key=lambda x: -x[1]):
                edge_lines += f"| {rt} | {count} |\n"
            lines.append("### Edge Types\n")
            lines.append(edge_lines)

        lines.append("---")
        lines.append(f"*Auto-generated overview for workspace '{workspace_id}'*")

        content = "\n".join(lines)

        note = self._client.create_note(
            workspace_id=workspace_id,
            title="_overview",
            content=content,
            embed=embed,
        )

        self._log_activity(
            workspace_id, "generate_overview",
            f"Workspace overview — {len(notes)} notes, "
            f"{len(nodes)} nodes, {len(edges)} edges",
        )

        return {"note": note}
