#!/usr/bin/env python3
# kg-explorer — Knowledge graph demo.
import os, uuid
from spacetime_memory import Client
c = Client(host=os.environ.get("STMEM_HOST", "localhost"),
           port=int(os.environ.get("STMEM_PORT", "3001")))
try: c._call("register", [f"demo_{os.urandom(4).hex()}", "Demo", "demopass"])
except RuntimeError: pass
ws = uuid.uuid4().hex[:32]
c.create_workspace("kg-demo", "KG Explorer", ws)
print("=== KG Explorer Demo ===")
# Create nodes via SDK method
c.create_node(ws, "SpacetimeDB", "entity", "Deterministic WASM database")
print("  Node: SpacetimeDB (entity)")
c.create_node(ws, "Hermes Agent", "entity", "AI coding agent")
print("  Node: Hermes Agent (entity)")
c.create_node(ws, "Rust", "concept", "Systems programming language")
print("  Node: Rust (concept)")
# Query nodes using filter_dict
spacetimedb = c._query("kg_node", filter_dict={"label": "SpacetimeDB"})
rust = c._query("kg_node", filter_dict={"label": "Rust"})
if spacetimedb and rust:
    c.create_edge(ws, spacetimedb[0]["id"], rust[0]["id"], "built_with")
    print("  Edge: SpacetimeDB --[built_with]--> Rust")
nodes = c._query("kg_node")
edges = c._query("kg_edge")
print(f"Graph: {len(nodes)} nodes, {len(edges)} edges")
c.delete_workspace(ws)
print("Done.\n")
