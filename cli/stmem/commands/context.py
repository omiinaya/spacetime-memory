"""Context pack / delta agent"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
    print_json,
    print_table,
)

# ===================================================================
# context — context pack / delta agent
# ===================================================================


@cli.group()
def context() -> None:
    """Query the context pack and delta system."""


@context.command(name="pack")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--token-budget", default=4096, type=int, help="Max tokens")
@click.option("--peer-id", default="cli", help="Peer requesting the pack")
def context_pack(workspace_id: str, query: str, token_budget: int,
                 peer_id: str) -> None:
    """Generate a context pack for a query and print results."""
    client = _sdk_client()
    with _root.console.status("Generating context pack..."):
        client._call("generate_context_pack", [
            workspace_id, query, token_budget, peer_id, "",
        ])
        rows = client.list_context_packs(workspace_id)

    if not rows:
        _root.console.print("[yellow]No context pack generated.[/yellow]")
        return

    pack = rows[0]
    print_json(pack)

    print_table(
        client.list_context_entries(pack.get("id", "")),
        title="Context entries",
    )


@context.command(name="delta")
@click.argument("previous_pack_id")
def context_delta(previous_pack_id: str) -> None:
    """Compute and show the delta from a previous pack."""
    client = _sdk_client()
    with _root.console.status("Computing delta..."):
        client._call("get_delta", [previous_pack_id])
        rows = client.list_context_deltas(previous_pack_id)
    print_table(rows, title=f"Delta from {previous_pack_id[:16]}...")
