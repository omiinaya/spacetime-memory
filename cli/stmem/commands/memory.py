"""Memory commands"""

from __future__ import annotations

import datetime
import time
from typing import Any

import click
from pydantic import BaseModel


from .. import root as _root
from ..root import (
    _esc,
    _quiet_print,
    _sdk_client,
    cli,
    parse_json_flag,
    print_json,
    print_table,
)

# ===================================================================
# memory commands
# ===================================================================


@cli.group()
def memory() -> None:
    """Manage memories."""


@memory.command(name="store")
@click.argument("workspace_id")
@click.argument("peer_id")
@click.argument("content")
@click.option("--observer-id", default="", help="Observer peer ID")
@click.option("--memory-type", default="experience",
              type=click.Choice(["world_fact", "experience", "mental_model"]),
              help="Type of memory")
@click.option("--summary", default="", help="Short summary")
@click.option("--entities-json", default="[]", help="JSON array of entity refs",
              callback=parse_json_flag)
@click.option("--confidence", default=0.8, type=float, help="Confidence 0.0-1.0")
@click.option("--source-session-id", default="", help="Source session ID")
@click.option("--source-message-id", default="", help="Source message ID")
@click.option("--tier", default="",
              type=click.Choice(["", "L0", "L1", "L2"]),
              help="Tier (L0=critical, L1=normal, L2=archival)")
def memory_store(
    workspace_id: str, peer_id: str, content: str,
    observer_id: str, memory_type: str, summary: str,
    entities_json: str, confidence: float,
    source_session_id: str, source_message_id: str,
    tier: str,
) -> None:
    """Store a new memory and index it for semantic search."""
    client = _sdk_client()
    with _root.console.status("Storing memory..."):
        result = client.store(
            workspace_id=workspace_id,
            content=content,
            summary=summary,
            memory_type=memory_type,
            peer_id=peer_id,
            observer_id=observer_id,
            entities_json=entities_json,
            confidence=confidence,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            tier=tier,
        )
    _quiet_print("[green]Memory stored successfully.[/green]")
    if result:
        print_json(result)


@memory.command(name="search")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--memory-type", help="Filter by memory type")
@click.option("--tier", help="Filter by tier (L0/L1/L2)")
@click.option("--limit", default=50, type=int, help="Max results")
@click.option("--semantic/--no-semantic", default=True,
              help="Use semantic (embedding) search")
@click.option("--polyphonic/--no-polyphonic", default=False,
              help="Use polyphonic recall (RRF + diversity penalty)")
@click.option("--mmr-lambda", type=float, default=0.0,
              help="MMR diversity reranking (0.7 default: 70% relevance, 30% diversity)")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.option("--snippet", "-s", is_flag=True,
              help="Show snippet preview (first ~200 chars) instead of full content in table output")
@click.option("--from", "from_ts", default=None,
              help="Show only results created after this timestamp. Accepts ISO-8601 "
                   "(e.g. '2026-06-01' or '2026-06-01T12:00:00Z') or a Unix epoch timestamp.")
@click.option("--to", "to_ts", default=None,
              help="Show only results created before this timestamp. Accepts ISO-8601 "
                   "(e.g. '2026-06-30' or '2026-06-30T12:00:00Z') or a Unix epoch timestamp.")
@click.option("--return-schema", default=None,
              help="Output schema: 'llm' for compact LLM-friendly dicts, or a dotted path "
                   "to a pydantic.BaseModel subclass (e.g. 'spacetime_memory.client._schemas.SearchResult'). "
                   "Default: raw dicts.",
              hidden=True)
