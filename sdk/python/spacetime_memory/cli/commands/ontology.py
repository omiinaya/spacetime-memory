"""CLI commands — ontology module."""

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
def ontology() -> None:
    """Manage the ontology hierarchy.

    Ontologies define entity types (with parent/child relationships) and
    relation types (with source/target constraints) for the knowledge graph.

    Examples:

      stmem ontology entity-type create ws1 Person "" --properties '["name","age"]'

      stmem ontology entity-type create ws1 Employee Person --properties '["title","salary"]'

      stmem ontology entity-type list ws1

      stmem ontology entity-type delete <type-id>

      stmem ontology relation-type create ws1 reports_to '["Employee"]' '["Manager"]'

      stmem ontology relation-type list ws1
    """


# ── entity-type sub-group ──────────────────────────────────────────────


@ontology.group(name="entity-type")
def ontology_entity_type() -> None:
    """Manage entity types in the ontology hierarchy."""


@ontology_entity_type.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("parent_type", default="")
@click.option("--properties", default="[]", help="JSON list of allowed property key names")
@click.option("--description", default="", help="Free-text description")
def ontology_entity_type_create(workspace_id: str, name: str,
                                parent_type: str, properties: str,
                                description: str) -> None:
    """Create a new entity type in the ontology hierarchy.

    WORKSPACE_ID is the target workspace.
    NAME is the type name (e.g. "Employee").
    PARENT_TYPE is the optional parent type name (e.g. "Person").
    """
    try:
        props_list = json.loads(properties) if properties else []
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid properties JSON: {e}[/red]")
        return

    with console.status(f"Creating entity type '{name}'..."):
        result = _sdk_client().create_entity_type(
            workspace_id=workspace_id,
            name=name,
            parent_type=parent_type,
            properties=props_list,
            description=description,
        )
    _quiet_print(f"[green]Entity type '{name}' created.[/green]")
    if result:
        print_json(result)


@ontology_entity_type.command(name="list")
@click.argument("workspace_id")
@click.option("--parent", default="", help="Optional parent type filter")
@click.pass_context
def ontology_entity_type_list(ctx: click.Context, workspace_id: str,
                              parent: str) -> None:
    """List entity types in a workspace.

    WORKSPACE_ID is the target workspace.
    """
    parent_val = parent if parent else None
    with console.status("Listing entity types..."):
        types = _sdk_client().list_entity_types(
            workspace_id=workspace_id,
            parent_type=parent_val,
        )
    print_table(types, title=f"Entity Types (workspace: {workspace_id})",
                output=ctx.obj.get("output", "table"))


@ontology_entity_type.command(name="delete")
@click.argument("entity_type_id")
def ontology_entity_type_delete(entity_type_id: str) -> None:
    """Delete an entity type by its ID.

    ENTITY_TYPE_ID is the entity type ID.
    """
    with console.status(f"Deleting entity type '{entity_type_id[:16]}...'..."):
        _sdk_client().delete_entity_type(type_id=entity_type_id)
    _quiet_print(f"[green]Entity type '{entity_type_id[:16]}...' deleted.[/green]")


# ── relation-type sub-group ────────────────────────────────────────────


@ontology.group(name="relation-type")
def ontology_relation_type() -> None:
    """Manage relation types with source/target constraints."""


@ontology_relation_type.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("source_types")
@click.argument("target_types")
@click.option("--properties", default="[]", help="JSON list of allowed property key names")
@click.option("--description", default="", help="Free-text description")
def ontology_relation_type_create(workspace_id: str, name: str,
                                  source_types: str, target_types: str,
                                  properties: str, description: str) -> None:
    """Create a new relation type with source/target constraints.

    WORKSPACE_ID is the target workspace.
    NAME is the relation type name (e.g. "reports_to").
    SOURCE_TYPES is a JSON list of allowed source entity type names.
    TARGET_TYPES is a JSON list of allowed target entity type names.
    """
    try:
        src_list = json.loads(source_types) if source_types else []
        tgt_list = json.loads(target_types) if target_types else []
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON: {e}[/red]")
        return

    try:
        props_list = json.loads(properties) if properties else []
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid properties JSON: {e}[/red]")
        return

    with console.status(f"Creating relation type '{name}'..."):
        result = _sdk_client().create_relation_type(
            workspace_id=workspace_id,
            name=name,
            source_types=src_list,
            target_types=tgt_list,
            properties=props_list,
            description=description,
        )
    _quiet_print(f"[green]Relation type '{name}' created.[/green]")
    if result:
        print_json(result)


@ontology_relation_type.command(name="list")
@click.argument("workspace_id")
@click.pass_context
def ontology_relation_type_list(ctx: click.Context,
                                workspace_id: str) -> None:
    """List all relation types in a workspace.

    WORKSPACE_ID is the target workspace.
    """
    with console.status("Listing relation types..."):
        types = _sdk_client().list_relation_types(workspace_id=workspace_id)
    print_table(types, title=f"Relation Types (workspace: {workspace_id})",
                output=ctx.obj.get("output", "table"))
