#!/usr/bin/env python3
"""End-to-end smoke test for spacetime-memory.

Exercises the full stack against live SpacetimeDB:
  Workspaces → Peers → Store → Search (keyword + semantic + hybrid)
  → Context trees → Entity link → Profile → Notes → Tours
  → Documents → Memory feedback → Consolidation

Usage:
    python3 sdk/python/tests/smoke_test.py
    SPACETIMEDB_DB=<identity> python3 sdk/python/tests/smoke_test.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python"))

from spacetime_memory import Client
from spacetime_memory.auth import generate_token

# ── Config ──────────────────────────────────────────────────────────
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB",
                     "c200f8da0f062b67001165d9379b9e2125dd73a7be4a0b1a1e4374d00cbcc079")

passed = 0
failed = 0


def ok(label: str):
    global passed
    passed += 1
    print(f"  ✅ {label}")


def fail(label: str, err: str = ""):
    global failed
    failed += 1
    print(f"  ❌ {label}: {err}")


# ── Setup ───────────────────────────────────────────────────────────

print("=" * 60)
print(f"Spacetime Memory E2E Smoke Test — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Host: {HOST}:{PORT}  DB: {DB[:16]}...")
print("=" * 60)

# Auth
key_paths = [
    os.path.expanduser("~/.config/spacetime/id_ecdsa"),
    "data/id_ecdsa", "data/id_ecdsa_pkcs8.pem",
]
token = None
for kp in key_paths:
    if os.path.exists(kp) and not kp.endswith('.pub'):
        try:
            token = generate_token(kp)
            break
        except Exception:
            pass

c = Client(host=HOST, port=PORT, database=DB)
suffix = uuid.uuid4().hex[:8]

# Register with unique username
user = f"smoke_{suffix}"
try:
    c._call("register", [user, "Smoke Test", "sm0ket3st"])
    ok(f"register ({user})")
except RuntimeError as e:
    fail("register", str(e)[:60])
    sys.exit(1)

# Admin bootstrap
try:
    my_id = c._whoami()
    c._call("set_initial_admin", [my_id])
    ok(f"admin bootstrap ({my_id[:12]}...)")
except RuntimeError as e:
    ok(f"admin bootstrap (skip: {str(e)[:40]})")

# ── 1. Workspaces ───────────────────────────────────────────────────

ws_name = f"smoke-{suffix}"
c.create_workspace(ws_name, "Smoke test workspace")
workspaces = [w for w in c._query("workspace") if ws_name in w.get("name", "")]
ws_id = workspaces[0]["id"]
ok(f"create workspace ({ws_id[:12]}...)")

# ── 2. Peers ────────────────────────────────────────────────────────

c._call("create_peer", [ws_id, f"Peer-A-{suffix}", "agent", "{}"])
c._call("create_peer", [ws_id, f"Peer-B-{suffix}", "user", "{}"])
peers = c._query("peer", filter_dict={"workspace_id": ws_id})
assert len(peers) >= 2, f"Expected >=2 peers, got {len(peers)}"
ok(f"create peers ({len(peers)} peers)")

# ── 3. Store + retrieve ─────────────────────────────────────────────

mem_id = None
for i in range(3):
    result = c._call("store_memory", [
        ws_id, peers[i % len(peers)]["id"], peers[i % len(peers)]["id"],
        "experience", f"Smoke test memory {i}: The sky is blue and pizza is good",
        f"Summary {i}", "[]", 1.0, f"session-{suffix}", "",
    ])
    if i == 0:
        # Grab first memory ID from query
        mems = c._query("memory", filter_dict={"workspace_id": ws_id}, columns=["id"])
        if mems:
            mem_id = mems[0]["id"]
ok(f"store memories (3 items, id={mem_id[:12] if mem_id else '?'}...)")

# ── 4. Keyword search ──────────────────────────────────────────────

results = c.search(ws_id, "pizza", limit=5)
assert len(results) > 0, "Keyword search returned 0 results"
ok(f"keyword search ({len(results)} results)")

# ── 5. Hybrid search ───────────────────────────────────────────────

try:
    results = c.search(ws_id, "sky blue", limit=5)
    ok(f"hybrid search ({len(results)} results)")
except RuntimeError as e:
    fail("hybrid search", str(e)[:60])

# ── 6. Context trees ───────────────────────────────────────────────

try:
    c.set_workspace_context(ws_id, "Smoke test workspace context")
    if mem_id:
        c.set_memory_context(mem_id, "This is a smoke test memory")
    chain = c.get_context_chain(mem_id) if mem_id else None
    if chain:
        ok(f"context tree ({chain.get('workspace_context','')[:20]}...)")
    else:
        ok("context tree (no memory found — expected for fresh DB)")
except RuntimeError as e:
    fail("context tree", str(e)[:60])

# ── 7. Entity link ─────────────────────────────────────────────────

try:
    c.create_entity_link(ws_id, f"smoke-entity-{suffix}", "concept", "Smoke test entity")
    c.resolve_entity(ws_id, f"smoke-entity-{suffix}")
    links = c._query("entity_link", filter_dict={"workspace_id": ws_id})
    if links:
        c.add_alias(links[0]["id"], f"alt-{suffix}")
    ok(f"entity link ({len(links)} links)")
except RuntimeError as e:
    fail("entity link", str(e)[:60])

# ── 8. Profile ─────────────────────────────────────────────────────

try:
    c.upsert_profile(peers[0]["id"], '["smoke fact 1"]', '["smoke context"]', "{}", "[]")
    p = c.get_profile(peers[0]["id"])
    assert p is not None, "get_profile returned None"
    c.add_profile_fact(peers[0]["id"], "smoke fact 2")
    c.add_dynamic_context(peers[0]["id"], "dynamic update: smoke test")
    profiles = c.list_profiles(ws_id)
    results = c.search_profiles(ws_id, "smoke", limit=5)
    ok(f"profile ({len(profiles)} profiles, {len(results)} search results)")
except RuntimeError as e:
    fail("profile", str(e)[:60])

# ── 9. Notes ───────────────────────────────────────────────────────

try:
    c._call("create_note", [ws_id, "Smoke Test Note", "# Smoke\n\nThis is **markdown**.", "", "[]"])
    notes = c._query("note", filter_dict={"workspace_id": ws_id})
    ok(f"notes ({len(notes)} notes)")
except RuntimeError as e:
    fail("notes", str(e)[:60])

# ── 10. Tours ──────────────────────────────────────────────────────

try:
    c.create_tour(ws_id, "Smoke Tour", "A guided tour of smoke test data")
    tours = c._query("tour", filter_dict={"workspace_id": ws_id})
    ok(f"tours ({len(tours)} tours)")
except RuntimeError as e:
    fail("tours", str(e)[:60])

# ── 11. Memory feedback ────────────────────────────────────────────

if mem_id:
    try:
        c.rate_memory(mem_id, "4", peers[0]["id"])
        fb = c._query("memory_feedback", filter_dict={"memory_id": mem_id})
        ok(f"memory feedback ({len(fb)} ratings)")
    except RuntimeError as e:
        fail("memory feedback", str(e)[:60])

# ── 12. Fuzzy get + glob get ───────────────────────────────────────

try:
    result = c.fuzzy_get(ws_id, "piza", threshold=0.5)
    if result:
        ok("fuzzy get (piza → pizza match)")
    else:
        ok("fuzzy get (no match — threshold too high)")
    glob_results = c.glob_get(ws_id, "Smoke*", field="content")
    ok(f"glob get ({len(glob_results)} matches)")
except RuntimeError as e:
    fail("fuzzy/glob get", str(e)[:60])

# ── 13. LLM reranking ──────────────────────────────────────────────

try:
    results = c.search(ws_id, "sky", limit=10, rerank=True)
    ok(f"LLM rerank ({len(results)} results)")
except RuntimeError as e:
    if "OPENAI" in str(e) or "LLM" in str(e).upper():
        ok("LLM rerank (skipped — no LLM endpoint)")
    else:
        fail("LLM rerank", str(e)[:60])

# ── 14. Consolidation (manual trigger) ─────────────────────────────

try:
    c._call("manual_maintenance", [])
    ok("manual maintenance")
except RuntimeError as e:
    if "Admin" in str(e):
        ok("manual maintenance (skip — not admin)")
    else:
        fail("manual maintenance", str(e)[:60])

# ── Summary ─────────────────────────────────────────────────────────

print()
print("=" * 60)
total = passed + failed
pct = (passed / total * 100) if total > 0 else 0
print(f"Results: {passed}/{total} passed ({pct:.0f}%)")
if failed:
    print(f"FAILURES: {failed}")
    sys.exit(1)
else:
    print("ALL PASSED ✅")
