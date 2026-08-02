#!/usr/bin/env python3
"""Final comparison: dirty content vs clean content vs clean + entity boost.
This test directly measures the impact of each improvement."""
import json, os, sys, time, urllib.request, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client

RESULT_FILE = "/tmp/final_comparison.json"
LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

def log(msg):
    print(msg, flush=True)

def cosine_sim(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    na = sum(x*x for x in a)**0.5
    nb = sum(x*x for x in b)**0.5
    return dot/(na*nb) if na*nb > 0 else 0

def main():
    log("Downloading...")
    resp = urllib.request.urlopen(LOCOMO_URL, timeout=30)
    data = json.loads(resp.read().decode())
    conv = data[0]["conversation"]
    sa = conv.get("speaker_a", "A")
    sb = conv.get("speaker_b", "B")

    # Extract turns
    session_keys = sorted([k for k in conv.keys() if k.startswith("session_") and not k.endswith("_date_time")], key=lambda x: int(x.split("_")[1]))
    turns = []
    for sk in session_keys:
        snum = sk.split("_")[1]
        sdt = conv.get(f"session_{snum}_date_time", "")
        for t in conv.get(sk, []):
            sp = sa if "a" in (t.get("speaker","")).lower() else sb
            turns.append({"text": t.get("text",""), "speaker": sp, "session": f"Session {snum}", "dt": sdt})

    log(f"Turns: {len(turns)}")

    c = Client()
    ts = int(time.time())
    
    # Workspace 1: DIRTY content (v1 style)
    ws_dirty = f"final_dirty_{ts}"
    c.create_workspace("dirty", id=ws_dirty)

    # Workspace 2: CLEAN content (v2 style)
    ws_clean = f"final_clean_{ts}"
    c.create_workspace("clean", id=ws_clean)

    # Ingest first 100 turns
    test_turns = turns[:100]
    for t in test_turns:
        entities = json.dumps([{"name": sa, "entity_type": "person"}, {"name": sb, "entity_type": "person"}])
        
        # DIRTY: metadata prefix in content
        dirty_content = f"[{t['session']} | {t['dt']}] {t['speaker']}: {t['text']}"
        c.store(workspace_id=ws_dirty, content=dirty_content, memory_type="turn", confidence=1.0, tier="L0", entities_json=entities)
        
        # CLEAN: just the text
        c.store(workspace_id=ws_clean, content=t["text"], memory_type="turn", confidence=1.0, tier="L0", entities_json=entities)

    log(f"Ingested {len(test_turns)} turns into both workspaces")
    time.sleep(2)

    # Test queries
    queries = [
        "What does Melanie do to destress",
        "What is Caroline's identity",
        "What kind of art does Caroline make",
        "What pet does Melanie have",
        "What activities does Melanie do",
        "What books has Melanie read",
        "What events has Caroline participated in",
        "What does Caroline want to pursue as a career",
    ]

    results = {"dirty": {}, "clean": {}}
    
    for q in queries:
        for label, ws in [("dirty", ws_dirty), ("clean", ws_clean)]:
            try:
                r = c.search(workspace_id=ws, query=q, limit=10, semantic=True, cross_encoder=False)
                mems = [(r2.get("memory_content","") or "")[:120] for r2 in r[:5]]
                results[label][q] = {"count": len(r), "top": mems}
            except Exception as e:
                results[label][q] = {"error": str(e)}

    with open(RESULT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    
    log("DONE - results saved")

if __name__ == "__main__":
    main()
