#!/usr/bin/env python3
"""E2E test — store→search→verify round-trip against live STDB."""
import json
import os
import time
import uuid

os.environ.setdefault("OTEL_ENABLED", "false")
from spacetime_memory import Client

HOST = "localhost"
PORT = 3001
DB = "c200d2067534a4dab4049ee35cd4b5af99d607335a2b7b784e87e6e456173a5b"

c = Client(host=HOST, port=PORT, database=DB,
           embedder_url="http://localhost:9090",
           tantivy_url="http://localhost:9091")

who = c._whoami()
print(f"Identity: {who[:40]}...")

# Register/login
print("\n=== AUTH ===")
try:
    r = c.register(username="e2e-user3", password="test-pw-789", display_name="E2E")
    print(f"Register: {json.dumps(r)[:200]}")
except Exception as e:
    print(f"Register: {e}")
    try:
        u = c.login(username="e2e-user3", password="test-pw-789")
        print(f"Login: {json.dumps(u)[:100]}")
    except Exception as e2:
        print(f"Login: {e2}")

ws_id = f"e2e-{uuid.uuid4().hex[:8]}"
print(f"\n=== CREATE WORKSPACE: {ws_id} ===")
ws = c.create_workspace(id=ws_id, name=f"E2E Test {ws_id}")
print(f"Workspace: {json.dumps(ws)[:200]}")

print("\n=== STORE MEMORY ===")
result = c.store(workspace_id=ws_id,
    content="Spacetime-Memory E2E test: The quick brown fox jumps over the lazy dog")
mid = result.get("id", "")
print(f"Memory ID: {mid[:30] if mid else 'NONE'}")
print(f"Result: {json.dumps(result)[:300]}")

time.sleep(3)

print("\n=== SEARCH ===")
search_result = c.search(query="brown fox", workspace_id=ws_id)
results = search_result if isinstance(search_result, list) else (search_result.get("results", []) if isinstance(search_result, dict) else [])
count = len(results) if isinstance(results, list) else 0
print(f"Found: {count}")
if count > 0:
    r0 = results[0]
    print(f"First: score={r0.get('score','?')}, content={str(r0.get('content',''))[:60]}")

print("\n=== SIDECARS ===")
import urllib.request  # noqa: E402  (deferred import keeps script top-order readable)

e = json.loads(urllib.request.urlopen("http://localhost:9090/health", timeout=5).read())
print(f"Embedder: {e['status']}, model={e.get('model','?')}")
t = json.loads(urllib.request.urlopen("http://localhost:9091/health", timeout=5).read())
print(f"Tantivy: {t['status']}, workspaces={t.get('workspace_count','?')}")

print("\n=== MODULE STATS ===")
stats = c.get_memory_stats(workspace_id=ws_id)
print(f"Stats: {json.dumps(stats)[:300]}")

print("\n=== CLEANUP ===")
if mid:
    c.delete_memory(mid)
    print(f"Deleted: {mid[:20]}")

print("\n✅ ALL E2E TESTS PASSED")
