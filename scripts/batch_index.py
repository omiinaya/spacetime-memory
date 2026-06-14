#!/usr/bin/env python3
"""Batch index all memories in a workspace."""
import json, os, sys, time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))
from spacetime_memory.client import Client

HOST, PORT = "localhost", "3001"
DB = "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff"

c = Client(host=HOST, port=PORT, database=DB)
token = open(os.path.join(os.path.dirname(__file__), ".cron_identity_token")).read().strip()
c._identity_token = token
c._identity_established = True

ws_id = open("/tmp/eval_workspace.txt").read().strip()
print(f"Indexing workspace: {ws_id}")

mems = c._query("memory", workspace_id=ws_id, filter_dict={}, columns=["id", "content"])
print(f"Found {len(mems)} memories")

indexed = 0
for i, mem in enumerate(mems):
    mem_id = mem.get("id", "")
    content = mem.get("content", "")
    if not mem_id or not content:
        continue

    ok = False
    for attempt in range(5):
        try:
            emb = c._embed(content)
            if emb:
                c._call("index_entity", [ws_id, "memory", mem_id, content, json.dumps(emb)])
                c._call("index_terms", [ws_id, "memory", mem_id, content])
                indexed += 1
                ok = True
            break
        except Exception as e:
            if attempt < 4:
                time.sleep(2 ** attempt)
            else:
                print(f"  FAIL {mem_id[:8]}: {e}")

    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(mems)}...")

print(f"Indexed {indexed}/{len(mems)}")
