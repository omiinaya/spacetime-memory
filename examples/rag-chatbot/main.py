#!/usr/bin/env python3
"""rag-chatbot — Hybrid search demo."""
import os, uuid
from spacetime_memory import Client
c = Client(host=os.environ.get("STMEM_HOST", "localhost"),
           port=int(os.environ.get("STMEM_PORT", "3001")))
try: c._call("register", [f"demo_{os.urandom(4).hex()}", "Demo", "demopass"])
except RuntimeError: pass
ws = uuid.uuid4().hex[:32]
c.create_workspace("rag-demo", "RAG Example", ws)
print("=== RAG Chatbot Demo ===")
docs = [
    "SpacetimeDB uses deterministic WASM modules for server-side logic.",
    "The Python SDK provides reducer-based CRUD with JWT authentication.",
    "Bge-m3 is a 1024-dim multilingual embedding model from BAAI.",
]
for i, d in enumerate(docs):
    c.store(workspace_id=ws, content=d)
    print(f"  Stored doc {i+1}")
results = c.search(workspace_id=ws, query="How does SpacetimeDB run code?")
for r in results:
    print(f"  [{r.get('score', 0):.2f}] {r.get('content', r.get('memory', ''))[:60]}")
c.delete_workspace(ws)
print("Done.\n")
