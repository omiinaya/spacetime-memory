"""CLI commands — compounder commands."""

from __future__ import annotations

import sys

import click
from rich import box
from rich.table import Table

from ..root import (
    _current_output_format,
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
)


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

    with console.status(
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
        console.print("[yellow]Workspace is empty. Nothing to generate.[/yellow]")

    if _current_output_format == "json":
        print_json(result)


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

    with console.status(
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
        console.print(f"\n[bold]Orphan nodes ({len(orphans)}):[/bold]")
        for o in orphans[:20]:
            console.print(f"  • {o.get('label', o.get('id', '?'))[:12]} — {o.get('node_type', '?')}")
        if len(orphans) > 20:
            console.print(f"  ... and {len(orphans) - 20} more")
    else:
        console.print("[green]No orphan nodes.[/green]")

    if crossrefs:
        console.print(f"\n[bold]Missing cross-references ({len(crossrefs)}):[/bold]")
        for cr in crossrefs[:10]:
            console.print(f"  • Note [cyan]{cr.get('note_title', cr.get('note_id', '?'))[:30]}[/cyan] mentions entity [yellow]{cr.get('entity', '?')}[/yellow] with no KG edge")
        if len(crossrefs) > 10:
            console.print(f"  ... and {len(crossrefs) - 10} more")
    elif not no_crossrefs:
        console.print("[green]Cross-references are clean.[/green]")

    if contradictions:
        console.print(f"\n[bold yellow]Contradictions found ({len(contradictions)}):[/bold yellow]")
        for c in contradictions[:5]:
            console.print(f"  • {c.get('note_id', '?')[:12]} vs {c.get('contradicts_note_id', '?')[:12]}")
            note_id = c.get("contradiction_note_id", "")
            if note_id:
                console.print(f"    → contradiction note: [cyan]{note_id[:16]}...[/cyan]")
        if len(contradictions) > 5:
            console.print(f"  ... and {len(contradictions) - 5} more")
    elif not no_contradictions:
        console.print("[green]No contradictions detected.[/green]")

    if not orphans and not crossrefs and not contradictions:
        console.print("[green]Workspace is clean![/green]")

    if _current_output_format == "json":
        print_json(result)


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

    with console.status(
        f"Cross-linking workspace '{workspace}'..."
    ):
        result = cp.cross_link(workspace_id=workspace)

    links = result.get("links_created", [])
    if dry_run and links:
        console.print(
            f"[yellow]DRY RUN:[/yellow] Would create {len(links)} edges"
        )
    elif links:
        console.print(
            f"[green]Created {len(links)} new cross-links.[/green]"
        )
    else:
        console.print("[green]No new cross-links found.[/green]")

    if _current_output_format == "json":
        print_json(result)


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

    with console.status(
        f"Finding connection suggestions for '{workspace}'..."
    ):
        result = cp.suggest_connections(
            workspace_id=workspace,
            limit=limit,
        )

    suggestions = result if isinstance(result, list) else result.get("suggestions", [])
    if suggestions:
        console.print(
            f"\n[bold]Suggested connections ({len(suggestions)}):[/bold]"
        )
        for s in suggestions[:20]:
            src = s.get("source_label", s.get("source", "?"))[:25]
            tgt = s.get("target_label", s.get("target", "?"))[:25]
            score = s.get("score", s.get("shared_neighbors", 0))
            console.print(f"  • [cyan]{src}[/cyan] ↔ [yellow]{tgt}[/yellow]  (score: {score})")
    else:
        console.print("[green]No connection suggestions found.[/green]")

    if _current_output_format == "json":
        print_json(result)


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

    with console.status(
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
        console.print("[red]Failed to store answer. Check STDB connection and that OPENAI_API_KEY is set.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


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
            console.print(f"[red]File not found: {pairs_file}[/red]")
            console.print("  [dim]→ Check the file path and try again[/dim]")
            sys.exit(1)
        except OSError as e:
            console.print(f"[red]Error reading {pairs_file}: {e}[/red]")
            sys.exit(1)
    else:
        raw = pairs

    try:
        qa_pairs = _json.loads(raw)
    except _json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON in pairs: {e}[/red]")
        sys.exit(1)

    if not isinstance(qa_pairs, list) or not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
        for p in qa_pairs
    ):
        console.print(
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

    with console.status(
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

    if _current_output_format == "json":
        print_json(results)


@cli.command(name="entity-page")
@click.option("--name", "-n", required=True, help="Entity name (page title + node label)")
@click.option("--description", "-d", required=True, help="2-3 sentence description")
@click.option("--type", "-t", "entity_type", default="concept",
              type=click.Choice(["person", "org", "concept", "product", "location", "event", "topic"]),
              help="Entity type")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--tags", help="Comma-separated tags")
@click.option("--related", help="Related entity names (comma-separated)")
def entity_page_cmd(name: str, description: str, entity_type: str,
                    workspace: str, tags: str | None,
                    related: str | None) -> None:
    """Create a structured entity wiki page + KG node.

    Creates both a markdown note with YAML frontmatter and a typed
    knowledge graph node. Use for any named entity: person, org,
    concept, product, location, event, or topic.
    """
    from spacetime_memory.compounder import Compounder

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    rel_list = (
        [{"name": r.strip(), "relation": "related_to"}
         for r in related.split(",") if r.strip()]
        if related else None
    )

    cp = Compounder(_sdk_client())
    with console.status(f"Creating entity page '{name}'..."):
        result = cp.create_entity_page(
            name=name,
            description=description,
            entity_type=entity_type,
            workspace_id=workspace,
            tags=tag_list,
            relations=rel_list,
        )

    note = result.get("note", {})
    node = result.get("node", {})
    if note.get("id"):
        _quiet_print(f"[green]Entity page created:[/green] [cyan]{name}[/cyan] ({entity_type})")
        if node.get("id"):
            _quiet_print(f"  KG node: [yellow]{node['id'][:16]}...[/yellow]")
    else:
        console.print("[red]Failed to create entity page. Check STDB connection and your inputs.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


@cli.command(name="update-entity-page")
@click.option("--name", "-n", required=True, help="Entity name to update")
@click.option("--description", "-d", default=None, help="New 2-3 sentence description")
@click.option("--type", "-t", "entity_type", default=None,
              type=click.Choice(["person", "org", "concept", "product", "location", "event", "topic"]),
              help="New entity type")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
def update_entity_page_cmd(name: str, description: str | None,
                           entity_type: str | None, workspace: str) -> None:
    """Update an existing entity wiki page + KG node.

    Finds the entity by name and updates the provided fields.
    Unset fields are left unchanged.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(_sdk_client())
    with console.status(f"Updating entity page '{name}'..."):
        result = cp.update_entity_page(
            name=name,
            description=description,
            entity_type=entity_type,
            workspace_id=workspace,
        )

    if result.get("note", {}).get("id"):
        _quiet_print(f"[green]Entity page updated:[/green] [cyan]{name}[/cyan]")
        if result.get("node", {}).get("id"):
            _quiet_print(f"  KG node: [yellow]{result['node']['id'][:16]}...[/yellow]")
    else:
        console.print(f"[red]Entity page '{name}' not found. List existing entities:[/red]")
        console.print("  [dim]→ stmem search-entities --label <keyword>[/dim]")

    if _current_output_format == "json":
        print_json(result)


@cli.command(name="concept-page")
@click.option("--concept", "-c", required=True, help="Concept name")
@click.option("--definition", "-d", required=True, help="Concept definition")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--related", help="Related concept names (comma-separated)")
def concept_page_cmd(concept: str, definition: str, workspace: str,
                     related: str | None) -> None:
    """Create a concept definition page with [[wiki-links]].

    Creates a note with YAML frontmatter (type: concept) and a
    structured definition. Related concepts are linked as wiki-links.
    """
    from spacetime_memory.compounder import Compounder

    rel_list = (
        [r.strip() for r in related.split(",") if r.strip()]
        if related else None
    )

    cp = Compounder(_sdk_client())
    with console.status(f"Creating concept page '{concept}'..."):
        result = cp.create_concept_page(
            concept=concept,
            definition=definition,
            workspace_id=workspace,
            related_concepts=rel_list,
        )

    note = result.get("note", {})
    if note.get("id"):
        _quiet_print(f"[green]Concept page created:[/green] [cyan]{concept}[/cyan]")
        if rel_list:
            _quiet_print(f"  Related: {', '.join(rel_list)}")
    else:
        console.print("[red]Failed to create concept page. Check STDB connection.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


@cli.command(name="comparison-page")
@click.option("--title", "-t", required=True, help="Page title (e.g. 'LangGraph vs CrewAI')")
@click.option("--items", "-i", required=True, help="Comma-separated items to compare")
@click.option("--criteria", "-c", default="features,performance,ecosystem",
              help="Comma-separated comparison criteria")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
def comparison_page_cmd(title: str, items: str, criteria: str,
                        workspace: str) -> None:
    """Create a comparison table wiki page.

    Creates a note with YAML frontmatter (type: comparison) and a
    markdown comparison table of the given items across specified
    criteria.
    """
    from spacetime_memory.compounder import Compounder

    item_list = [i.strip() for i in items.split(",") if i.strip()]
    crit_list = [c.strip() for c in criteria.split(",") if c.strip()]

    cp = Compounder(_sdk_client())
    with console.status(f"Creating comparison page '{title}'..."):
        result = cp.create_comparison_page(
            title=title,
            items=item_list,
            workspace_id=workspace,
            criteria=crit_list,
        )

    note = result.get("note", {})
    if note.get("id"):
        _quiet_print(
            f"[green]Comparison page created:[/green] [cyan]{title}[/cyan] "
            f"({len(item_list)} items)"
        )
    else:
        console.print("[red]Failed to create comparison page. Check STDB connection.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


@cli.command(name="search-entities")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--label", "-l", help="Exact entity label to search for")
@click.option("--type", "-t", "node_type",
              help="Entity type (person, org, concept, product, location, event, topic)")
@click.option("--query", "-q", "semantic_query", help="Natural-language semantic query")
@click.option("--limit", type=int, default=20, help="Max results (default: 20)")
def search_entities_cmd(workspace: str, label: str | None, node_type: str | None,
                        semantic_query: str | None, limit: int) -> None:
    """Search knowledge-graph entities with flexible filters.

    Supports label search, type filtering, and semantic search.
    Combine filters to narrow results.

    Examples:

      stmem search-entities --type person

      stmem search-entities --label "RLHF"

      stmem search-entities --type concept --query "machine learning"

      stmem search-entities --query "reinforcement learning" --limit 5
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(_sdk_client())
    with console.status("Searching entities..."):
        results = cp.search_entities(
            workspace_id=workspace,
            label=label,
            node_type=node_type,
            semantic_query=semantic_query,
            limit=limit,
        )

    if not results:
        console.print("[yellow]No entities found.[/yellow]")
        if _current_output_format == "json":
            print_json([])
        return

    if _current_output_format == "json":
        print_json(results)
        return

    table = Table(title=f"Entities ({len(results)} found)", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Label", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Summary")
    for n in results:
        nid = n.get("id", "")[:12]
        label_text = n.get("label", "?")
        ntype = n.get("node_type", "?")
        summary = (n.get("summary", "") or "")[:80]
        table.add_row(nid, label_text, ntype, summary)
    console.print(table)
