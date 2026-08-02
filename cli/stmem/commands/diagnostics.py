"""Diagnostics, health, and doctor commands"""

from __future__ import annotations

import json
import os
import subprocess

import click


from .. import root as _root
from ..root import (
    DB,
    EMBEDDER_URL,
    HOST,
    PORT,
    _sdk_client,
    cli,
)

# ===================================================================
# diagnostics — full system health and metrics dump
# ===================================================================


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def diagnostics(as_json: bool, token: str | None) -> None:
    """Run comprehensive system diagnostics.

    Checks connectivity, gathers metrics, inspects workspace/memory
    counts, and reports embedder status in a single snapshot.
    """
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    with _root.console.status("Running diagnostics..."):
        # 1. Connectivity
        ping_result = client.ping()
        health_result = client.health()
        embedder = health_result.get("embedder", {})

        # 2. Memory counts (STDB SQL has no GROUP BY — aggregate client-side)
        try:
            mem_rows = client._sql("SELECT memory_type, created_at FROM memory")
            mem_by_type: dict[str, int] = {}
            total_memories = 0
            for r in mem_rows or []:
                mt = r.get("memory_type", "")
                mem_by_type[mt] = mem_by_type.get(mt, 0) + 1
                total_memories += 1
        except (OSError, json.JSONDecodeError, RuntimeError):
            mem_by_type = {}
            total_memories = 0

        try:
            tier_rows = client._sql("SELECT tier FROM memory")
            mem_by_tier: dict[str, int] = {}
            for r in tier_rows or []:
                tier = r.get("tier", "")
                if tier:
                    mem_by_tier[tier] = mem_by_tier.get(tier, 0) + 1
        except (OSError, json.JSONDecodeError, RuntimeError):
            mem_by_tier = {}

        mc.record_memory_stats(total=total_memories, by_type=mem_by_type, by_tier=mem_by_tier)

        # 3. Workspace count
        try:
            workspaces = client.list_workspaces()
            ws_count = len(workspaces) if workspaces else 0
        except (OSError, json.JSONDecodeError):
            workspaces = []
            ws_count = 0

    metrics_data = mc.to_dict()

    if as_json:
        data = {
            **metrics_data,
            "database": {
                "host": HOST,
                "port": PORT,
                "database": DB,
                "reachable": ping_result.get("status") == "ok",
                "latency_ms": ping_result.get("latency_ms", 0),
            },
            "embedder": {
                "reachable": embedder.get("reachable", False),
                "model_path": embedder.get("model_path", ""),
            },
            "workspaces": {
                "count": ws_count,
                "names": [w.get("name", "") for w in (workspaces or [])][:50],
            },
            "memory_counts": {
                "total": total_memories,
                "by_type": mem_by_type,
                "by_tier": mem_by_tier,
            },
        }
        _root.console.print_json(json.dumps(data, default=str))
        return

    # Human-readable output
    _root.console.print("\n[bold cyan]═══ System Diagnostics ═══[/bold cyan]\n")

    # Connectivity
    db_status = "[green]✔[/green]" if ping_result.get("status") == "ok" else "[red]✘[/red]"
    emb_status = "[green]✔[/green]" if embedder.get("reachable") else "[red]✘[/red]"
    auth_status = "[green]JWT[/green]" if health_result.get("token_configured") else "[yellow]anonymous[/yellow]"

    _root.console.print(f"[bold]SpacetimeDB:[/bold] {db_status}  {ping_result.get('latency_ms', '?')}ms  ({HOST}:{PORT})")
    _root.console.print(f"[bold]Embedder:[/bold]   {emb_status}  {embedder.get('model_path', 'n/a')}")
    _root.console.print(f"[bold]Auth:[/bold]       {auth_status}")
    _root.console.print()

    # Metrics
    _root.console.print(f"[bold]Metrics (uptime: {metrics_data['uptime_human']}):[/bold]")
    _root.console.print(f"  Calls:  {metrics_data['total_calls']}  |  "
                  f"Errors: {metrics_data['total_errors']}  |  "
                  f"Rate: {metrics_data['overall_error_rate_pct']}%")
    _root.console.print(f"  Embedder errors: {metrics_data['embedder_errors']}")
    _root.console.print()

    # Memory
    _root.console.print(f"[bold]Memory:[/bold]  {total_memories} total")
    if mem_by_type:
        _root.console.print(f"  By type: {', '.join(f'{k}={v}' for k, v in sorted(mem_by_type.items()))}")
    if mem_by_tier:
        _root.console.print(f"  By tier: {', '.join(f'{k}={v}' for k, v in sorted(mem_by_tier.items()))}")
    _root.console.print(f"[bold]Workspaces:[/bold]  {ws_count}")
    _root.console.print()


