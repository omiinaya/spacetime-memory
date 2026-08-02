"""Export wiki data to external formats"""

from __future__ import annotations

import json

import click


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
)

# ── Export ────────────────────────────────────────────────────────────────────

@cli.group()
def export() -> None:
    """Export wiki data to external formats.

    Examples:

      stmem export markdown ./my-vault/ --workspace default
      stmem export markdown ./my-vault/ --include-kg --kg-json
      stmem export obsidian ./my-obsidian-vault/ --workspace default
    """


@export.command(name="markdown")
@click.argument("output_dir", type=click.Path())
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--include-kg", is_flag=True,
              help="Also export KG nodes as markdown entity pages")
@click.option("--kg-json", is_flag=True,
              help="Export knowledge graph (nodes + edges) as kg.json")
@click.option("--include-system", is_flag=True,
              help="Include _index and _log notes")
def export_markdown(output_dir: str, workspace: str,
                    include_kg: bool, kg_json: bool,
                    include_system: bool) -> None:
    """Export all notes as markdown files with YAML frontmatter.

    Each note becomes a ``.md`` file with frontmatter (id, title,
    created, updated, backlinks).  The output directory is ready
    for Obsidian or git-based wiki browsing.

    Use ``--kg-json`` to also export the full knowledge graph (all
    nodes and edges) as a single ``kg.json`` file for external
    tooling (LLM pipelines, graph analysis).
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Exporting workspace '{workspace}' to {output_dir}..."
    ):
        result = cp.export_workspace(
            output_dir=output_dir,
            workspace_id=workspace,
            include_kg=include_kg,
            kg_json=kg_json,
            include_system_notes=include_system,
        )

    errors = result.get("errors", [])
    files = result.get("files_written", 0)

    if errors:
        for err in errors:
            _root.console.print(f"  [red]✗[/red] {err}")

    _quiet_print(
        f"[green]Exported {files} files to {output_dir}/[/green]"
    )
    if _root._current_output_format == "json":
        print_json(result)



@export.command(name="obsidian")
@click.argument("output_dir", type=click.Path())
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--include-system", is_flag=True,
              help="Include _index and _log notes")
@click.option("--overwrite-config", is_flag=True,
              help="Overwrite existing .obsidian/ config files")
def export_obsidian(output_dir: str, workspace: str,
                    include_system: bool,
                    overwrite_config: bool) -> None:
    """Export workspace as a complete Obsidian vault.

    Creates an Obsidian-ready directory containing:

      * One ``.md`` file per note with YAML frontmatter
      * ``_kg_nodes/`` — knowledge-graph entity pages as markdown
      * ``kg.json`` — full KG (nodes + edges) as structured JSON
      * ``.obsidian/`` — vault configuration (app.json, appearance.json,
        graph.json) for a ready-to-open vault

    Examples::

      stmem export obsidian ./my-brain/ --workspace default
      stmem export obsidian ./my-brain/ --include-system
    """
    import pathlib

    out = pathlib.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Step 1 — export notes + KG via the SDK
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with _root.console.status(
        f"Exporting workspace '{workspace}' to Obsidian vault at {output_dir}..."
    ):
        result = cp.export_workspace(
            output_dir=output_dir,
            workspace_id=workspace,
            include_kg=True,
            kg_json=True,
            include_system_notes=include_system,
        )

    errors = result.get("errors", [])
    files = result.get("files_written", 0)

    # Step 2 — create .obsidian/ config directory
    obsidian_dir = out / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)

    # app.json — base vault settings
    app_json = obsidian_dir / "app.json"
    if not app_json.exists() or overwrite_config:
        app_config = {
            "promptDelete": False,
            "alwaysUpdateLinks": True,
            "newFileLocation": "root",
            "attachmentFolderPath": "_attachments",
            "showUnsupportedFiles": False,
            "useMarkdownLinks": True,
            "showFrontmatter": True,
            "showLineNumber": False,
            "spellcheck": True,
            "vimMode": False,
            "strictLineBreaks": False,
            "tabSize": 4,
        }
        app_json.write_text(json.dumps(app_config, indent=2) + "\n", encoding="utf-8")
        files += 1

    # appearance.json — dark theme defaults
    appearance_json = obsidian_dir / "appearance.json"
    if not appearance_json.exists() or overwrite_config:
        appearance_config = {
            "accentColor": "#7c3aed",
            "cssTheme": "",
            "enabledCssSnippets": [],
            "baseColorScheme": "dark",
            "interfaceFontFamily": "",
            "textFontFamily": "",
            "monospaceFontFamily": "",
        }
        appearance_json.write_text(
            json.dumps(appearance_config, indent=2) + "\n", encoding="utf-8"
        )
        files += 1

    # graph.json — KG-aware graph view defaults
    graph_json = obsidian_dir / "graph.json"
    if not graph_json.exists() or overwrite_config:
        # Fetch KG nodes for the colour-by-type filter
        nodes = client._query(
            "kg_node",
            workspace_id=workspace,
            filter_dict={},
        )
        type_tags: set[str] = set()
        for n in nodes or []:
            nt = n.get("node_type", "concept")
            type_tags.add(nt)

        # Build colour groups from node types
        palette = [
            "#7c3aed",  # purple
            "#3b82f6",  # blue
            "#10b981",  # emerald
            "#f59e0b",  # amber
            "#ef4444",  # red
            "#ec4899",  # pink
            "#06b6d4",  # cyan
            "#f97316",  # orange
        ]
        search_groups = []
        for i, nt in enumerate(sorted(type_tags)):
            search_groups.append({
                "query": 'path:("_kg_nodes/' + nt + '")',
                "color": palette[i % len(palette)],
            })

        graph_config = {
            "colorGroups": search_groups,
        }
        graph_json.write_text(
            json.dumps(graph_config, indent=2) + "\n", encoding="utf-8"
        )
        files += 1

    # core-plugins.json — enable graph view
    core_plugins = obsidian_dir / "core-plugins.json"
    if not core_plugins.exists() or overwrite_config:
        core_plugins.write_text(
            json.dumps({
                "file-explorer": True,
                "global-search": True,
                "graph": True,
                "backlink": True,
                "outgoing-link": True,
                "tag-pane": True,
                "page-preview": True,
                "command-palette": True,
                "markdown-importer": False,
                "word-count": True,
                "slides": False,
                "audio-recorder": False,
                "open-with-default-app": True,
            }, indent=2) + "\n"
        )
        files += 1

    # Report
    if errors:
        for err in errors:
            _root.console.print(f"  [red]✗[/red] {err}")

    _quiet_print(
        f"[green]Exported Obsidian vault ({files} files) to {output_dir}/[/green]\n"
        f"      Open the folder in Obsidian via 'Manage Vaults -> Open folder as vault'."
    )
    if _root._current_output_format == "json":
        print_json(result)
