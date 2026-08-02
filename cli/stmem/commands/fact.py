"""Peer facts"""

from __future__ import annotations

import json
import time
from typing import Any

import click


from .. import root as _root
from ..root import (
    _esc,
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
    print_table,
)

# ===================================================================
# fact commands
# ===================================================================


@cli.group()
def fact() -> None:
    """Manage peer facts."""


@fact.command(name="add")
@click.argument("workspace_id")
@click.argument("peer_id")
@click.argument("content")
@click.option("--type", "fact_type", default="dynamic", type=click.Choice(["static", "dynamic"]))
@click.option("--category", default="custom", type=click.Choice(["preference", "behavior", "knowledge", "relationship", "custom"]))
@click.option("--confidence", default=0.8, type=float)
@click.option("--source", default="manual", type=click.Choice(["manual", "extracted", "inferred", "imported"]))
@click.option("--tier", default="L1", type=click.Choice(["L0", "L1", "L2"]))
def fact_add(workspace_id: str, peer_id: str, content: str,
             fact_type: str, category: str, confidence: float,
             source: str, tier: str) -> None:
    """Add a new fact about a peer."""
    with _root.console.status("Adding fact..."):
        _sdk_client()._call("add_fact", [workspace_id, peer_id, fact_type, category, content, confidence, source, tier])
    _quiet_print("[green]Fact added successfully.[/green]")


@fact.command(name="list")
@click.argument("workspace_id")
@click.option("--peer", default="")
@click.option("--type", "fact_type", default="")
@click.option("--tier", default="")
@click.option("--category", default="")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def fact_list(ctx: click.Context, workspace_id: str, peer: str, fact_type: str,
              tier: str, category: str, watch: bool) -> None:
    """List facts for a workspace with optional filters."""
    client = _sdk_client()

    def _run() -> list[dict[str, Any]]:
        query_hash = f"{workspace_id}:{peer}:{fact_type}:{tier}:{category}"
        with _root.console.status("Listing facts..."):
            client._call("list_facts", [workspace_id, peer, fact_type, tier, category])
            rows = client._query(
                "fact_result",
                filter_dict={"query_hash": query_hash},
            )
        facts: list[dict[str, Any]] = []
        if rows:
            try:
                facts = json.loads(rows[0].get("json_data", "[]"))
            except (json.JSONDecodeError, IndexError):
                pass
        return facts

    def _display(rows: list[dict[str, Any]]) -> None:
        print_table(rows, title=f"Facts (workspace: {workspace_id})",
                    output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                _root.console.clear()
                rows = _run()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run()
        _display(rows)


@fact.command(name="search")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--tier", default="")
def fact_search(workspace_id: str, query: str, tier: str) -> None:
    """Search facts by content (LIKE / substring match)."""
    client = _sdk_client()
    with _root.console.status("Searching facts..."):
        client._call("search_facts", [workspace_id, query, tier])
        rows = client._query(
            "fact_result",
            filter_dict={"workspace_id": workspace_id},
        )
    facts = []
    if rows:
        try:
            facts = json.loads(rows[0].get("json_data", "[]"))
        except (json.JSONDecodeError, IndexError):
            pass
    if facts:
        facts.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
        facts = facts[:50]
    print_table(facts, title=f"Fact search: '{query}'")


@fact.command(name="get")
@click.argument("fact_id")
def fact_get(fact_id: str) -> None:
    """Get a single fact by ID."""
    with _root.console.status(f"Fetching fact '{fact_id[:16]}'..."):
        rows = _sdk_client()._sql_param("SELECT * FROM fact WHERE id = ?", fact_id)
    if rows:
        print_json(rows[0])
    else:
        _root.console.print(f"[yellow]Fact '{fact_id[:16]}...' not found.[/yellow]")


@fact.command(name="update")
@click.argument("fact_id")
@click.option("--content", default="")
@click.option("--confidence", type=float, default=None)
@click.option("--tier", type=click.Choice(["L0", "L1", "L2", ""]), default="")
@click.option("--category", default="")
def fact_update(fact_id: str, content: str, confidence: float | None,
                tier: str, category: str) -> None:
    """Update a fact's content, confidence, category, and/or tier."""
    tier_val = tier if tier else ""
    client = _sdk_client()
    with _root.console.status(f"Updating fact '{fact_id[:16]}...'..."):
        client._call("update_fact", [fact_id, content, confidence if confidence else 0.0, category, tier_val])
    _quiet_print(f"[green]Fact '{fact_id[:16]}...' updated.[/green]")


@fact.command(name="delete")
@click.argument("fact_id")
def fact_delete(fact_id: str) -> None:
    """Deactivate a fact (soft delete)."""
    with _root.console.status(f"Deleting fact '{fact_id[:16]}...'..."):
        _sdk_client()._call("delete_fact", [fact_id])
    _quiet_print(f"[green]Fact '{fact_id[:16]}...' deactivated.[/green]")
