#!/usr/bin/env python3
# llm-wiki — LLM Wiki pattern demo.
import os, uuid
from spacetime_memory import Client
c = Client(host=os.environ.get("STMEM_HOST", "localhost"),
           port=int(os.environ.get("STMEM_PORT", "3001")))
try: c._call("register", [f"demo_{os.urandom(4).hex()}", "Demo", "demopass"])
except RuntimeError: pass
ws = uuid.uuid4().hex[:32]
c.create_workspace("wiki-demo", "LLM Wiki", ws)
print("=== LLM Wiki Demo ===")
# Store a wiki-like memory
c.store(workspace_id=ws, content="# SpacetimeDB\nSpacetimeDB stores logic as WASM reducers.", memory_type="note")
print("  Wiki memory stored")
# Search it back
results = c.search(workspace_id=ws, query="WASM database")
for r in results:
    print(f"  [{r.get('score', 0):.2f}] {r.get('content', r.get('memory', ''))[:60]}")
c.delete_workspace(ws)
print("Done.\n")
