#!/usr/bin/env python3
"""Quick timing test for memory store."""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from spacetime_memory import Client

# Download dataset
print("Downloading...", flush=True)
resp = urllib.request.urlopen(
    "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
    timeout=30,
)
data = json.loads(resp.read().decode())[0]
print(f"Downloaded", flush=True)

c = Client()

conv = data.get("conversation", {})
speaker_a = conv.get("speaker_a", "A")
speaker_b = conv.get("speaker_b", "B")

# Extract all turns
session_keys = sorted(
    [k for k in conv.keys() if k.startswith("session_") and not k.endswith("_date_time")],
    key=lambda x: int(x.split("_")[1]),
)
turns = []
for sk in session_keys:
    for t in conv.get(sk, []):
        turns.append(t.get("text", ""))

print(f"{len(turns)} total turns", flush=True)

# Create workspace
ws = "timing_test_" + str(int(time.time() % 100000))
c.create_workspace("timing-test", id=ws)

# Time 10 stores
start = time.time()
for i in range(min(10, len(turns))):
    entities = json.dumps([
        {"name": speaker_a, "entity_type": "person"},
        {"name": speaker_b, "entity_type": "person"},
    ])
    c.store(workspace_id=ws, content=turns[i], memory_type="test",
            confidence=1.0, tier="L0", entities_json=entities)
    elapsed = time.time() - start
    print(f"  turn {i}: {elapsed:.2f}s total", flush=True)

print(f"10 turns: {time.time()-start:.2f}s total, {(time.time()-start)/10:.2f}s avg", flush=True)
