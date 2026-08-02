"""stmem — CLI entry point and command registration."""

from __future__ import annotations

import sys

import click
import httpx

from .root import HOST, PORT, cli, console

# Import all command modules so their @cli.* decorators register the commands
from . import commands  # noqa: F401  (side-effect registration)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the stmem CLI."""
    args = sys.argv[1:]
    if args and args[0] not in ("alias", "completion", "--help", "--version"):
        # Check for alias substitution before Click parses arguments
        from .root import _load_aliases

        aliases = _load_aliases()
        for i, arg in enumerate(args):
            if not arg.startswith("-") and arg in aliases:
                alias_cmd = aliases[arg]
                rest = args[i + 1 :]
                sys.argv = [sys.argv[0]] + alias_cmd.split() + rest
                break

    try:
        cli()
    except click.ClickException as e:
        console.print(f"[red]Error:[/red] {e.format_message()}")
        sys.exit(1)
    except httpx.ConnectError as e:
        console.print(
            f"[red]Connection error:[/red] Could not connect to SpacetimeDB at "
            f"http://{HOST}:{PORT}. Is it running?\n  {e}"
        )
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
