"""CLI commands — kg module."""

from __future__ import annotations

import click
from rich.table import Table, box

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
    parse_json_flag,
    print_json,
    print_table,
)


@cli.group(name="kg")
def kg() -> None:
    """Manage the knowledge graph."""


@kg.group(name="node")
def kg_node() -> None:
    """Manage knowledge graph nodes."""


@kg_node.command(name="create")
@click.argument("workspace_id")
@click.argument("label")
@click.argument("node_type",
                type=click.Choice(["code", "concept", "entity", "document", "topic"]))
@click.option("--summary", default="", help="Node summary")
@click.option("--metadata", default="{}", help="JSON metadata",
              callback=parse_json_flag)
def kg_node_create(workspace_id: str, label: str, node_type: str,
                   summary: str, metadata: str) -> None:
    """Create a knowledge graph node and index it for semantic search."""
    with console.status(f"Creating KG node '{label}'..."):
        result = _sdk_client().create_node(workspace_id, label, node_type, summary, metadata)
    _quiet_print(f"[green]KG node '{label}' created.[/green]")
    if result:
        print_json(result)


@kg.group(name="edge")
def kg_edge() -> None:
    """Manage knowledge graph edges."""


@kg_edge.command(name="create")
@click.argument("workspace_id")
@click.argument("source_node_id")
@click.argument("target_node_id")
@click.argument("relation")
@click.option("--weight", default=1.0, type=float, help="Edge weight")
@click.option("--confidence", default="EXTRACTED",
              type=click.Choice(["EXTRACTED", "INFERRED", "AMBIGUOUS"]),
              help="Confidence level")
@click.option("--metadata", default="{}", help="JSON metadata",
              callback=parse_json_flag)
def kg_edge_create(workspace_id: str, source_node_id: str,
                   target_node_id: str, relation: str,
                   weight: float, confidence: str, metadata: str) -> None:
    """Create a knowledge graph edge."""
    with console.status(f"Creating edge '{relation}'..."):
        result = _sdk_client()._call("create_edge", [
            workspace_id, source_node_id, target_node_id,
            relation, weight, confidence, metadata,
        ])
    _quiet_print(f"[green]Edge '{relation}' created.[/green]")
    if result:
        print_json(result)


@kg.command(name="query")
@click.argument("workspace_id")
@click.argument("query")
def kg_query(workspace_id: str, query: str) -> None:
    """Search knowledge graph nodes by label."""
    with console.status(f"Searching KG nodes for '{query}'..."):
        rows = _sdk_client().query_graph(workspace_id, query)
    print_table(rows, title=f"KG nodes matching '{query}'")


@kg.command(name="neighbors")
@click.argument("node_id")
def kg_neighbors(node_id: str) -> None:
    """Get neighbors of a node in the knowledge graph."""
    with console.status(f"Fetching neighbors for node '{node_id}'..."):
        rows = _sdk_client().get_neighbors(node_id)
    print_table(rows, title=f"Neighbors of node '{node_id}'")


@kg.command(name="bridges")
@click.argument("workspace_id")
@click.option("--limit", default=20, type=int, help="Max bridge nodes")
@click.option("--min-communities", default=2, type=int,
              help="Minimum communities to qualify as bridge (default: 2)")
@click.pass_context
def kg_bridges(ctx: click.Context, workspace_id: str, limit: int,
               min_communities: int) -> None:
    """Detect bridge nodes — concepts connecting multiple communities."""
    with console.status("Detecting bridge nodes..."):
        rows = _sdk_client().detect_bridge_nodes(
            workspace_id, limit=limit, min_communities=min_communities,
        )
    if rows:
        for r in rows:
            score = r.get("bridge_score", 0.0)
            bar = "█" * int(score * 20)
            label = r.get("node_label", r.get("node_id", ""))[:60]
            console.print(
                f"[cyan]{bar}[/cyan] "
                f"score={score:.2f} "
                f"communities={r.get('community_count', 0)} "
                f"[bold]{label}[/bold]"
            )
        if ctx.obj.get("output") == "json":
            print_json(rows)
    else:
        console.print("[yellow]No bridge nodes found.[/yellow]")


