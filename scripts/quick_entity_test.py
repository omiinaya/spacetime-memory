#!/usr/bin/env python3
"""Quick entity-linking retrieval test.

Measures whether entity-aware boosting improves search recall for entity-specific
queries (people, pets, books, etc.) compared to semantic-only search.

Usage:
    python scripts/quick_entity_test.py
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

from spacetime_memory import Client
from spacetime_memory.entity_linking import extract_entities_llm, link_entities


LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"


def extract_turns(conversation: dict) -> list[dict]:
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "A")
    speaker_b = conv.get("speaker_b", "B")

    session_keys = sorted(
        [k for k in conv.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )

    turns = []
    turn_id = 0
    for sk in session_keys:
        for t in conv.get(sk, []):
            turn_id += 1
            speaker = speaker_a if "a" in (t.get("speaker", "") or "").lower() else speaker_b
            turns.append({
                "turn_id": turn_id,
                "text": t.get("text", ""),
                "speaker": speaker,
            })
    return turns


def main():
    # Download dataset
    print("Downloading LoCoMo dataset...", flush=True)
    resp = urllib.request.urlopen(LOCOMO_URL, timeout=30)
    dataset = json.loads(resp.read().decode())
    conversation = dataset[0]  # conv-26
    sample = conversation.get("sample_id", "conv-26")
    print(f"Loaded {len(dataset)} conversations, using {sample}", flush=True)

    turns = extract_turns(conversation)
    print(f"Extracted {len(turns)} turns", flush=True)

    # Create client
    c = Client()

    # Create two workspaces — one WITH entity linking, one WITHOUT
    ts = int(time.time() * 1_000_000)
    ws_plain = f"entity_test_plain_{ts}"
    ws_entity = f"entity_test_entity_{ts}"

    for ws_id in [ws_plain, ws_entity]:
        try:
            c.create_workspace(f"entity-test-{ws_id[-6:]}", id=ws_id)
            print(f"Created workspace {ws_id}", flush=True)
        except RuntimeError as e:
            print(f"  Warning: {e}", flush=True)

    # Ingest first 50 turns into BOTH workspaces
    test_turns = turns[:50]
    
    speaker_a = conversation.get("conversation", {}).get("speaker_a", "A")
    speaker_b = conversation.get("conversation", {}).get("speaker_b", "B")
    full_text = "\n".join(t["text"] for t in test_turns)

    print(f"Ingesting {len(test_turns)} turns...", flush=True)
    for i, t in enumerate(test_turns):
        content = t["text"]
        entities_json = json.dumps([
            {"name": speaker_a, "entity_type": "person"},
            {"name": speaker_b, "entity_type": "person"},
        ])

        # Store into PLAIN workspace (no entity linking)
        try:
            c.store(workspace_id=ws_plain, content=content,
                    memory_type="locomo_turn", confidence=1.0,
                    tier="L0", entities_json=entities_json)
        except RuntimeError as e:
            print(f"  Plain workspace store error: {e}", flush=True)

        # Store into ENTITY workspace
        try:
            result = c.store(workspace_id=ws_entity, content=content,
                            memory_type="locomo_turn", confidence=1.0,
                            tier="L0", entities_json=entities_json)
        except RuntimeError as e:
            print(f"  Entity workspace store error: {e}", flush=True)

    print(f"Ingested {len(test_turns)} turns", flush=True)

    # Batch-extract entities for the ENTITY workspace
    print("Batch-extracting entities via LLM...", flush=True)
    entities = extract_entities_llm(full_text)
    if entities:
        entity_names = [e.get("name", "") for e in entities if e.get("name")]
        print(f"Extracted {len(entities)} entities: {entity_names[:20]}", flush=True)

        # Create KG nodes for each entity
        entity_count = 0
        for ent in entities:
            name = (ent.get("name", "") or "").strip()
            if not name or len(name) < 2:
                continue
            etype = ent.get("entity_type", "entity") or "entity"
            type_map = {"person": "entity", "pet": "entity", "book": "entity",
                       "place": "entity", "event": "entity", "activity": "entity",
                       "organization": "entity", "concept": "concept", "other": "entity"}
            node_type = type_map.get(etype.lower(), "entity")

            # Check if node exists
            existing = c._query("kg_node", workspace_id=ws_entity,
                               filter_dict={"label": name}, columns=["id"])
            if existing:
                continue

            try:
                c.create_node(ws_entity, label=name, node_type=node_type,
                              summary=f"{etype}: {name}")
                entity_count += 1
            except RuntimeError:
                continue

        print(f"Created {entity_count} new entity KG nodes", flush=True)

    # Wait for indexing
    time.sleep(2)

    # ── Entity-specific test queries ──
    test_queries = [
        "What are Melanie pets names",
        "What books has Melanie read",
        "What does Melanie do to destress",
        "What is Caroline identity",
        "What activities does Melanie do",
        "Where has Melanie camped",
        "What do Melanie kids like",
        "What events has Caroline participated in",
        "What kind of art does Caroline make",
        "How many times has Melanie gone to the beach",
        "What is Caroline relationship status",
        "What does Caroline think about counseling",
    ]

    print("\n" + "=" * 60, flush=True)
    print("  SEARCH QUALITY COMPARISON", flush=True)
    print("=" * 60, flush=True)

    plain_results: dict[str, list] = {}
    entity_results: dict[str, list] = {}

    for query in test_queries:
        print(f"\n--- Query: {query}", flush=True)

        # Search in PLAIN workspace (no entity linking)
        try:
            r_plain = c.search(workspace_id=ws_plain, query=query,
                              limit=10, semantic=True, cross_encoder=False)
        except RuntimeError as e:
            print(f"  Plain search error: {e}", flush=True)
            r_plain = []
        plain_results[query] = r_plain

        # Search in ENTITY workspace (with entity linking)
        try:
            r_entity = c.search(workspace_id=ws_entity, query=query,
                               limit=10, semantic=True, cross_encoder=False)
        except RuntimeError as e:
            print(f"  Entity search error: {e}", flush=True)
            r_entity = []
        entity_results[query] = r_entity

        # Score: count results that mention the key entity
        query_lower = query.lower()
        # Extract likely entity names from query
        key_words = [w.strip("'s") for w in query_lower.split() 
                    if len(w) > 3 and w not in ("what", "does", "have", "has", "been", "where", "how", "who", "when", "the", "and", "are", "for")]
        
        # Find how many results mention the entities in the query
        plain_entity_hits = sum(
            1 for r in r_plain[:5]
            if any(kw in (r.get("memory_content", "") or "").lower() for kw in key_words)
        )
        entity_entity_hits = sum(
            1 for r in r_entity[:5]
            if any(kw in (r.get("memory_content", "") or "").lower() for kw in key_words)
        )

        print(f"  Plain: {len(r_plain)} results, {plain_entity_hits}/5 entity hits", flush=True)
        print(f"  Entity: {len(r_entity)} results, {entity_entity_hits}/5 entity hits", flush=True)
        if r_plain:
            print(f"    Plain top: {r_plain[0].get('memory_content','')[:80]}", flush=True)
        if r_entity:
            print(f"    Entity top: {r_entity[0].get('memory_content','')[:80]}", flush=True)

    # Summary
    print("\n" + "=" * 60, flush=True)
    print("  SUMMARY", flush=True)
    print("=" * 60, flush=True)
    
    total_plain = sum(
        sum(1 for r in plain_results[q][:5] if any(kw in (r.get("memory_content", "") or "").lower()
            for kw in [w.strip("'s") for w in q.lower().split() if len(w) > 3 and w not in ("what", "does", "have", "has", "been", "where", "how", "who", "when", "the", "and", "are", "for")]))
        for q in test_queries if plain_results.get(q)
    )
    total_entity = sum(
        sum(1 for r in entity_results[q][:5] if any(kw in (r.get("memory_content", "") or "").lower()
            for kw in [w.strip("'s") for w in q.lower().split() if len(w) > 3 and w not in ("what", "does", "have", "has", "been", "where", "how", "who", "when", "the", "and", "are", "for")]))
        for q in test_queries if entity_results.get(q)
    )
    max_possible = len(test_queries) * 5
    print(f"Plain  workspace entity recall: {total_plain}/{max_possible} = {total_plain/max_possible*100:.1f}%", flush=True)
    print(f"Entity workspace entity recall: {total_entity}/{max_possible} = {total_entity/max_possible*100:.1f}%", flush=True)
    print(f"Improvement: +{(total_entity - total_plain)/max_possible*100:.1f} percentage points", flush=True)


if __name__ == "__main__":
    main()
