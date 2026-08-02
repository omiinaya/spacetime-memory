#!/usr/bin/env python3
"""Bridge: import Graphify codebase knowledge into STMEM notes + KG nodes.

Usage:
  python3 scripts/graphify_bridge.py import-gods [--limit 20] [--workspace default]
  python3 scripts/graphify_bridge.py import-repo <repo> [--workspace default] [--max-nodes 500]
  python3 scripts/graphify_bridge.py import-community <id> [--workspace default] [--max-nodes 500]
  python3 scripts/graphify_bridge.py search <query> [--workspace default] [--max-nodes 50]
"""

import argparse, json, os, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

GRAPH_PATH = "$HOME/graphify/master/graph.json"
DEFAULT_WORKSPACE = "default"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_graph(path: str) -> dict:
    """Load Graphify master graph JSON."""
    with open(path) as f:
        return json.load(f)


def build_index(nodes: list[dict]) -> dict[str, dict]:
    """Build id → node lookup index."""
    idx = {}
    for n in nodes:
        idx[n["id"]] = n
    return idx


def file_type_to_node_type(file_type: str) -> str:
    mapping = {
        "code": "code",
        "concept": "concept",
        "document": "document",
        "rationale": "rationale",
    }
    return mapping.get(file_type, "concept")


def get_node_summary(node: dict) -> str:
    parts = []
    if node.get("repo"):
        parts.append(f"repo: {node['repo']}")
    if node.get("source_file"):
        parts.append(f"file: {node['source_file']}")
    if node.get("source_location"):
        parts.append(f"line: {node['source_location']}")
    if node.get("community") is not None:
        parts.append(f"community: {node['community']}")
    return " | ".join(parts) if parts else node.get("norm_label", node["label"])


def format_node_note(node: dict) -> str:
    lines = [
        f"# {node['label']}",
        "",
        f"**Type:** {node.get('file_type', 'unknown')}",
        f"**Repository:** {node.get('repo', 'unknown')}",
        f"**Source:** `{node.get('source_file', '?')}` at {node.get('source_location', '?')}",
        f"**Graphify Community:** {node.get('community', '?')}",
        "",
        "---",
        "",
        "### Graphify Node Metadata",
        "",
        f"- **ID:** `{node['id']}`",
        f"- **Normalized Label:** `{node.get('norm_label', '')}`",
        "",
        "### Connected Concepts",
        "",
        "This node is part of the Graphify codebase knowledge graph. "
        "Query via spacetime_search to find related code entities.",
        "",
        "---",
        f"*Imported from Graphify master graph*",
    ]
    return "\n".join(lines)
# Part 2: Import logic — appends to graphify_bridge.py
# Run: cat graphify_bridge_import.py >> graphify_bridge.py

# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------

def _compute_god_scores(nodes: list[dict], links: list[dict]) -> dict[str, int]:
    """Compute degree centrality (edge count) per node."""
    scores: dict[str, int] = {}
    for link in links:
        scores[link["source"]] = scores.get(link["source"], 0) + 1
        scores[link["target"]] = scores.get(link["target"], 0) + 1
    return scores


def _get_workspace_id(client, args_ws: str | None) -> tuple[str, str]:
    """Resolve workspace — returns (name, id). Creates if needed."""
    import uuid as _uuid
    import os as _os

    name = args_ws or DEFAULT_WORKSPACE
    try:
        client._call("set_initial_admin", [])
    except RuntimeError:
        pass
    # Try creating workspace (fails silently if already exists)
    try:
        ws_id = _uuid.uuid4().hex[:32]
        client._call("create_workspace", [name, f"Graphify bridge - {name}", ws_id])
        return (name, ws_id)
    except RuntimeError:
        pass
    # Fallback: create unique workspace
    peer_id = client._identity_token[-8:] if client._identity_token else _os.urandom(4).hex()
    alt_name = f"graphify-{peer_id}"
    try:
        ws_id = _uuid.uuid4().hex[:32]
        client._call("create_workspace", [alt_name, f"Graphify bridge - {alt_name}", ws_id])
        print(f"  Created workspace '{alt_name}' (id: {ws_id})")
        return (alt_name, ws_id)
    except RuntimeError as e:
        print(f"  Warning: Could not create workspace: {e}")
        return (name, name)