@kg.command(name="stats")
@click.argument("workspace_id")
def kg_stats(workspace_id: str) -> None:
    """Show knowledge graph statistics."""
    with console.status("Computing graph statistics..."):
        stats = _sdk_client().compute_kg_stats(workspace_id)
    if stats:
        from rich import box
        from rich.table import Table
        table = Table(title=f"KG Stats ({workspace_id[:12]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Nodes", str(stats.get("node_count", 0)))
        table.add_row("Edges", str(stats.get("edge_count", 0)))
        table.add_row("Communities", str(stats.get("community_count", 0)))
        table.add_row("Avg Degree", f"{stats.get('avg_degree', 0):.1f}")
        table.add_row("Unassigned (no community)", str(stats.get("unassigned_nodes", 0)))
        table.add_row("Orphans (no edges)", str(stats.get("orphan_nodes", 0)))
        console.print(table)
    else:
        console.print("[yellow]No knowledge graph data — add some nodes first.[/yellow]")


@kg.command(name="add-node-citation")
@click.argument("workspace_id")
@click.argument("node_id")
@click.argument("memory_id")
@click.option("--description", default="",
              help="Description of the citation relationship")
def kg_add_node_citation(workspace_id: str, node_id: str,
                         memory_id: str, description: str) -> None:
    """Add a citation linking a KG node to a source memory.

    Citations provide provenance: they record which memory (raw source,
    note, or observation) supports a particular knowledge-graph node.
    """
    with console.status("Adding node citation..."):
        result = _sdk_client().add_node_citation(
            workspace_id, node_id, memory_id, description,
        )
    _quiet_print("[green]Citation added to node.[/green]")
    if result:
        print_json(result)


@kg.command(name="add-edge-citation")
@click.argument("workspace_id")
@click.argument("edge_id")
@click.argument("memory_id")
@click.option("--description", default="",
              help="Description of the citation relationship")
def kg_add_edge_citation(workspace_id: str, edge_id: str,
                         memory_id: str, description: str) -> None:
    """Add a citation linking a KG edge to a source memory.

    Citations provide provenance for edges — useful for marking which
    source memory supports a particular relationship between nodes.
    """
    with console.status("Adding edge citation..."):
        result = _sdk_client().add_edge_citation(
            workspace_id, edge_id, memory_id, description,
        )
    _quiet_print("[green]Citation added to edge.[/green]")
    if result:
        print_json(result)


@kg.command(name="get-citations")
@click.argument("workspace_id")
@click.argument("entity_id")
@click.option("--entity-type", default="node",
              type=click.Choice(["node", "edge"]),
              help="Entity type: 'node' (default) or 'edge'")
def kg_get_citations(workspace_id: str, entity_id: str,
                     entity_type: str) -> None:
    """Get all citations for a KG entity (node or edge).

    Citations link KG nodes/edges back to the source memories that
    support them. Use this to trace provenance for any KG entity.
    """
    with console.status(f"Fetching citations for {entity_type} '{entity_id}'..."):
        rows = _sdk_client().get_citations(workspace_id, entity_id, entity_type)
    if rows:
        print_table(rows, title=f"Citations for {entity_type} '{entity_id[:40]}'")
    else:
        console.print("[yellow]No citations found for this entity.[/yellow]")


