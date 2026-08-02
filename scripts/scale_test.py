#!/usr/bin/env python3
"""Scale test — measure latency at increasing corpus sizes."""
import os, sys, time, json, uuid, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
import httpx
from spacetime_memory import Client

DB = os.environ.get("SPACETIMEDB_DB", "")
if not DB:
    db_file = os.path.join(os.path.dirname(__file__), "..", "data", "database_identity")
    if os.path.exists(db_file):
        DB = open(db_file).read().strip()
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:4000")
TANTIVY = "http://localhost:9091"

# SAMPLE_CONTENT — 1000 pre-baked sentences
SAMPLE_CONTENT = [
    f"Memory item {i}: This is a test document about {topic} with various keywords and concepts."
    for i, topic in enumerate([
        "machine learning", "distributed systems", "databases", "web development",
        "security", "networking", "storage", "monitoring", "deployment", "testing",
    ] * 100)
][:1000]

QUERY_SAMPLES = [
    ("machine learning performance", ["machine"]),
    ("distributed database scaling", ["distributed"]),
    ("security best practices", ["security"]),
    ("web deployment pipeline", ["deployment"]),
    ("network monitoring tools", ["monitoring"]),
    ("storage optimization techniques", ["storage"]),
    ("testing methodology approaches", ["testing"]),
]


def main():
    resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
    token = resp.headers.get("spacetime-identity-token", "")
    identity = resp.headers.get("spacetime-identity", "")

    c = Client(database=DB, embedder_url=EMB, token=token)
    http = httpx.Client(timeout=30)

    peer = f"scale-{uuid.uuid4().hex[:8]}"
    try:
        c._call("register", [peer, "scale123", identity])
    except (OSError, json.JSONDecodeError):
        pass

    results = []
    sizes = [10, 50, 100, 250, 500, 1000]

    for size in sizes:
        print(f"\n{'='*50}")
        print(f"SIZE: {size} docs")
        print(f"{'='*50}")

        ws = c.create_workspace(f"scale-{uuid.uuid4().hex[:6]}", f"Scale test {size}")
        WS = ws["id"]
        c._call("set_workspace_visibility", [WS, True])

        # Seed
        t0 = time.time()
        for i in range(size):
            c.store(workspace_id=WS, content=SAMPLE_CONTENT[i],
                    memory_type="world_fact", peer_id=peer, confidence=0.9)
            # Index into Tantivy
            mem_id = f"mem-{i}"
            try:
                http.post(f"{TANTIVY}/index", json={
                    "workspace_id": WS, "entity_id": mem_id,
                    "content": SAMPLE_CONTENT[i], "entity_type": "memory"
                })
            except (OSError, json.JSONDecodeError):
                pass
        seed_time = time.time() - t0
        print(f"  Seeded {size} docs in {seed_time:.1f}s ({seed_time/size*1000:.0f}ms/doc)", flush=True)

        # Search latency
        search_times = []
        for qt, _ in QUERY_SAMPLES:
            t0 = time.time()
            res = c.search(WS, query=qt, limit=5, semantic=True)
            elapsed = time.time() - t0
            search_times.append(elapsed)

        avg_ms = sum(search_times) / len(search_times) * 1000
        p50_ms = sorted(search_times)[len(search_times)//2] * 1000
        p99_ms = sorted(search_times)[-1] * 1000

        results.append({
            "size": size,
            "seed_time_s": round(seed_time, 1),
            "seed_ms_per_doc": round(seed_time / size * 1000, 0),
            "search_ms_avg": round(avg_ms, 0),
            "search_ms_p50": round(p50_ms, 0),
            "search_ms_p99": round(p99_ms, 0),
        })
        print(f"  Search: avg={avg_ms:.0f}ms p50={p50_ms:.0f}ms p99={p99_ms:.0f}ms", flush=True)

    # Summary
    print(f"\n{'='*65}")
    print("SCALE TEST RESULTS")
    print(f"{'='*65}")
    print(f"{'Size':>6} {'Seed':>8} {'ms/doc':>8} {'Search avg':>11} {'p50':>8} {'p99':>8}")
    print(f"{'─'*6} {'─'*8} {'─'*8} {'─'*11} {'─'*8} {'─'*8}")
    for r in results:
        print(f"{r['size']:>6} {r['seed_time_s']:>7.1f}s {r['seed_ms_per_doc']:>7.0f}ms "
              f"{r['search_ms_avg']:>10.0f}ms {r['search_ms_p50']:>7.0f}ms {r['search_ms_p99']:>7.0f}ms")

    with open("/tmp/scale_test.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to /tmp/scale_test.json")


if __name__ == "__main__":
    main()
