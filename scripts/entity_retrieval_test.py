#!/usr/bin/env python3
"""Quick entity-linking retrieval test — write results to file."""
import json, os, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client
from spacetime_memory.entity_linking import extract_entities_llm

RESULT_FILE = "/tmp/entity_test_results.json"
LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

def log(msg):
    with open(RESULT_FILE, "a") as f:
        f.write(str(msg) + "\n")

def main():
    log("=== Entity Linking Retrieval Test ===")
    
    # Download
    resp = urllib.request.urlopen(LOCOMO_URL, timeout=30)
    dataset = json.loads(resp.read().decode())
    conversation = dataset[0]
    sample = conversation.get("sample_id", "conv-26")
    log(f"Dataset: {sample}")

    # Extract turns
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "A")
    speaker_b = conv.get("speaker_b", "B")
    session_keys = sorted([k for k in conv.keys() if k.startswith("session_") and not k.endswith("_date_time")], key=lambda x: int(x.split("_")[1]))
    turns = []
    for sk in session_keys:
        for t in conv.get(sk, []):
            speaker = speaker_a if "a" in (t.get("speaker", "").lower()) else speaker_b
            turns.append({"text": t.get("text", ""), "speaker": speaker})
    log(f"Turns: {len(turns)}")

    c = Client()
    ts = int(time.time() * 1_000_000)
    ws_plain = f"eqt_plain_{ts}"
    ws_entity = f"eqt_entity_{ts}"

    for ws_id in [ws_plain, ws_entity]:
        c.create_workspace(f"eqt-{ws_id[-6:]}", id=ws_id)
    log(f"Workspaces: {ws_plain}, {ws_entity}")

    # Ingest first 50 turns
    test_turns = turns[:50]
    full_text = "\n".join(t["text"] for t in test_turns)
    
    for t in test_turns:
        entities = json.dumps([{"name": speaker_a, "entity_type": "person"}, {"name": speaker_b, "entity_type": "person"}])
        for ws in [ws_plain, ws_entity]:
            try:
                c.store(workspace_id=ws, content=t["text"], memory_type="locomo_turn", confidence=1.0, tier="L0", entities_json=entities)
            except Exception as e:
                log(f"Store error for {ws}: {e}")
    
    log(f"Ingested {len(test_turns)} turns")

    # Batch entity extraction
    log("Extracting entities via LLM...")
    entities = extract_entities_llm(full_text)
    if entities:
        log(f"Entities: {len(entities)}")
        entity_count = 0
        for ent in entities:
            name = (ent.get("name", "") or "").strip()
            if not name or len(name) < 2: continue
            etype = ent.get("entity_type", "entity") or "entity"
            type_map = {"person":"entity","pet":"entity","book":"entity","place":"entity","event":"entity","activity":"entity","organization":"entity","concept":"concept","other":"entity"}
            ntype = type_map.get(etype.lower(), "entity")
            existing = c._query("kg_node", workspace_id=ws_entity, filter_dict={"label":name}, columns=["id"])
            if not existing:
                try:
                    c.create_node(ws_entity, label=name, node_type=ntype, summary=f"{etype}: {name}")
                    entity_count += 1
                except: pass
        log(f"Created {entity_count} KG nodes")
    else:
        log("No entities extracted")

    time.sleep(2)

    # Test queries
    queries = [
        "What are Melanie pets names",
        "What books has Melanie read",
        "What does Melanie do to destress",
        "What is Caroline identity",
        "What activities does Melanie do",
    ]

    results = {"plain": {}, "entity": {}}
    for q in queries:
        for label, ws in [("plain", ws_plain), ("entity", ws_entity)]:
            try:
                r = c.search(workspace_id=ws, query=q, limit=10, semantic=True, cross_encoder=False)
                mems = [(r2.get("memory_content","") or "")[:100] for r2 in r[:5]]
                results[label][q] = {"count": len(r), "top_memories": mems}
            except Exception as e:
                results[label][q] = {"error": str(e)}

    with open(RESULT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    
    log("=== DONE ===")

if __name__ == "__main__":
    main()
