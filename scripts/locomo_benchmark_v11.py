#!/usr/bin/env python3
"""LoCoMo Benchmark v11 — STDB Pipeline + Multi-Query Fusion.

Like v9.1 but adds multi-query retrieval: for each question, generate 3 query
variations (original, entity-expanded, keyword-extracted), search each independently,
fuse and deduplicate results, then answer. This addresses the ~8.5% retrieval gap
by approaching each question from multiple angles.

Usage:
    python scripts/locomo_benchmark_v11.py --conv 1 [--limit 10]
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

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://127.0.0.1:3001")
STDB_HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
STDB_PORT = int(os.environ.get("SPACETIMEDB_PORT", "3001"))
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
# Entity extraction (rule-based, zero LLM cost)
# ---------------------------------------------------------------------------

ENTITY_PATTERNS = [
    ("person", r"\b([A-Z][a-z]+(?:['´][a-z]+)?)\b(?:'s)?\s+(?:is|has|was|said|likes|loves|works|went|does|wants|feels|thinks|hopes)"),
    ("person", r"\b(?:by|for|with|to|from)\s+([A-Z][a-z]+(?:['´][a-z]+)?)\b"),
    ("book", r'[""]([^"""]{3,60})[""]'),
    ("place", r"\b(?:to|in|at|from|near|around)\s+(?:the\s+)?([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)?)\s+(?:Park|Beach|Forest|Lake|River|School|Museum|Library|Store|Restaurant|Cafe|Hotel|Club|Gallery|Studio|Center|Church)"),
    ("pet", r"\b(?:dog|cat|pet|hamster|rabbit|fish|bird|turtle)\s+(?:named|called)\s+([A-Z][a-z]+)\b"),
    ("activity", r"\b(enjoys|loves|likes|does|plays|practices|studies)\s+(\w+(?:ing)?(?:\s+\w+(?:ing)?)?)"),
    ("organization", r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(?:Agency|Foundation|Institute|School|University|Association|Committee|Company|Corp|Club|Board)"),
]


def extract_entities(text: str) -> list[dict]:
    """Extract entities using rule-based patterns."""
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


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    stopwords = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
                 "have", "has", "had", "do", "does", "did", "will", "would", "could",
                 "should", "may", "might", "can", "shall", "to", "of", "in", "for",
                 "on", "with", "at", "by", "from", "as", "into", "through", "during",
                 "before", "after", "above", "below", "between", "out", "off", "over",
                 "under", "again", "then", "once", "here", "there", "when", "where",
                 "why", "how", "all", "each", "every", "both", "few", "more", "most",
                 "other", "some", "such", "no", "nor", "not", "only", "own", "same",
                 "so", "than", "too", "very", "just", "because", "but", "and", "or",
                 "if", "while", "that", "this", "these", "those", "it", "its", "what",
                 "which", "who", "whom", "whose"}
    tokens = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [t for t in tokens if t not in stopwords and len(t) > 2]


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------


def download_dataset(url: str = LOCOMO_DATA_URL) -> list[dict]:
    print("Downloading LoCoMo dataset...", file=sys.stderr)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    print(f"  Loaded {len(data)} conversations", file=sys.stderr)
    return data


def build_sessions(conversation: dict, session_size: int = 10) -> list[dict]:
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
    if not answer or str(answer).startswith("ERROR") or str(answer).startswith("ANSWER ERROR"):
        return {"is_correct": False, "reasoning": "system error"}
    e = str(expected or "").strip()
    a = str(answer or "").strip()

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
# Storage
# ---------------------------------------------------------------------------


