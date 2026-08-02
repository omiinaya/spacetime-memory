"""Compounder operations (overview, lint, merges, answers)"""

from __future__ import annotations

import sys

import click
from rich import box
from rich.table import Table


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
)

# ── Overview ────────────────────────────────────────────────────────────────# ── Overview ──────────────────────────────────────────────────────────────────

@cli.command(name="overview")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--no-embed", is_flag=True,
              help="Skip semantic embedding for the overview note")
def overview_cmd(workspace: str, no_embed: bool) -> None:
    """Generate a workspace overview/synthesis page.

    Creates a ``_overview`` note with stats, entity tables, recent
    activity, and (if LLM available) an AI-written synthesis.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Generating overview for workspace '{workspace}'..."
    ):
        result = cp.generate_overview_page(
            workspace_id=workspace,
            embed=not no_embed,
        )

    note = result.get("note", {})
    if note.get("id"):
        _quiet_print(
            f"[green]Overview generated:[/green] `{note['id'][:16]}...`"
        )
    else:
        _root.console.print("[yellow]Workspace is empty. Nothing to generate.[/yellow]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Lint ──────────────────────────────────────────────────────────────────────

@cli.command(name="lint")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--no-contradictions", is_flag=True,
              help="Skip contradiction detection (LLM-intensive)")
@click.option("--no-crossrefs", is_flag=True,
              help="Skip missing-crossref detection")
def lint_cmd(workspace: str, no_contradictions: bool, no_crossrefs: bool) -> None:
    """Run a workspace health-check.

    Finds orphan KG nodes (no edges), missing cross-references,
    and (optionally) contradictory memory pairs via LLM analysis.

    Contradiction detection requires an available LLM and can be
    slow on large workspaces — use --no-contradictions to skip it.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Linting workspace '{workspace}'..."
    ):
        result = cp.lint_workspace(
            workspace_id=workspace,
            check_contradictions=not no_contradictions,
            check_missing_crossrefs=not no_crossrefs,
        )

    orphans = result.get("orphans", [])
    crossrefs = result.get("missing_crossrefs", [])
    contradictions = result.get("contradictions", [])

    if orphans:
        _root.console.print(f"\n[bold]Orphan nodes ({len(orphans)}):[/bold]")
        for o in orphans[:20]:
            _root.console.print(f"  • {o.get('label', o.get('id', '?'))[:12]} — {o.get('node_type', '?')}")
        if len(orphans) > 20:
            _root.console.print(f"  ... and {len(orphans) - 20} more")
    else:
        _root.console.print("[green]No orphan nodes.[/green]")

    if crossrefs:
        _root.console.print(f"\n[bold]Missing cross-references ({len(crossrefs)}):[/bold]")
        for cr in crossrefs[:10]:
            _root.console.print(f"  • Note [cyan]{cr.get('note_title', cr.get('note_id', '?'))[:30]}[/cyan] mentions entity [yellow]{cr.get('entity', '?')}[/yellow] with no KG edge")
        if len(crossrefs) > 10:
            _root.console.print(f"  ... and {len(crossrefs) - 10} more")
    elif not no_crossrefs:
        _root.console.print("[green]Cross-references are clean.[/green]")

    if contradictions:
        _root.console.print(f"\n[bold yellow]Contradictions found ({len(contradictions)}):[/bold yellow]")
        for c in contradictions[:5]:
            _root.console.print(f"  • {c.get('note_id', '?')[:12]} vs {c.get('contradicts_note_id', '?')[:12]}")
            note_id = c.get("contradiction_note_id", "")
            if note_id:
                _root.console.print(f"    → contradiction note: [cyan]{note_id[:16]}...[/cyan]")
        if len(contradictions) > 5:
            _root.console.print(f"  ... and {len(contradictions) - 5} more")
    elif not no_contradictions:
        _root.console.print("[green]No contradictions detected.[/green]")

    if not orphans and not crossrefs and not contradictions:
        _root.console.print("[green]Workspace is clean![/green]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Cross-link ────────────────────────────────────────────────────────────────

@cli.command(name="cross-link")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--dry-run", is_flag=True, help="Preview links without creating them")
def cross_link_cmd(workspace: str, dry_run: bool) -> None:
    """Auto-link related but unconnected memories.

    Finds semantically similar memories that aren't linked in the
    knowledge graph and creates edges between them.  Uses keyword +
    embedding similarity when available.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Cross-linking workspace '{workspace}'..."
    ):
        result = cp.cross_link(workspace_id=workspace)

    links = result.get("links_created", [])
    if dry_run and links:
        _root.console.print(
            f"[yellow]DRY RUN:[/yellow] Would create {len(links)} edges"
        )
    elif links:
        _root.console.print(
            f"[green]Created {len(links)} new cross-links.[/green]"
        )
    else:
        _root.console.print("[green]No new cross-links found.[/green]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Merge Operations ────────────────────────────────────────────────────────

@cli.command(name="suggest-merges")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--threshold", "-t", default=0.8, type=float,
              help="Minimum cosine similarity threshold (default: 0.8)")
def suggest_merges_cmd(workspace: str, threshold: float) -> None:
    """Scan active memories and suggest near-duplicate merges.

    Compares all active memory embeddings pairwise in the workspace.
    Pairs with cosine similarity >= threshold AND edit distance <= 30 %
    are recorded as MergeSuggestion rows with status "pending".
    Previous pending suggestions for the workspace are cleared first.
    """
    client = _sdk_client()
    with _root.console.status(
        f"Scanning workspace '{workspace}' for merge candidates..."
    ):
        result = client.suggest_merges(workspace, threshold)

    if result.get("status") == "ok":
        suggestions = client._query("merge_suggestion",
                                    filter_dict={"workspace_id": workspace, "status": "pending"})
        _root.console.print(
            f"[green]Merge scan complete:[/green] "
            f"[cyan]{len(suggestions)}[/cyan] candidate(s) found "
            f"(threshold: {threshold})"
        )
        if suggestions:
            table = Table(title="Merge Candidates", box=box.ROUNDED)
            table.add_column("ID", style="dim")
            table.add_column("Source → Target", style="cyan")
            table.add_column("Cos. Sim.", style="yellow")
            table.add_column("Edit Dist.", style="yellow")
            for s in suggestions[:20]:
                sid = s.get("id", "?")[:12]
                preview = s.get("content_overlap_preview", "")[:80]
                cos_sim = f"{s.get('cosine_similarity', 0):.4f}"
                edit_dist = f"{s.get('edit_distance', 0):.4f}"
                table.add_row(sid, preview, cos_sim, edit_dist)
            _quiet_print("")
            _root.console.print(table)
            _quiet_print(
                "  [dim]Use [cyan]stmem approve-merge <id>[/cyan] "
                "or [cyan]stmem reject-merge <id>[/cyan][/dim]"
            )
    else:
        _root.console.print("[red]Merge scan failed.[/red]")

    if _root._current_output_format == "json":
        print_json(result)


@cli.command(name="approve-merge")
@click.argument("suggestion_id")
def approve_merge_cmd(suggestion_id: str) -> None:
    """Approve a pending merge suggestion.

    Deactivates the source memory and consolidates it into the target
    (survivor) memory. The source is marked inactive with a pointer
    to the target.
    """
    client = _sdk_client()
    with _root.console.status(f"Approving merge {suggestion_id[:16]}..."):
        result = client.approve_merge(suggestion_id)

    if result.get("status") == "ok":
        _root.console.print(
            f"[green]Merge approved:[/green] {suggestion_id[:16]}... "
            f"— source deactivated, target reinforced."
        )
    else:
        _root.console.print("[red]Merge approval failed.[/red]")

    if _root._current_output_format == "json":
        print_json(result)


@cli.command(name="reject-merge")
@click.argument("suggestion_id")
def reject_merge_cmd(suggestion_id: str) -> None:
    """Reject a pending merge suggestion without merging.

    Simply marks the suggestion as "rejected" — no memories are changed.
    """
    client = _sdk_client()
    with _root.console.status(f"Rejecting merge {suggestion_id[:16]}..."):
        result = client.reject_merge(suggestion_id)

    if result.get("status") == "ok":
        _root.console.print(
            f"[green]Merge rejected:[/green] {suggestion_id[:16]}..."
        )
    else:
        _root.console.print("[red]Merge rejection failed.[/red]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Suggest Connections ───────────────────────────────────────────────────────

@cli.command(name="suggest-connections")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--limit", "-n", default=20, type=int,
              help="Max suggestions to return")
def suggest_connections_cmd(workspace: str, limit: int) -> None:
    """Suggest node pairs that should be connected.

    Identifies entity/node pairs that share many neighbors but aren't
    directly linked — candidates for manual review or auto-linking.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Finding connection suggestions for '{workspace}'..."
    ):
        result = cp.suggest_connections(
            workspace_id=workspace,
            limit=limit,
        )

    suggestions = result if isinstance(result, list) else result.get("suggestions", [])
    if suggestions:
        _root.console.print(
            f"\n[bold]Suggested connections ({len(suggestions)}):[/bold]"
        )
        for s in suggestions[:20]:
            src = s.get("source_label", s.get("source", "?"))[:25]
            tgt = s.get("target_label", s.get("target", "?"))[:25]
            score = s.get("score", s.get("shared_neighbors", 0))
            _root.console.print(f"  • [cyan]{src}[/cyan] ↔ [yellow]{tgt}[/yellow]  (score: {score})")
    else:
        _root.console.print("[green]No connection suggestions found.[/green]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Store Answer ──────────────────────────────────────────────────────────────

@cli.command(name="store-answer")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--query", "-q", required=True, help="The question that was answered")
@click.option("--answer", "-a", required=True, help="The answer text")
@click.option("--source-ids", "-s", help="Comma-separated source memory IDs")
@click.option("--no-embed", is_flag=True, help="Skip semantic embedding")
def store_answer_cmd(workspace: str, query: str, answer: str,
                     source_ids: str | None, no_embed: bool) -> None:
    """Persist an LLM answer as a wiki page.

    Creates a note + KG nodes + index entry from an answer synthesis.
    Implements the 'answers get filed back into the wiki' pattern
    from Karpathy's LLM Wiki.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    mem_ids = (
        [s.strip() for s in source_ids.split(",") if s.strip()]
        if source_ids else None
    )

    with _root.console.status(
        f"Storing answer for '{query[:40]}...'"
    ):
        result = cp.store_answer(
            query=query,
            answer=answer,
            workspace_id=workspace,
            source_memory_ids=mem_ids,
            embed=not no_embed,
        )

    note = result.get("note", {})
    entities = result.get("entities_created", [])
    if note.get("id"):
        _quiet_print(
            f"[green]Answer stored:[/green] [cyan]{note.get('title', note['id'][:16])}[/cyan]"
        )
        if entities:
            _quiet_print(
                f"  Entities created: [yellow]{', '.join(e.get('label', '?') for e in entities)}[/yellow]"
            )
    else:
        _root.console.print("[red]Failed to store answer. Check STDB connection and that OPENAI_API_KEY is set.[/red]")
        _root.console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Store Answers Batch ──────────────────────────────────────────────────────

@cli.command(name="store-answers-batch")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--pairs", "-p", required=True,
              help='JSON string of [[query, answer], ...] pairs. '
                   'Example: --pairs \'[["Q1","A1"],["Q2","A2"]]\'')
@click.option("--source-ids", "-s", help="Comma-separated source memory IDs")
@click.option("--file", "-f", "pairs_file",
              help="Read JSON pairs from a file instead of --pairs argument")
def store_answers_batch_cmd(workspace: str, pairs: str,
                             source_ids: str | None,
                             pairs_file: str | None) -> None:
    """Batch-persist multiple LLM-synthesized answers as wiki pages.

    More efficient than calling store-answer repeatedly — fetches the
    workspace index once and creates a single consolidated log entry.

    Provide pairs as a JSON string via --pairs, or read from a file
    via --file. Each pair is [query, answer].
    """
    import json as _json

    from spacetime_memory.compounder import Compounder

    # Resolve pairs source
    if pairs_file:
        try:
            with open(pairs_file, "r") as f:
                raw = f.read()
        except FileNotFoundError:
            _root.console.print(f"[red]File not found: {pairs_file}[/red]")
            _root.console.print("  [dim]→ Check the file path and try again[/dim]")
            sys.exit(1)
        except OSError as e:
            _root.console.print(f"[red]Error reading {pairs_file}: {e}[/red]")
            sys.exit(1)
    else:
        raw = pairs

    try:
        qa_pairs = _json.loads(raw)
    except _json.JSONDecodeError as e:
        _root.console.print(f"[red]Invalid JSON in pairs: {e}[/red]")
        sys.exit(1)

    if not isinstance(qa_pairs, list) or not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
        for p in qa_pairs
    ):
        _root.console.print(
            "[red]Pairs must be a JSON list of [query, answer] string pairs, "
            "e.g. '[['Q1','A1'],['Q2','A2']]'[/red]"
        )
        sys.exit(1)

    mem_ids = (
        [s.strip() for s in source_ids.split(",") if s.strip()]
        if source_ids else None
    )

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Storing {len(qa_pairs)} answers in batch..."
    ):
        results = cp.store_answers(
            qa_pairs=qa_pairs,
            workspace_id=workspace,
            source_memory_ids=mem_ids,
        )

    n_stored = len(results)
    n_entities = sum(len(r.get("entities", [])) for r in results)
    _quiet_print(
        f"[green]Batch stored {n_stored} answers[/green] "
        f"([yellow]{n_entities}[/yellow] total entities)"
    )

    if _root._current_output_format == "json":
        print_json(results)
