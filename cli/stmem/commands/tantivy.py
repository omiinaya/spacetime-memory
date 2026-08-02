"""Tantivy BM25 sidecar management commands"""

from __future__ import annotations

import json
import os
from typing import Any

import click
import httpx


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
    print_table,
)

# ===================================================================
# Configuration
# ===================================================================

TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")


def _tantivy_http() -> httpx.Client:
    """Return an httpx client for the Tantivy sidecar."""
    return httpx.Client(base_url=TANTIVY_URL, timeout=10.0)


def _check_reachable(http: httpx.Client) -> dict[str, Any] | None:
    """Check if the Tantivy sidecar is reachable. Returns health JSON or None."""
    try:
        resp = http.get("/health", timeout=3.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, OSError, json.JSONDecodeError):
        return None


# ===================================================================
# tantivy — BM25 sidecar management group
# ===================================================================


@cli.group()
def tantivy() -> None:
    """Manage the Tantivy BM25 sidecar (index, search, evict)."""


# ===================================================================
# tantivy status
# ===================================================================


@tantivy.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def status_cmd(as_json: bool) -> None:
    """Check Tantivy sidecar status — reachability, workspace count, memory stats.

    Queries the sidecar /health endpoint and reports reachability,
    workspace count, and any available memory/resource information.
    """
    http = _tantivy_http()

    # Attempt to pull full /status if available, fall back to /health
    try:
        resp = http.get("/status", timeout=3.0)
        if resp.status_code < 400:
            full_status: dict[str, Any] = resp.json()
        else:
            full_status = {}
    except (httpx.HTTPError, OSError, json.JSONDecodeError):
        full_status = {}

    health = _check_reachable(http)

    if health is None:
        _root.console.print(
            f"[red]✗ Tantivy sidecar unreachable at {TANTIVY_URL}[/red]"
        )
        return

    if as_json:
        data: dict[str, Any] = {
            "reachable": True,
            "url": TANTIVY_URL,
            "health": health,
        }
        if full_status:
            data["status"] = full_status
        _root.console.print_json(json.dumps(data, default=str))
        return

    ws_count = health.get("workspace_count", "?")
    total_indexed = health.get("total_indexed", "?")
    memory_mb = health.get("memory_mb", health.get("memory_bytes", None))

    _root.console.print(
        "\n[bold cyan]═══ Tantivy Sidecar Status ═══[/bold cyan]\n"
    )
    _root.console.print(f"[bold]URL:[/bold]        {TANTIVY_URL}")
    _root.console.print("[bold]Status:[/bold]     [green]✔ Reachable[/green]")

    rows: list[dict[str, Any]] = [
        {"property": "Workspace Count", "value": ws_count},
    ]
    if total_indexed != "?":
        rows.append({"property": "Total Indexed", "value": total_indexed})
    if memory_mb is not None:
        # Format as MB if raw bytes
        if isinstance(memory_mb, (int, float)) and memory_mb > 1_000_000:
            memory_mb = f"{memory_mb / 1024 / 1024:.1f} MB"
        rows.append({"property": "Memory", "value": memory_mb})

    # Include extra fields from health
    for key in ("version", "uptime_seconds", "index_count"):
        if key in health:
            rows.append({"property": key.replace("_", " ").title(), "value": health[key]})

    print_table(rows, title="Sidecar Info")

    # If full /status returned, show additional detail
    if full_status:
        extra_rows: list[dict[str, Any]] = []
        for k, v in full_status.items():
            if k not in health and k != "workspaces":
                extra_rows.append({"property": k.replace("_", " ").title(), "value": v})
        if "workspaces" in full_status:
            ws_list = full_status["workspaces"]
            extra_rows.append({"property": "Workspaces", "value": ", ".join(
                [w.get("workspace_id", str(w))[:24] for w in (ws_list or [])]
            )})
        if extra_rows:
            print_table(extra_rows, title="Detailed Status")


# ===================================================================
# tantivy evict
# ===================================================================


@tantivy.command(name="evict")
@click.argument("workspace_id")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def evict_cmd(workspace_id: str, as_json: bool) -> None:
    """Evict a workspace from the Tantivy sidecar to free memory.

    Removes the workspace's indexed data from the BM25 index.
    The workspace will need to be reindexed before search works again.
    """
    http = _tantivy_http()

    if not _check_reachable(http):
        _root.console.print(
            f"[red]✗ Tantivy sidecar unreachable at {TANTIVY_URL}[/red]"
        )
        return

    try:
        resp = http.post(f"/evict/{workspace_id}", timeout=5.0)
        result = resp.json()
    except httpx.TimeoutException:
        _root.console.print(
            f"[red]✗ Timeout evicting workspace {workspace_id[:24]}...[/red]"
        )
        return
    except (httpx.HTTPError, OSError, json.JSONDecodeError) as e:
        _root.console.print(
            f"[red]✗ Failed to evict workspace: {e}[/red]"
        )
        return

    if as_json:
        _root.console.print_json(json.dumps(result, default=str))
        return

    status = result.get("status", "error")
    if status == "ok":
        _root.console.print(
            f"[green]✔ Workspace {workspace_id[:24]}... evicted from Tantivy[/green]"
        )
    elif status == "not_found":
        _root.console.print(
            f"[yellow]⚠ Workspace {workspace_id[:24]}... not found in Tantivy[/yellow]"
        )
    else:
        _root.console.print(
            f"[red]✗ Eviction returned status: {status}[/red]"
        )