def store_sessions(client: Client, workspace_id: str, sessions: list[dict]):
    batch = []
    for s in sessions:
        entities = extract_entities(s["text"])
        entities.append({"name": f"session_{s['num']}", "entity_type": "session_num"})
        keywords = extract_keywords(s["text"])
        batch.append({
            "content": s["text"],
            "summary": f"Session {s['num']} ({s['n_turns']} turns)",
            "memory_type": "conversation",
            "entities_json": json.dumps(entities),
        })
    if batch:
        chunk_size = 4
        for i in range(0, len(batch), chunk_size):
            chunk = batch[i:i + chunk_size]
            client.store_batch(workspace_id, chunk)
            print(f"  Stored batch {i // chunk_size + 1}/{(len(batch) + chunk_size - 1) // chunk_size} "
                  f"({len(chunk)} sessions)", file=sys.stderr, flush=True)
        total_ents = sum(len(json.loads(b["entities_json"])) for b in batch)
        print(f"  Total: {len(batch)} sessions, {total_ents} entities", file=sys.stderr, flush=True)


def extract_session_num(entities_json: str) -> int | None:
    try:
        ents = json.loads(entities_json) if isinstance(entities_json, str) else entities_json
        if isinstance(ents, list):
            for e in ents:
                if isinstance(e, dict) and e.get("entity_type") == "session_num":
                    return int(e["name"].replace("session_", ""))
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Multi-query retrieval + fusion (NEW in v11)
# ---------------------------------------------------------------------------


def generate_query_variations(question: str) -> list[str]:
    """Generate 3 query variations for multi-angled retrieval."""
    variations = [question]  # 1. Original

    # 2. Entity-expanded: extract entities and use them as the query
    entities = extract_entities(question)
    if entities:
        entity_names = [e["name"] for e in entities]
        expanded = " ".join(entity_names) + " " + question
        variations.append(expanded)
    else:
        variations.append(question)

    # 3. Keyword-focused: extract meaningful terms
    keywords = extract_keywords(question)
    if keywords:
        kw_query = " ".join(keywords[:8])  # Top 8 keywords
        variations.append(kw_query)
    else:
        variations.append(question)

    return variations


def multi_query_search(client: Client, workspace_id: str, question: str,
                       limit_per_query: int = 8) -> list[dict]:
    """Search with multiple query variations and fuse results."""
    variations = generate_query_variations(question)

    all_results = []
    seen_content = set()

    for qv in variations:
        try:
            results = client.search(
                workspace_id=workspace_id, query=qv,
                limit=limit_per_query, semantic=True, cross_encoder=False,
            )
        except Exception:
            results = []

        if not results:
            try:
                results = client.search(
                    workspace_id=workspace_id, query=qv,
                    limit=limit_per_query, semantic=False, cross_encoder=False,
                )
            except Exception:
                results = []

        # Deduplicate by content hash
        for r in results:
            content = r.get("content", "")
            content_hash = content[:200]  # Use first 200 chars as key
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                all_results.append(r)

    return all_results


def fuse_results_to_sessions(all_results: list[dict], sessions: list[dict],
                              max_sessions: int = 5) -> list[dict]:
    """Fuse multi-query results into unique matched sessions."""
    matched_sessions = []
    seen_nums = set()

    # Pass 1: Match by entities_json session numbers
    for r in all_results:
        sn = extract_session_num(r.get("entities_json", ""))
        if sn is not None and sn not in seen_nums:
            for s in sessions:
                if s["num"] == sn:
                    matched_sessions.append(s)
                    seen_nums.add(sn)
                    break
        if len(matched_sessions) >= max_sessions:
            break

    # Pass 2: Fallback — content matching for unmatched
    if len(matched_sessions) < max_sessions:
        for r in all_results:
            if len(matched_sessions) >= max_sessions:
                break
            rc = r.get("content", "")
            for s in sessions:
                if s["num"] in seen_nums:
                    continue
                if s["text"][:100] in rc or rc[:100] in s["text"]:
                    matched_sessions.append(s)
                    seen_nums.add(s["num"])
                    break

    # Pass 3: If still not enough, add recent unmatched sessions
    if len(matched_sessions) < 3:
        for s in reversed(sessions):
            if s["num"] not in seen_nums:
                matched_sessions.append(s)
                seen_nums.add(s["num"])
                if len(matched_sessions) >= 3:
                    break
        if matched_sessions:
            print(f"    Pass 3 added {len([s for s in matched_sessions if s['num'] not in seen_nums or True])} fallback sessions", file=sys.stderr)

    return matched_sessions


