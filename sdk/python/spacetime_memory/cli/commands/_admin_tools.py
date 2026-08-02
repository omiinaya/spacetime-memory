"""CLI commands — admin commands."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import click
import httpx

import spacetime_memory

from ..root import (
    ADAPTER_MODULES,
    DB,
    EMBEDDER_URL,
    HOST,
    PORT,
    _sdk_client,
    cli,
    console,
)


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

    with console.status("Running diagnostics..."):
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
        except (spacetime_memory.ClientError, httpx.HTTPError):
            mem_by_type = {}
            total_memories = 0

        try:
            tier_rows = client._sql("SELECT tier FROM memory")
            mem_by_tier: dict[str, int] = {}
            for r in tier_rows or []:
                tier = r.get("tier", "")
                if tier:
                    mem_by_tier[tier] = mem_by_tier.get(tier, 0) + 1
        except (spacetime_memory.ClientError, httpx.HTTPError):
            mem_by_tier = {}

        mc.record_memory_stats(total=total_memories, by_type=mem_by_type, by_tier=mem_by_tier)

        # 3. Workspace count
        try:
            workspaces = client.list_workspaces()
            ws_count = len(workspaces) if workspaces else 0
        except (spacetime_memory.ClientError, httpx.HTTPError):
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
        console.print_json(json.dumps(data, default=str))
        return

    # Human-readable output
    console.print("\n[bold cyan]═══ System Diagnostics ═══[/bold cyan]\n")

    # Connectivity
    db_status = "[green]✔[/green]" if ping_result.get("status") == "ok" else "[red]✘[/red]"
    emb_status = "[green]✔[/green]" if embedder.get("reachable") else "[red]✘[/red]"
    auth_status = "[green]JWT[/green]" if health_result.get("token_configured") else "[yellow]anonymous[/yellow]"

    console.print(f"[bold]SpacetimeDB:[/bold] {db_status}  {ping_result.get('latency_ms', '?')}ms  ({HOST}:{PORT})")
    console.print(f"[bold]Embedder:[/bold]   {emb_status}  {embedder.get('model_path', 'n/a')}")
    console.print(f"[bold]Auth:[/bold]       {auth_status}")
    console.print()

    # Metrics
    console.print(f"[bold]Metrics (uptime: {metrics_data['uptime_human']}):[/bold]")
    console.print(f"  Calls:  {metrics_data['total_calls']}  |  "
                  f"Errors: {metrics_data['total_errors']}  |  "
                  f"Rate: {metrics_data['overall_error_rate_pct']}%")
    console.print(f"  Embedder errors: {metrics_data['embedder_errors']}")
    console.print()

    # Memory
    console.print(f"[bold]Memory:[/bold]  {total_memories} total")
    if mem_by_type:
        console.print(f"  By type: {', '.join(f'{k}={v}' for k, v in sorted(mem_by_type.items()))}")
    if mem_by_tier:
        console.print(f"  By tier: {', '.join(f'{k}={v}' for k, v in sorted(mem_by_tier.items()))}")
    console.print(f"[bold]Workspaces:[/bold]  {ws_count}")
    console.print()


@cli.command()
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def health(token: str | None) -> None:
    """Check connectivity to SpacetimeDB, embedder, and Tantivy sidecar."""
    client = _sdk_client()
    if token:
        client.token = token
    result = client.health()
    if result["status"] == "ok":
        console.print("[green]All systems healthy[/green]")
    else:
        console.print(f"[yellow]System degraded:[/yellow] {result['status']}")
    console.print(f"  Database: {result['database']['status']} "
                  f"({result['database'].get('latency_ms', '?')}ms)")
    emb = result["embedder"]
    console.print(f"  Embedder: {'reachable' if emb.get('reachable') else 'unreachable'}")
    if emb.get("reachable") and emb.get("model_path"):
        console.print(f"    Model: {emb['model_path']}")
    tan = result.get("tantivy", {})
    if tan:
        console.print(f"  Tantivy: {'reachable' if tan.get('reachable') else 'unreachable'}"
                      f" (workspaces: {tan.get('workspace_count', '?')})")
    console.print(f"  Auth: {'JWT configured' if result['token_configured'] else 'anonymous'}")


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

    console.print("\n[bold]🔬 stmem doctor — full system check[/bold]\n")

    # 1. Core connectivity (reuses health logic)
    console.print("[bold]1. Core Connectivity[/bold]")
    result = client.health()
    db_ok = result["database"].get("status") == "ok"
    emb_ok = result["embedder"].get("reachable", False)
    auth_type = "JWT configured" if result["token_configured"] else "anonymous"

    if db_ok:
        console.print(f"  [green]✅[/green] SpacetimeDB: {result['database'].get('latency_ms', '?')}ms")
    else:
        console.print(f"  [red]❌[/red] SpacetimeDB: unreachable — is STDB running on {HOST}:{PORT}?")

    if emb_ok:
        model = result["embedder"].get("model_path", "unknown")
        console.print(f"  [green]✅[/green] Embedder: reachable (model: {model})")
    else:
        console.print(f"  [red]❌[/red] Embedder: unreachable — check EMBEDDER_URL ({EMBEDDER_URL})")

    tan_ok = result.get("tantivy", {}).get("reachable", False)
    if tan_ok:
        ws_count = result["tantivy"].get("workspace_count", "?")
        console.print(f"  [green]✅[/green] Tantivy: reachable ({ws_count} workspaces)")
    else:
        console.print("  [red]❌[/red] Tantivy: unreachable — sidecar may be down on port 9091")

    console.print(f"  {'[green]✅[/green]' if auth_type != 'anonymous' else '[yellow]⚠️[/yellow]'} Auth: {auth_type}")

    # 2. Published module
    console.print("\n[bold]2. Published Module[/bold]")
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
                        console.print(f"  [green]✅[/green] Module published — identity: {identity}")
                        break
                else:
                    console.print(f"  [green]✅[/green] Module '{db_name}' found in database list")
            elif db_name not in proc.stdout:
                console.print(f"  [yellow]⚠️[/yellow] Database '{db_name}' not found in spacetime list — module may not be published")
            else:
                console.print(f"  [yellow]⚠️[/yellow] Could not verify module: {proc.stderr.strip() or 'unknown error'}")
        except (subprocess.TimeoutExpired, OSError) as e:
            console.print(f"  [yellow]⚠️[/yellow] Module check failed: {e}")
    else:
        console.print("  [yellow]⚠️[/yellow] `spacetime` CLI not found — install STDB to check module version")

    # 3. Client library version
    console.print("\n[bold]3. SDK Version[/bold]")
    try:
        import importlib.metadata
        sdk_version = importlib.metadata.version("spacetime_memory")
        console.print(f"  [green]✅[/green] spacetime-memory SDK: v{sdk_version}")
    except (importlib.metadata.PackageNotFoundError, ImportError):
        console.print("  [yellow]⚠️[/yellow] spacetime-memory SDK version not found (editable install?)")

    # 4. Adapter imports
    console.print("\n[bold]4. Adapter Import Status[/bold]")
    all_adapters_ok = True
    for name, module_path in ADAPTER_MODULES:
        try:
            __import__(module_path)
            console.print(f"  [green]✅[/green] {name}")
        except ImportError as e:
            console.print(f"  [red]❌[/red] {name}: {e}")
            all_adapters_ok = False

    # 5. Summary
    console.print("\n[bold]─── Summary ───[/bold]")
    checks = [
        ("SpacetimeDB", db_ok),
        ("Embedder", emb_ok),
        ("Module version", True),  # non-fatal warning only
        ("Adapters", all_adapters_ok),
    ]
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    if passed == total:
        console.print(f"  [green]✅ All {total}/{total} checks passed[/green]")
        console.print("  [dim]Try: stmem store \"hello\" && stmem search \"hello\"[/dim]")
    else:
        console.print(f"  [yellow]⚠️ {passed}/{total} checks passed[/yellow]")
        if not db_ok:
            console.print("  [red]  → Fix: start SpacetimeDB (docker run clockworklabs/spacetimedb:latest -p 3001:3001)[/red]")
        if not emb_ok:
            console.print(f"  [red]  → Fix: check embedder proxy at {EMBEDDER_URL}/v1/embeddings[/red]")
        if not all_adapters_ok:
            console.print("  [red]  → Fix: pip install upstream packages (mem0, graphiti-core, etc.)[/red]")
    console.print()


@cli.command()
@click.option("--host", default=None, help="SpacetimeDB host (default: localhost)")
@click.option("--port", default=None, help="SpacetimeDB port (default: 3001)")
@click.option("--db", default=None, help="Database name (default: spacetime-memory)")
def init(host: str | None, port: str | None, db: str | None) -> None:
    """One-command setup: check prerequisites, start STDB, publish module.

    Performs the full setup flow:
    \b
      1. Check prerequisites (Docker or spacetime CLI)
      2. Start SpacetimeDB via Docker if not running
      3. Publish the Rust module
      4. Create .env config (doesn't overwrite existing)
      5. Run `stmem doctor` to verify
      6. Print test commands
    """
    console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/]")
    console.print("[bold cyan]║   Spacetime Memory — One-Command Setup      ║[/]")
    console.print("[bold cyan]╚══════════════════════════════════════════════╝[/]")

    # ── Resolve paths ──────────────────────────────────────────────────
    # When run via pip install, the module is inside the package.
    # Try to locate the repo root (where server/ and scripts/ live).
    _mod_dir = os.path.dirname(__file__)
    _repo_root = None
    for candidate in [
        os.path.join(_mod_dir, "..", "..", "..", ".."),  # from site-packages
        os.path.join(_mod_dir, "..", ".."),  # from sdk/python/spacetime_memory
        os.path.join(_mod_dir, ".."),  # from sdk/python
        os.getcwd(),
    ]:
        test_path = os.path.abspath(candidate)
        if os.path.isdir(os.path.join(test_path, "server")):
            _repo_root = test_path
            break

    if _repo_root and os.path.isdir(os.path.join(_repo_root, "server", "spacetimedb")):
        module_dir = os.path.join(_repo_root, "server")
    else:
        module_dir = None

    errs = 0

    # ── Step 1: Check prerequisites ────────────────────────────────────
    console.print("[bold]1. Prerequisites[/bold]")
    spacetime_bin = _find_spacetime_bin()
    docker_available = False
    if shutil.which("docker") is not None:
        docker_available = True
        console.print("  [green]✅[/green] Docker found")
    if spacetime_bin:
        console.print(f"  [green]✅[/green] spacetime CLI: {spacetime_bin}")
    if not spacetime_bin and not docker_available:
        console.print("  [red]❌[/red] Neither Docker nor spacetime CLI found.")
        console.print("  [dim]→ Install Docker: https://docs.docker.com/engine/install/[/dim]")
        console.print("  [dim]→ Or install SpacetimeDB: https://spacetimedb.com/install[/dim]")
        errs += 1
    console.print()

    # ── Step 2: Start SpacetimeDB ──────────────────────────────────────
    console.print("[bold]2. SpacetimeDB[/bold]")
    stdb_host = host or os.environ.get("STMEM_HOST", os.environ.get("SPACETIMEDB_HOST", "127.0.0.1"))
    stdb_port = port or os.environ.get("STMEM_PORT", os.environ.get("SPACETIMEDB_PORT", "3001"))
    db_name = db or os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))

    # Quick connectivity test
    stdb_running = False
    try:
        import httpx
        r = httpx.get(f"http://{stdb_host}:{stdb_port}/health", timeout=2.0)
        # STDB returns 200 (health endpoint) or 404 (no health endpoint) when running
        if r.status_code in (200, 404):
            stdb_running = True
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    # Also try localhost if target host isn't reachable
    if not stdb_running and stdb_host != "localhost" and stdb_host != "127.0.0.1":
        try:
            import httpx
            r = httpx.get("http://localhost:3001/health", timeout=2.0)
            if r.status_code in (200, 404):
                stdb_host = "localhost"
                stdb_port = "3001"
                stdb_running = True
                console.print("  [yellow]⚠️[/yellow] Found STDB on localhost:3001 (not {})".format(host or os.environ.get("STMEM_HOST", "127.0.0.1")))
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

    if stdb_running:
        console.print(f"  [green]✅[/green] SpacetimeDB is running ({stdb_host}:{stdb_port})")
    elif docker_available:
        console.print("  [yellow]→[/yellow] Starting SpacetimeDB via Docker...")
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=spacetimedb", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5,
            )
            if "spacetimedb" not in result.stdout:
                console.print("  [yellow]→[/yellow] Pulling clockworklabs/spacetimedb:latest...")
                subprocess.run(
                    ["docker", "pull", "clockworklabs/spacetimedb:latest"],
                    capture_output=True, text=True, timeout=120,
                )
                subprocess.Popen(
                    ["docker", "run", "-d", "--name", "spacetimedb",
                     "-p", f"{stdb_port}:3001",
                     "clockworklabs/spacetimedb:latest",
                     "start"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                # Wait for startup
                for _ in range(15):
                    import time as _time
                    _time.sleep(2)
                    try:
                        r = httpx.get(f"http://{stdb_host}:{stdb_port}/health", timeout=2.0)
                        if r.status_code in (200, 404):
                            stdb_running = True
                            break
                    except (httpx.ConnectError, httpx.TimeoutException):
                        continue
            else:
                stdb_running = True

            if stdb_running:
                console.print("  [green]✅[/green] SpacetimeDB started")
            else:
                console.print("  [red]❌[/red] SpacetimeDB failed to start (check `docker logs spacetimedb`)")
                errs += 1
        except subprocess.TimeoutExpired:
            console.print("  [red]❌[/red] Docker pull timed out")
            errs += 1
        except FileNotFoundError:
            console.print("  [red]❌[/red] Docker not found (shouldn't happen — checked above)")
            errs += 1
    else:
        console.print("  [red]❌[/red] SpacetimeDB not running and Docker unavailable")
        console.print("  [dim]→ Start STDB manually: docker run clockworklabs/spacetimedb:latest -p 3001:3001[/dim]")
        errs += 1
    console.print()

    # ── Step 3: Create .env config ──────────────────────────────────────
    console.print("[bold]3. Configuration[/bold]")
    env_path = os.path.join(os.path.expanduser("~"), ".spacetime-memory.env")
    if not os.path.isfile(env_path):
        try:
            with open(env_path, "w") as f:
                f.write("# Spacetime Memory — generated by `stmem init`\n")
                f.write(f"SPACETIMEDB_HOST={stdb_host}\n")
                f.write(f"SPACETIMEDB_PORT={stdb_port}\n")
                f.write(f"SPACETIMEDB_DB={db_name}\n")
                f.write("EMBEDDER_URL=http://127.0.0.1:4000\n")
            console.print(f"  [green]✅[/green] Created {env_path}")
        except OSError as e:
            console.print(f"  [yellow]⚠️[/yellow] Could not create {env_path}: {e}")
    else:
        console.print(f"  [yellow]⚠️[/yellow] {env_path} already exists — not overwriting")
    console.print()

    # ── Step 4: Publish module ─────────────────────────────────────────
    console.print("[bold]4. Publish Module[/bold]")
    if module_dir:
        wasm_path = os.path.join(module_dir, "target", "wasm32-wasip1", "release", "spacetime_memory.wasm")
        if os.path.isfile(wasm_path):
            console.print(f"  [green]✅[/green] WASM binary found: {wasm_path}")
            if spacetime_bin:
                console.print("  [yellow]→[/yellow] Publishing module...")
                proc = subprocess.run(
                    [spacetime_bin, "publish", "--server", f"http://{stdb_host}:{stdb_port}",
                     "-y", db_name, "--project-path", module_dir],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode == 0:
                    console.print("  [green]✅[/green] Module published")
                else:
                    stderr_clean = proc.stderr.strip()
                    if "already exists" in stderr_clean or "already" in proc.stdout:
                        console.print("  [yellow]⚠️[/yellow] Module already published (ok)")
                    else:
                        console.print(f"  [yellow]⚠️[/yellow] Publish may have issues: {stderr_clean[:200]}")
            else:
                console.print("  [yellow]⚠️[/yellow] `spacetime` CLI not found — cannot auto-publish")
                console.print("  [dim]  → Publish manually: spacetime publish ...[/dim]")
        else:
            console.print(f"  [yellow]⚠️[/yellow] WASM binary not found at {wasm_path}")
            console.print("  [dim]  → Build first: cd server && cargo build --release --target wasm32-wasip1[/dim]")
    else:
        console.print("  [yellow]⚠️[/yellow] Module source not found (running from pip install?)")
        console.print("  [dim]  → Set STMEM_DB env var and publish manually[/dim]")
    console.print()

    # ── Step 5: Run doctor ────────────────────────────────────────────────
    console.print("[bold]5. Verification[/bold]")
    doctor("")
    console.print()

    # ── Summary ────────────────────────────────────────────────────────────
    console.print("[bold cyan]─── Summary ───[/]")
    if errs == 0:
        console.print("  [green]✅ Setup complete![/green]")
        console.print("  [dim]→ stmem store \"hello world\"[/dim]")
        console.print("  [dim]→ stmem search \"hello\"[/dim]")
        console.print("  [dim]→ stmem doctor[/dim]")
    else:
        console.print(f"  [yellow]⚠️ Setup completed with {errs} error(s)[/yellow]")


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


@cli.command(name="synthesize")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--budget", default=4096, type=int, help="Token budget for context (default: 4096)")
def synthesize_cmd(workspace_id: str, query: str, budget: int) -> None:
    """Synthesize a grounded answer with gap analysis (GBrain-style).

    Searches the workspace, finds relevant memories, and calls an LLM to
    produce a structured answer that includes:

    \b
    - answer: synthesized answer grounded in found memories
    - gaps: what the knowledge base does NOT contain
    - sources: indices of source memories used
    - confidence: 0.0-1.0

    Requires OPENAI_API_KEY for LLM calls.

    Example:
        stmem synthesize my-workspace "What do we know about Alice Chen?"
    """
    from spacetime_memory.context_agent import ContextAgent

    client = _sdk_client()
    agent = ContextAgent(client)

    with console.status("Synthesizing with gap analysis..."):
        result = agent.synthesize(query, workspace_id=workspace_id, token_budget=budget)

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        return

    answer = result.get("answer")
    gaps = result.get("gaps", [])
    sources = result.get("sources", [])
    confidence = result.get("confidence", 0.0)

    if answer:
        console.print(f"\n[bold green]Answer[/bold green] (confidence: {confidence:.0%})")
        console.print(f"[dim]{'─' * 60}[/dim]")
        console.print(answer)
    else:
        console.print("\n[yellow]LLM unavailable — showing raw context entries.[/yellow]")
        if "pack" in result:
            pack = result["pack"]
            console.print(f"  Pack: {pack.get('id', '')[:16]}...")

    if gaps:
        console.print(f"\n[bold yellow]Knowledge Gaps[/bold yellow] ({len(gaps)})")
        console.print(f"[dim]{'─' * 60}[/dim]")
        for i, gap in enumerate(gaps, 1):
            console.print(f"  {i}. {gap}")

    if sources:
        console.print(f"\n[bold dim]Sources[/bold dim]: {' '.join(str(s) for s in sources)}")


@cli.command(name="backup")
@click.argument("workspace_id")
@click.option("--output", "-o", default=None, help="Output file (default: ~/.hermes/backups/<ws>.jsonl)")
@click.option("--tables", default="memory,session,message,profile,insight,note,kg_node,kg_edge",
              help="Comma-separated tables to backup")
def backup_cmd(workspace_id: str, output: str | None, tables: str) -> None:
    """Backup all data for a workspace to a JSONL file."""
    from pathlib import Path

    table_list = [t.strip() for t in tables.split(",")]

    if not output:
        backup_dir = Path.home() / ".hermes" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        output = str(backup_dir / f"{workspace_id[:16]}.jsonl")

    client = _sdk_client()
    total = 0

    with open(output, "w") as f:
        for table in table_list:
            try:
                rows = client._query(table, workspace_id=workspace_id)
            except RuntimeError:
                console.print(f"  [yellow]Skipping {table}[/yellow] (not accessible)")
                continue
            for row in rows:
                f.write(json.dumps({"table": table, **row}) + "\n")
                total += 1
        console.print(f"  {total} rows from {len(table_list)} tables")

    console.print(f"\n[green]Backup complete:[/green] {output}")
    console.print(f"  {total} rows written")


@cli.command(name="restore")
@click.argument("workspace_id")
@click.argument("backup_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Print what would be restored without making changes")
def restore_cmd(workspace_id: str, backup_file: str, dry_run: bool) -> None:
    """Restore workspace data from a JSONL backup file."""
    client = _sdk_client()
    total = 0
    errors = 0

    with open(backup_file) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                console.print(f"  [red]Line {line_no}: invalid JSON[/red]")
                errors += 1
                continue

            table = row.pop("table", "")
            if not table:
                console.print(f"  [red]Line {line_no}: missing table field[/red]")
                errors += 1
                continue

            if dry_run:
                console.print(f"  [DRY] {table}: {json.dumps(row)[:80]}...")
                total += 1
                continue

            try:
                # Use store_memory for memory rows, generic _call for others
                if table == "memory":
                    client.store(
                        workspace_id=workspace_id,
                        content=row.get("content", ""),
                        summary=row.get("summary", ""),
                        memory_type=row.get("memory_type", "world_fact"),
                        peer_id=row.get("peer_id", ""),
                    )
                elif table == "session":
                    client._call("create_session", [
                        workspace_id, row.get("id", ""), row.get("name", ""),
                        row.get("summary", ""), row.get("participants_json", "[]"),
                    ])
                elif table == "kg_node":
                    client._call("create_node", [
                        workspace_id, row.get("label", ""), row.get("node_type", ""),
                        row.get("summary", ""), row.get("metadata_json", "{}"),
                    ])
                elif table == "kg_edge":
                    client._call("create_edge", [
                        workspace_id, row.get("source_node_id", ""),
                        row.get("target_node_id", ""), row.get("relation", ""),
                        row.get("weight", 1.0), row.get("confidence", "EXTRACTED"),
                        row.get("metadata_json", "{}"),
                    ])
                elif table == "profile":
                    client._call("upsert_profile", [
                        workspace_id, row.get("peer_id", ""),
                        row.get("static_facts_json", "{}"),
                        row.get("dynamic_context_json", "{}"),
                    ])
                elif table == "insight":
                    client._call("create_insight", [
                        workspace_id, row.get("source", "restore"),
                        row.get("content", ""), row.get("insight_type", "observation"),
                        row.get("entities_json", "[]"), row.get("confidence", 0.7),
                    ])
                elif table == "note":
                    client._call("create_note", [
                        workspace_id, row.get("title", ""), row.get("content", ""),
                        row.get("tags_json", "[]"),
                    ])
                else:
                    console.print(f"  [yellow]Skipping {table} (no restore handler)[/yellow]")
                    continue

                total += 1
            except RuntimeError as e:
                console.print(f"  [red]Line {line_no} ({table}): {e}[/red]")
                errors += 1

    mode = " [DRY-RUN]" if dry_run else ""
    console.print(f"\n[green]Restore complete{mode}:[/green] {total} rows restored, {errors} errors")


@cli.command(name="serve")
@click.option("--transport", default="stdio",
              type=click.Choice(["stdio", "sse"]),
              help="MCP transport protocol (default: stdio)")
@click.option("--host", default=None, help="SSE listen host (default: SPACETIMEDB_HOST)")
@click.option("--port", default=None, type=int, help="SSE listen port (default: 8100)")
@click.option("--api-key", default=None, help="API key for SSE auth (default: MCP_API_KEY env)")
def serve(transport: str, host: str | None, port: int | None, api_key: str | None) -> None:
    """Start the MCP (Model Context Protocol) server.

    By default runs on stdio transport for local agent integration.
    Use ``--transport sse`` for HTTP/SSE mode.
    """
    host_val = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
    port_val = port if port is not None else int(os.environ.get("SPACETIMEDB_PORT", "3001"))
    db_val = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
    embedder_url = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

    os.environ.setdefault("SPACETIMEDB_HOST", host_val)
    os.environ.setdefault("SPACETIMEDB_PORT", str(port_val))
    os.environ.setdefault("SPACETIMEDB_DB", db_val)
    os.environ.setdefault("EMBEDDER_URL", embedder_url)
    if api_key:
        os.environ["MCP_API_KEY"] = api_key

    listen_host = os.environ.get("MCP_HOST", "0.0.0.0")
    listen_port = int(os.environ.get("MCP_PORT", "8100"))

    if transport == "sse":
        console.print(f"MCP SSE server starting on http://{listen_host}:{listen_port} ...")
        console.print(f"  DB: {host_val}:{port_val}/{db_val}")
        console.print(f"  Embedder: {embedder_url}")
        console.print(f"  Auth: {'enabled' if os.environ.get('MCP_API_KEY') else 'disabled'}")
    else:
        console.print("MCP stdio server starting ...", highlight=False)

    try:
        from server.mcp.main import run
        run(
            transport=transport,
            host=listen_host if transport == "sse" else None,
            port=listen_port if transport == "sse" else None,
        )
    except ImportError as e:
        console.print(f"[red]Error:[/red] Cannot start MCP server — missing dependencies: {e}")
        console.print("  pip install spacetime-memory[mcp]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] MCP server failed: {e}")
        sys.exit(1)


