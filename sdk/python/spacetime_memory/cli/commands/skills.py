"""CLI commands — skills module."""

from __future__ import annotations

import json

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
def skills() -> None:
    """Manage reusable agent skills.

    Skills are executable capabilities that agents can learn and run.
    They can be user-created or drawn from the built-in catalog.

    Examples:

      stmem skills create ws1 my-skill "Does something" "def run(client, ws, **kw): return 'ok'" --category custom

      stmem skills list ws1

      stmem skills list ws1 --category llm

      stmem skills execute ws1 <skill-id> --inputs '{"text":"hello"}'

      stmem skills delete <skill-id>

      stmem skills catalog
    """


@skills.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("description")
@click.argument("code")
@click.option("--category", default="custom", help="Skill category (memory, llm, graph, workspace, custom)")
def skills_create(workspace_id: str, name: str, description: str,
                  code: str, category: str) -> None:
    """Define a new skill in a workspace.

    WORKSPACE_ID is the target workspace.
    NAME is a short unique name for the skill (e.g. "my_summarizer").
    DESCRIPTION is a human-readable description.
    CODE is the executable Python code — must define a ``run(client, workspace_id, **inputs)`` function.
    """
    with console.status(f"Creating skill '{name}'..."):
        result = _sdk_client().create_skill(
            workspace_id=workspace_id,
            name=name,
            description=description,
            code=code,
            category=category,
        )
    _quiet_print(f"[green]Skill '{name}' created successfully.[/green]")
    if result:
        print_json(result)


@skills.command(name="list")
@click.argument("workspace_id")
@click.option("--category", default="", help="Filter by category (memory, llm, graph, workspace)")
@click.pass_context
def skills_list(ctx: click.Context, workspace_id: str, category: str) -> None:
    """List skills in a workspace, optionally filtered by category.

    WORKSPACE_ID is the target workspace.
    """
    cat_val = category if category else None
    with console.status("Listing skills..."):
        skills_data = _sdk_client().list_skills(
            workspace_id=workspace_id,
            category=cat_val,
        )
    print_table(skills_data, title=f"Skills (workspace: {workspace_id})",
                output=ctx.obj.get("output", "table"))


@skills.command(name="execute")
@click.argument("workspace_id")
@click.argument("skill_id")
@click.option("--inputs", default="{}", help="JSON dict of input parameters")
def skills_execute(workspace_id: str, skill_id: str, inputs: str) -> None:
    """Execute a skill by its ID.

    WORKSPACE_ID is the target workspace.
    SKILL_ID is the skill's memory ID.
    """
    try:
        inputs_dict = json.loads(inputs)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid inputs JSON: {e}[/red]")
        return

    with console.status(f"Executing skill '{skill_id[:16]}...'..."):
        result = _sdk_client().execute_skill(
            workspace_id=workspace_id,
            skill_id=skill_id,
            inputs=inputs_dict,
        )

    if result.get("status") == "error":
        _quiet_print(f"[red]Skill execution failed: {result.get('error')}[/red]")
    else:
        _quiet_print(f"[green]Skill '{result.get('skill_name', '')}' executed successfully.[/green]")
    print_json(result)


@skills.command(name="delete")
@click.argument("skill_id")
def skills_delete(skill_id: str) -> None:
    """Remove a skill by its memory ID.

    SKILL_ID is the skill's memory ID.
    """
    with console.status(f"Deleting skill '{skill_id[:16]}...'..."):
        _sdk_client().delete_skill(skill_id=skill_id)
    _quiet_print(f"[green]Skill '{skill_id[:16]}...' deleted.[/green]")


@skills.command(name="catalog")
def skills_catalog() -> None:
    """Show the built-in skills catalog.

    Displays all pre-defined skills that agents can use immediately.
    """
    with console.status("Fetching built-in skill catalog..."):
        catalog = _sdk_client().get_skills_catalog()
    print_table(catalog, title="Built-in Skill Catalog")
