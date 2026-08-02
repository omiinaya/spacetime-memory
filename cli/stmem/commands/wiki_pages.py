"""Wiki page commands (entity/concept/comparison pages)"""

from __future__ import annotations


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

# ── Entity Page ────────────────────────────────────────────────────────���──────

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
    with _root.console.status(f"Creating entity page '{name}'..."):
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
        _root.console.print("[red]Failed to create entity page. Check STDB connection and your inputs.[/red]")
        _root.console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Update Entity Page ─────────────────────────────────────────────────────────

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
    with _root.console.status(f"Updating entity page '{name}'..."):
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
        _root.console.print(f"[red]Entity page '{name}' not found. List existing entities:[/red]")
        _root.console.print("  [dim]→ stmem search-entities --label <keyword>[/dim]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Concept Page ──────────────────────────────────────────────────────────────

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
    with _root.console.status(f"Creating concept page '{concept}'..."):
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
        _root.console.print("[red]Failed to create concept page. Check STDB connection.[/red]")
        _root.console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Comparison Page ───────────────────────────────────────────────────────────

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
    with _root.console.status(f"Creating comparison page '{title}'..."):
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
        _root.console.print("[red]Failed to create comparison page. Check STDB connection.[/red]")
        _root.console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _root._current_output_format == "json":
        print_json(result)


# ── Search Entities ───────────────────────────────────────────────────────────

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
    with _root.console.status("Searching entities..."):
        results = cp.search_entities(
            workspace_id=workspace,
            label=label,
            node_type=node_type,
            semantic_query=semantic_query,
            limit=limit,
        )

    if not results:
        _root.console.print("[yellow]No entities found.[/yellow]")
        if _root._current_output_format == "json":
            print_json([])
        return

    if _root._current_output_format == "json":
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
    _root.console.print(table)
