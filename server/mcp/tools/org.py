"""MCP tools — Org-mode sync tool."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Org-mode sync tool
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def org_sync(
    workspace_id: str,
    directory: str = "~/org",
    dry_run: bool = False,
) -> str:
    """One-shot sync of .org files in a directory to Spacetime Memory as notes and KG task nodes.

    Scans all .org files under DIRECTORY, parses headings with OrgModeParser,
    and stores each heading as a memory. TODO items are additionally created
    as knowledge graph nodes (type="task").

    Args:
        workspace_id: The target workspace to sync into.
        directory: Path to directory containing .org files (default: ~/org).
        dry_run: If True, preview changes without writing any data.

    Returns:
        A summary string describing how many events were synced.
    """
    import os
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"),
    )
    from org_sync_daemon import OrgSyncDaemon

    daemon = OrgSyncDaemon(
        org_dir=directory,
        workspace_id=workspace_id,
        client=get_client(),
        dry_run=dry_run,
    )
    total = daemon.scan()
    if dry_run:
        return f"[dry-run] Org sync would produce {total} events from {daemon.get_status()['files_tracked']} file(s)."
    return f"Org sync complete — {total} events synced from {daemon.get_status()['files_tracked']} file(s)."


# ---------------------------------------------------------------------------