@kg.command(name="ripple-detect")
@click.argument("source_id")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--max-hops", default=2, type=int, help="Max graph-traversal depth (default: 2)")
@click.option("--include-notes", is_flag=True, help="Include notes/memories in results alongside KG nodes")
def kg_ripple_detect(source_id: str, workspace: str, max_hops: int,
                     include_notes: bool) -> None:
    """Detect which KG nodes need re-summarization when SOURCE_ID is updated.

    Walks the knowledge graph outward from SOURCE_ID, following edges to
    find all entities that may have stale summaries.  SOURCE_ID can be a
    kg_node, note, or memory ID.

    Example:

        stmem kg ripple-detect note_abc123
        stmem kg ripple-detect node_xyz --workspace my-ws --max-hops 3
        stmem kg ripple-detect mem_456 --include-notes
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Detecting ripple effects from '{source_id}' (max {max_hops} hops)..."
    ):
        result = cp.detect_ripple_effects(
            source_id=source_id,
            workspace_id=workspace,
            max_hops=max_hops,
            include_notes=include_notes,
        )

    stats = result.get("stats", {})
    src = result.get("source", {})

    # Source info
    src_type = src.get("type", "unknown")
    src_label = src.get("label", source_id[:12])
    console.print(f"\n[bold]Ripple effects from[/bold] [cyan]{src_label}[/cyan] "
                  f"({src_type}, id={source_id[:16]}...)")

    # Summary line
    total = stats.get("total_entities", 0)
    need_review = stats.get("kg_nodes_needing_review", 0)
    direct = stats.get("direct_count", 0)
    transitive = stats.get("transitive_count", 0)
    hops = stats.get("max_hops_reached", 0)
    console.print(
        f"[dim]Found {total} connected entities "
        f"({direct} direct, {transitive} transitive) "
        f"across {hops} hop(s). "
        f"{need_review} KG node(s) need re-summarization.[/dim]"
    )

    # Directly affected table
    directly = result.get("directly_affected", [])
    if directly:
        table = Table(title=f"Directly Affected ({len(directly)})", box=box.ROUNDED)
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Entity", style="cyan")
        table.add_column("Type")
        if include_notes:
            table.add_column("Entity Type")
        table.add_column("Relation")
        for ent in directly:
            eid = ent.get("id", "?")[:12]
            label = ent.get("label", "?")
            ntype = ent.get("node_type", ent.get("entity_type", "?"))
            path = ent.get("ripple_path", [])
            rel = path[0].get("relation", "?") if path else "?"
            row = [eid, label[:40], ntype[:15]]
            if include_notes:
                row.append(ent.get("entity_type", "?"))
            row.append(rel)
            table.add_row(*row)
        console.print(table)

    # Transitively affected
    transitive_list = result.get("transitively_affected", [])
    if transitive_list:
        table2 = Table(title=f"Transitively Affected ({len(transitive_list)})", box=box.ROUNDED)
        table2.add_column("Hop", style="dim")
        table2.add_column("ID", style="dim", no_wrap=True)
        table2.add_column("Entity", style="cyan")
        table2.add_column("Type")
        for ent in transitive_list:
            eid = ent.get("id", "?")[:12]
            label = ent.get("label", "?")
            ntype = ent.get("node_type", ent.get("entity_type", "?"))
            hop = str(ent.get("hop", "?"))
            table2.add_row(hop, eid, label[:40], ntype[:15])
        console.print(table2)

    # Needs review call to action
    needs_review = result.get("needs_review", [])
    if needs_review:
        console.print(
            f"\n[bold yellow]! {len(needs_review)} KG node(s) need re-summarization.[/bold yellow] "
            "[dim]Use `stmem kg ripple-apply` to re-summarize them automatically, "
            "or pass the node IDs above to trigger ripple updates.[/dim]"
        )


@kg.command(name="ripple-apply")
@click.argument("source_id")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--max-hops", default=2, type=int, help="Max graph-traversal depth (default: 2)")
@click.option("--dry-run", is_flag=True, help="Preview which nodes would be updated without making changes")
def kg_ripple_apply(source_id: str, workspace: str, max_hops: int,
                    dry_run: bool) -> None:
    """Detect AND re-summarize nodes affected by a SOURCE_ID update.

    Combines detection + update into one step: finds all KG nodes that may
    have stale summaries when SOURCE_ID is updated, then merges new info into
    each node's summary via LLM.

    Use ``--dry-run`` to see what would be updated without making changes.

    Examples:

        stmem kg ripple-apply note_abc123
        stmem kg ripple-apply node_xyz --workspace my-ws --max-hops 3 --dry-run
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    # Step 1: Detect
    with console.status(
        f"Detecting ripple effects from '{source_id}' (max {max_hops} hops)..."
    ):
        detection = cp.detect_ripple_effects(
            source_id=source_id,
            workspace_id=workspace,
            max_hops=max_hops,
        )

    stats = detection.get("stats", {})
    src = detection.get("source", {})
    total = stats.get("total_entities", 0)
    need_review = stats.get("kg_nodes_needing_review", 0)

    if total == 0:
        console.print("[yellow]No connected entities found -- nothing to update.[/yellow]")
        return

    src_label = src.get("label", source_id[:12])
    console.print(
        f"\n[bold]Ripple effects from[/bold] [cyan]{src_label}[/cyan]: "
        f"[dim]{total} connected, {need_review} need review[/dim]"
    )

    # Step 2: Get source content for the LLM merge prompt
    new_info = ""
    if not dry_run:
        source_type = src.get("type", "")
        source_id_val = src.get("id", source_id)
        with console.status("Fetching source content..."):
            try:
                if source_type == "note":
                    notes = client._query("note", workspace_id=workspace,
                                          filter_dict={"id": source_id_val})
                    if notes:
                        new_info = notes[-1].get("content", "")
                elif source_type == "memory":
                    mems = client._query("memory", workspace_id=workspace,
                                         filter_dict={"id": source_id_val})
                    if mems:
                        new_info = mems[-1].get("content", "")
                elif source_type == "kg_node":
                    nodes = client._query("kg_node", workspace_id=workspace,
                                          filter_dict={"id": source_id_val})
                    if nodes:
                        new_info = nodes[-1].get("summary", "")
            except RuntimeError:
                new_info = ""

    # Step 3: Apply updates
    if dry_run:
        prefix = "[dim][dry-run][/dim] "
    else:
        prefix = ""

    with console.status(
        f"{prefix}Applying ripple updates to {need_review} node(s)..."
    ):
        update_result = cp.apply_ripple_updates(
            detection_result=detection,
            new_information=new_info or "Updated information from source",
            source_note_id=source_id,
            workspace_id=workspace,
            dry_run=dry_run,
        )

    up_stats = update_result.get("stats", {})
    updated_count = up_stats.get("updated_count", 0)
    skipped_count = up_stats.get("skipped_count", 0)

    if updated_count:
        console.print(
            f"[green]Updated {updated_count} node(s)[/green] "
            f"[dim]({skipped_count} skipped, {up_stats.get('total', 0)} total)[/dim]"
        )

        upd_table = Table(title=f"Updated Nodes ({updated_count})", box=box.ROUNDED)
        upd_table.add_column("ID", style="dim", no_wrap=True)
        upd_table.add_column("Entity", style="cyan")
        upd_table.add_column("Status", style="green")
        for ent in update_result.get("updated", []):
            eid = ent.get("node_id", "?")[:12]
            label = ent.get("label", "?")
            status = "[dim]dry-run[/dim]" if dry_run else "[green]updated[/green]"
            upd_table.add_row(eid, label[:40], status)
        console.print(upd_table)

    if skipped_count:
        skip_table = Table(title=f"Skipped Nodes ({skipped_count})", box=box.ROUNDED)
        skip_table.add_column("ID", style="dim")
        skip_table.add_column("Entity", style="cyan")
        skip_table.add_column("Reason", style="yellow")
        for ent in update_result.get("skipped", []):
            eid = ent.get("node_id", "?")[:12]
            label = ent.get("label", "?")
            reason = ent.get("reason", "?")
            skip_table.add_row(eid, label[:40], reason)
        console.print(skip_table)

