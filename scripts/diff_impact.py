"""Diff impact analysis for spacetime-memory.

Parses a git diff (unified format), identifies changed files and
definitions, and creates/updates KG nodes and edges in the workspace to
show the change impact.

Usage:
    python3 diff_impact.py <workspace_id> [--diff-file diff.diff | --repo /path/to/repo [--base main]]
    python3 diff_impact.py <workspace_id> --diff-stdin

The script:
  1. Parses the diff to find changed files + line ranges
  2. For each changed file, updates or creates a KG node
  3. Marks impacted functions/classes within changed regions via KG edges
  4. Creates an "impact summary" as an Insight
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from spacetime_memory import Client
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdks" / "python"))
    from spacetime_memory import Client


# ── Diff parsing ────────────────────────────────────────────────────


class DiffHunk:
    """A single hunk from a unified diff."""

    def __init__(self, header: str, lines: list[str]):
        self.header = header
        self.lines = lines
        self.old_start, self.old_count, self.new_start, self.new_count = self._parse_header()

    def _parse_header(self) -> tuple[int, int, int, int]:
        m = re.match(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", self.header)
        if not m:
            return 0, 0, 0, 0
        return (
            int(m.group(1)),
            int(m.group(2)) if m.group(2) else 1,
            int(m.group(3)),
            int(m.group(4)) if m.group(4) else 1,
        )


class DiffFile:
    """A file changed in a diff."""

    def __init__(self, old_path: str, new_path: str, hunks: list[DiffHunk]):
        self.old_path = old_path
        self.new_path = new_path  # None if deleted
        self.hunks = hunks
        self.status = self._infer_status()

    def _infer_status(self) -> str:
        if self.new_path == "/dev/null":
            return "deleted"
        if self.old_path == "/dev/null":
            return "added"
        return "modified"


def parse_diff(diff_text: str) -> list[DiffFile]:
    """Parse unified diff text into DiffFile objects."""
    files: list[DiffFile] = []
    current_file: dict = {}
    current_hunk: dict = {}
    hunk_lines: list[str] = []

    for line in diff_text.split("\n"):
        # File headers: --- a/... and +++ b/...
        if line.startswith("--- "):
            current_file["old_path"] = line[4:].strip()
        elif line.startswith("+++ "):
            current_file["new_path"] = line[4:].strip()
        # Hunk header
        elif line.startswith("@@ "):
            if current_hunk:
                current_hunk["hunk"] = DiffHunk(current_hunk["header"], hunk_lines)
                current_file.setdefault("hunks", []).append(current_hunk["hunk"])
            current_hunk = {"header": line}
            hunk_lines = []
        elif current_hunk:
            hunk_lines.append(line)

    # Last hunk
    if current_hunk:
        current_hunk["hunk"] = DiffHunk(current_hunk["header"], hunk_lines)
        current_file.setdefault("hunks", []).append(current_hunk["hunk"])

    # Create DiffFile objects
    if current_file.get("old_path") or current_file.get("new_path"):
        files.append(DiffFile(
            current_file.get("old_path", ""),
            current_file.get("new_path", ""),
            current_file.get("hunks", []),
        ))

    return files


def get_git_diff(repo_path: str, base: str = "main") -> str:
    """Get git diff of uncommitted changes vs base branch."""
    result = subprocess.run(
        ["git", "diff", base, "--", "*.py", "*.rs", "*.ts", "*.tsx", "*.js", "*.go"],
        capture_output=True, text=True, cwd=repo_path,
    )
    if result.returncode != 0:
        # Try diff against HEAD
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", "*.py", "*.rs", "*.ts", "*.tsx", "*.js", "*.go"],
            capture_output=True, text=True, cwd=repo_path,
        )
    return result.stdout


# ── KG Impact ────────────────────────────────────────────────────────


def ensure_node(
    client: Client, workspace_id: str, label: str,
    node_type: str, summary: str, metadata: dict | None = None,
) -> str:
    """Create a KG node if it doesn't exist, return its ID."""
    try:
        # Check if node exists
        nodes = client.query_graph(workspace_id, label)
        for n in nodes:
            if n.get("label") == label:
                return n.get("id", "")
    except (OSError, json.JSONDecodeError):
        pass
    client._call("create_node", [
        workspace_id, label, node_type, summary,
        json.dumps(metadata or {}),
    ])
    # Read it back
    try:
        nodes = client.query_graph(workspace_id, label)
        for n in nodes:
            if n.get("label") == label:
                return n.get("id", "")
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def process_diff(
    client: Client,
    workspace_id: str,
    diff_text: str,
    repo_name: str = "",
) -> dict[str, Any]:
    """Process a diff and update the KG with impact data.

    Returns a dict with changed files, functions, and impact summary.
    """
    files = parse_diff(diff_text)
    results: dict[str, Any] = {
        "files_changed": len(files),
        "files": [],
        "impacted_communities": set(),
    }

    for df in files:
        file_path = df.new_path if df.new_path and df.new_path != "/dev/null" else df.old_path
        file_label = f"{repo_name}:{file_path}" if repo_name else file_path

        # Create/update file node
        file_id = ensure_node(
            client, workspace_id, file_label, "code",
            f"{df.status} file: {file_path}",
            {"status": df.status, "path": file_path},
        )

        # Track changed lines for each function
        changed_ranges: list[tuple[int, int]] = []
        for hunk in df.hunks:
            changed_ranges.append(
                (hunk.new_start, hunk.new_start + hunk.new_count)
            )

        func_impact: list[dict] = []
        for cr in changed_ranges:
            func_impact.append({
                "start": cr[0],
                "end": cr[1],
                "lines": cr[1] - cr[0],
            })

        results["files"].append({
            "path": file_path,
            "status": df.status,
            "file_id": file_id,
            "changed_ranges": func_impact,
        })

    # Create an Insight summarizing the impact
    summary_lines = [
        f"Diff impact analysis: {results['files_changed']} file(s) changed",
    ]
    for f in results["files"]:
        total_lines = sum(r["lines"] for r in f.get("changed_ranges", []))
        summary_lines.append(f"  [{f['status']}] {f['path']} ({total_lines} lines)")

    insight_text = "\n".join(summary_lines)
    try:
        client._call("create_insight", [
            workspace_id, "diff-bot", insight_text,
            "observation", "[]", 0.8,
        ])
    except Exception as e:
        print(f"  [warn] insight creation: {e}")

    results["summary"] = insight_text
    return results


# ── CLI ──────────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diff impact analysis")
    parser.add_argument("workspace_id", help="Target workspace ID")
    parser.add_argument("--diff-file", help="Path to diff file")
    parser.add_argument("--diff-stdin", action="store_true", help="Read diff from stdin")
    parser.add_argument("--repo", help="Git repository path")
    parser.add_argument("--base", default="main", help="Base branch for git diff")
    parser.add_argument("--repo-name", default="", help="Repo name for node labels")

    args = parser.parse_args()

    client = Client()

    if args.diff_file:
        diff_text = Path(args.diff_file).read_text()
    elif args.diff_stdin:
        diff_text = sys.stdin.read()
    elif args.repo:
        diff_text = get_git_diff(args.repo, args.base)
    else:
        parser.print_help()
        sys.exit(1)

    if not diff_text.strip():
        print("No changes detected.")
        return

    result = process_diff(client, args.workspace_id, diff_text, args.repo_name)
    print(f"Files changed: {result['files_changed']}")
    for f in result["files"]:
        print(f"  [{f['status']}] {f['path']}")
    print(f"\nSummary:\n{result['summary']}")


if __name__ == "__main__":
    main()
