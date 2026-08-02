"""CLI commands — pipeline module."""

from __future__ import annotations

import json
from typing import Any

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
def pipeline() -> None:
    """Manage cognitive pipelines.

    Pipelines compose ordered stages (search, filter, extract, transform,
    store) to process memories and knowledge.

    Examples:

      stmem pipeline create ws1 daily-summary \
          '[{"type":"search","params":{"query":"daily updates","top_k":20}},{"type":"store","params":{"target":"note","title":"Daily Summary"}}]'

      stmem pipeline execute <pipeline-id>

      stmem pipeline status <pipeline-id>

      stmem pipeline list ws1

      stmem pipeline delete <pipeline-id>
    """


@pipeline.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("stages_json")
@click.option("--schedule", default="", help="Optional cron expression (e.g. '0 9 * * *')")
def pipeline_create(workspace_id: str, name: str, stages_json: str,
                    schedule: str) -> None:
    """Define a new cognitive pipeline.

    WORKSPACE_ID is the target workspace.
    NAME is a human-readable name for the pipeline.
    STAGES_JSON is a JSON array of stage objects, each with "type" and "params".
    """
    from spacetime_memory.client._pipeline import PipelineStage

    try:
        stages_data = json.loads(stages_json)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid stages JSON: {e}[/red]")
        return

    stages = []
    for i, s in enumerate(stages_data):
        stage_type = s.get("type", "")
        params = s.get("params", {})
        stages.append(PipelineStage(type=stage_type, params=params))

    with console.status(f"Creating pipeline '{name}'..."):
        result = _sdk_client().create_pipeline(
            workspace_id=workspace_id,
            name=name,
            stages=stages,
            schedule=schedule,
        )

    _quiet_print(f"[green]Pipeline '{name}' created (id: {result.id}).[/green]")
    print_json(result.to_dict())


@pipeline.command(name="execute")
@click.argument("pipeline_id")
@click.option("--override", multiple=True, help="Override stage params as key=value (repeatable)")
def pipeline_execute(pipeline_id: str, override: tuple[str, ...]) -> None:
    """Run a pipeline synchronously.

    PIPELINE_ID is the pipeline to execute.
    """
    overrides: dict[str, Any] = {}
    for ov in override:
        if "=" in ov:
            k, v = ov.split("=", 1)
            overrides[k] = v

    with console.status(f"Executing pipeline '{pipeline_id[:16]}...'..."):
        result = _sdk_client().execute_pipeline(
            pipeline_id=pipeline_id,
            **overrides,
        )

    if result.success:
        _quiet_print(f"[green]Pipeline executed successfully ({result.duration_ms}ms).[/green]")
    else:
        _quiet_print(f"[red]Pipeline failed: {result.error}[/red]")
    print_json(result.to_dict())


@pipeline.command(name="status")
@click.argument("pipeline_id")
def pipeline_status(pipeline_id: str) -> None:
    """Check the status of a pipeline.

    PIPELINE_ID is the pipeline to inspect.
    """
    with console.status(f"Fetching pipeline status '{pipeline_id[:16]}...'..."):
        status = _sdk_client().get_pipeline_status(pipeline_id=pipeline_id)
    print_json(status)


@pipeline.command(name="list")
@click.argument("workspace_id")
def pipeline_list(workspace_id: str) -> None:
    """List all pipelines for a workspace.

    WORKSPACE_ID is the target workspace.
    """
    with console.status(f"Listing pipelines for '{workspace_id}'..."):
        pipelines = _sdk_client().list_pipelines(workspace_id=workspace_id)
    data = [p.to_dict() for p in pipelines]
    print_table(data, title=f"Pipelines (workspace: {workspace_id})")


@pipeline.command(name="delete")
@click.argument("pipeline_id")
def pipeline_delete(pipeline_id: str) -> None:
    """Remove a pipeline definition.

    PIPELINE_ID is the pipeline to delete.
    """
    with console.status(f"Deleting pipeline '{pipeline_id[:16]}...'..."):
        _sdk_client().delete_pipeline(pipeline_id=pipeline_id)
    _quiet_print(f"[green]Pipeline '{pipeline_id[:16]}...' deleted.[/green]")