# ===================================================================
# tantivy reindex
# ===================================================================


@tantivy.command(name="reindex")
@click.option("--workspace", "workspace_id", default=None,
              help="Limit to a specific workspace ID")
@click.option("--dry-run", is_flag=True,
              help="Show what would be indexed without sending data")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output at end")
def reindex_cmd(workspace_id: str | None, dry_run: bool, as_json: bool) -> None:
    """Reindex all STDB memories and KG nodes into the Tantivy BM25 sidecar.

    Safe to run multiple times — Tantivy upserts by entity_id.
    Use --workspace to limit to a specific workspace.

    This wraps the batch indexing API, pulling content from STDB and
    pushing it to the Tantivy sidecar /index endpoint.
    """
    http = _tantivy_http()

    # ── Check Tantivy reachability ──
    if not _check_reachable(http):
        _root.console.print(
            f"[red]✗ Tantivy sidecar unreachable at {TANTIVY_URL}[/red]\n"
            f"  Start the sidecar or set TANTIVY_URL if using a different address."
        )
        return

    # ── SDK client ──
    client = _sdk_client()

    # ── Fetch workspaces ──
    with _root.console.status("Fetching workspaces from STDB..."):
        try:
            workspaces = client.list_workspaces()
        except (OSError, json.JSONDecodeError) as e:
            _root.console.print(f"[red]✗ Failed to list workspaces: {e}[/red]")
            return

    if workspace_id:
        workspaces = [w for w in workspaces if w.get("id") == workspace_id]
        if not workspaces:
            _root.console.print(
                f"[red]✗ Workspace not found: {workspace_id}[/red]"
            )
            return

    _root.console.print(
        f"\n[bold]Reindexing {len(workspaces)} workspace(s) into Tantivy...[/bold]\n"
    )

    total_memories = 0
    total_nodes = 0
    errors = 0

    for ws in workspaces:
        ws_id = ws["id"]
        ws_name = ws.get("name", ws_id[:16])
        _root.console.print(f"  [bold]Workspace:[/bold] {ws_name}  ({ws_id[:16]}...)")

        # ── Memories ──
        try:
            memories = client._query("memory", workspace_id=ws_id)
            _root.console.print(f"    Memories: {len(memories)}")
        except (OSError, json.JSONDecodeError) as e:
            _root.console.print(f"    [red]✗ Failed to query memories: {e}[/red]")
            errors += 1
            continue

        for mem in memories:
            mem_id = mem.get("id", "")
            content = mem.get("content", "")
            if not content:
                continue

            if dry_run:
                total_memories += 1
                continue

            try:
                resp = http.post(
                    "/index",
                    json={
                        "workspace_id": ws_id,
                        "entity_id": mem_id,
                        "content": content,
                        "entity_type": "memory",
                    },
                    timeout=5.0,
                )
                if resp.status_code < 400:
                    total_memories += 1
                else:
                    errors += 1
                    _root.console.print(
                        f"      [red]✗ HTTP {resp.status_code} for memory {mem_id[:16]}...[/red]"
                    )
            except (httpx.HTTPError, OSError) as e:
                errors += 1
                _root.console.print(
                    f"      [red]✗ Failed memory {mem_id[:16]}... — {e}[/red]"
                )

            if total_memories % 100 == 0 and total_memories > 0:
                _root.console.print(f"      ... {total_memories} memories indexed")

        # ── KG Nodes ──
        try:
            nodes = client._query("kg_node", workspace_id=ws_id)
            _root.console.print(f"    KG Nodes: {len(nodes)}")
        except (OSError, json.JSONDecodeError) as e:
            _root.console.print(f"    [red]✗ Failed to query kg_node: {e}[/red]")
            errors += 1
            continue

        for node in nodes:
            node_id = node.get("id", "")
            label = node.get("label", "")
            summary = node.get("summary", "")
            searchable = f"{label}: {summary}" if summary else label
            if not searchable.strip(": "):
                continue

            if dry_run:
                total_nodes += 1
                continue

            try:
                resp = http.post(
                    "/index",
                    json={
                        "workspace_id": ws_id,
                        "entity_id": node_id,
                        "content": searchable,
                        "entity_type": "node",
                    },
                    timeout=5.0,
                )
                if resp.status_code < 400:
                    total_nodes += 1
                else:
                    errors += 1
            except (httpx.HTTPError, OSError):
                errors += 1

    # ── Summary ──
    _root.console.print()
    if as_json:
        summary_data = {
            "memories_indexed": total_memories,
            "nodes_indexed": total_nodes,
            "errors": errors,
            "dry_run": dry_run,
            "workspace_count": len(workspaces),
        }
        _root.console.print_json(json.dumps(summary_data, default=str))
        return

    if dry_run:
        _root.console.print(
            f"  [yellow][DRY RUN] Would index {total_memories} memories"
            f" + {total_nodes} nodes[/yellow]"
        )
    else:
        _root.console.print(
            f"  [green]✔ Indexed {total_memories} memories"
            f" + {total_nodes} nodes[/green]"
        )
        if errors:
            _root.console.print(f"  [red]⚠ {errors} errors[/red]")

        # Verify
        try:
            health2 = http.get("/health", timeout=3.0).json()
            ws_count = health2.get("workspace_count", "?")
            _root.console.print(
                f"  Workspaces in Tantivy: {ws_count}"
            )
        except (httpx.HTTPError, OSError, json.JSONDecodeError):
            _root.console.print("  [yellow]⚠ Could not verify Tantivy health after reindex[/yellow]")