def _import_nodes(
    client,
    workspace_id: str,
    nodes_to_import: list[dict],
    node_index: dict[str, dict],
    links: list[dict],
    dry_run: bool = False,
) -> dict:
    """Import a list of Graphify nodes into STMEM."""
    imported_ids: set[str] = set()
    stats = {"nodes": 0, "edges": 0, "notes": 0, "errors": 0}

    node_id_map: dict[str, str] = {}  # graphify_id → stmem_node_id

    print(f"\nImporting {len(nodes_to_import)} nodes into workspace '{workspace_id}'...")

    for i, gnode in enumerate(nodes_to_import):
        label = f"graphify:{gnode['label']}"
        ntype = file_type_to_node_type(gnode.get("file_type", "code"))
        summary = get_node_summary(gnode)
        metadata = json.dumps({
            "graphify_id": gnode["id"],
            "graphify_community": gnode.get("community"),
            "source_file": gnode.get("source_file", ""),
            "source_location": gnode.get("source_location", ""),
            "repo": gnode.get("repo", ""),
        })

        if dry_run:
            print(f"  [DRY] Would create node '{label}' ({ntype})")
            imported_ids.add(gnode["id"])
            continue

        try:
            result = client.create_node(
                workspace_id=workspace_id,
                label=label,
                node_type=ntype,
                summary=summary,
                metadata_json=metadata,
            )
            # Find the STMEM node ID from the just-created node
            rows = client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={"label": label},
                columns=["id"],
            )
            if rows:
                node_id_map[gnode["id"]] = rows[-1]["id"]
            imported_ids.add(gnode["id"])
            stats["nodes"] += 1

            # Also create a note for richer context
            note_content = format_node_note(gnode)
            try:
                client.create_note(
                    workspace_id=workspace_id,
                    title=f"graphify: {gnode['label']}",
                    content=note_content,
                    embed=True,
                )
                stats["notes"] += 1
            except RuntimeError as e:
                print(f"  ⚠ Note error for '{label}': {e}")
                stats["errors"] += 1

            if (i + 1) % 20 == 0:
                print(f"  Progress: {i+1}/{len(nodes_to_import)} nodes...")

        except RuntimeError as e:
            print(f"  ✗ Error creating node '{label}': {e}")
            stats["errors"] += 1

    # Create edges between imported nodes
    if not dry_run:
        local_ids = imported_ids  # graphify node IDs in this batch
        relevant_edges = [
            link for link in links
            if link["source"] in local_ids and link["target"] in local_ids
        ]
        print(f"  Creating {len(relevant_edges)} edges between imported nodes...")

        for link in relevant_edges:
            src_stmem = node_id_map.get(link["source"])
            tgt_stmem = node_id_map.get(link["target"])
            if not src_stmem or not tgt_stmem:
                continue
            try:
                client.create_edge(
                    workspace_id=workspace_id,
                    source_node_id=src_stmem,
                    target_node_id=tgt_stmem,
                    relation=link["relation"],
                    weight=link.get("weight", 1.0),
                    confidence=link.get("confidence", "EXTRACTED"),
                )
                stats["edges"] += 1
            except RuntimeError:
                pass  # edge may already exist

    return stats


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_import_gods(client, args):
    """Import top-N most-connected nodes (god nodes)."""
    print("Computing god nodes (degree centrality)...")
    graph = load_graph(GRAPH_PATH)
    scores = _compute_god_scores(graph["nodes"], graph.get("links", []))
    sorted_nodes = sorted(scores.items(), key=lambda x: -x[1])
    limit = args.limit
    top_ids = [nid for nid, _ in sorted_nodes[:limit]]

    node_index = build_index(graph["nodes"])
    nodes = [node_index[nid] for nid in top_ids if nid in node_index]
    ws_name, ws = _get_workspace_id(client, args.workspace)
    print(f"Using workspace '{ws_name}' (id: {ws})")

    print(f"Top god nodes: {[n['label'] for n in nodes]}")
    stats = _import_nodes(client, ws, nodes, node_index, graph.get("links", []), dry_run=args.dry_run)
    print(f"\n✅ Done: {stats['nodes']} nodes, {stats['edges']} edges, {stats['notes']} notes ({stats['errors']} errors)")


def cmd_import_repo(client, args):
    """Import all nodes for a specific repository."""
    graph = load_graph(GRAPH_PATH)
    repo = args.repo
    nodes = [n for n in graph["nodes"] if n.get("repo") == repo]

    if not nodes:
        print(f"No nodes found for repo '{repo}'")
        return

    max_n = args.max_nodes
    if len(nodes) > max_n:
        print(f"Repo '{repo}' has {len(nodes)} nodes, limiting to {max_n}")
        nodes = nodes[:max_n]

    node_index = build_index(graph["nodes"])
    ws_name, ws = _get_workspace_id(client, args.workspace)
    print(f"Using workspace '{ws_name}' (id: {ws})")
    print(f"Repo '{repo}': {len(nodes)} nodes to import")

    stats = _import_nodes(client, ws, nodes, node_index, graph.get("links", []), dry_run=args.dry_run)
    print(f"\n✅ Done: {stats['nodes']} nodes, {stats['edges']} edges, {stats['notes']} notes ({stats['errors']} errors)")


