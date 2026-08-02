"""Git-backed memory versioning — Letta/QMD parity.

Provides versioned memory management with git as the backend:

- Memory blocks stored as markdown with YAML frontmatter
- Git commit history tracking
- Block operations: create/update/delete/rename
- Tag-based enable/disable
- Rollback to any historical version

All features use native git — no external dependencies.
The versioning store is a standalone git repository that mirrors
selected workspace memories as versioned markdown files.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_VERSIONING_DIR = os.path.expanduser("~/.spacetime-memory/versions")
VERSIONING_MEMORY_TYPE = "versioned_block"


def _run_git(cmd: list[str], cwd: str) -> str:
    """Run a git command and return stdout, raising on failure."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Git command {' '.join(cmd)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _format_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    safe = ""
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe += ch
        elif ch in (" ",):
            safe += "_"
        else:
            safe += "_"
    return safe.strip("_") or "unnamed"


# ---------------------------------------------------------------------------
# GitMemoryVersioningMixin
# ---------------------------------------------------------------------------


class GitMemoryVersioningMixin:
    """Git-backed memory versioning — Letta/QMD parity.

    Provides versioned memory blocks stored as markdown files in a git
    repository, with full commit history and rollback capability.

    Usage::

        # Initialize the versioning store
        client.init_versioning_store("ws-123")

        # Create a versioned block
        block = client.create_versioned_block(
            workspace_id="ws-123",
            name="user-preferences",
            content="User prefers dark mode and short responses.",
            tags=["preference", "user"],
        )

        # Update and commit
        client.update_versioned_block(
            workspace_id="ws-123",
            name="user-preferences",
            content="User prefers dark mode, short responses, and code examples.",
        )

        # View history
        history = client.get_block_history("ws-123", "user-preferences")

        # Rollback
        client.rollback_block("ws-123", "user-preferences", commit_hash="abc123")

        # List all blocks
        blocks = client.list_versioned_blocks("ws-123")
    """

    # ------------------------------------------------------------------
    # Repository management
    # ------------------------------------------------------------------

    def init_versioning_store(
        self,
        workspace_id: str,
        store_dir: str | None = None,
    ) -> dict[str, Any]:
        """Initialize a git repository for versioned memory blocks.

        Args:
            workspace_id: Workspace to create store for.
            store_dir: Custom directory (default: ``~/.spacetime-memory/versions/<ws>``).

        Returns:
            Dict with path, status, and git info.
        """
        ws_dir = store_dir or os.path.join(
            DEFAULT_VERSIONING_DIR, _sanitize_filename(workspace_id)
        )
        os.makedirs(ws_dir, exist_ok=True)

        # Initialize git repo if not already
        git_dir = os.path.join(ws_dir, ".git")
        if not os.path.isdir(git_dir):
            _run_git(["git", "init"], ws_dir)
            _run_git(["git", "config", "user.name", "SpacetimeMemory"], ws_dir)
            _run_git(
                ["git", "config", "user.email", "memory@spacetimedb.local"],
                ws_dir,
            )

        # Create initial commit
        readme_path = os.path.join(ws_dir, "README.md")
        if not os.path.exists(readme_path):
            with open(readme_path, "w") as f:
                f.write(
                    f"# SpacetimeMemory Version Store\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Created: {_format_timestamp()}\n"
                )
            _run_git(["git", "add", "README.md"], ws_dir)
            _run_git(["git", "commit", "-m", "Initial commit"], ws_dir)

        # Store the path on the client instance for later use
        self._versioning_dirs: dict[str, str] = getattr(
            self, "_versioning_dirs", {}
        )
        self._versioning_dirs[workspace_id] = ws_dir

        return {
            "workspace_id": workspace_id,
            "store_dir": ws_dir,
            "status": "initialized",
            "git_available": True,
        }

    def _ensure_store(self, workspace_id: str) -> str:
        """Get the git store directory for a workspace, auto-initializing."""
        dirs: dict[str, str] = getattr(self, "_versioning_dirs", {})
        if workspace_id in dirs:
            return dirs[workspace_id]

        ws_dir = os.path.join(
            DEFAULT_VERSIONING_DIR, _sanitize_filename(workspace_id)
        )
        if os.path.isdir(os.path.join(ws_dir, ".git")):
            dirs[workspace_id] = ws_dir
            self._versioning_dirs = dirs
            return ws_dir

        result = self.init_versioning_store(workspace_id, ws_dir)
        return result["store_dir"]

    # ------------------------------------------------------------------
    # Block operations
    # ------------------------------------------------------------------

    def create_versioned_block(
        self,
        workspace_id: str,
        name: str,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new versioned memory block.

        Args:
            workspace_id: Target workspace.
            name: Human-readable block name (used as filename).
            content: Markdown content.
            tags: Optional categorization tags.
            metadata: Optional metadata dict (YAML frontmatter).

        Returns:
            Dict with block name, path, commit hash.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)
        filepath = os.path.join(store_dir, f"{safe_name}.md")

        if os.path.exists(filepath):
            raise FileExistsError(
                f"Block '{name}' already exists. Use update_versioned_block."
            )

        # Build YAML frontmatter manually (no pyyaml dep needed)
        frontmatter = {
            "block_name": name,
            "created_at": _format_timestamp(),
            "tags": tags or [],
            "type": VERSIONING_MEMORY_TYPE,
        }
        if metadata:
            for k, v in metadata.items():
                if k not in frontmatter:
                    frontmatter[k] = v

        yaml_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                items = "\n".join(f"  - {item}" for item in v)
                yaml_lines.append(f"{k}:\n{items}")
            else:
                yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")

        full_content = "\n".join(yaml_lines) + "\n\n" + content

        with open(filepath, "w") as f:
            f.write(full_content)

        _run_git(["git", "add", f"{safe_name}.md"], store_dir)
        commit_hash = _run_git(
            ["git", "commit", "-m", f"Create block '{name}'"], store_dir
        )

        # Also store as a memory in STDB for searchability
        try:
            self.store(
                workspace_id=workspace_id,
                content=content,
                summary=f"Versioned block: {name}",
                memory_type=VERSIONING_MEMORY_TYPE,
                source_session_id="",
                entities_json=json.dumps(tags or []),
            )
        except Exception:
            pass

        return {
            "name": name,
            "path": filepath,
            "commit_hash": commit_hash,
            "status": "created",
        }

    def update_versioned_block(
        self,
        workspace_id: str,
        name: str,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing versioned block (creates a new commit).

        Args:
            workspace_id: Target workspace.
            name: Block name.
            content: New markdown content.
            tags: Updated tags (None = keep existing).
            metadata: Updated metadata (None = keep existing).

        Returns:
            Dict with block name, commit hash, previous commit hash.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)
        filepath = os.path.join(store_dir, f"{safe_name}.md")

        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Block '{name}' not found. Use create_versioned_block first."
            )

        # Get previous commit hash
        try:
            prev_hash = _run_git(
                ["git", "log", "--oneline", "-1", "--format=%H", "--", f"{safe_name}.md"],
                store_dir,
            )
        except RuntimeError:
            prev_hash = "none"

        # Read existing frontmatter if tags/metadata not provided
        if tags is None or metadata is None:
            existing = self._read_block_file(filepath)
            if tags is None:
                tags = existing.get("tags", [])
            if metadata is None:
                metadata = {k: v for k, v in existing.items()
                           if k not in ("block_name", "created_at",
                                        "tags", "type")}

        # Build frontmatter
        frontmatter = {
            "block_name": name,
            "created_at": _format_timestamp(),
            "tags": tags or [],
            "type": VERSIONING_MEMORY_TYPE,
        }
        if metadata:
            for k, v in metadata.items():
                if k not in frontmatter:
                    frontmatter[k] = v

        yaml_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                items = "\n".join(f"  - {item}" for item in v)
                yaml_lines.append(f"{k}:\n{items}")
            else:
                yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")

        full_content = "\n".join(yaml_lines) + "\n\n" + content

        with open(filepath, "w") as f:
            f.write(full_content)

        _run_git(["git", "add", f"{safe_name}.md"], store_dir)
        commit_hash = _run_git(
            ["git", "commit", "-m", f"Update block '{name}'"], store_dir
        )

        return {
            "name": name,
            "path": filepath,
            "commit_hash": commit_hash,
            "previous_commit_hash": prev_hash,
            "status": "updated",
        }

    def delete_versioned_block(
        self,
        workspace_id: str,
        name: str,
    ) -> dict[str, Any]:
        """Delete a versioned block (git rm + commit).

        Args:
            workspace_id: Target workspace.
            name: Block name.

        Returns:
            Dict with block name and status.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)
        filepath = os.path.join(store_dir, f"{safe_name}.md")

        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Block '{name}' not found."
            )

        os.remove(filepath)
        _run_git(["git", "rm", f"{safe_name}.md"], store_dir)
        commit_hash = _run_git(
            ["git", "commit", "-m", f"Delete block '{name}'"], store_dir
        )

        return {
            "name": name,
            "commit_hash": commit_hash,
            "status": "deleted",
        }

    def rename_versioned_block(
        self,
        workspace_id: str,
        old_name: str,
        new_name: str,
    ) -> dict[str, Any]:
        """Rename a versioned block.

        Args:
            workspace_id: Target workspace.
            old_name: Current block name.
            new_name: New block name.

        Returns:
            Dict with old/new names and commit hash.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_old = _sanitize_filename(old_name)
        safe_new = _sanitize_filename(new_name)
        old_path = os.path.join(store_dir, f"{safe_old}.md")
        new_path = os.path.join(store_dir, f"{safe_new}.md")

        if not os.path.exists(old_path):
            raise FileNotFoundError(f"Block '{old_name}' not found.")

        shutil.move(old_path, new_path)
        _run_git(["git", "add", f"{safe_old}.md", f"{safe_new}.md"], store_dir)
        _run_git(["git", "rm", "--cached", f"{safe_old}.md"], store_dir)
        commit_hash = _run_git(
            ["git", "commit", "-m", f"Rename block '{old_name}' → '{new_name}'"],
            store_dir,
        )

        return {
            "old_name": old_name,
            "new_name": new_name,
            "commit_hash": commit_hash,
            "status": "renamed",
        }

    # ------------------------------------------------------------------
    # History & rollback
    # ------------------------------------------------------------------

    def get_block_history(
        self,
        workspace_id: str,
        name: str,
        max_count: int = 20,
    ) -> list[dict[str, Any]]:
        """Get the commit history for a versioned block.

        Args:
            workspace_id: Target workspace.
            name: Block name.
            max_count: Max commits to return.

        Returns:
            List of dicts with commit_hash, author, date, message.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)

        try:
            log = _run_git(
                [
                    "git", "log", f"--max-count={max_count}",
                    "--format=%H|%an|%ai|%s",
                    "--", f"{safe_name}.md",
                ],
                store_dir,
            )
        except RuntimeError:
            return []

        history = []
        for line in log.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                history.append({
                    "commit_hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                    "block_name": name,
                })
        return history

    def get_block_at_commit(
        self,
        workspace_id: str,
        name: str,
        commit_hash: str,
    ) -> dict[str, Any]:
        """Get the content of a block at a specific commit.

        Args:
            workspace_id: Target workspace.
            name: Block name.
            commit_hash: Git commit hash.

        Returns:
            Dict with block content and metadata.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)

        content = _run_git(
            ["git", "show", f"{commit_hash}:{safe_name}.md"],
            store_dir,
        )
        parsed = self._parse_block_content(content)
        parsed["commit_hash"] = commit_hash
        return parsed

    def rollback_block(
        self,
        workspace_id: str,
        name: str,
        commit_hash: str,
    ) -> dict[str, Any]:
        """Rollback a block to a specific historical version.

        Args:
            workspace_id: Target workspace.
            name: Block name.
            commit_hash: Target commit hash to rollback to.

        Returns:
            Dict with rollback result.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)

        # Checkout the file from the target commit
        _run_git(
            ["git", "checkout", commit_hash, "--", f"{safe_name}.md"],
            store_dir,
        )
        commit_hash_new = _run_git(
            ["git", "commit", "-m", f"Rollback block '{name}' to {commit_hash[:8]}"],
            store_dir,
        )

        return {
            "name": name,
            "rollback_to": commit_hash,
            "commit_hash": commit_hash_new,
            "status": "rolled_back",
        }

    # ------------------------------------------------------------------
    # Listing & querying
    # ------------------------------------------------------------------

    def list_versioned_blocks(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List all versioned blocks for a workspace.

        Returns:
            List of block dicts with name, path, last_modified, tags.
        """
        store_dir = self._ensure_store(workspace_id)

        blocks = []
        for fname in os.listdir(store_dir):
            if not fname.endswith(".md") or fname == "README.md":
                continue
            filepath = os.path.join(store_dir, fname)
            parsed = self._read_block_file(filepath)
            blocks.append({
                "name": parsed.get("block_name", fname[:-3]),
                "path": filepath,
                "tags": parsed.get("tags", []),
                "last_modified": time.ctime(os.path.getmtime(filepath)),
                "block_name": parsed.get("block_name", ""),
            })

        return blocks

    def read_versioned_block(
        self,
        workspace_id: str,
        name: str,
    ) -> dict[str, Any]:
        """Read the current content of a versioned block.

        Args:
            workspace_id: Target workspace.
            name: Block name.

        Returns:
            Dict with block content, frontmatter, and metadata.
        """
        store_dir = self._ensure_store(workspace_id)
        safe_name = _sanitize_filename(name)
        filepath = os.path.join(store_dir, f"{safe_name}.md")

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Block '{name}' not found.")

        with open(filepath) as f:
            content = f.read()

        return self._parse_block_content(content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_block_content(self, content: str) -> dict[str, Any]:
        """Parse a markdown file with YAML frontmatter.

        Returns dict with 'content' (markdown body) and individual
        frontmatter fields.
        """
        result: dict[str, Any] = {"content": content}
        text = content.strip()

        if text.startswith("---"):
            end_idx = text.find("---", 3)
            if end_idx != -1:
                frontmatter_text = text[3:end_idx].strip()
                body = text[end_idx + 3:].strip()
                result["content"] = body

                # Parse YAML frontmatter (handles multi-line lists)
                lines = frontmatter_text.split("\n")
                current_key = None
                current_list = None

                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if ":" in line and not line.lstrip().startswith("- "):
                        # New key-value pair
                        if current_key is not None and current_list is not None:
                            result[current_key] = current_list
                            current_list = None
                        key, _, val = line.partition(":")
                        current_key = key.strip()
                        val = val.strip()
                        if val == "":
                            # Could be a multi-line list
                            current_list = []
                            result[current_key] = current_list
                        else:
                            # Scalar value
                            if val.startswith("[") and val.endswith("]"):
                                try:
                                    val = json.loads(val)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            elif val.startswith('"') and val.endswith('"'):
                                val = val[1:-1]
                            elif val == "true":
                                val = True
                            elif val == "false":
                                val = False
                            elif val.isdigit():
                                val = int(val)
                            result[current_key] = val
                            current_key = None
                            current_list = None
                    elif stripped.startswith("- ") and current_list is not None:
                        # List item
                        item = stripped[2:].strip()
                        # Try to parse simple types
                        if item == "true":
                            item = True
                        elif item == "false":
                            item = False
                        elif item.isdigit():
                            item = int(item)
                        elif item.startswith('"') and item.endswith('"'):
                            item = item[1:-1]
                        current_list.append(item)

                if current_key is not None and current_list is not None:
                    result[current_key] = current_list

        return result

    def _read_block_file(self, filepath: str) -> dict[str, Any]:
        """Read and parse a block file."""
        with open(filepath) as f:
            content = f.read()
        return self._parse_block_content(content)
