#!/usr/bin/env python3
"""Full eval pipeline: populate + resolve + evaluate in one shot."""
import json, sys, time, uuid
sys.path.insert(0, "/home/user/spacetime-memory/sdk/python")
from spacetime_memory import Client
from spacetime_memory.client import _query_hash

HOST, PORT = "localhost", 3001
DB = "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff"

# ── Setup ───────────────────────────────────────────────────────────
c = Client(host=HOST, port=PORT, database=DB)
uname = f"eval_{uuid.uuid4().hex[:6]}"
try: c._call("register", [uname, "Eval", "evalpass"])
except: pass
c._call("login", [uname, "evalpass"])

with open("scripts/.cron_identity_token", "w") as f:
    f.write(c._identity_token)

ws_id = f"eval-final-{uuid.uuid4().hex[:8]}"
c._call("create_workspace", ["eval_final", "Final eval", ws_id])
print(f"Workspace: {ws_id}")

# ── Load memories ───────────────────────────────────────────────────
import importlib.util
spec = importlib.util.spec_from_file_location("gen", "scripts/generate_eval_dataset_large.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# ── Store with fixed SDK ────────────────────────────────────────────
print(f"Storing {len(mod.MEMORIES)} memories (indexed, ~1s each)...")
for i, (text, mtype) in enumerate(mod.MEMORIES):
    try:
        c.store(workspace_id=ws_id, content=text, memory_type=mtype, peer_id=uname, confidence=0.8)
    except Exception as e:
        print(f"  [{i}] store FAIL: {str(e)[:80]}")
    if (i+1) % 20 == 0:
        print(f"  {i+1}/{len(mod.MEMORIES)}...")

print("Waiting for indexing to settle...")
time.sleep(5)

# ── Resolve IDs by content-exact match via query_table ──────────────
# The hybrid_search entity_ids should match memory UUIDs now
# since we fixed the content-based lookup in store().
mems = c._query("memory", workspace_id=ws_id, filter_dict={}, columns=["id", "content"])
content_to_id = {}
for m in mems:
    content_to_id[m.get("content", "")] = m.get("id", "")

resolved = []
for text, _ in mod.MEMORIES:
    resolved.append(content_to_id.get(text, ""))

n_resolved = len([x for x in resolved if x])
print(f"Resolved by content: {n_resolved}/{len(mod.MEMORIES)}")

# ── Build queries ───────────────────────────────────────────────────
queries_out = []
for q in mod.QUERIES:
    rels = [resolved[i] for i in q["relevant_indices"] if i < len(resolved) and resolved[i]]
    queries_out.append({"query": q["query"], "description": q["description"], "relevant_ids": rels})

n_with_ids = len([q for q in queries_out if q["relevant_ids"]])
print(f"Queries: {len(queries_out)} ({n_with_ids} with resolved IDs)")

# ── Sanity check ────────────────────────────────────────────────────
sanity = c.search(ws_id, query="CEO", limit=5, semantic=True)
print(f"Sanity: search 'CEO' → {len(sanity)} results")
for r in sanity[:3]:
    print(f"  score={r.get('score',0):.4f} eid={r.get('entity_id','')[:20]}... content={r.get('content','')[:60]}")

# ── Save artifacts ──────────────────────────────────────────────────
qfile = "data/eval_queries_large.jsonl"
with open(qfile, "w") as f:
    for q in queries_out:
        f.write(json.dumps(q) + "\n")
with open(qfile.replace(".jsonl", "_workspace_id.txt"), "w") as f:
    f.write(ws_id)

# ── Run eval ────────────────────────────────────────────────────────
print("\n" + "="*60)
print("RUNNING EVAL HARNESS")
print("="*60)

from scripts.eval_harness import run_eval
results = run_eval(c, ws_id, queries_out, k=5)

summary = results["summary"]
print(f"\n{'='*60}")
print(f"FINAL:  P@5={summary['P@5']:.1%}  R@5={summary['R@5']:.1%}  MRR={summary['MRR']:.3f}")
print(f"Queries evaluated: {summary['queries_evaluated']}")
print(f"Workspace: {ws_id}")
print(f"{'='*60}")
