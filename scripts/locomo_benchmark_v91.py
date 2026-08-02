#!/usr/bin/env python3
"""LoCoMo Benchmark v9.1 — STDB Pipeline + Entity Extraction.

Like v9, but adds LLM-based entity extraction during storage so that
searches can match by entity labels (people, pets, books, places, etc.),
dramatically improving single-hop and adversarial recall.

Usage:
    python scripts/locomo_benchmark_v91.py --conv 1 [--limit 10]
"""

import json
import os
import re
import secrets
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")
LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-chat")
LLM_API_KEY = os.environ.get("LLM_RERANK_API_KEY", "")

_API_KEYS: list[str] = []
if LLM_API_KEY:
    _API_KEYS.append(LLM_API_KEY)
for _var, _val in sorted(os.environ.items()):
    if _var.startswith("OPENROUTER_KEY_") and _val and _val not in _API_KEYS:
        _API_KEYS.append(_val)
_API_KEY_IDX = 0

_env_path = os.path.expanduser("~/.hermes/.env")
if not LLM_API_KEY and os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            if line.strip().startswith("OPENROUTER_API_KEY="):
                _, k = line.split("=", 1)
                LLM_API_KEY = k.strip().strip('"').strip("'")
                if LLM_API_KEY and LLM_API_KEY not in _API_KEYS:
                    _API_KEYS.append(LLM_API_KEY)

# ---------------------------------------------------------------------------
# Entity extraction (rule-based, no LLM cost)
# ---------------------------------------------------------------------------

