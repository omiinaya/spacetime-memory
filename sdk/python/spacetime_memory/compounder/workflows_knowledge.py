"""Compounder workflows — knowledge base workflows."""
from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)




class CompounderWorkflowsKnowledge:
    """Mixin — knowledge base workflows."""


    def store_answer(
        self,
        query: str,
        answer: str,
        workspace_id: str = "default",
        source_memory_ids: list[str] | None = None,
        title: str | None = None,
        embed: bool = True,
        skip_duplicates: bool = True,
        duplicate_threshold: float = 0.92,
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
            skip_duplicates: If True (default), check for near-duplicate
                content before creating a new note.  When a near-duplicate
                is found, the new note is NOT created and the result
                includes the existing note info under a ``duplicate_of`` key.
            duplicate_threshold: Minimum similarity score to consider
                content a near-duplicate (0.0-1.0).  Default 0.92 catches
                rephrased facts while letting novel content through.

        Returns:
            Dict with ``note``, ``entities``, and ``links`` keys, or
            empty dict on failure.  If ``skip_duplicates`` is True and a
            near-duplicate was found, the result includes a
            ``duplicate_of`` key with info about the existing content.
        """
        if not answer.strip():
            return {}

        # ── Near-duplicate detection ──
        if skip_duplicates:
            dupes = self.find_near_duplicates(
                answer,
                workspace_id=workspace_id,
                threshold=duplicate_threshold,
                limit=3,
            )
            if dupes:
                best = dupes[0]
                logger.info(
                    "Skipping store_answer — near-duplicate found (score=%.3f): %s",
                    best.get("score", 0.0),
                    str(best.get("content", ""))[:80],
                )
                return {
                    "note": best,
                    "entities": [],
                    "links": [],
                    "duplicate_of": best.get("entity_id", ""),
                    "duplicate_score": best.get("score", 0.0),
                }

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
                        "create_edge",
                        [
                            workspace_id,
                            note_id,
                            mid,
                            "informed_by",
                            1.0,
                            "INFERRED",
                            "{}",
                            "",
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
                    workspace_id,
                    ent.get("name", ""),
                    answer,
                    note.get("id", ""),
                )

        # 6. Log the activity
        self._log_activity(
            workspace_id,
            "store_answer",
            f"'{generated_title}' ({len(result['entities'])} entities, "
            f"{len(result['links'])} links)",
        )

        logger.info(
            "Stored answer note '%s' (%d entities, %d links)",
            generated_title,
            len(result["entities"]),
            len(result["links"]),
        )
        return result



    def store_answers(
        self,
        qa_pairs: list[tuple[str, str]],
        workspace_id: str = "default",
        source_memory_ids: list[str] | None = None,
        embed: bool = True,
        skip_duplicates: bool = True,
        duplicate_threshold: float = 0.92,
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
            skip_duplicates: If True (default), check each answer for
                near-duplicate content before creating a new note.
            duplicate_threshold: Minimum similarity score to consider
                content a near-duplicate (0.0-1.0).  Default 0.92.

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
                    skip_duplicates=skip_duplicates,
                    duplicate_threshold=duplicate_threshold,
                )
                results.append(result)
            except RuntimeError:
                results.append({"note": {}, "entities": [], "links": []})

        # Single consolidated log entry for the batch
        total_entities = sum(len(r.get("entities", [])) for r in results)
        total_links = sum(len(r.get("links", [])) for r in results)
        self._log_activity(
            workspace_id,
            "store_answers",
            f"Batch of {len(qa_pairs)} answers ({total_entities} entities, {total_links} links)",
        )

        logger.info(
            "Stored batch of %d answers (%d entities, %d links)",
            len(qa_pairs),
            total_entities,
            total_links,
        )
        return results



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
            return {"note": {}, "entities": [], "links": [], "contradictions": []}

        result: dict[str, Any] = {
            "note": {},
            "entities": [],
            "links": [],
            "contradictions": [],
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
            source_title,
            source_text,
            summary_text,
            source_type,
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
                workspace_id,
                f"Source: {source_title}",
                note,
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
                        "create_edge",
                        [
                            workspace_id,
                            note_id,
                            node_id,
                            "informed_by",
                            1.0,
                            "INFERRED",
                            "{}",
                            "",
                        ],
                    )
                    result["links"].append(node_id)
                except RuntimeError:
                    continue

        # 4. Ripple-update existing entity nodes
        if self._llm.available and entities:
            for ent in entities:
                self._ripple_update_entity(
                    workspace_id,
                    ent.get("name", ""),
                    summary_text,
                    note_id,
                )

        # 5. Proactive contradiction check
        if self._llm.available:
            result["contradictions"] = self._check_contradictions_on_ingest(
                workspace_id,
                summary_text,
                note_id,
            )

        # 6. Update index
        ingest_summary = (
            summary_text[:100] if len(summary_text) < 100 else summary_text[:97] + "..."
        )
        self._update_index(workspace_id, f"Source: {source_title}", note, summary=ingest_summary)

        # 7. Log
        self._log_activity(
            workspace_id,
            "ingest_source",
            f"'{source_title}' ({len(result['entities'])} entities, "
            f"{len(result['links'])} links, "
            f"{len(result['contradictions'])} contradictions)",
        )

        logger.info(
            "Ingested source '%s' (%d entities, %d links, %d contradictions)",
            source_title,
            len(result["entities"]),
            len(result["links"]),
            len(result["contradictions"]),
        )
        return result



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
            "kg_node",
            workspace_id=workspace_id,
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
            f"created: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d')}\n"
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
                    "create_edge",
                    [
                        workspace_id,
                        note["id"],
                        node["id"],
                        "describes",
                        1.0,
                        "INFERRED",
                        "{}",
                        "",
                    ],
                )
            except RuntimeError:
                pass

        # 4. Update index
        self._update_index(
            workspace_id,
            name,
            note,
            summary=description[:100],
        )

        # 5. Log
        self._log_activity(
            workspace_id,
            "create_entity_page",
            f"'{name}' ({entity_type})",
        )

        return {"node": node, "note": note}



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
            "kg_node",
            workspace_id=workspace_id,
            filter_dict={"label": name},
        )
        if not existing:
            logger.warning("update_entity_page: entity '%s' not found", name)
            return {}
        node = existing[0]

        # 2. Find the associated wiki note (entity pages use name as title)
        notes = self._client._query(
            "note",
            workspace_id=workspace_id,
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
                        rel_lines += (
                            f"- **{r.get('relation', 'related_to')}**: {r.get('name', '')}\n"
                        )
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
                f"created: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d')}\n"
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
            workspace_id,
            name,
            note,
            summary=(description or node.get("summary", ""))[:100],
        )

        # 6. Log
        self._log_activity(
            workspace_id,
            "update_entity_page",
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
            f"created: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d')}\n"
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
                    "create_edge",
                    [
                        workspace_id,
                        note["id"],
                        node["id"],
                        "describes",
                        1.0,
                        "INFERRED",
                        "{}",
                        "",
                    ],
                )
            except RuntimeError:
                pass

        # Update index
        self._update_index(
            workspace_id,
            f"Concept: {concept}",
            note,
            summary=definition[:100],
        )

        self._log_activity(
            workspace_id,
            "create_concept_page",
            concept,
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
            row = "| " + " | ".join(item.get(k, "") for k in all_keys) + " |"
            rows.append(row)

        table = "\n".join([header, sep] + rows)

        content = (
            f"---\n"
            f"type: comparison\n"
            f"tags: [comparison]\n"
            f"created: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d')}\n"
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
        item_names = ", ".join(i.get("name", "") for i in dict_items[:5])
        self._update_index(
            workspace_id,
            f"Comparison: {title}",
            note,
            summary=item_names[:100],
        )

        self._log_activity(
            workspace_id,
            "create_comparison_page",
            title,
        )
        return {"note": note}

    def synthesize_with_gap_analysis(
        self,
        query: str,
        workspace_id: str = "default",
        *,
        answer: str | None = None,
        llm_client: Any | None = None,
    ) -> dict[str, Any]:
        """GBrain-parity synthesis with explicit gap analysis.

        Searches the workspace for evidence, produces a synthesized
        answer (LLM if available, otherwise a grounded summary built from
        the top results), and explicitly reports **what the brain
        doesn't know** — gaps between the query and the available
        evidence.

        Args:
            query: The question to synthesize an answer for.
            workspace_id: Target workspace.
            answer: Optional pre-computed answer text.  When omitted, an
                answer is generated from search results (LLM preferred).
            llm_client: Optional LLMClient-compatible object.  When
                omitted and no LLM is configured, a grounded summary is
                built from the retrieved evidence.

        Returns:
            Dict with:
              - ``answer`` (str): the synthesized answer.
              - ``gaps`` (list[str]): explicit knowledge-gap statements.
              - ``evidence_count`` (int): how many memories informed it.
              - ``method`` (str): "llm" | "grounded" | "empty".
        """
        results = self._client.search(workspace_id, query, limit=10)

        if not results:
            return {
                "answer": "No relevant memories found in this workspace.",
                "gaps": ["No evidence exists for this topic in the workspace."],
                "evidence_count": 0,
                "method": "empty",
            }

        evidence = [
            (r.get("content") or r.get("memory_content") or r.get("memory") or "")
            for r in results
            if r.get("content") or r.get("memory_content") or r.get("memory")
        ]
        evidence = [str(e)[:800] for e in evidence if e]

        llm = llm_client
        if llm is None and getattr(self, "_llm", None) is not None:
            candidate = self._llm
            try:
                if candidate.available:
                    llm = candidate
            except Exception:
                llm = None
        if llm is None:
            try:
                from spacetime_memory.llm import LLMClient

                candidate = LLMClient()
                if candidate.available:
                    llm = candidate
            except Exception:
                llm = None

        gap_prompt = (
            "You are a knowledge-base analyst. Given the question and the "
            "available evidence, answer the question AND list explicit "
            "knowledge gaps — facts the answer relies on that are NOT "
            "present in the evidence.\n\n"
            "Return JSON with keys \"answer\" (string) and \"gaps\" "
            "(array of strings).\n\n"
        )

        if llm is not None:
            try:
                raw = llm.chat(
                    [
                        {
                            "role": "system",
                            "content": gap_prompt,
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Question: {query}\n\n"
                                f"Evidence:\n"
                                + "\n---\n".join(
                                    f"[{i+1}] {e}" for i, e in enumerate(evidence[:10])
                                )
                            ),
                        },
                    ],
                    temperature=0.0,
                    max_tokens=1024,
                    response_format={"type": "json_object"},
                )
                if raw:
                    parsed = self._parse_gap_json(raw)
                    if parsed:
                        return {
                            "answer": parsed.get("answer", ""),
                            "gaps": parsed.get("gaps", []),
                            "evidence_count": len(evidence),
                            "method": "llm",
                        }
            except Exception:
                pass

        # Grounded fallback: synthesize from evidence, state the gaps
        # conservatively (anything the evidence doesn't cover).
        summary = " ".join(evidence[:5])[:1500]
        return {
            "answer": f"Based on {len(evidence)} memory/evidence item(s), the "
            f"workspace indicates: {summary[:1200]}",
            "gaps": [
                "The evidence does not directly answer this question; "
                "further sources are needed to confirm specifics.",
            ],
            "evidence_count": len(evidence),
            "method": "grounded",
        }

    @staticmethod
    def _parse_gap_json(raw: str) -> dict[str, Any] | None:
        """Parse the LLM's gap-analysis JSON defensively."""
        import json as _json
        import re as _re

        text = raw.strip()
        text = _re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            obj = _json.loads(text)
            if isinstance(obj, dict) and ("answer" in obj or "gaps" in obj):
                return {
                    "answer": str(obj.get("answer", "")),
                    "gaps": [
                        str(g) for g in obj.get("gaps", []) if isinstance(g, str)
                    ],
                }
        except (_json.JSONDecodeError, TypeError):
            pass
        # Regex fallback: "answer": "..." and "gaps": ["...", ...]
        ans_m = _re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        gaps_m = _re.findall(r'"((?:[^"\\]|\\.)*)"', text.split("gaps", 1)[-1])
        if ans_m:
            return {
                "answer": ans_m.group(1).replace('\\"', '"'),
                "gaps": [g.replace('\\"', '"') for g in gaps_m if g],
            }
        return None


