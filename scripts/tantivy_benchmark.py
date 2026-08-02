#!/usr/bin/env python3
"""Direct Tantivy benchmark — seed eval data via HTTP API, measure latency + quality."""
import json, os, sys, time, statistics, math, urllib.request, urllib.error, uuid

TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
eval_mem_path = os.path.join(DATA_DIR, "eval_memories_50.json")
eval_qry_path = os.path.join(DATA_DIR, "eval_queries_25.json")

with open(eval_mem_path) as f: memories = json.load(f)
with open(eval_qry_path) as f: queries = json.load(f)
memories_by_id = {m["id"]: m for m in memories}

print(f"Dataset: {len(memories)} memories, {len(queries)} queries")
print(f"Tantivy: {TANTIVY_URL}")
print()

WS_ID = f"bench-tantivy-{uuid.uuid4().hex[:8]}"

def tantivy(path, data=None):
    url = f"{TANTIVY_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method="POST" if data else "GET",
        headers=({"Content-Type": "application/json"} if data else {}))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None
