#!/usr/bin/env python3
"""Quick retrieval quality test — stores 10 memories, runs recall@5, measures accuracy."""

import os, sys, json, time, httpx, urllib.request

STDB_URL = "http://localhost:3001"
EMBEDDER_URL = "http://localhost:9090"
TANTIVY_URL = "http://localhost:9091"
os.environ.setdefault("SPACETIMEDB_HOST", "localhost")
os.environ.setdefault("SPACETIMEDB_PORT", "3001")
os.environ.setdefault("TANTIVY_URL", TANTIVY_URL)
os.environ.setdefault("EMBEDDER_URL", EMBEDDER_URL)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from spacetime_memory import Client

DB = os.environ.get("SPACETIMEDB_DB", "c20076381c624767a61e93ef07b3a8f2a2f012f11d5312a479dbcecc72066e5c")
resp = httpx.get(f"{STDB_URL}/v1/database/{DB}", timeout=10)
token = resp.headers.get("spacetime-identity-token", "")
identity = resp.headers.get("spacetime-identity", "")

client = Client(database=DB, embedder_url=EMBEDDER_URL, token=token or None)
try:
    suffix = os.urandom(4).hex()
    client._call("register", [f"quicktest-{suffix}", "quicktest789", identity])
except Exception:
    pass

# Create workspace
ws = client.create_workspace(f"quick-retrieval-{os.urandom(4).hex()}", "Quick retrieval test")
ws_id = ws.get("id") or ws.get("workspace_id", "")
print(f"Workspace: {ws_id}")

# Store 10 test memories with unique content
test_memories = [
    ("The capital of France is Paris and it is known for the Eiffel Tower.", "geography"),
    ("Python is a high-level programming language created by Guido van Rossum.", "programming"),
    ("The human heart has four chambers: left atrium, right atrium, left ventricle, right ventricle.", "biology"),
    ("William Shakespeare wrote Hamlet, Romeo and Juliet, and Macbeth.", "literature"),
    ("The speed of light in vacuum is approximately 299,792,458 meters per second.", "physics"),
    ("The Amazon rainforest produces about 20% of the world's oxygen.", "environment"),
    ("Beethoven's Fifth Symphony is one of the most recognizable classical pieces.", "music"),
    ("The Great Wall of China is over 13,000 miles long.", "history"),
    ("DNA contains the genetic instructions for the development and functioning of living organisms.", "biology"),
    ("The Internet was developed from ARPANET in the late 1960s.", "technology"),
]

print(f"\nStoring {len(test_memories)} memories...")
t0 = time.time()
for i, (content, cat) in enumerate(test_memories):
    try:
        client.store(workspace_id=ws_id, content=content, memory_type="fact", confidence=1.0, tier="L0",
                     entities_json=json.dumps([{"name": cat, "entity_type": "topic"}]))
        print(f"  [{i+1}/{len(test_memories)}] Stored ({len(content)} chars)", flush=True)
    except Exception as e:
        print(f"  [{i+1}/{len(test_memories)}] ERROR: {e}", flush=True)
store_time = time.time() - t0
print(f"Stored {len(test_memories)} memories in {store_time:.1f}s")

# Wait for indexing
print("\nWaiting 2s for indexing...")
time.sleep(2)

# Test queries
queries = [
    ("What is the capital of France?", "Paris"),
    ("Who created Python?", "Guido van Rossum"),
    ("How many chambers does the human heart have?", "four"),
    ("Who wrote Hamlet?", "Shakespeare"),
    ("What is the speed of light?", "299,792,458"),
]

print(f"\n=== RETRIEVAL QUALITY TEST ({len(queries)} queries) ===\n")

correct = 0
total = 0

for q_text, q_expected in queries:
    total += 1
    t0 = time.time()
    results = client.search(workspace_id=ws_id, query=q_text, limit=5, semantic=True)
    latency = (time.time() - t0) * 1000
    
    top_results = []
    for r in results[:5]:
        content = r.get("memory_content") or r.get("content", "")
        score = r.get("score", 0)
        top_results.append((content, score))
    
    # Check if expected answer appears in top 5
    found = any(q_expected.lower() in c.lower() for c, s in top_results)
    if found:
        correct += 1
    
    print(f"  Q{total}: \"{q_text}\"")
    print(f"    Expected: \"{q_expected}\" | Found in top-5: {'YES ✓' if found else 'NO ✗'}")
    print(f"    Latency: {latency:.0f}ms")
    for j, (c, s) in enumerate(top_results[:3]):
        print(f"    [{j+1}] score={s:.3f} \"{c[:80]}...\"")
    print()

# Summary
accuracy = correct / total * 100
print(f"{'='*50}")
print(f"  RESULTS: {correct}/{total} correct ({accuracy:.1f}%)")
print(f"  Store time: {store_time:.1f}s for {len(test_memories)} memories")
print(f"{'='*50}")