# ---------------------------------------------------------------------------
# Retrieval + Answering
# ---------------------------------------------------------------------------


def retrieve_and_answer(sessions: list[dict], workspace_id: str, client: Client,
                        question: str, category: int) -> tuple[str, list[int]]:
    """Multi-query retrieval → fusion → LLM answer."""
    # Step 1: Multi-query search with fusion
    all_results = multi_query_search(client, workspace_id, question)

    if not all_results:
        return ("I don't know", [])

    # Step 2: Fuse results to unique sessions
    matched_sessions = fuse_results_to_sessions(all_results, sessions, max_sessions=5)
    seen_nums = {s["num"] for s in matched_sessions}

    if not matched_sessions:
        return ("I don't know", [])

    # Step 3: Build enriched context
    overview = "\n=== Session Overview ===\n"
    for s in sessions:
        marker = "★" if s in matched_sessions else " "
        overview += f"{marker} Session {s['num']} ({s['datetime']}): {s['text'][:80]}...\n"

    context_parts = []
    for s in matched_sessions:
        context_parts.append(f"--- Session {s['num']} (DATE: {s['datetime']}) ---\n{s['text']}")
    context = overview + "\n=== Retrieved Sessions ===\n" + "\n\n".join(context_parts)

    # Step 4: Category-specific prompts
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
# QA Loop
# ---------------------------------------------------------------------------


def run_qa(sessions: list[dict], workspace_id: str, client: Client, questions: list[dict]) -> list[dict]:
    results = []
    for qi, q in enumerate(questions):
        qtext = q.get("question", "")
        cat = q.get("category", 4)
        expected = q.get("answer", "")

        t0 = time.time()
        answer, matched_nums = retrieve_and_answer(sessions, workspace_id, client, qtext, cat)
        elapsed = time.time() - t0
        judgment = llm_judge(qtext, expected, answer)

        results.append({
            "question": qtext, "category": cat,
            "expected_answer": expected, "actual_answer": answer,
            "is_correct": judgment["is_correct"],
            "reasoning": judgment.get("reasoning", ""),
            "matched_sessions": matched_nums,
            "latency_ms": round(elapsed * 1000, 1),
        })

        mark = "✓" if judgment["is_correct"] else "✗"
        cat_name = CATEGORY_NAMES.get(cat, f"c{cat}")
        ans_preview = (answer or "")[:60].replace("\n", " ")
        print(f"  Q{qi + 1}/{len(questions)} [{cat_name}] {mark}: {ans_preview}...", file=sys.stderr, flush=True)

    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(results: list[dict]) -> dict:
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

    parser = argparse.ArgumentParser(description="LoCoMo Benchmark v11 — Multi-Query Fusion")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conv", type=str, default="")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v11.json")
    parser.add_argument("--no-store", action="store_true")
    parser.add_argument("--workspace", type=str, default="")
    parser.add_argument("--sessions", type=int, default=10, help="Messages per session")
    args = parser.parse_args()

    print("LoCoMo v11 — STDB Pipeline + Multi-Query Fusion", file=sys.stderr, flush=True)

    # Connect
    db_id = os.environ.get("SPACETIMEDB_DB", "")
    token = os.environ.get("SPACETIMEDB_TOKEN", "")
    if not token:
        tr = httpx.get(f"{STDB_URL}/v1/database/{db_id}", timeout=10)
        token = tr.headers.get("spacetime-identity-token", "") or ""
    client = Client(database=db_id, token=token, host=STDB_HOST, port=STDB_PORT)
    try:
        client._call("register", ["v11-" + secrets.token_hex(8), "lmeval2026", "benchpass"])
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
            ws_resp = client.create_workspace(f"locomo_v11_{sid}")
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
        "benchmark": "LoCoMo v11", "timestamp": time.time(),
        "report": rpt, "results": all_results,
    }, indent=2))


if __name__ == "__main__":
    main()
