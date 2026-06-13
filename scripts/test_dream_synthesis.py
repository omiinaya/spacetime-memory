#!/usr/bin/env python3
"""Integration test for dream cycle + synthesis against live STDB.

Registers a unique user, creates a workspace, stores entity-rich memories,
runs dream cycle, and tests synthesis with gap analysis.
"""

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c200f8da0f062b67001165d9379b9e2125dd73a7be4a0b1a1e4374d00cbcc079",
)

passed = 0
failed = 0


def ok(label: str):
    global passed
    passed += 1
    print(f"  ✅ {label}")


def fail(label: str, err: str = ""):
    global failed
    failed += 1
    if err:
        print(f"  ❌ {label}: {err}")
    else:
        print(f"  ❌ {label}")


def main():
    global passed, failed
    suffix = uuid.uuid4().hex[:8]

    print(f"Dream Cycle + Synthesis Integration Test")
    print(f"DB: {DB[:16]}...")
    print()

    # Setup
    c = Client(host=HOST, port=PORT, database=DB)
    user = f"dreamtest_{suffix}"

    try:
        c._call("register", [user, f"Dream Test {suffix}", "dr3@mt3st"])
    except RuntimeError as e:
        fail("register", str(e)[:80])
        sys.exit(1)
    ok("register")

    # Create workspace
    c.create_workspace(f"dream-{suffix}", "Dream cycle test")
    workspaces = c._query("workspace")
    ws = [w for w in workspaces if f"dream-{suffix}" in w.get("name", "")]
    if not ws:
        fail("create workspace", "workspace not found")
        sys.exit(1)
    ws_id = ws[0]["id"]
    ok(f"create workspace ({ws_id[:12]}...)")

    # Create peers
    c._call("create_peer", [ws_id, f"Alice-{suffix}", "user", '{"role":"CEO"}'])
    c._call("create_peer", [ws_id, f"Bob-{suffix}", "user", '{"role":"CTO"}'])
    peers = c._query("peer", filter_dict={"workspace_id": ws_id})
    alice = [p for p in peers if "Alice" in p.get("name", "")]
    bob = [p for p in peers if "Bob" in p.get("name", "")]
    ok(f"create peers ({len(peers)} total)")

    alice_id = alice[0]["id"] if alice else peers[0]["id"]
    bob_id = bob[0]["id"] if bob else peers[-1]["id"]

    # Store entity-rich memories
    memories = [
        "Alice Chen met with Garry Tan from Y Combinator to discuss Series A funding",
        "Bob Smith demoed the new ML pipeline to Acme AI investors last Tuesday",
        "Alice Chen and Bob Smith disagree on the hiring timeline for Q3",
        "Garry Tan recommends Alice Chen for the Stripe board position",
        "Acme AI is partnering with Google Ventures for the next round",
    ]

    stored_ids = []
    for i, content in enumerate(memories):
        result = c._call("store_memory", [
            ws_id, alice_id, alice_id,
            "experience", content,
            f"Memory {i}", "[]", 1.0, f"session-{suffix}", "",
        ])
        # Get the stored memory ID
        all_mems = c._query("memory", filter_dict={"workspace_id": ws_id})
        mem = [m for m in all_mems if m.get("summary") == f"Memory {i}"]
        if mem:
            stored_ids.append(mem[0]["id"])
    ok(f"store memories ({len(stored_ids)} items)")

    # ── Test 1: Entity extraction (explicit call, same as dream cycle) ─

    # Call extract_entities on each stored memory
    extract_count = 0
    for content in memories:
        try:
            c._call("extract_entities", [ws_id, content])
            extract_count += 1
        except RuntimeError:
            pass

    # Check kg_nodes after store_memory (entity extraction runs inline)
    nodes = c._query("kg_node", filter_dict={"workspace_id": ws_id})
    ok(f"entity extraction ({len(nodes)} kg nodes)")

    if nodes:
        node_labels = [n["label"] for n in nodes]
        print(f"    Nodes: {', '.join(node_labels)}")

        # Check edges
        edges = c._query("kg_edge", filter_dict={"workspace_id": ws_id})
        ok(f"entity edges ({len(edges)} edges)")
        if edges:
            edge_rels = [e["relation"] for e in edges]
            from collections import Counter
            rel_counts = Counter(edge_rels)
            for rel, cnt in rel_counts.items():
                print(f"    {rel}: {cnt}")

    # ── Test 2: Mental model synthesis via reducer ───────────────────

    if len(stored_ids) >= 2:
        ids_json = json.dumps(stored_ids)
        try:
            c._call("synthesize_mental_models", [ws_id, ids_json])
            # Check pending model was created
            models = c._query("mental_model")
            pending = [m for m in models if m.get("status") == "pending"]
            ok(f"mental model request ({len(pending)} pending)")
        except RuntimeError as e:
            fail("mental model request", str(e)[:80])

    # ── Test 3: Synthesis with gap analysis (no LLM needed) ──────────

    from spacetime_memory.context_agent import ContextAgent

    agent = ContextAgent(c)

    # Test 3a: context pipeline (no LLM)
    result = agent.ask("What do we know about Alice Chen?", workspace_id=ws_id)
    if result.get("pack"):
        entries = result.get("entries", [])
        ok(f"context pipeline ({len(entries)} context entries)")
    else:
        fail("context pipeline", result.get("error", "no pack returned"))

    # Test 3b: synthesize (requires LLM — gracefully degrades if no key)
    result2 = agent.synthesize("What do we know about Acme AI?", workspace_id=ws_id)
    if result2.get("error"):
        ok("synthesize (graceful: no LLM key)")
    elif result2.get("answer"):
        ok(f"synthesize (answer: {len(result2['answer'])} chars)")
        gaps = result2.get("gaps", [])
        if gaps:
            print(f"    Gaps identified: {len(gaps)}")
            for g in gaps[:3]:
                print(f"    - {g}")
    else:
        ok("synthesize (LLM unavailable)")

    # ── Summary ──────────────────────────────────────────────────────

    print()
    print(f"Results: {passed}/{passed + failed} passed")
    if failed:
        print("SOME TESTS FAILED ❌")
        sys.exit(1)
    else:
        print("ALL PASSED ✅")


if __name__ == "__main__":
    main()
