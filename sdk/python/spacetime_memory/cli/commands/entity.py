"""Entity resolution and dedup CLI commands"""

from __future__ import annotations

import click

from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
    print_json,
)

# ===================================================================
# entity — entity resolution, dedup, and merge
# ===================================================================


@cli.group()
def entity() -> None:
    """Extract entities, resolve names, dedup and merge."""


@entity.command(name="extract")
@click.argument("workspace_id")
@click.argument("content")
def entity_extract(workspace_id: str, content: str) -> None:
    """Extract entities from text content and create KG nodes."""
    client = _sdk_client()
    client.extract_entities(workspace_id, content)
    _root.console.print("[green]Entities extracted.[/green]")


# ------------------------------------------------------------------
# stmem entity resolve
# ------------------------------------------------------------------


@entity.command(name="resolve")
@click.argument("workspace_id")
@click.argument("name")
@click.option("--type", "entity_type", default="", help="Expected entity type hint")
@click.option("--description", default=None, help="Entity description for LLM context")
def entity_resolve(
    workspace_id: str,
    name: str,
    entity_type: str,
    description: str | None,
) -> None:
    """Resolve an entity name using the full three-phase pipeline."""
    client = _sdk_client()
    result = client.resolve_entity(
        workspace_id=workspace_id,
        name=name,
        entity_type=entity_type,
        description=description,
    )
    if _root._current_output_format == "json":
        print_json(result)
    else:
        phase = result.get("phase", "none")
        if result.get("resolved"):
            _root.console.print(
                f"[green]Resolved[/green] '{name}' → "
                f"[bold]{result.get('entity_name', '')}[/bold] "
                f"(id={result.get('entity_id', '')}, "
                f"phase={phase})"
            )
        else:
            _root.console.print(
                f"[yellow]Not resolved[/yellow] '{name}' "
                f"(phase={phase})"
            )


# ------------------------------------------------------------------
# stmem entity dedup
# ------------------------------------------------------------------


@entity.command(name="dedup")
@click.argument("workspace_id")
@click.option("--dry-run", is_flag=True, default=True, help="Dry-run mode (default: true)")
@click.option("--no-dry-run", is_flag=True, help="Actually perform merges")
def entity_dedup(workspace_id: str, dry_run: bool, no_dry_run: bool) -> None:
    """Scan entities and find duplicates using the resolution pipeline."""
    actual_dry_run = dry_run and not no_dry_run
    client = _sdk_client()
    result = client.deduplicate_entities(
        workspace_id=workspace_id,
        dry_run=actual_dry_run,
    )
    if _root._current_output_format == "json":
        print_json(result)
    else:
        _root.console.print(
            f"[cyan]Scanned:[/cyan] {result.get('scanned', 0)} entities, "
            f"[yellow]duplicates:[/yellow] {result.get('duplicates_found', 0)}"
        )
        if actual_dry_run:
            _root.console.print("[yellow]Dry-run mode — no changes made.[/yellow]")
            for m in result.get("merges", []):
                _root.console.print(
                    f"  Would merge: {m.get('entity_a_name', '?')} → "
                    f"{m.get('entity_b_name', '?')} "
                    f"(sim={m.get('similarity', 0):.3f})"
                )
        else:
            _root.console.print(
                f"[green]Merges performed:[/green] {result.get('merges_performed', 0)}"
            )


# ------------------------------------------------------------------
# stmem entity merge
# ------------------------------------------------------------------


@entity.command(name="merge")
@click.argument("workspace_id")
@click.argument("source_id")
@click.argument("target_id")
def entity_merge(workspace_id: str, source_id: str, target_id: str) -> None:
    """Merge source entity into target entity."""
    client = _sdk_client()
    result = client.merge_entities(
        workspace_id=workspace_id,
        source_id=source_id,
        target_id=target_id,
    )
    if _root._current_output_format == "json":
        print_json(result)
    else:
        _root.console.print(
            f"[green]Merged[/green] '{result.get('source_name', '?')}' "
            f"→ '{result.get('target_name', '?')}'"
        )


# ------------------------------------------------------------------
# stmem entity dedup-edges
# ------------------------------------------------------------------


@entity.command(name="dedup-edges")
@click.argument("workspace_id")
def entity_dedup_edges(workspace_id: str) -> None:
    """Find and merge duplicate KG edges."""
    client = _sdk_client()
    result = client.deduplicate_edges(workspace_id=workspace_id)
    if _root._current_output_format == "json":
        print_json(result)
    else:
        _root.console.print(
            f"[cyan]Duplicate edges found:[/cyan] {result.get('duplicates_found', 0)}, "
            f"[green]merged:[/green] {result.get('merged', 0)}"
        )
        if result.get("errors"):
            _root.console.print("[red]Errors:[/red]")
            for err in result["errors"]:
                _root.console.print(f"  [red]{err}[/red]")