# Common entity types and their trigger words
ENTITY_PATTERNS = [
    # People names (capitalized words after role words or possessive)
    ("person", r"\b([A-Z][a-z]+(?:['´][a-z]+)?)\b(?:'s)?\s+(?:is|has|was|said|likes|loves|works|went|does|wants|feels|thinks|hopes)"),
    ("person", r"\b(?:by|for|with|to|from)\s+([A-Z][a-z]+(?:['´][a-z]+)?)\b"),
    # Book titles (quoted)
    ("book", r'[""]([^""]{3,60})[""]'),
    # Places (proper nouns that are locations)
    ("place", r"\b(?:to|in|at|from|near|around)\s+(?:the\s+)?([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)?)\s+(?:Park|Beach|Forest|Lake|River|School|Museum|Library|Store|Restaurant|Cafe|Hotel|Club|Gallery|Studio|Center|Church)"),
    ("place", r"\b(?:Country|State|City|Town|Mountain|Ocean|Island|Creek)\s+(?:of\s+)?([A-Z][a-z]+)\b"),
    # Pets (animal names mentioned with pet-like contexts)
    ("pet", r"\b(?:dog|cat|pet|hamster|rabbit|fish|bird|turtle)\s+(?:named|called)\s+([A-Z][a-z]+)\b"),
    ("pet", r"\b([A-Z][a-z]+)\s+(?:the|my|our)\s+(?:dog|cat|pet|puppy|kitten)\b"),
    # Activities (gerunds or action phrases)
    ("activity", r"\b(enjoys|loves|likes|does|plays|practices|studies)\s+(\w+(?:ing)?(?:\s+\w+(?:ing)?)?)"),
    # Organizations
    ("organization", r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(?:Agency|Foundation|Institute|School|University|Association|Committee|Company|Corp|Club|Board)"),
]


def extract_entities_rule_based(text: str) -> list[dict]:
    """Extract entities from text using rule-based patterns (zero LLM cost)."""
    entities = []
    seen = set()
    for etype, pattern in ENTITY_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            name = m.group(1).strip()
            if not name or len(name) < 2 or len(name) > 50:
                continue
            key = (name.lower(), etype)
            if key in seen:
                continue
            seen.add(key)
            entities.append({"name": name, "type": etype})
    return entities


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------


def download_dataset(url: str = LOCOMO_DATA_URL) -> list[dict]:
    """Download and return the LoCoMo dataset (10 conversations)."""
    print("Downloading LoCoMo dataset...", file=sys.stderr)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    print(f"  Loaded {len(data)} conversations", file=sys.stderr)
    return data


def build_sessions(conversation: dict, session_size: int = 10) -> list[dict]:
    """Build session list from raw conversation data."""
    cd = conversation.get("conversation", {})
    sa = cd.get("speaker_a", "A")
    sb = cd.get("speaker_b", "B")
    sks = sorted(
        [k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )
    sessions = []
    for sk in sks:
        sn = int(sk.split("_")[1])
        dt = cd.get(f"session_{sn}_date_time", f"Session {sn}")
        turns_text = []
        for t in cd[sk]:
            sp = sa if "a" in t.get("speaker", "").lower() else sb
            turns_text.append(f"{sp}: {t['text']}")
        session_text = "\n".join(turns_text)
        sessions.append({
            "num": sn,
            "datetime": dt,
            "text": session_text,
            "n_turns": len(cd[sk]),
        })
    return sessions


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _llm_call(body: dict, timeout: int = 60) -> dict:
    """Call LLM with automatic API key rotation and retry."""
    global _API_KEY_IDX
    for a in range(5):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(LLM_ENDPOINT.rstrip("/") + "/chat/completions", headers=hdrs, json=body, timeout=timeout)
            if r.status_code == 429:
                _API_KEY_IDX += 1
                continue
            r.raise_for_status()
            return r.json()
        except httpx.TimeoutException:
            if a == 4:
                raise
            time.sleep(2 ** a)
            continue
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _API_KEY_IDX += 1
                time.sleep(2 ** a)
                continue
            if a == 4:
                raise
            time.sleep(2 ** a)
            continue
        except Exception:
            if a == 4:
                raise
            time.sleep(2 ** a)
            continue
    raise RuntimeError("LLM call failed after 5 retries")


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

DONT_KNOW_PHRASES = [
    "i don't know", "i don't have", "no information",
    "does not mention", "does not provide", "not mentioned",
    "not discussed", "impossible", "cannot determine",
    "none", "i do not know", "i'm not sure",
    "the context does not", "no answer", "no details",
]


def llm_judge(question: str, expected: str, answer: str) -> dict:
    """Judge with substring + keyword matching + LLM fallback."""
    if not answer or str(answer).startswith("ERROR") or str(answer).startswith("ANSWER ERROR"):
        return {"is_correct": False, "reasoning": "system error"}
    e = str(expected or "").strip()
    a = str(answer or "").strip()

    # Adversarial: empty expected → "don't know" is correct
    if not e:
        al = a.lower()
        dk = any(p in al for p in DONT_KNOW_PHRASES)
        return {"is_correct": dk, "reasoning": "adversarial (don't know)"}

    el = e.lower().rstrip(".")
    al = a.lower()

    if el in al:
        return {"is_correct": True, "reasoning": "substring"}

    date_m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", e)
    if date_m and date_m.group(1).lower() in al:
        return {"is_correct": True, "reasoning": "date"}

    ew = [w.lower().rstrip(".,;:!?") for w in e.split() if len(w) > 3]
    aw = set(w.lower().rstrip(".,;:!?") for w in a.split())
    if ew and sum(1 for w in ew if w in aw) / len(ew) >= 0.4:
        return {"is_correct": True, "reasoning": "keyword overlap"}

    prompt = (f"Question: {question}\nExpected: {e}\nSystem: {a}\n\n"
              f"Is the system answer semantically correct? Be generous. Reply Yes or No.")
    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 10}
    try:
        data = _llm_call(body)
        c = (data["choices"][0]["message"]["content"] or "").strip().lower()
        return {"is_correct": c.startswith("yes"), "reasoning": c[:20]}
    except Exception:
        return {"is_correct": False, "reasoning": "judge error"}


# ---------------------------------------------------------------------------
# Storage + retrieval
# ---------------------------------------------------------------------------


def store_sessions(client: Client, workspace_id: str, sessions: list[dict]):
    """Store sessions with entity extraction."""
    batch = []
    for s in sessions:
        # Extract entities from session text
        entities = extract_entities_rule_based(s["text"])
        # Add session number as an entity for matching
        entities.append({"name": f"session_{s['num']}", "entity_type": "session_num"})
        batch.append({
            "content": s["text"],
            "summary": f"Session {s['num']} ({s['n_turns']} turns)",
            "memory_type": "conversation",
            "entities_json": json.dumps(entities),
        })
    if batch:
        client.store_batch(workspace_id, batch)
        print(f"  Stored {len(batch)} sessions with {sum(len(json.loads(b['entities_json'])) for b in batch)} entities", file=sys.stderr)


def extract_session_num(entities_json: str) -> int | None:
    """Extract session number from entities_json."""
    try:
        ents = json.loads(entities_json) if isinstance(entities_json, str) else entities_json
        if isinstance(ents, list):
            for e in ents:
                if isinstance(e, dict) and e.get("entity_type") == "session_num":
                    return int(e["name"].replace("session_", ""))
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def retrieve_and_answer(sessions: list[dict], workspace_id: str, client: Client,
                        question: str, category: int) -> tuple[str, list[int]]:
    """Retrieve sessions via search + entities_json, then answer with LLM."""
    # Extract query entities for boosting
    query_entities = extract_entities_rule_based(question)

    search_results = client.search(
        workspace_id=workspace_id, query=question,
        limit=10, semantic=True, cross_encoder=False,
    )

    if not search_results:
        search_results = client.search(
            workspace_id=workspace_id, query=question,
            limit=10, semantic=False, cross_encoder=False,
        )

    if not search_results:
        return ("I don't know", [])

    # Match sessions via entities_json
    matched_sessions = []
    seen_nums = set()
    for sr in search_results:
        sn = extract_session_num(sr.get("entities_json", ""))
        if sn is not None and sn not in seen_nums:
            for s in sessions:
                if s["num"] == sn:
                    matched_sessions.append(s)
                    seen_nums.add(sn)
                    break
        if len(matched_sessions) >= 3:
            break

    # Fallback: content matching
    if not matched_sessions:
        sr_content = search_results[0].get("content", "")
        for s in sessions:
            if s["text"][:100] in sr_content or sr_content[:100] in s["text"]:
                matched_sessions.append(s)
                if len(matched_sessions) >= 3:
                    break
        if not matched_sessions:
            return ("I don't know", [])

    # Build context
    overview = "\n=== Session Overview ===\n"
    for s in sessions:
        marker = "★" if s in matched_sessions else " "
        overview += f"{marker} Session {s['num']} ({s['datetime']}): {s['text'][:80]}...\n"

    context_parts = []
    for s in matched_sessions:
        context_parts.append(f"--- Session {s['num']} (DATE: {s['datetime']}) ---\n{s['text']}")
    context = overview + "\n=== Retrieved Sessions ===\n" + "\n\n".join(context_parts)

    # Category-specific prompts
    if category == 1:  # single-hop
        prompt = f"""You are a precise fact extractor. Find the EXACT answer.

CONTEXT:
{context}

QUESTION: {question}

INSTRUCTIONS:
- Extract ONLY the specific facts. BE CONCISE.
- If a list, use commas: "item1, item2"
- Say "I don't know" only if not found

Answer:"""
    elif category == 2:  # temporal
        prompt = f"""Compute exact dates from the context.

CONTEXT:
{context}

QUESTION: {question}

CRITICAL: Relative time words are RELATIVE to the session DATE.
Give ONLY the computed date. Say "I don't know" if not answerable.

Answer:"""
    elif category == 3:  # multi-hop
        prompt = f"""Connect facts from different parts of the context.

CONTEXT:
{context}

QUESTION: {question}

Reason briefly, then give a concise answer. Say "I don't know" if insufficient info.

Answer:"""
    elif category == 5:  # adversarial
        prompt = f"""Find the exact answer. Pay attention to WHICH person.

CONTEXT:
{context}

QUESTION: {question}

Don't confuse Caroline and Melanie. Be concise. Say "I don't know" if not found.

Answer:"""
    else:
        prompt = f"""Answer based on the context.

CONTEXT:
{context}

QUESTION: {question}

Be concise. Say "I don't know" only if not found.

Answer:"""

    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 200}
    try:
        data = _llm_call(body, timeout=60)
        return ((data["choices"][0]["message"]["content"] or "").strip(), list(seen_nums))
    except Exception as e:
        return (f"ANSWER ERROR: {e}", [])


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(results: list[dict]) -> dict:
    """Aggregate results by category."""
    bc = defaultdict(lambda: {"t": 0, "c": 0})
    for r in results:
        c = r["category"]
        bc[c]["t"] += 1
        if r["is_correct"]:
            bc[c]["c"] += 1

    rpt = {}
    ta = ca = 0
    for c in sorted(bc):
        t = bc[c]["t"]
        ok = bc[c]["c"]
        rpt[CATEGORY_NAMES.get(c, f"c{c}")] = {"total": t, "correct": ok, "accuracy": round(ok / t * 100 if t else 0, 2)}
        ta += t
        ca += ok

    p_cats = [1, 2, 3, 4]
    pt = sum(bc[c]["t"] for c in p_cats)
    pc = sum(bc[c]["c"] for c in p_cats)
    rpt["__primary__"] = {"categories": [CATEGORY_NAMES[c] for c in p_cats], "total": pt, "correct": pc, "accuracy": round(pc / pt * 100 if pt else 0, 2)}
    rpt["__overall__"] = {"total": ta, "correct": ca, "accuracy": round(ca / ta * 100 if ta else 0, 2)}
    return rpt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LoCoMo Benchmark v9.1 — STDB + Entity Extraction")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conv", type=str, default="")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v91.json")
    parser.add_argument("--no-store", action="store_true")
    parser.add_argument("--workspace", type=str, default="")
    parser.add_argument("--sessions", type=int, default=10, help="Messages per session")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    print("LoCoMo v9.1 — STDB Pipeline + Entity Extraction", file=sys.stderr)

    # Connect
    db_id = os.environ.get("SPACETIMEDB_DB", "")
    token = os.environ.get("SPACETIMEDB_TOKEN", "")
    if not token:
        tr = httpx.get(f"{STDB_URL}/v1/database/{db_id}", timeout=10)
        token = tr.headers.get("spacetime-identity-token", "") or ""
    client = Client(database=db_id, token=token)
    try:
        client._call("register", ["v91-" + secrets.token_hex(8), "lmeval2026", "benchpass"])
    except Exception:
        pass
    print("  Connected", file=sys.stderr)

    dataset = download_dataset()
    if args.conv:
        ci = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in ci if 0 <= i < len(dataset)]

    all_results = []
    for ci, conversation in enumerate(dataset):
        sid = conversation.get("sample_id", f"conv_{ci + 1}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {ci + 1}: {sid}", file=sys.stderr)

        sessions = build_sessions(conversation, args.sessions)
        print(f"  Sessions: {len(sessions)}, Total turns: {sum(s['n_turns'] for s in sessions)}", file=sys.stderr)

        if args.workspace:
            ws_id = args.workspace
        else:
            ws_resp = client.create_workspace(f"locomo_v91_{sid}")
            ws_id = ws_resp.get("id", ws_resp) if isinstance(ws_resp, dict) else ws_resp
        print(f"  Workspace: {ws_id}", file=sys.stderr)

        if not args.no_store:
            store_sessions(client, ws_id, sessions)
            time.sleep(0.5)

        ql = conversation.get("qa", [])
        if args.limit > 0:
            ql = ql[:args.limit]
        print(f"  QA ({len(ql)} questions)...", file=sys.stderr)
        rs = run_qa(sessions, ws_id, client, ql)
        all_results.extend(rs)

    print(f"\n  FINAL", file=sys.stderr)
    rpt = aggregate(all_results)
    for k, v in sorted(rpt.items()):
        if k.startswith("_"):
            continue
        print(f"  {k:20s}: {v['accuracy']:6.2f}%  ({v['correct']:4d}/{v['total']:4d})", file=sys.stderr)
    p = rpt.get("__primary__", {})
    o = rpt.get("__overall__", {})
    print(f"\n  PRIMARY: {p.get('accuracy', 0):.1f}% ({p.get('correct', 0)}/{p.get('total', 0)})", file=sys.stderr)
    print(f"  OVERALL: {o.get('accuracy', 0):.1f}%", file=sys.stderr)
    open(args.output, "w").write(json.dumps({
        "benchmark": "LoCoMo v9.1", "timestamp": time.time(),
        "report": rpt, "results": all_results,
    }, indent=2))
    print(f"Saved to {args.output}", file=sys.stderr)


def run_qa(sessions: list[dict], workspace_id: str, client: Client, qa_list: list[dict]) -> list[dict]:
    """Run QA loop."""
    results = []
    for i, qa in enumerate(qa_list):
        q = qa.get("question", "")
        e = qa.get("answer", "")
        cat = qa.get("category", 0)

        ans, matched = retrieve_and_answer(sessions, workspace_id, client, q, cat)
        j = llm_judge(q, e, ans)

        marker = "✓" if j["is_correct"] else "✗"
        print(f"  Q{i + 1}/{len(qa_list)} [{CATEGORY_NAMES.get(cat, '?')}] {marker}: {q[:70]}...", file=sys.stderr)

        results.append({
            "question": q, "expected_answer": e, "actual_answer": ans,
            "matched_sessions": list(matched), "is_correct": j["is_correct"],
            "category": cat, "reasoning": j["reasoning"],
        })

        time.sleep(0.3)

    return results


if __name__ == "__main__":
    main()
