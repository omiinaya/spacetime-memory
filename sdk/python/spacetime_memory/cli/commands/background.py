"""CLI commands — background processing module.

Manages native background processing jobs (derivation, summarization, dreaming)
using STDB-backed priority queues.
"""

from __future__ import annotations

import click

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
    print_table,
)


@cli.group()
def background() -> None:
    """Manage background processing jobs.

    Native (no Celery/RabbitMQ) background job system using SpacetimeDB
    tables for persistence.  Supports three job types:

    - derive: extract explicit observations from messages
    - summarize: auto-generate session summaries
    - dream: generate synthetic memories

    Examples:

      stmem background enqueue-derive ws-1 msg-123 "User said they prefer async"

      stmem background enqueue-summarize ws-1 sess-abc

      stmem background enqueue-dream ws-1 --strategy connect

      stmem background process ws-1 --max-count 10

      stmem background status ws-1

      stmem background list ws-1
    """


@background.command(name="enqueue-derive")
@click.argument("workspace_id")
@click.argument("message_id")
@click.argument("content", default="")
@click.option("--priority", default=10, type=int, help="Job priority (higher = sooner)")
def bg_enqueue_derive(workspace_id: str, message_id: str,
                      content: str, priority: int) -> None:
    """Enqueue a derivation job for a message.

    WORKSPACE_ID is the target workspace.
    MESSAGE_ID is the source message to derive observations from.
    CONTENT is optional message content (fetched from DB if not provided).
    """
    with console.status("Enqueuing derivation job..."):
        result = _sdk_client().enqueue_derivation(
            workspace_id=workspace_id,
            message_id=message_id,
            content=content,
            priority=priority,
        )
    _quiet_print("[green]Derivation job enqueued.[/green]")
    print_json(result)


@background.command(name="enqueue-summarize")
@click.argument("workspace_id")
@click.argument("session_id")
@click.option("--priority", default=5, type=int, help="Job priority (higher = sooner)")
def bg_enqueue_summarize(workspace_id: str, session_id: str,
                         priority: int) -> None:
    """Enqueue a summarization job for a session.

    WORKSPACE_ID is the target workspace.
    SESSION_ID is the session to summarize.
    """
    with console.status("Enqueuing summarization job..."):
        result = _sdk_client().enqueue_summarization(
            workspace_id=workspace_id,
            session_id=session_id,
            priority=priority,
        )
    _quiet_print("[green]Summarization job enqueued.[/green]")
    print_json(result)


@background.command(name="enqueue-dream")
@click.argument("workspace_id")
@click.option("--strategy", default="connect",
              type=click.Choice(["connect", "generalize", "fill_gaps", "contrast", "all"]),
              help="Dream/synthesis strategy")
@click.option("--max-new", default=5, type=int, help="Maximum synthetic memories")
@click.option("--priority", default=3, type=int, help="Job priority (higher = sooner)")
def bg_enqueue_dream(workspace_id: str, strategy: str,
                     max_new: int, priority: int) -> None:
    """Enqueue a dream/synthesis job.

    WORKSPACE_ID is the target workspace.
    """
    with console.status("Enqueuing dream job..."):
        result = _sdk_client().enqueue_dream(
            workspace_id=workspace_id,
            strategy=strategy,
            max_new=max_new,
            priority=priority,
        )
    _quiet_print(f"[green]Dream job enqueued (strategy={strategy}).[/green]")
    print_json(result)


@background.command(name="process")
@click.argument("workspace_id")
@click.option("--max-count", "-n", default=10, type=int,
              help="Maximum jobs to process (default: 10)")
def bg_process(workspace_id: str, max_count: int) -> None:
    """Process pending background jobs for a workspace.

    WORKSPACE_ID is the target workspace.

    Dequeues up to MAX_COUNT jobs, dispatches each to the appropriate
    handler (deriver/summarizer/dreamer), and updates status.
    """
    with console.status(f"Processing up to {max_count} background jobs..."):
        results = _sdk_client().process_background_jobs(
            workspace_id=workspace_id,
            max_count=max_count,
        )

    if not results:
        console.print("[yellow]No pending jobs to process.[/yellow]")
        return

    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")

    _quiet_print(
        f"[green]Processed {len(results)} jobs "
        f"({completed} completed, {failed} failed).[/green]"
    )
    print_table([
        {
            "job_id": r.get("job_id", "")[:16] + "...",
            "job_type": r.get("job_type", ""),
            "status": r.get("status", ""),
            "error": r.get("error", ""),
        }
        for r in results
    ], title="Background Job Results")


@background.command(name="status")
@click.argument("workspace_id")
def bg_status(workspace_id: str) -> None:
    """Get background job status counts for a workspace.

    WORKSPACE_ID is the target workspace.
    """
    with console.status(f"Fetching background job status for '{workspace_id}'..."):
        status = _sdk_client().get_background_job_status(workspace_id=workspace_id)

    counts = status.get("counts", {})
    console.print(f"\n[bold]Workspace:[/bold] {workspace_id}")
    console.print(f"[bold]Total jobs:[/bold] {counts.get('total', 0)}")
    console.print(f"  Queued:    {counts.get('queued', 0)}")
    console.print(f"  Running:   {counts.get('running', 0)}")
    console.print(f"  Completed: {counts.get('completed', 0)}")
    console.print(f"  Failed:    {counts.get('failed', 0)}")

    recent = status.get("recent_jobs", [])
    if recent:
        print_table(
            recent,
            title="Recent Jobs (last 20)",
        )


@background.command(name="list")
@click.argument("workspace_id")
@click.option("--status", "-s", default=None,
              type=click.Choice(["queued", "running", "completed", "failed"]),
              help="Filter by status")
@click.option("--limit", "-n", default=50, type=int, help="Max results")
def bg_list(workspace_id: str, status: str | None, limit: int) -> None:
    """List background jobs.

    WORKSPACE_ID is the target workspace.
    """
    with console.status(f"Listing background jobs for '{workspace_id}'..."):
        jobs = _sdk_client().list_background_jobs(
            workspace_id=workspace_id,
            status=status,
            limit=limit,
        )

    if not jobs:
        console.print("[yellow]No background jobs found.[/yellow]")
        return

    print_table(
        jobs,
        title=f"Background Jobs (workspace: {workspace_id})",
    )
