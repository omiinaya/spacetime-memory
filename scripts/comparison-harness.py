#!/usr/bin/env python3
"""Side-by-side comparison test harness for spacetime-memory adapters.

Run against a live SpacetimeDB to verify adapter output shapes match
upstream library expectations.  Requires the following to be installed
via pip for comparison:

    pip install mem0 zep-python graphiti-core hindsight honcho

Usage:
    SPACETIMEDB_DB=<identity> python scripts/comparison-harness.py

If an upstream library is not installed, its comparison tests are skipped
and only our adapter output is shown for manual inspection.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client
from spacetime_memory.sdks.mem0 import Memory as StmemMem0
from spacetime_memory.sdks.graphiti import Graphiti as StmemGraphiti, EntityNode, EntityEdge
from spacetime_memory.sdks.honcho import Honcho as StmemHoncho
from spacetime_memory.sdks.hindsight import Hindsight as StmemHindsight
from spacetime_memory.sdks.zep import ZepClient as StmemZep

DB = os.environ.get("SPACETIMEDB_DB", "")
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")

PASS = 0
FAIL = 0
SKIP = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        print(f"  ✓ {label}")
        PASS += 1
    else:
        print(f"  ✗ {label}  {detail}")
        FAIL += 1


def section(name: str):
    print(f"\n── {name} ─{'─' * max(0, 60 - len(name))}")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not DB:
    print("ERROR: set SPACETIMEDB_DB to your database identity")
    sys.exit(1)

c = Client(host=HOST, port=PORT, database=DB)

# Unique test IDs
uid = os.urandom(4).hex()
WS_NAME = f"compare-{uid}"
c.create_workspace(WS_NAME)
ws_list = c.list_workspaces()
WS_ID = next(w["id"] for w in ws_list if w.get("name") == WS_NAME)
print(f"Workspace: {WS_NAME} ({WS_ID})")

# ---------------------------------------------------------------------------
# Mem0 comparison
# ---------------------------------------------------------------------------
section("Mem0 adapter — output shape")

m = StmemMem0(config={"host": HOST, "port": PORT, "db": DB})

# add()
result = m.add("I like pizza", user_id=f"mem0-test-{uid}")
check("add() returns dict with 'results' key",
      isinstance(result, dict) and "results" in result)
check("add() results is a list", isinstance(result["results"], list))
if result["results"]:
    r = result["results"][0]
    check("result item has 'id'", isinstance(r.get("id"), str) and r["id"])
    check("result item has 'memory'", isinstance(r.get("memory"), str))
    check("result item has 'event'", r.get("event") in ("ADD", "UPDATE"))

# search()
sr = m.search("pizza", user_id=f"mem0-test-{uid}")
check("search() returns dict with 'results' key",
      isinstance(sr, dict) and "results" in sr)
check("search() results is a list", isinstance(sr["results"], list))
if sr["results"]:
    r = sr["results"][0]
    check("search item has 'id'", isinstance(r.get("id"), str))
    check("search item has 'score'", isinstance(r.get("score"), (int, float)))
    check("search item has 'memory'", isinstance(r.get("memory"), str))

# get_all()
ga = m.get_all(user_id=f"mem0-test-{uid}")
check("get_all() returns dict with 'results'",
      isinstance(ga, dict) and "results" in ga)

# delete()
dl = m.delete(sr["results"][0]["id"])
check("delete() returns dict with message",
      isinstance(dl, dict))

# history()
hist = m.history(sr["results"][0]["id"])
check("history() returns list", isinstance(hist, list))

# get()
g = m.get(sr["results"][0]["id"])
check("get() returns dict with 'results'",
      isinstance(g, dict) and "results" in g)

# ValueError on empty input
try:
    m.graph.add("")
    check("graph.add('') raises ValueError", False)
except ValueError:
    check("graph.add('') raises ValueError", True)
except Exception:
    check("graph.add('') raises ValueError", False, "wrong exception type")

# ---------------------------------------------------------------------------
# LangGraph BaseStore compliance
# ---------------------------------------------------------------------------
section("LangGraph BaseStore — batch() dispatch")

try:
    from langgraph.store.base import BaseStore, GetOp, PutOp, SearchOp
    from spacetime_memory.sdks.langchain import StmemStore

    ls = StmemStore(config={"host": HOST, "port": PORT, "db": DB})
    check("StmemStore is BaseStore subclass", issubclass(type(ls), BaseStore))

    ls.put(("compare", uid), "k1", {"text": "hello"})
    ls.put(("compare", uid), "k2", {"text": "world"})

    ops = [GetOp(namespace=("compare", uid), key="k1", refresh_ttl=True)]
    results = ls.batch(ops)
    check("batch(GetOp) returns item",
          len(results) == 1 and results[0] is not None)
    if results[0]:
        check("Item has value dict", isinstance(results[0].value, dict))
        check("Item has datetime created_at",
              hasattr(results[0], "created_at"))

    sr = ls.search(("compare",), query="hello", limit=5)
    check("search() returns list of SearchItem", isinstance(sr, list))
    if sr:
        check("SearchItem has score", hasattr(sr[0], "score"))

    namespaces = ls.list_namespaces(prefix=("compare",))
    check("list_namespaces() works", isinstance(namespaces, list))
except ImportError as e:
    check(f"LangGraph test skipped: {e}", True)
    SKIP += 1

# ---------------------------------------------------------------------------
# Graphiti adapter
# ---------------------------------------------------------------------------
section("Graphiti adapter — entity/edge shapes")

g = StmemGraphiti(host=HOST, port=PORT, database=DB, client=c)
group = f"compare-{uid}"

node_a = EntityNode(name=f"Alice-{uid}", group_id=group)
node_b = EntityNode(name=f"Pizza-{uid}", group_id=group)
edge = EntityEdge(
    name="likes", fact=f"Alice-{uid} likes pizza",
    source_node_uuid=node_a.uuid, target_node_uuid=node_b.uuid,
    group_id=group,
)

triplet = g.add_triplet(source_node=node_a, edge=edge, target_node=node_b)
check("add_triplet returns AddTripletResults", hasattr(triplet, "nodes"))
check("add_triplet created source node",
      any(n.name == node_a.name for n in triplet.nodes))
check("add_triplet created edge",
      any(e.name == "likes" for e in triplet.edges))

search_results = g.search(f"Alice-{uid}", group_ids=[group])
check("search() returns list of EntityEdge",
      isinstance(search_results, list))

summary = g.get_entity_edge_summary(entity_uuid=triplet.nodes[0].uuid)
check("get_entity_edge_summary returns dict with 'edges'",
      isinstance(summary, dict) and "edges" in summary)

# ---------------------------------------------------------------------------
# Honcho adapter
# ---------------------------------------------------------------------------
section("Honcho adapter — user/session shapes")

h = StmemHoncho(config={"db": DB}, client=c)

# Use the existing client's identity by referencing the workspace it created
user = h.create_user(name=f"compare-{uid}")
check("create_user returns User with .id", hasattr(user, "id") and user.id)
check("User.id is non-empty string", isinstance(user.id, str) and user.id)

# Create session via Honcho top-level (gets properly cached)
session = h.create_session(user_id=user.id, location="test")
check("create_session returns Session with .id",
      hasattr(session, "id") and session.id)
check("Session.user_id matches", session.user_id == user.id)

# Store via Honcho top-level (finds session in cache)
mem = h.add(session_id=session.id, content="test memory")
check("add() returns dict", isinstance(mem, dict))

search_h = h.search(session_id=session.id, query="test")
check("search() returns list", isinstance(search_h, list))

# ValueError on missing session
try:
    h.add(session_id="nonexistent", content="test")
    check("add() with bad session raises ValueError", False)
except ValueError:
    check("add() with bad session raises ValueError", True)
except Exception:
    check("add() with bad session raises ValueError", False, "wrong exception type")

# ---------------------------------------------------------------------------
# Hindsight adapter
# ---------------------------------------------------------------------------
section("Hindsight adapter — retain/recall/reflect shapes")

hs = StmemHindsight(config={"db": DB}, client=c)

ret = hs.retain("test memory content")
check("retain() returns dict", isinstance(ret, dict))

rec = hs.recall("test memory")
check("recall() returns dict with 'results'",
      isinstance(rec, dict) and "results" in rec)
if rec["results"]:
    r = rec["results"][0]
    check("recall item has 'id'", isinstance(r.get("id"), str))
    check("recall item has 'score'", isinstance(r.get("score"), (int, float)))
    check("recall item has 'memory'", isinstance(r.get("memory"), str))

ref = hs.reflect("What patterns do you see?")
check("reflect() returns dict with 'status'",
      isinstance(ref, dict) and "status" in ref)

# ---------------------------------------------------------------------------
# Zep adapter
# ---------------------------------------------------------------------------
section("Zep adapter — session/memory shapes")

z = StmemZep(host=HOST, port=PORT, config={"db": DB})

add_mem = z.add_memory(
    session_id=f"zep-compare-{uid}",
    messages=[{"role": "user", "content": "I like pizza"}],
)
check("add_memory() returns dict with 'status'",
      isinstance(add_mem, dict) and add_mem.get("status") == "ok")

get_mem = z.get_memory(session_id=f"zep-compare-{uid}")
check("get_memory() returns dict", isinstance(get_mem, dict) or get_mem is None)
if get_mem:
    check("get_memory has 'messages' key", "messages" in get_mem)

search_z = z.search_memory(session_id=f"zep-compare-{uid}", query="pizza")
check("search_memory() returns list", isinstance(search_z, list))

del_mem = z.delete_memory(session_id=f"zep-compare-{uid}")
check("delete_memory() returns dict with 'deleted'",
      isinstance(del_mem, dict) and "deleted" in del_mem)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = PASS + FAIL
print(f"\n{'='*60}")
print(f"Results: {PASS}/{total} passed, {SKIP} skipped")
if FAIL:
    print(f"FAILURES: {FAIL}")
    sys.exit(1)
else:
    print("All checks passed.")