@click.pass_context
def memory_search(ctx: click.Context, workspace_id: str, query: str,
                  memory_type: str | None, tier: str | None, limit: int,
                  semantic: bool, polyphonic: bool, watch: bool,
                  mmr_lambda: float, snippet: bool,
                  from_ts: str | None, to_ts: str | None,
                  return_schema: str | None) -> None:
    """Search memories in a workspace."""

    def _parse_timestamp(val: str | None) -> float | None:
        """Parse ISO-8601 string or Unix timestamp. Returns Unix timestamp (float) or None."""
        if val is None:
            return None
        val = val.strip()
        # Try numeric (Unix timestamp)
        try:
            return float(val)
        except ValueError:
            pass
        # Try ISO-8601 datetime
        for fmt in [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                dt = datetime.datetime.strptime(val, fmt)
                return dt.timestamp()
            except ValueError:
                continue
        raise click.BadParameter(
            f"Cannot parse '{val}' as a timestamp. Use ISO-8601 or a Unix epoch number."
        )

    client = _sdk_client()

    def _resolve_return_schema(val: str | None) -> Any:
        """Resolve CLI --return-schema value."""
        if val is None:
            return None
        if val == "llm":
            return "llm"
        # Try dotted-path import for BaseModel subclasses
        try:
            import importlib
            mod_path, _, cls_name = val.rpartition(".")
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            if isinstance(cls, type) and issubclass(cls, BaseModel):
                return cls
        except (ImportError, AttributeError, ValueError):
            raise click.BadParameter(
                f"Cannot resolve '{val}' as a pydantic.BaseModel subclass. "
                "Use 'llm' or a dotted path like 'spacetime_memory.client._schemas.SearchResult'."
            )
        return val

    resolved_schema = _resolve_return_schema(return_schema)

    def _run_search() -> list[dict[str, Any]]:
        with _root.console.status("Searching..."):
            return client.search(
                workspace_id=workspace_id,
                query=query,
                memory_type=memory_type or "",
                tier=tier or "",
                limit=limit,
                semantic=semantic,
                polyphonic=polyphonic,
                mmr_lambda=mmr_lambda,
                before=_parse_timestamp(to_ts),
                after=_parse_timestamp(from_ts),
                return_schema=resolved_schema,
            )

    def _display(rows: list[dict[str, Any]]) -> None:
        if snippet:
            # Replace verbose content fields with snippet preview
            for r in rows:
                r["memory_content"] = r.get("snippet", "")
                r.pop("content", None)
        print_table(rows, title=f"Search results (workspace: {workspace_id})",
                    output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                _root.console.clear()
                rows = _run_search()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run_search()
        _display(rows)


@memory.command(name="get")
@click.argument("memory_id")
def memory_get(memory_id: str) -> None:
    """Get a single memory by ID (auto-reinforces on read)."""
    client = _sdk_client()
    with _root.console.status(f"Fetching memory '{memory_id}'..."):
        rows = client.get_memory(memory_id)
    if rows:
        print_json(rows[0])
    else:
        _root.console.print(f"[yellow]Memory '{memory_id}' not found.[/yellow]")


@memory.command(name="reinforce")
@click.argument("memory_id")
def memory_reinforce(memory_id: str) -> None:
    """Reinforce a memory (increment access count and bump strength)."""
    with _root.console.status(f"Reinforcing memory '{memory_id}'..."):
        result = _sdk_client().reinforce(memory_id)
    _quiet_print(f"[green]Memory '{memory_id}' reinforced.[/green]")
    if result:
        print_json(result)


@memory.command(name="escalate")
@click.argument("workspace_id")
@click.option("--l2-to-l1", default=5, type=int, help="Access count threshold for L2→L1 escalation (default: 5)")
@click.option("--l1-to-l0", default=20, type=int, help="Access count threshold for L1→L0 escalation (default: 20)")
def memory_escalate(workspace_id: str, l2_to_l1: int, l1_to_l0: int) -> None:
    """Batch-escalate memory tiers based on access_count thresholds."""
    with _root.console.status(f"Escalating memories in workspace '{workspace_id[:16]}...'..."):
        result = _sdk_client().escalate_memories(workspace_id, l2_to_l1, l1_to_l0)
    _quiet_print(f"[green]Tier escalation triggered for workspace {workspace_id[:16]}...[/green]")
    if result:
        print_json(result)


@memory.command(name="rate")
@click.argument("memory_id")
@click.argument("rating", type=click.Choice(["helpful", "unhelpful"]))
@click.argument("peer_id")
def memory_rate(memory_id: str, rating: str, peer_id: str) -> None:
    """Rate a memory as 'helpful' or 'unhelpful'."""
    with _root.console.status(f"Rating memory '{memory_id}' as '{rating}'..."):
        result = _sdk_client()._call("rate_memory", [memory_id, rating, peer_id])
    _quiet_print(f"[green]Memory '{memory_id}' rated as '{rating}'.[/green]")
    if result:
        print_json(result)


@memory.command(name="list")
@click.argument("workspace_id")
@click.option("--type", "memory_type", help="Filter by memory type (world_fact/experience/mental_model)")
@click.option("--tier", default="", type=click.Choice(["", "L0", "L1", "L2"]), help="Filter by tier")
@click.option("--directory", default="", help="Directory ID — list memories linked to this directory")
@click.option("--recursive", is_flag=True, help="When used with --directory, recursively traverse subdirectories")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def memory_list(ctx: click.Context, workspace_id: str, memory_type: str | None, tier: str,
                directory: str, recursive: bool, watch: bool) -> None:
    """List memories in a workspace."""
    client = _sdk_client()

    def _run_list() -> list[dict[str, Any]]:
        if directory:
            with _root.console.status(f"Listing directory '{directory[:16]}...'..."):
                if recursive:
                    rows = client.traverse_directory(workspace_id, directory)
                else:
                    rows = client.list_directory(directory)
            # Show linked memories if any rows have memory_id
            linked_memories = []
            for r in rows:
                mid = r.get("memory_id", "")
                if mid:
                    mems = client.get_memory(mid)
                    if mems:
                        linked_memories.append(mems[0])
            if linked_memories:
                return linked_memories
            return rows

        with _root.console.status(f"Fetching memories for workspace '{workspace_id}'..."):
            if tier:
                clauses = [
                    f"workspace_id = '{_esc(workspace_id)}'",
                    "is_active = true",
                ]
                if memory_type:
                    clauses.append(f"memory_type = '{_esc(memory_type)}'")
                if tier:
                    clauses.append(f"tier = '{_esc(tier)}'")
                where = " AND ".join(clauses)
                rows = client._sql(f"SELECT * FROM memory WHERE {where}")
                rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
                return rows
            else:
                return client.list_memories(
                    workspace_id=workspace_id,
                    memory_type=memory_type or "",
                )

    def _display(rows: list[dict[str, Any]]) -> None:
        if directory and not any(r.get("memory_id", "") for r in rows):
            print_table(rows, title=f"Directory contents (workspace: {workspace_id})",
                        output=ctx.obj.get("output", "table"))
        else:
            print_table(rows, title=f"Memories (workspace: {workspace_id})",
                        output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                _root.console.clear()
                rows = _run_list()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run_list()
        _display(rows)


@memory.command(name="update")
@click.argument("memory_id")
@click.option("--content", default="", help="New content")
@click.option("--summary", default="", help="New summary")
@click.option("--confidence", type=float, default=None, help="New confidence 0.0-1.0")
@click.option("--tier", type=click.Choice(["", "L0", "L1", "L2"]), default="", help="New tier")
def memory_update(memory_id: str, content: str, summary: str,
                  confidence: float | None, tier: str) -> None:
    """Update a memory's content, summary, confidence, and/or tier."""
    client = _sdk_client()
    updates: dict[str, Any] = {}
    if content:
        updates["content"] = content
    if summary:
        updates["summary"] = summary
    if confidence is not None:
        updates["confidence"] = confidence
    if tier:
        updates["tier"] = tier

    if not updates:
        _root.console.print("[yellow]No changes specified. Use --content, --summary, --confidence, or --tier.[/yellow]")
        return

    with _root.console.status(f"Updating memory '{memory_id[:16]}...'..."):
        if "content" in updates or "summary" in updates or "confidence" in updates:
            client.update_memory(
                memory_id,
                content=updates.get("content", ""),
                summary=updates.get("summary", ""),
                confidence=updates.get("confidence", 0.8),
            )
        if "tier" in updates:
            client._call("update_memory_tier", [memory_id, updates["tier"]])
    _quiet_print(f"[green]Memory '{memory_id[:16]}...' updated.[/green]")


@memory.command(name="batch-update")
@click.argument("workspace_id")
@click.argument("memory_ids")
@click.option("--content", default="", help="New content (applied to all)")
@click.option("--summary", default="", help="New summary (applied to all)")
@click.option("--confidence", type=float, default=None, help="New confidence (applied to all)")
@click.option("--tier", type=click.Choice(["", "L0", "L1", "L2"]), default="", help="New tier (applied to all)")
@click.option("--is-active", type=bool, default=None, help="Set active/inactive")
def memory_batch_update(workspace_id: str, memory_ids: str, content: str,
                        summary: str, confidence: float | None,
                        tier: str, is_active: bool | None) -> None:
    """Batch update multiple memories. MEMORY_IDS is a comma-separated list of IDs."""
    client = _sdk_client()
    ids = [m.strip() for m in memory_ids.split(",") if m.strip()]
    if not ids:
        _root.console.print("[yellow]No memory IDs provided.[/yellow]")
        return
    updates: dict[str, Any] = {}
    if content:
        updates["content"] = content
    if summary:
        updates["summary"] = summary
    if confidence is not None:
        updates["confidence"] = confidence
    if tier:
        updates["tier"] = tier
    if is_active is not None:
        updates["is_active"] = is_active
    if not updates:
        _root.console.print("[yellow]No updates specified.[/yellow]")
        return
    with _root.console.status(f"Batch updating {len(ids)} memories..."):
        result = client.batch_update_memories(workspace_id, ids, updates)
    _quiet_print(f"[green]Batch update completed for {len(ids)} memories.[/green]")
    if result:
        print_json(result)


@memory.command(name="history")
@click.argument("memory_id")
def memory_history(memory_id: str) -> None:
    """Get version history for a memory."""
    client = _sdk_client()
    with _root.console.status(f"Fetching history for memory '{memory_id[:16]}...'..."):
        rows = client.get_memory_history(memory_id)
    print_table(rows, title=f"Memory History ({memory_id[:16]}...)")