# ===================================================================
# health
# ===================================================================


@cli.command()
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def health(token: str | None) -> None:
    """Check connectivity to SpacetimeDB, embedder, and Tantivy sidecar."""
    client = _sdk_client()
    if token:
        client.token = token
    result = client.health()
    if result["status"] == "ok":
        _root.console.print("[green]All systems healthy[/green]")
    else:
        _root.console.print(f"[yellow]System degraded:[/yellow] {result['status']}")
    _root.console.print(f"  Database: {result['database']['status']} "
                  f"({result['database'].get('latency_ms', '?')}ms)")
    emb = result["embedder"]
    _root.console.print(f"  Embedder: {'reachable' if emb.get('reachable') else 'unreachable'}")
    if emb.get("reachable") and emb.get("model_path"):
        _root.console.print(f"    Model: {emb['model_path']}")
    tan = result.get("tantivy", {})
    if tan:
        _root.console.print(f"  Tantivy: {'reachable' if tan.get('reachable') else 'unreachable'}"
                      f" (workspaces: {tan.get('workspace_count', '?')})")
    _root.console.print(f"  Auth: {'JWT configured' if result['token_configured'] else 'anonymous'}")


# ===================================================================
# doctor
# ===================================================================


ADAPTER_MODULES = [
    ("langchain", "spacetime_memory.sdks.langchain"),
    ("mem0", "spacetime_memory.sdks.mem0"),
    ("graphiti", "spacetime_memory.sdks.graphiti"),
    ("zep", "spacetime_memory.sdks.zep"),
    ("hindsight", "spacetime_memory.sdks.hindsight"),
    ("honcho", "spacetime_memory.sdks.honcho"),
]


