"""Peer profiles"""

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
# profile commands
# ===================================================================


@cli.group()
def profile() -> None:
    """Manage peer profiles."""


@profile.command(name="get")
@click.argument("peer_id")
def profile_get(peer_id: str) -> None:
    """Retrieve the profile for a peer."""
    with _root.console.status(f"Fetching profile for peer '{peer_id}'..."):
        rows = _sdk_client().get_profile(peer_id)
    print_table(rows, title=f"Profile (peer: {peer_id})")


@profile.command(name="upsert")
@click.argument("peer_id")
@click.option("--static-facts", default="[]", help="JSON array of static facts",
              callback=parse_json_flag)
@click.option("--dynamic-context", default="[]", help="JSON array of dynamic context",
              callback=parse_json_flag)
@click.option("--preferences", default="{}", help="JSON object of preferences",
              callback=parse_json_flag)
@click.option("--tags", default="[]", help="JSON array of tags",
              callback=parse_json_flag)
def profile_upsert(peer_id: str, static_facts: str, dynamic_context: str,
                   preferences: str, tags: str) -> None:
    """Create or update a peer profile."""
    with _root.console.status(f"Upserting profile for peer '{peer_id}'..."):
        result = _sdk_client().upsert_profile(
            peer_id, static_facts, dynamic_context, preferences, tags,
        )
    _quiet_print(f"[green]Profile for peer '{peer_id}' updated.[/green]")
    if result:
        print_json(result)
