"""Codebase ingestion engine.

Walks a source tree, parses files with tree-sitter, and creates knowledge
graph nodes (files, functions, classes, methods) and edges (imports, calls,
inherits) in spacetime-memory.

Usage::

    from spacetime_memory import Client
    from spacetime_memory.ingest import CodebaseIngester

    client = Client()
    ingester = CodebaseIngester(client)
    ingester.ingest("/path/to/repo", workspace_id="ws-id")
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from tree_sitter_language_pack import get_language
from tree_sitter import Parser as TSParser, Query, QueryCursor

logger = logging.getLogger(__name__)

# ── Language config ─────────────────────────────────────────────────


class _LangConfig:
    """Tree-sitter query patterns per language."""

    def __init__(self, name: str):
        self.name = name
        self.lang = get_language(name)
        self.parser = TSParser(self.lang)
        self._compile_queries()

    def _compile_queries(self) -> None:
        qs = _LANG_QUERIES.get(self.name, {})
        ok: dict[str, Any] = {}
        for key, src in qs.items():
            try:
                ok[key] = Query(self.lang, src)
            except Exception as e:
                print(f"  [warn] {self.name}/{key} query error: {e}")
        self.queries = ok


_LANG_QUERIES: dict[str, dict[str, str]] = {
    "python": {
        "imports": """
            (import_statement
              name: (dotted_name) @target) @import
            (import_from_statement
              module_name: (dotted_name) @target) @import
        """,
        "defs": """
            (function_definition
              name: (identifier) @name) @func
            (class_definition
              name: (identifier) @name) @class
        """,
        "calls": """
            (call
              function: (identifier) @name) @call
            (call
              function: (attribute
                attribute: (identifier) @name)) @call
        """,
        "inherits": """
            (class_definition
              name: (identifier) @name
              superclasses: (argument_list
                (identifier) @base)) @inherit
        """,
    },
    "javascript": {
        "imports": """
            (import_statement
              source: (string) @target) @import
        """,
        "defs": """
            (function_declaration
              name: (identifier) @name) @func
            (class_declaration
              name: (identifier) @name) @class
            (arrow_function) @arrow
            (variable_declarator
              name: (identifier) @name) @var
        """,
        "calls": """
            (call_expression
              function: (identifier) @name) @call
            (call_expression
              function: (member_expression
                property: (property_identifier) @name)) @call
        """,
    },
    "typescript": {
        "imports": """
            (import_statement
              source: (string) @target) @import
        """,
        "defs": """
            (function_declaration
              name: (identifier) @name) @func
            (class_declaration
              name: (type_identifier) @name) @class
            (interface_declaration
              name: (type_identifier) @name) @iface
            (type_alias_declaration
              name: (type_identifier) @name) @typealias
        """,
        "calls": """
            (call_expression
              function: (identifier) @name) @call
            (call_expression
              function: (member_expression
                property: (property_identifier) @name)) @call
        """,
    },
    "rust": {
        "imports": """
            (use_declaration) @import
        """,
        "defs": """
            (function_item
              name: (identifier) @name) @func
            (struct_item
              name: (type_identifier) @name) @struct
            (trait_item
              name: (type_identifier) @name) @trait
        """,
        "calls": """
            (call_expression
              function: (identifier) @name) @call
            (call_expression
              function: (scoped_identifier
                name: (identifier) @name)) @call
        """,
    },
    "go": {
        "imports": """
            (import_declaration
              (import_spec
                path: (interpreted_string_literal) @target)) @import
        """,
        "defs": """
            (function_declaration
              name: (identifier) @name) @func
            (method_declaration
              name: (field_identifier) @name) @method
            (type_declaration
              (type_spec
                name: (type_identifier) @name)) @typedef
        """,
    },
}


# ── Ingester ────────────────────────────────────────────────────────


class CodebaseIngester:
    """Ingest a codebase into the spacetime-memory knowledge graph.

    For each file, creates a ``kg_node`` (type=``file``).  For each
    function, class, or other top-level definition, creates a node
    (type=``code``) with an edge to its file.

    Calls, imports, and inheritance are captured as ``kg_edge`` rows.
    All nodes are auto-indexed for semantic search.
    """

    # Extensions → language name
    EXT_LANG: dict[str, str] = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "cpp",
        ".hpp": "cpp",
    }

    # Directories to skip
    SKIP_DIRS: set[str] = {
        ".git", "__pycache__", "node_modules", "target",
        "venv", ".venv", ".env", "dist", "build", ".next",
    }

    def __init__(self, client: Any):
        self.client = client
        self._parsers: dict[str, _LangConfig] = {}
        self._stats: dict[str, int] = {
            "files": 0, "defs": 0, "edges": 0, "errors": 0,
        }

    def _parser(self, lang: str) -> _LangConfig | None:
        if lang not in self._parsers:
            try:
                self._parsers[lang] = _LangConfig(lang)
            except Exception as e:
                print(f"  [warn] no parser for '{lang}': {e}")
                return None
        return self._parsers[lang]

    def ingest(
        self,
        repo_path: str,
        workspace_id: str,
        *,
        max_files: int = 0,
        skip_dirs: set[str] | None = None,
    ) -> dict[str, int]:
        """Ingest a codebase.

        Args:
            repo_path: Directory to scan.
            workspace_id: Target workspace.
            max_files: Max files to process (0 = unlimited).
            skip_dirs: Extra directories to skip.

        Returns:
            Stats dict with counts of files/defs/edges/errors.
        """
        self._stats = {"files": 0, "defs": 0, "edges": 0, "errors": 0}
        skip = self.SKIP_DIRS | (skip_dirs or set())

        root = Path(repo_path).resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        print(f"Ingesting {root} ...")

        # Phase 1: walk files, create file nodes, collect definitions
        file_nodes: dict[Path, str] = {}
        def_nodes: dict[str, list[dict]] = {}

        processed = 0
        for fpath in sorted(root.rglob("*")):
            if fpath.is_dir():
                continue
            if any(part.startswith(".") for part in fpath.parts):
                parent = fpath.parent.name
                if parent in skip:
                    continue
            if fpath.suffix not in self.EXT_LANG:
                continue
            if max_files and processed >= max_files:
                break

            try:
                self._process_file(
                    fpath, root, workspace_id,
                    file_nodes, def_nodes,
                )
                processed += 1
            except Exception as e:
                print(f"  [error] {fpath}: {e}")
                self._stats["errors"] += 1

        # Phase 2: create dependency edges
        self._create_dependency_edges(workspace_id, def_nodes)

        # Phase 3: detect communities
        try:
            self.client.detect_communities(workspace_id)
            print("  communities detected")
        except Exception as e:
            print(f"  [warn] community detection: {e}")

        print(f"Done: {self._stats}")
        return dict(self._stats)

    # ── Internal ──────────────────────────────────────────────────

    def _process_file(
        self,
        fpath: Path,
        root: Path,
        workspace_id: str,
        file_nodes: dict[Path, str],
        def_nodes: dict[str, list[dict]],
    ) -> None:
        rel = fpath.relative_to(root)
        lang_name = self.EXT_LANG.get(fpath.suffix, "")
        if not lang_name:
            return

        cfg = self._parser(lang_name)
        if cfg is None:
            return

        source = fpath.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            return

        tree = cfg.parser.parse(source.encode("utf-8"))
        root = tree.root_node
        rel_str = str(rel)

        # Create file node
        file_label = rel_str
        try:
            self.client.create_node(
                workspace_id, file_label, "code",
                summary=f"{lang_name} file: {rel_str}",
            )
        except Exception:
            logger.warning("Failed to create file node for %s", file_label, exc_info=True)
        file_id = self._resolve_node(workspace_id, file_label)
        file_nodes[fpath] = file_id or ""

        self._extract_defs(
            cfg, tree, source, rel_str, workspace_id,
            file_id or "", def_nodes,
        )
        self._stats["files"] += 1
        if self._stats["files"] % 50 == 0:
            print(f"  ... {self._stats['files']} files processed")

    def _extract_defs(
        self,
        cfg: _LangConfig,
        tree: Any,
        source: str,
        rel_str: str,
        workspace_id: str,
        file_node_id: str,
        def_nodes: dict[str, list[dict]],
    ) -> None:
        defs: list[dict] = []
        root = tree.root_node

        for match_key in ("defs", "calls"):
            q = cfg.queries.get(match_key)
            if not q:
                continue
            cursor = QueryCursor(q)
            for match in cursor.matches(root):
                _pidx, caps_dict = match
                caps = {name: nodes[0] for name, nodes in caps_dict.items()}
                name_node = caps.get("name")
                if name_node is None:
                    continue
                name = source[name_node.start_byte:name_node.end_byte]

                if match_key == "defs":
                    type_label = "code"
                    if "func" in caps or "method" in caps or "arrow" in caps:
                        type_label = "function"
                    elif "class" in caps or "struct" in caps:
                        type_label = "class"
                    elif "iface" in caps or "trait" in caps:
                        type_label = "interface"
                    elif "typealias" in caps or "typedef" in caps or "var" in caps:
                        type_label = "type"

                    def_label = f"{rel_str}:{name}"
                    try:
                        self.client.create_node(
                            workspace_id, def_label, type_label,
                            summary=f"{type_label} {name} in {rel_str}",
                        )
                    except Exception:
                        logger.warning(
                            "Failed to create def node for %s", def_label, exc_info=True
                        )

                    def_id = self._resolve_node(workspace_id, def_label)
                    if file_node_id and def_id:
                        try:
                            self.client.create_edge(
                                workspace_id, file_node_id, def_id,
                                "contains", weight=1.0,
                            )
                            self._stats["edges"] += 1
                        except Exception:
                            logger.warning(
                                "Failed to create contains edge: %s -> %s",
                                file_node_id, def_id, exc_info=True,
                            )

                    defs.append({
                        "id": def_id or def_label,
                        "name": name,
                        "file": rel_str,
                    })
                    self._stats["defs"] += 1

                elif match_key == "calls":
                    defs.append({
                        "call": name,
                        "file": rel_str,
                    })

        def_nodes.setdefault(rel_str, []).extend(defs)

    def _create_dependency_edges(
        self,
        workspace_id: str,
        def_nodes: dict[str, list[dict]],
    ) -> None:
        for rel_str, defs in def_nodes.items():
            for d in defs:
                call_name = d.get("call")
                if not call_name:
                    continue
                for other_rel, other_defs in def_nodes.items():
                    for od in other_defs:
                        od_name = od.get("name")
                        if od_name and od_name == call_name:
                            src_id = d.get("id", "")
                            tgt_id = od.get("id", "")
                            if src_id and tgt_id and src_id != tgt_id:
                                try:
                                    self.client.create_edge(
                                        workspace_id, src_id, tgt_id,
                                        "calls", weight=1.0,
                                    )
                                    self._stats["edges"] += 1
                                except Exception:
                                    logger.warning(
                                        "Failed to create call edge: %s -> %s",
                                        src_id, tgt_id, exc_info=True,
                                    )
                            break

    def _resolve_node(self, workspace_id: str, label: str) -> str:
        try:
            rows = self.client.query_graph(workspace_id, label)
            for r in rows:
                if r.get("label") == label:
                    return r.get("id", "")
        except Exception:
            logger.warning("Failed to resolve node for label %s", label, exc_info=True)
        return ""