@cli.command()
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def doctor(token: str | None) -> None:
    """Full system health check: STDB, module, embedder, adapters.

    Runs every diagnostic available and reports a summary with
    actionable guidance for any issues found.
    """
    client = _sdk_client()
    if token:
        client.token = token

    _root.console.print("\n[bold]🔬 stmem doctor — full system check[/bold]\n")

    # 1. Core connectivity (reuses health logic)
    _root.console.print("[bold]1. Core Connectivity[/bold]")
    result = client.health()
    db_ok = result["database"].get("status") == "ok"
    emb_ok = result["embedder"].get("reachable", False)
    auth_type = "JWT configured" if result["token_configured"] else "anonymous"

    if db_ok:
        _root.console.print(f"  [green]✅[/green] SpacetimeDB: {result['database'].get('latency_ms', '?')}ms")
    else:
        _root.console.print(f"  [red]❌[/red] SpacetimeDB: unreachable — is STDB running on {HOST}:{PORT}?")

    if emb_ok:
        model = result["embedder"].get("model_path", "unknown")
        _root.console.print(f"  [green]✅[/green] Embedder: reachable (model: {model})")
    else:
        _root.console.print(f"  [red]❌[/red] Embedder: unreachable — check EMBEDDER_URL ({EMBEDDER_URL})")

    tan_ok = result.get("tantivy", {}).get("reachable", False)
    if tan_ok:
        ws_count = result["tantivy"].get("workspace_count", "?")
        _root.console.print(f"  [green]✅[/green] Tantivy: reachable ({ws_count} workspaces)")
    else:
        _root.console.print("  [red]❌[/red] Tantivy: unreachable — sidecar may be down on port 9091")

    _root.console.print(f"  {'[green]✅[/green]' if auth_type != 'anonymous' else '[yellow]⚠️[/yellow]'} Auth: {auth_type}")

    # 2. Published module
    _root.console.print("\n[bold]2. Published Module[/bold]")
    spacetime_bin = _find_spacetime_bin()
    db_name = os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))
    if spacetime_bin:
        try:
            proc = subprocess.run(
                [spacetime_bin, "list"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and db_name in proc.stdout:
                # Extract the identity hash for the matching database
                for line in proc.stdout.splitlines():
                    if db_name in line and "|" in line:
                        parts = line.split("|")
                        identity = parts[-1].strip()[:16] + "..."
                        _root.console.print(f"  [green]✅[/green] Module published — identity: {identity}")
                        break
                else:
                    _root.console.print(f"  [green]✅[/green] Module '{db_name}' found in database list")
            elif db_name not in proc.stdout:
                _root.console.print(f"  [yellow]⚠️[/yellow] Database '{db_name}' not found in spacetime list — module may not be published")
            else:
                _root.console.print(f"  [yellow]⚠️[/yellow] Could not verify module: {proc.stderr.strip() or 'unknown error'}")
        except (subprocess.TimeoutExpired, OSError) as e:
            _root.console.print(f"  [yellow]⚠️[/yellow] Module check failed: {e}")
    else:
        _root.console.print("  [yellow]⚠️[/yellow] `spacetime` CLI not found — install STDB to check module version")

    # 3. Client library version
    _root.console.print("\n[bold]3. SDK Version[/bold]")
    try:
        import importlib.metadata
        sdk_version = importlib.metadata.version("spacetime_memory")
        _root.console.print(f"  [green]✅[/green] spacetime-memory SDK: v{sdk_version}")
    except (importlib.metadata.PackageNotFoundError, ImportError):
        _root.console.print("  [yellow]⚠️[/yellow] spacetime-memory SDK version not found (editable install?)")

    # 4. Adapter imports
    _root.console.print("\n[bold]4. Adapter Import Status[/bold]")
    all_adapters_ok = True
    for name, module_path in ADAPTER_MODULES:
        try:
            __import__(module_path)
            _root.console.print(f"  [green]✅[/green] {name}")
        except ImportError as e:
            _root.console.print(f"  [red]❌[/red] {name}: {e}")
            all_adapters_ok = False

    # 5. Summary
    _root.console.print("\n[bold]─── Summary ───[/bold]")
    checks = [
        ("SpacetimeDB", db_ok),
        ("Embedder", emb_ok),
        ("Module version", True),  # non-fatal warning only
        ("Adapters", all_adapters_ok),
    ]
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    if passed == total:
        _root.console.print(f"  [green]✅ All {total}/{total} checks passed[/green]")
        _root.console.print("  [dim]Try: stmem store \"hello\" && stmem search \"hello\"[/dim]")
    else:
        _root.console.print(f"  [yellow]⚠️ {passed}/{total} checks passed[/yellow]")
        if not db_ok:
            _root.console.print("  [red]  → Fix: start SpacetimeDB (docker run clockworklabs/spacetimedb:latest -p 3001:3001)[/red]")
        if not emb_ok:
            _root.console.print(f"  [red]  → Fix: check embedder proxy at {EMBEDDER_URL}/v1/embeddings[/red]")
        if not all_adapters_ok:
            _root.console.print("  [red]  → Fix: pip install upstream packages (mem0, graphiti-core, etc.)[/red]")
    _root.console.print()


def _find_spacetime_bin() -> str | None:
    """Locate the `spacetime` CLI binary."""
    import shutil
    # Check PATH first
    exe = shutil.which("spacetime")
    if exe:
        return exe
    # Common fallback locations
    for candidate in [
        os.path.expanduser("~/.local/bin/spacetime"),
        os.path.expanduser("~/.cargo/bin/spacetime"),
        "/usr/local/bin/spacetime",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
