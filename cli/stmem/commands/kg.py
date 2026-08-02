"""Knowledge graph"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    parse_json_flag,
    print_json,
    print_table,
)

# ===================================================================
# knowledge-graph commands
# ===================================================================


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
    with _root.console.status(f"Creating KG node '{label}'..."):
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
    with _root.console.status(f"Creating edge '{relation}'..."):
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
    with _root.console.status(f"Searching KG nodes for '{query}'..."):
        rows = _sdk_client().query_graph(workspace_id, query)
    print_table(rows, title=f"KG nodes matching '{query}'")


@kg.command(name="neighbors")
@click.argument("node_id")
def kg_neighbors(node_id: str) -> None:
    """Get neighbors of a node in the knowledge graph."""
    with _root.console.status(f"Fetching neighbors for node '{node_id}'..."):
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
    with _root.console.status("Detecting bridge nodes..."):
        rows = _sdk_client().detect_bridge_nodes(
            workspace_id, limit=limit, min_communities=min_communities,
        )
    if rows:
        for r in rows:
            score = r.get("bridge_score", 0.0)
            bar = "█" * int(score * 20)
            label = r.get("node_label", r.get("node_id", ""))[:60]
            _root.console.print(
                f"[cyan]{bar}[/cyan] "
                f"score={score:.2f} "
                f"communities={r.get('community_count', 0)} "
                f"[bold]{label}[/bold]"
            )
        if ctx.obj.get("output") == "json":
            print_json(rows)
    else:
        _root.console.print("[yellow]No bridge nodes found.[/yellow]")


@kg.command(name="stats")
@click.argument("workspace_id")
def kg_stats(workspace_id: str) -> None:
    """Show knowledge graph statistics."""
    with _root.console.status("Computing graph statistics..."):
        stats = _sdk_client().compute_kg_stats(workspace_id)
    if stats:
        from rich.table import Table
        from rich import box
        table = Table(title=f"KG Stats ({workspace_id[:12]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Nodes", str(stats.get("node_count", 0)))
        table.add_row("Edges", str(stats.get("edge_count", 0)))
        table.add_row("Communities", str(stats.get("community_count", 0)))
        table.add_row("Avg Degree", f"{stats.get('avg_degree', 0):.1f}")
        table.add_row("Unassigned (no community)", str(stats.get("unassigned_nodes", 0)))
        table.add_row("Orphans (no edges)", str(stats.get("orphan_nodes", 0)))
        _root.console.print(table)
    else:
        _root.console.print("[yellow]No knowledge graph data — add some nodes first.[/yellow]")
