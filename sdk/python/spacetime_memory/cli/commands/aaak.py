"""CLI commands — aaak module."""

from __future__ import annotations

import sys

import click
from rich.table import Table, box

from ..root import (
    cli,
    console,
)


@cli.group()
def aaak() -> None:
    """AAAK compression — lossless LLM context shorthand.

    Compresses text using the Mnemosyne AAAK dialect so LLMs
    consume fewer tokens without losing meaning.

    Examples:
      stmem aaak compress "PREFERENCE: User asked for dark mode"
      stmem aaak ratio memory_id ...
    """


@aaak.command(name="compress")
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read text from file")
@click.option("--pipe", "-p", is_flag=True, help="Read from stdin")
def aaak_compress_cmd(text: str | None, file: str | None, pipe: bool) -> None:
    """Compress text using AAAK shorthand."""
    from pathlib import Path

    from spacetime_memory.aaak import aaak_compress as _compress
    from spacetime_memory.aaak import aaak_ratio

    if pipe or (not text and not file and sys.stdin.isatty() is False):
        text = sys.stdin.read().strip()
    elif file:
        text = Path(file).read_text().strip()
    elif not text:
        console.print("[red]Error:[/red] provide text, --file, or pipe input")
        sys.exit(1)

    compressed = _compress(text)
    ratio = aaak_ratio(text)

    if pipe or file:
        # Machine-readable output for piping
        console.print(compressed, highlight=False)
    else:
        table = Table(title="AAAK Compression", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Original", text[:200] + ("..." if len(text) > 200 else ""))
        table.add_row("Compressed", compressed[:200] + ("..." if len(compressed) > 200 else ""))
        table.add_row("Ratio", f"{ratio:.1%} ({len(text)} → {len(compressed)} chars)")
        table.add_row("Savings", f"{len(text) - len(compressed)} chars ({1-ratio:.0%})")
        console.print(table)


@aaak.command(name="decompress")
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read compressed text from file")
@click.option("--pipe", "-p", is_flag=True, help="Read from stdin")
def aaak_decompress_cmd(text: str | None, file: str | None, pipe: bool) -> None:
    """Partially decompress AAAK shorthand (categories + phrases only)."""
    from pathlib import Path

    from spacetime_memory.aaak import aaak_decompress as _decompress

    if pipe or (not text and not file and sys.stdin.isatty() is False):
        text = sys.stdin.read().strip()
    elif file:
        text = Path(file).read_text().strip()
    elif not text:
        console.print("[red]Error:[/red] provide text, --file, or pipe input")
        sys.exit(1)

    decompressed = _decompress(text)
    if pipe or file:
        console.print(decompressed, highlight=False)
    else:
        console.print(f"[bold]Original:[/bold] {text}")
        console.print(f"[bold]Decompressed:[/bold] {decompressed}")


@aaak.command(name="ratio")
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read text from file")
@click.option("--pipe", "-p", is_flag=True, help="Read from stdin")
def aaak_ratio_cmd(text: str | None, file: str | None, pipe: bool) -> None:
    """Show AAAK compression ratio for text."""
    from pathlib import Path

    from spacetime_memory.aaak import aaak_ratio as _ratio

    if pipe or (not text and not file and sys.stdin.isatty() is False):
        text = sys.stdin.read().strip()
    elif file:
        text = Path(file).read_text().strip()
    elif not text:
        console.print("[red]Error:[/red] provide text, --file, or pipe input")
        sys.exit(1)

    ratio = _ratio(text)
    compressed_len = int(len(text) * ratio)
    console.print(f"AAAK ratio: [cyan]{ratio:.1%}[/cyan] "
                  f"({len(text)} → {compressed_len} chars, "
                  f"[green]{len(text) - compressed_len}[/green] saved)")

