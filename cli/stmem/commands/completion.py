"""Shell completion scripts"""

from __future__ import annotations


import click


from ..root import (
    cli,
)

# ===================================================================
# completion — shell completion scripts
# ===================================================================


@cli.command(name="completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Generate shell completion script.

    Usage: eval "$(stmem completion bash)"
    """
    if shell == "bash":
        click.echo('eval "$(_STMEM_COMPLETE=bash_source stmem)"')
    elif shell == "zsh":
        click.echo('eval "$(_STMEM_COMPLETE=zsh_source stmem)"')
    elif shell == "fish":
        click.echo('eval "$(_STMEM_COMPLETE=fish_source stmem)"')
