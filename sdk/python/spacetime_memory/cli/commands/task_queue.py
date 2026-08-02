"""CLI commands — task queue module."""

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


@cli.group(name="task-queue")
def task_queue() -> None:
    """Manage the durable task queue.

    Tasks are processed in priority order by workers. Each task has a type,
    payload, priority, delay, and status lifecycle (pending → claimed →
    completed/failed).

    Examples:

      stmem task-queue enqueue ws1 embed "Insert text here" --priority 5

      stmem task-queue claim ws1 worker-01

      stmem task-queue complete <task-id> "done"

      stmem task-queue fail <task-id> "Something went wrong"

      stmem task-queue list ws1 --status pending

      stmem task-queue stats ws1
    """


@task_queue.command(name="enqueue")
@click.argument("workspace_id")
@click.argument("task_type")
@click.argument("payload")
@click.option("--priority", type=int, default=0, help="Priority (higher = processed sooner)")
@click.option("--delay", type=int, default=0, help="Delay in seconds before claimable")
def task_queue_enqueue(workspace_id: str, task_type: str, payload: str,
                       priority: int, delay: int) -> None:
    """Add a task to the queue.

    WORKSPACE_ID is the target workspace.
    TASK_TYPE is a label categorising the task (e.g. "embed", "summarise").
    PAYLOAD is an opaque string payload for the worker.
    """
    with console.status("Enqueuing task..."):
        result = _sdk_client().enqueue_task(
            workspace_id=workspace_id,
            task_type=task_type,
            payload=payload,
            priority=priority,
            delay=delay,
        )
    _quiet_print("[green]Task enqueued successfully.[/green]")
    if result:
        print_json(result)


@task_queue.command(name="claim")
@click.argument("workspace_id")
@click.argument("worker_id")
@click.option("--task-types", default="", help="Comma-separated task types to filter")
def task_queue_claim(workspace_id: str, worker_id: str,
                     task_types: str) -> None:
    """Claim the next available task for a worker.

    WORKSPACE_ID is the target workspace.
    WORKER_ID is a unique identifier for the worker.
    """
    types_list = [t.strip() for t in task_types.split(",") if t.strip()] or None
    with console.status("Claiming task..."):
        task = _sdk_client().claim_next_task(
            workspace_id=workspace_id,
            worker_id=worker_id,
            task_types=types_list,
        )
    if task:
        print_json(task)
    else:
        _quiet_print("[yellow]No task available.[/yellow]")


@task_queue.command(name="complete")
@click.argument("task_id")
@click.argument("result")
def task_queue_complete(task_id: str, result: str) -> None:
    """Mark a task as completed.

    TASK_ID is the task ID returned by enqueue/claim.
    RESULT is the opaque result string produced by the worker.
    """
    with console.status(f"Completing task '{task_id[:16]}...'..."):
        _sdk_client().complete_task(task_id=task_id, result=result)
    _quiet_print(f"[green]Task '{task_id[:16]}...' completed.[/green]")


@task_queue.command(name="fail")
@click.argument("task_id")
@click.argument("error")
def task_queue_fail(task_id: str, error: str) -> None:
    """Mark a task as failed.

    TASK_ID is the task ID returned by enqueue/claim.
    ERROR is the error description or traceback.
    """
    with console.status(f"Failing task '{task_id[:16]}...'..."):
        _sdk_client().fail_task(task_id=task_id, error=error)
    _quiet_print(f"[red]Task '{task_id[:16]}...' marked as failed.[/red]")


@task_queue.command(name="list")
@click.argument("workspace_id")
@click.option("--status", default="", help="Filter by status (pending, claimed, completed, failed)")
@click.option("--task-type", default="", help="Filter by task type")
@click.pass_context
def task_queue_list(ctx: click.Context, workspace_id: str,
                    status: str, task_type: str) -> None:
    """List tasks with optional filtering.

    WORKSPACE_ID is the target workspace.
    """
    status_val = status if status else None
    type_val = task_type if task_type else None
    with console.status("Listing tasks..."):
        tasks = _sdk_client().list_tasks(
            workspace_id=workspace_id,
            status=status_val,
            task_type=type_val,
        )
    print_table(tasks, title=f"Tasks (workspace: {workspace_id})",
                output=ctx.obj.get("output", "table"))


@task_queue.command(name="stats")
@click.argument("workspace_id")
def task_queue_stats(workspace_id: str) -> None:
    """Get queue depth, processing time, and status breakdown.

    WORKSPACE_ID is the target workspace.
    """
    with console.status("Fetching queue stats..."):
        stats = _sdk_client().get_queue_stats(workspace_id=workspace_id)
    print_json(stats)
