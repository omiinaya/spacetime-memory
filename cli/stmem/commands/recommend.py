"""Recommend command"""

from __future__ import annotations

from typing import Any

import click


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
    print_json,
)

# ===================================================================
# recommend command
# ===================================================================


@cli.command(name="recommend")
@click.argument("workspace_id")
@click.option("--limit", default=20, type=int, help="Max recommendations")
@click.option("--min-urgency", default=0.3, type=float,
              help="Minimum urgency threshold (0.0-1.0)")
@click.pass_context
def recommend(ctx: click.Context, workspace_id: str, limit: int,
              min_urgency: float) -> None:
    """Recommend memories needing attention (review/reinforce/discard)."""

    def _run() -> list[dict[str, Any]]:
        with _root.console.status("Analyzing memories..."):
            return _sdk_client().recommend_memories(
                workspace_id, limit=limit, min_urgency=min_urgency,
            )

    rows = _run()
    if rows:
        # Color by action
        action_colors = {"discard": "red", "reinforce": "yellow", "review": "cyan"}
        for r in rows:
            action = r.get("action", "review")
            color = action_colors.get(action, "white")
            urgency = r.get("urgency", 0.0)
            content = (r.get("content", "") or "")[:120]
            _root.console.print(
                f"[{color}][{action.upper():>9}][/{color}] "
                f"[dim]urgency={urgency:.2f}[/dim] "
                f"trust={r.get('trust_score', 0):.2f} "
                f"fb={r.get('feedback_count', 0)} "
                f"[italic]{content}[/italic]"
            )
        if ctx.obj.get("output") == "json":
            print_json(rows)
    else:
        _root.console.print("[green]No memories need attention — all clear![/green]")
