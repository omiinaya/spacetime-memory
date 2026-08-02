"""MCP tools — Compounder tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Compounder tools — LLM Wiki workflow
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def ingest_source(
    source_text: str,
    source_title: str,
    workspace_id: str = "default",
    source_type: str = "article",
) -> str:
    """Ingest a source document into the wiki.

    Full LLM Wiki workflow: summarize, extract entities, create KG nodes,
    link, ripple-update entities, and check for contradictions.
    """
    from spacetime_memory.compounder import Compounder

    client = get_client()
    cp = Compounder(client)
    result = cp.ingest_source(
        source_text=source_text,
        source_title=source_title,
        workspace_id=workspace_id,
        source_type=source_type,
    )
    n_entities = len(result.get("entities", []))
    n_links = len(result.get("links", []))
    n_contra = len(result.get("contradictions", []))
    return (
        f"Ingested '{source_title}' into workspace {workspace_id[:16]}...\n"
        f"  Entities: {n_entities}, Links: {n_links}, "
        f"Contradictions: {n_contra}"
    )


@mcp.tool()
@require_api_key
def create_entity_page(
    name: str,
    description: str,
    entity_type: str = "concept",
    workspace_id: str = "default",
) -> str:
    """Create a structured entity wiki page with KG node + YAML frontmatter.

    Entity types: person, org, concept, product, location, event, topic.
    Creates both a wiki note and a knowledge graph node.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.create_entity_page(
        name=name,
        description=description,
        entity_type=entity_type,
        workspace_id=workspace_id,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    return f"Entity page '{name}' created (note: {note_id}...)"


@mcp.tool()
@require_api_key
def update_entity_page(
    name: str,
    description: str | None = None,
    entity_type: str | None = None,
    workspace_id: str = "default",
) -> str:
    """Update an existing entity wiki page and its KG node.

    Finds the entity by name and updates the provided fields. Fields not
    provided are left unchanged.

    Args:
        name: Entity name (used to find the existing entity).
        description: New 2-3 sentence description (optional).
        entity_type: New entity type (e.g. person, org, concept).
        workspace_id: Target workspace.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.update_entity_page(
        name=name,
        description=description,
        entity_type=entity_type,
        workspace_id=workspace_id,
    )
    if not result:
        return f"Entity page '{name}' not found."
    return f"Entity page '{name}' updated."


@mcp.tool()
@require_api_key
def create_concept_page(
    concept: str,
    definition: str,
    workspace_id: str = "default",
    related_concepts: str = "",
) -> str:
    """Create a concept wiki page with definition and [[wiki-links]].

    Args:
        concept: The concept name.
        definition: Clear definition text.
        workspace_id: Target workspace.
        related_concepts: Comma-separated list of related concept names.
    """
    from spacetime_memory.compounder import Compounder

    rel_list = [c.strip() for c in related_concepts.split(",") if c.strip()]
    cp = Compounder(get_client())
    result = cp.create_concept_page(
        concept=concept,
        definition=definition,
        workspace_id=workspace_id,
        related_concepts=rel_list or None,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    return f"Concept page '{concept}' created (note: {note_id}...)"


@mcp.tool()
@require_api_key
def create_comparison_page(
    title: str,
    items: str,
    workspace_id: str = "default",
    criteria: str = "features,performance,ecosystem",
) -> str:
    """Create a comparison wiki page with markdown table.

    Creates a note with YAML frontmatter (type: comparison) and a
    markdown comparison table of the given items across specified
    criteria.

    Args:
        title: Page title (e.g. \"LangGraph vs CrewAI vs AutoGen\").
        items: Comma-separated list of items to compare.
        workspace_id: Target workspace.
        criteria: Comma-separated comparison criteria.
    """
    from spacetime_memory.compounder import Compounder

    item_list = [i.strip() for i in items.split(",") if i.strip()]
    crit_list = [c.strip() for c in criteria.split(",") if c.strip()]
    cp = Compounder(get_client())
    result = cp.create_comparison_page(
        title=title,
        items=item_list,
        workspace_id=workspace_id,
        criteria=crit_list,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    return f"Comparison page '{title}' created with {len(item_list)} items (note: {note_id}...)"


@mcp.tool()
@require_api_key
def lint_workspace(
    workspace_id: str = "default",
    check_contradictions: bool = False,
) -> str:
    """Health-check the workspace wiki.

    Scans for orphans (KG nodes with no edges) and missing
    cross-references.  Set check_contradictions=True (slower)
    to also detect contradictory claims using the LLM.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.lint_workspace(
        workspace_id=workspace_id,
        check_contradictions=check_contradictions,
    )
    summary = result.get("summary", {})
    return (
        f"Lint complete for workspace {workspace_id[:16]}...\n"
        f"  Orphans: {summary.get('orphan_count', 0)}\n"
        f"  Missing crossrefs: {summary.get('missing_crossref_count', 0)}\n"
        f"  Note orphans: {summary.get('note_orphan_count', 0)}\n"
        f"  Contradictions: {summary.get('contradiction_count', 0)}\n"
        f"  Total issues: {summary.get('total_issues', 0)}"
    )


@mcp.tool()
@require_api_key
def generate_overview(workspace_id: str = "default") -> str:
    """Generate a workspace overview/synthesis page (_overview).

    Creates a note with workspace stats, entity tables, recent activity,
    and (if LLM available) an AI-written synthesis.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.generate_overview_page(workspace_id=workspace_id)
    note = result.get("note", {})
    if note.get("id"):
        return f"Overview generated: `{note['id'][:16]}...`"
    return "Workspace is empty. Nothing to generate."


@mcp.tool()
@require_api_key
def search_entities(
    workspace_id: str = "default",
    label: str = "",
    node_type: str = "",
    semantic_query: str = "",
    limit: int = 20,
) -> str:
    """Search knowledge-graph entities with flexible filters.

    Supports label search, type filtering, and semantic search.
    Combine filters to narrow results.

    Args:
        workspace_id: Target workspace.
        label: Exact entity label to search for (optional).
        node_type: Entity type filter (person, org, concept, product,
            location, event, topic). Optional.
        semantic_query: Natural-language query for semantic entity
            search (optional).
        limit: Max results (default: 20).
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    results = cp.search_entities(
        workspace_id=workspace_id,
        label=label or None,
        node_type=node_type or None,
        semantic_query=semantic_query or None,
        limit=limit,
    )
    if not results:
        return "No entities found."
    lines = [f"Found {len(results)} entities:"]
    for n in results:
        nid = n.get("id", "")[:12]
        label_text = n.get("label", "?")
        ntype = n.get("node_type", "?")
        summary = (n.get("summary", "") or "")[:80]
        lines.append(f"- [{label_text}]({nid}) [{ntype}] {summary}")
    return "\n".join(lines)


@mcp.tool()
@require_api_key
def find_near_duplicates(
    content: str,
    workspace_id: str = "default",
    threshold: float = 0.92,
    limit: int = 5,
) -> str:
    """Find memories with semantically similar content to the given text.

    Uses the hybrid search pipeline to catch rephrasings of the same fact.
    Default threshold of 0.92 works well for BGE-M3 embeddings.

    Args:
        content: The text to check for near-duplicates.
        workspace_id: Target workspace (default: "default").
        threshold: Minimum similarity score (0.0-1.0, default: 0.92).
        limit: Max results to return (default: 5).

    Returns:
        Formatted string listing near-duplicate candidates with scores.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    results = cp.find_near_duplicates(
        content=content,
        workspace_id=workspace_id,
        threshold=threshold,
        limit=limit,
    )
    if not results:
        return "No near-duplicates found."
    lines = [f"Found {len(results)} near-duplicate candidate(s):"]
    for r in results[:limit]:
        eid = r.get("entity_id", "")[:16]
        etype = r.get("entity_type", "?")
        score = r.get("score", 0.0)
        snippet = (r.get("content", "") or "")[:120].replace("\n", " ")
        lines.append(f"  - [{etype}] {eid} (score: {score:.4f}) {snippet}")
    return "\n".join(lines)


@mcp.tool()
@require_api_key
def cross_link(workspace_id: str = "default") -> str:
    """Auto-link related but unconnected memories in a workspace.

    Finds memories that reference similar concepts or share entities
    but aren't directly linked, and creates edges between them.

    Args:
        workspace_id: Target workspace (default: "default").
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.cross_link(workspace_id=workspace_id)
    links_created = result.get("links_created", 0)
    pairs_checked = result.get("pairs_checked", 0)
    return (
        f"Cross-link complete for workspace {workspace_id[:16]}...\n"
        f"  Pairs checked: {pairs_checked}\n"
        f"  Links created: {links_created}"
    )


@mcp.tool()
@require_api_key
def suggest_connections(workspace_id: str = "default") -> str:
    """Find knowledge-graph node pairs that should be linked.

    Identifies node pairs that share neighbours but aren't directly
    connected, and returns ranked suggestions for new edges.

    Args:
        workspace_id: Target workspace (default: "default").
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    suggestions = cp.suggest_connections(workspace_id=workspace_id)
    if not suggestions:
        return "No connection suggestions found."
    lines = [
        f"Found {len(suggestions)} connection suggestion(s) "
        f"for workspace {workspace_id[:16]}...:"
    ]
    for s in suggestions[:20]:
        src = s.get("source_label", "?")
        tgt = s.get("target_label", "?")
        common = s.get("common_count", 0)
        lines.append(f"  - {src[:40]} → {tgt[:40]} ({common} common neighbour(s))")
    return "\n".join(lines)


@mcp.tool()
@require_api_key
def store_answer(
    query: str,
    answer: str,
    workspace_id: str = "default",
    source_memory_ids: str = "",
) -> str:
    """Persist an LLM-synthesized answer as a wiki page.

    Creates a note, extracts entities, creates KG nodes, links to
    source memories, ripple-updates entity summaries, and logs the
    activity.

    Args:
        query: The question that prompted the answer.
        answer: The synthesized answer text.
        workspace_id: Target workspace.
        source_memory_ids: Comma-separated list of source memory/node IDs.
    """
    from spacetime_memory.compounder import Compounder

    ids = [s.strip() for s in source_memory_ids.split(",") if s.strip()]
    cp = Compounder(get_client())
    result = cp.store_answer(
        query=query,
        answer=answer,
        workspace_id=workspace_id,
        source_memory_ids=ids or None,
    )
    note_id = result.get("note", {}).get("id", "")[:16]
    n_entities = len(result.get("entities", []))
    return (
        f"Answer stored (note: {note_id}...)\n"
        f"  Entities extracted: {n_entities}"
    )


@mcp.tool()
@require_api_key
def store_answers_batch(
    qa_pairs_json: str,
    workspace_id: str = "default",
    source_memory_ids: str = "",
) -> str:
    """Batch-persist multiple LLM-synthesized answers as wiki pages.

    More efficient than calling store_answer repeatedly — fetches the
    workspace index once and creates a single consolidated log entry.

    Args:
        qa_pairs_json: JSON string of [[query, answer], ...] pairs.
            Example: '[["What is RLHF?", "RLHF is..."], ["What is
            PPO?", "PPO is a..."]]'
        workspace_id: Target workspace (default: "default").
        source_memory_ids: Comma-separated list of source memory/node
            IDs that informed *all* answers in this batch (optional).

    Returns:
        Summary string with count of stored answers and extracted
        entities.
    """
    import json as _json

    from spacetime_memory.compounder import Compounder

    try:
        qa_pairs = _json.loads(qa_pairs_json)
    except _json.JSONDecodeError as e:
        return f"Error: invalid JSON in qa_pairs_json — {e}"

    if not isinstance(qa_pairs, list) or not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
        for p in qa_pairs
    ):
        return (
            "Error: qa_pairs_json must be a JSON list of [query, answer] "
            "string pairs, e.g. '[[\"Q1\", \"A1\"], [\"Q2\", \"A2\"]]'"
        )

    ids = (
        [s.strip() for s in source_memory_ids.split(",") if s.strip()]
        if source_memory_ids
        else None
    )
    cp = Compounder(get_client())
    results = cp.store_answers(
        qa_pairs=qa_pairs,
        workspace_id=workspace_id,
        source_memory_ids=ids,
    )

    n_stored = len(results)
    n_entities = sum(len(r.get("entities", [])) for r in results)
    return (
        f"Batch stored {n_stored} answers (note: {n_stored} notes)\n"
        f"  Total entities extracted: {n_entities}"
    )


@mcp.tool()
@require_api_key
def export_workspace(
    output_dir: str,
    workspace_id: str = "default",
    include_kg: bool = False,
    include_system_notes: bool = False,
) -> str:
    """Export all notes in a workspace as markdown files with YAML frontmatter.

    Generates one ``.md`` file per note, using the note title as the filename.
    Output is ready for Obsidian or git-based wiki browsing.

    Args:
        output_dir: Directory to write markdown files into.
        workspace_id: Target workspace (default: "default").
        include_kg: Also export KG node summaries as markdown.
        include_system_notes: Include ``_index`` and ``_log`` notes.

    Returns:
        Summary string with files written and output directory.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(get_client())
    result = cp.export_workspace(
        output_dir=output_dir,
        workspace_id=workspace_id,
        include_kg=include_kg,
        include_system_notes=include_system_notes,
    )
    files_written = result.get("files_written", 0)
    out_dir = result.get("output_dir", output_dir)
    errors = result.get("errors", [])
    summary = f"Exported {files_written} file(s) to {out_dir}"
    if errors:
        summary += f"\n  Errors: {len(errors)}"
        for e in errors[:5]:
            summary += f"\n    - {e}"
    return summary


@mcp.tool()
@require_api_key
def backup(workspace_id: str = "default", output_path: str = "") -> str:
    """Back up all user data tables to a JSON file.

    Exports memory, note, KG, and other user data tables to a portable
    JSON backup file. The backup includes all tables, row counts, and a
    creation timestamp.

    Args:
        workspace_id: The workspace to back up (default: "default").
        output_path: Optional output file path. If empty, generates a
            timestamped filename like
            ``spacetime-memory-backup-YYYY-MM-DD.json``.

    Returns:
        Confirmation message with backup path and stats.
    """
    path = output_path or None
    result = get_client().backup(output_path=path)
    tbl_count = result.get("table_count", 0)
    total_rows = result.get("total_rows", 0)
    out = result.get("path", output_path or "auto")
    return (
        f"Backup written to {out}\n"
        f"  Tables: {tbl_count}, Total rows: {total_rows}"
    )


@mcp.tool()
@require_api_key
def restore(input_path: str) -> str:
    """Restore data from a backup JSON file.

    Imports a previously-created backup file into the current database.
    Tables and rows are inserted directly; duplicates are silently skipped.

    Args:
        input_path: Path to the backup JSON file created by ``backup``.

    Returns:
        Confirmation message with restore stats.
    """
    result = get_client().restore(input_path)
    tbl_restored = len(result.get("restored", []))
    total_rows = result.get("total_rows", 0)
    return (
        f"Restored {total_rows} row(s) across {tbl_restored} table(s) "
        f"from {input_path}"
    )


# ---------------------------------------------------------------------------
