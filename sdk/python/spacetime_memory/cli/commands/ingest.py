"""CLI commands — ingest module."""

from __future__ import annotations

import sys

import click
from rich.table import Table, box

from ..root import (
    _current_output_format,
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
)


@cli.group()
def ingest() -> None:
    """Ingest source documents into the wiki.

    Subcommands:
      codebase  — parse a codebase with tree-sitter and populate the KG
      file      — ingest a source document from a file
      text      — ingest a source document from raw text or stdin

    Examples:
      stmem ingest file article.md --title "My Article" --source-type paper
      stmem ingest text "Reinforcement learning is..." --title "RL Notes"
      cat notes.md | stmem ingest text --pipe --title "Piped Notes"
      stmem ingest codebase /path/to/repo workspace_id
    """


@ingest.command(name="codebase")
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False))
@click.argument("workspace_id")
@click.option("--max-files", default=0, type=int,
              help="Max files to process (0 = unlimited)")
@click.option("--skip-dirs", default="",
              help="Extra directories to skip (comma-separated)")
def ingest_codebase(repo_path: str, workspace_id: str,
                    max_files: int, skip_dirs: str) -> None:
    """Parse a codebase with tree-sitter and populate the KG."""
    skip_set: set[str] = set()
    if skip_dirs:
        skip_set = set(d.strip() for d in skip_dirs.split(",") if d.strip())

    try:
        from spacetime_memory.ingest import CodebaseIngester
    except ImportError:
        console.print(
            "[red]Error:[/red] `spacetime-memory` SDK not installed. "
            "Run: pip install spacetime-memory"
        )
        sys.exit(1)

    with console.status(f"Ingesting {repo_path} ..."):
        ingester = CodebaseIngester(_sdk_client())
        stats = ingester.ingest(repo_path, workspace_id,
                                max_files=max_files, skip_dirs=skip_set)

    _quiet_print(
        f"[green]Ingestion complete.[/green] "
        f"{stats['files']} files, {stats['defs']} definitions, "
        f"{stats['edges']} edges, {stats['errors']} errors"
    )


@ingest.command(name="file")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--title", "-t", required=True, help="Source title")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--source-type", "-s", default="article",
              type=click.Choice(["article", "paper", "transcript",
                                 "note", "podcast"]),
              help="Type of source")
@click.option("--no-embed", is_flag=True, help="Skip semantic embedding")
def ingest_file(path: str, title: str, workspace: str,
                source_type: str, no_embed: bool) -> None:
    """Ingest a source document from a file.

    Uses Compounder.ingest_source() to run the full LLM Wiki ingest
    workflow: summarize, extract entities, create KG nodes, link,
    ripple-update entities, and check for contradictions.
    """
    import pathlib
    text = pathlib.Path(path).read_text(encoding="utf-8")
    _run_ingest(text, title, workspace, source_type, not no_embed)


@ingest.command(name="text")
@click.argument("text", required=False)
@click.option("--title", "-t", required=True, help="Source title")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--source-type", "-s", default="article",
              type=click.Choice(["article", "paper", "transcript",
                                 "note", "podcast"]),
              help="Type of source")
@click.option("--pipe", "-p", is_flag=True, help="Read text from stdin")
@click.option("--no-embed", is_flag=True, help="Skip semantic embedding")
def ingest_text(text: str | None, title: str, workspace: str,
                source_type: str, pipe: bool, no_embed: bool) -> None:
    """Ingest a source document from raw text or stdin."""
    if pipe or (not text and sys.stdin.isatty() is False):
        text = sys.stdin.read()
    elif not text:
        console.print("[red]Error:[/red] provide text or --pipe")
        sys.exit(1)
    _run_ingest(text, title, workspace, source_type, not no_embed)


def _run_ingest(text: str, title: str, workspace: str,
                source_type: str, embed: bool) -> None:
    """Shared ingest logic for file and text commands."""
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Ingesting '{title}' into workspace '{workspace}'..."
    ):
        result = cp.ingest_source(
            source_text=text,
            source_title=title,
            workspace_id=workspace,
            source_type=source_type,
            embed=embed,
        )

    note = result.get("note", {})
    entities = result.get("entities", [])
    links = result.get("links", [])
    contradictions = result.get("contradictions", [])

    summary = Table(title=f"Ingest: {title}", box=box.ROUNDED)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value")
    summary.add_row("Note ID", note.get("id", "N/A")[:16] + "...")
    summary.add_row("Entities", str(len(entities)))
    summary.add_row("Links Created", str(len(links)))
    summary.add_row("Contradictions", str(len(contradictions)))
    console.print(summary)

    if contradictions:
        console.print("\n[bold yellow]Contradictions found:[/bold yellow]")
        for c in contradictions:
            console.print(
                f"  [yellow]⚠[/yellow] vs `{c.get('memory_id', '?')[:12]}`: "
                f"{c.get('explanation', '')[:120]}"
            )

    if _current_output_format == "json":
        print_json(result)