def cmd_import_community(client, args):
    """Import all nodes in a specific Graphify community."""
    graph = load_graph(GRAPH_PATH)
    cid = args.community_id
    nodes = [n for n in graph["nodes"] if n.get("community") == cid]

    if not nodes:
        print(f"No nodes found for community {cid}")
        return

    max_n = args.max_nodes
    if len(nodes) > max_n:
        print(f"Community {cid} has {len(nodes)} nodes, limiting to {max_n}")
        nodes = nodes[:max_n]

    node_index = build_index(graph["nodes"])
    ws_name, ws = _get_workspace_id(client, args.workspace)
    print(f"Using workspace '{ws_name}' (id: {ws})")
    print(f"Community {cid}: {len(nodes)} nodes to import")

    stats = _import_nodes(client, ws, nodes, node_index, graph.get("links", []), dry_run=args.dry_run)
    print(f"\n✅ Done: {stats['nodes']} nodes, {stats['edges']} edges, {stats['notes']} notes ({stats['errors']} errors)")


def cmd_search(client, args):
    """Search Graphify nodes by label and import matches."""
    graph = load_graph(GRAPH_PATH)
    q = args.query.lower()
    nodes = [n for n in graph["nodes"] if q in n["label"].lower() or q in n.get("norm_label", "").lower()]

    if not nodes:
        print(f"No nodes matching '{args.query}'")
        return

    max_n = args.max_nodes
    if len(nodes) > max_n:
        print(f"Found {len(nodes)} matching nodes, limiting to {max_n}")
        nodes = nodes[:max_n]

    node_index = build_index(graph["nodes"])
    ws_name, ws = _get_workspace_id(client, args.workspace)
    print(f"Using workspace '{ws_name}' (id: {ws})")
    print(f"Query '{args.query}': {len(nodes)} nodes to import")

    stats = _import_nodes(client, ws, nodes, node_index, graph.get("links", []), dry_run=args.dry_run)
    print(f"\n✅ Done: {stats['nodes']} nodes, {stats['edges']} edges, {stats['notes']} notes ({stats['errors']} errors)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Graphify → STMEM bridge")
    parser.add_argument("--workspace", help=f"STMEM workspace ID (default: '{DEFAULT_WORKSPACE}')")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without making changes")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gods = sub.add_parser("import-gods", help="Import top-N most-connected god nodes")
    p_gods.add_argument("--limit", type=int, default=20, help="Number of god nodes (default: 20)")

    p_repo = sub.add_parser("import-repo", help="Import all nodes for a repo")
    p_repo.add_argument("repo", help="Repository name (e.g. 'spacetime-memory')")
    p_repo.add_argument("--max-nodes", type=int, default=500, help="Max nodes to import (default: 500)")

    p_comm = sub.add_parser("import-community", help="Import all nodes in a community")
    p_comm.add_argument("community_id", type=int, help="Community ID")
    p_comm.add_argument("--max-nodes", type=int, default=500, help="Max nodes (default: 500)")

    p_search = sub.add_parser("search", help="Search nodes by label and import matches")
    p_search.add_argument("query", help="Search term")
    p_search.add_argument("--max-nodes", type=int, default=50, help="Max nodes (default: 50)")

    args = parser.parse_args()

    # --dry-run is on parent but subparsers inherit it
    dry_run = getattr(args, 'dry_run', False)
    workspace = getattr(args, 'workspace', None)

    from spacetime_memory.client import Client

    import os as _os
    _host = _os.environ.get("STMEM_HOST", _os.environ.get("SPACETIMEDB_HOST", "127.0.0.1"))
    _port = _os.environ.get("STMEM_PORT", _os.environ.get("SPACETIMEDB_PORT", "3001"))
    _db = _os.environ.get("STMEM_DB", _os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))
    client = Client(host=_host, port=_port, database=_db)
    suffix = _os.urandom(4).hex()
    try:
        client._call("register", [f"graphify-bridge_{suffix}", "Graphify Bridge", "graphify_bridge_pass"])
    except RuntimeError:
        pass

    # Override args for command functions
    args.dry_run = dry_run
    args.workspace = workspace

    commands = {
        "import-gods": cmd_import_gods,
        "import-repo": cmd_import_repo,
        "import-community": cmd_import_community,
        "search": cmd_search,
    }
    commands[args.command](client, args)


if __name__ == "__main__":
    main()
