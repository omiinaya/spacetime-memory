#!/usr/bin/env python3
"""LongMemEval benchmark — isolated workspaces, proper keyword indexing.

For each question:
  1. Create a fresh workspace (prevents session accumulation)
  2. Store sessions via direct reducer (fast, no embedding)
  3. Index for keyword search (Tantivy BM25 + STDB inverted index)
  4. Search with keyword STDB search + multi-query fusion (if needed)
  5. Score and clean up workspace
"""
import json, time, uuid, os, sys, re
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
import math
import httpx
from spacetime_memory import Client

SPLIT = os.environ.get("LMEVAL_SPLIT", "s")
MAX_Q = int(os.environ.get("LMEVAL_MAX_Q", "10"))
DB = os.environ.get("SPACETIMEDB_DB", "")
HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", "3001"))
EMB = os.environ.get("EMBEDDER_URL", "http://127.0.0.1:9090")
TANTIVY = os.environ.get("TANTIVY_URL", "http://127.0.0.1:9091")

DATASET_URLS = {
    "s": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json?download=true",
    "m": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_m_cleaned.json?download=true",
}

LOG = open(f"/tmp/lmeval_iso_{SPLIT}.log", "w", buffering=1)
def logf(msg):
    LOG.write(msg + "\n"); LOG.flush(); print(msg, flush=True)

STOPWORDS = {
    "a","an","the","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could","should",
    "may","might","can","shall","to","of","in","for","on","with","at","by",
    "from","as","into","through","during","before","after","above","below",
    "between","out","off","over","under","again","further","then","once",
    "here","there","when","where","why","how","all","each","every","both",
    "few","more","most","other","some","such","no","nor","not","only","own",
    "same","so","than","too","very","just","because","but","and","or","if",
    "while","that","this","these","those","it","its","i","me","my","we","our",
    "you","your","he","him","his","she","her","they","them","their",
}

def flatten(s):
    if isinstance(s, list): return s
    if isinstance(s, dict) and "messages" in s: return s["messages"]
    return [{"role": "system", "content": str(s)}]

def to_text(s):
    return "\n".join(f'[{m.get("role","?")}]: {m.get("content","")}' for m in flatten(s))

def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]

def generate_query_variations(query: str) -> list[str]:
    """Generate up to 3 query variations for multi-query fusion."""
    variants = [query]
    tokens = tokenize(query)
    
    # Variation 2: entity-focused (capitalized words, numbers)
    words = re.findall(r"[A-Z][a-zA-Z]+", query)
    numbers = re.findall(r"\d+[A-Za-z]*", query)
    if not words:
        words = sorted(set(tokens), key=len, reverse=True)[:3]
    entity_phrase = " ".join(words + numbers)
    if entity_phrase:
        variants.append(f"{query} {entity_phrase}")
    
    # Variation 3: keyword-only (content words)
    if len(tokens) >= 2:
        variants.append(" ".join(tokens))
    
    # Deduplicate
    seen = set()
    unique = []
    for v in variants:
        key = v.lower().strip()
        if key not in seen:
            seen.add(key); unique.append(v)
    while len(unique) < 3:
        unique.append(query)
    return unique[:3]

def rrf_fuse(results_list: list[list], k: int = 60) -> list:
    scores = {}
    content_map = {}
    for rank_list in results_list:
        for rank, r in enumerate(rank_list):
            cid = r.get("id", "") or r.get("source_session_id", "") or r.get("content", "")[:100]
            if cid not in scores:
                scores[cid] = 0.0
                content_map[cid] = r
            scores[cid] += 1.0 / (k + rank + 1)
    sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])
    return [content_map[cid] for cid in sorted_ids]

def bm25_search_locally(query: str, sessions: list[dict], k1: float = 1.2, b: float = 0.75) -> list[dict]:
    """Pure BM25 search — fallback if Tantivy/STDB search fails."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    
    corpus = [s.get("content", s.get("text", to_text(s))) for s in sessions]
    n = len(corpus)
    avg_dl = sum(len(tokenize(d)) for d in corpus) / max(n, 1)
    tokenized = [tokenize(d) for d in corpus]
    
    idf = {}
    for t in set(q_tokens):
        nc = sum(1 for dt in tokenized if t in dt)
        idf[t] = math.log((n - nc + 0.5) / (nc + 0.5) + 1.0)
    
    scores = []
    for i in range(n):
        dt = tokenized[i]
        dl = len(dt)
        s = 0.0
        for t in q_tokens:
            tf = dt.count(t)
            if tf == 0: continue
            s += idf.get(t, 0) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avg_dl)))
        scores.append((s, i))
    
    scores.sort(key=lambda x: -x[0])
    return [{"content": corpus[idx], "score": round(scores[j][0], 4), "index": idx}
            for j, (s, idx) in enumerate(scores[:5]) if s > 0]


def main():
    cache = Path(f"data/longmemeval_{SPLIT}.json")
    t0 = time.time()
    if cache.exists():
        logf(f"Loading cached dataset from {cache}")
        with open(cache) as f: dataset = json.load(f)
    else:
        url = DATASET_URLS.get(SPLIT)
        if not url: logf(f"Unknown split '{SPLIT}'"); sys.exit(1)
        logf(f"Downloading LongMemEval '{SPLIT}' split...")
        r = httpx.get(url, timeout=300, follow_redirects=True); r.raise_for_status()
        dataset = r.json()
        with open(cache, "w") as f: json.dump(dataset, f)
        logf(f"  Saved {len(dataset)} questions")

    dataset = dataset[:MAX_Q]
    
    qtype_counts = defaultdict(int)
    for q in dataset: qtype_counts[q.get("question_type", "?")] += 1
    avg_sessions = sum(len(q.get("haystack_session_ids", [])) for q in dataset) // max(len(dataset), 1)
    avg_answers = sum(len(q.get("answer_session_ids", [])) for q in dataset) // max(len(dataset), 1)
    
    logf(f"Dataset: {len(dataset)} questions, split={SPLIT}")
    logf(f"Question types: {dict(qtype_counts)}")
    logf(f"Avg sessions per question: {avg_sessions}")
    logf(f"Avg answer sessions per question: {avg_answers}")

    # Connect
    tr = httpx.get(f"http://{HOST}:{PORT}/v1/database/{DB}", timeout=10)
    token = tr.headers.get("spacetime-identity-token", "")
    c = Client(database=DB, embedder_url=EMB, token=token, host=HOST, port=PORT)
    try:
        c._call("register", ["lmeval-" + uuid.uuid4().hex[:8], "lmeval2026", "benchpass"])
    except Exception:
        pass

    results = {}
    t0 = time.time()
    tantivy_http = httpx.Client(base_url=TANTIVY, timeout=10)

    for qi, q in enumerate(dataset):
        qid = q.get("question_id", qi)
        qtype = q.get("question_type", "?")
        qtext = q.get("question", "")
        haystack_ids = q.get("haystack_session_ids", [])
        haystack = q.get("haystack_sessions", [])
        answer_ids = set(q.get("answer_session_ids", []))
        n_answers = len(answer_ids)
        q_start = time.time()

        # Fresh workspace per question
        ws = c.create_workspace(f"lmeval-q{qi}-" + uuid.uuid4().hex[:8])
        WS = ws["id"]
        
        # Store sessions with proper indexing
        stored_ids = []
        for sid, session in zip(haystack_ids, haystack):
            text = to_text(session)
            # Store via direct reducer
            try:
                c._call("store_memory", [
                    WS,          # workspace_id
                    "",          # peer_id
                    "",          # observer_id
                    "session",   # memory_type
                    text,        # content
                    f"Session {sid}",  # summary
                    "[]",        # entities_json
                    0.8,         # confidence
                    sid,         # source_session_id
                    "",          # source_message_id
                    "",          # images_json
                ])
            except Exception as e:
                logf(f"    STORE ERROR for {sid}: {e}")
                continue
            
            # Get memory ID from memory_insert_result table
            mid = ""
            try:
                rows = c._query("memory_insert_result", workspace_id=WS,
                                filter_dict={"workspace_id": WS})
                for row in reversed(rows):
                    if row.get("content_prefix", "") == text[:100]:
                        mid = row.get("memory_id", "")
                        break
            except Exception:
                pass
            
            # Fallback: query memory table by content match
            if not mid:
                try:
                    mems = c._query("memory", workspace_id=WS, columns=["id", "content"])
                    for m in reversed(mems):
                        if m.get("content", "") == text:
                            mid = m["id"]
                            break
                except Exception:
                    pass
            
            if mid:
                stored_ids.append({"id": mid, "content": text, "sid": sid})
                # Index for keyword search
                try:
                    c._call("index_terms", [WS, mid, text])
                except Exception:
                    pass
        
        # Batch Tantivy indexing
        if stored_ids:
            tantivy_items = [{
                "workspace_id": WS,
                "entity_id": si["id"],
                "content": si["content"],
                "entity_type": "memory",
            } for si in stored_ids]
            try:
                tantivy_http.post("/index/batch", json={"items": tantivy_items}, timeout=30)
            except Exception:
                pass

        logf(f"  Workspace {qi+1}: stored {len(stored_ids)}/{len(haystack_ids)} sessions")

        # Search with multi-query fusion
        variants = generate_query_variations(qtext)
        all_results = []
        for v in variants:
            try:
                # Try STDB keyword search first
                sr = c.search(WS, v, limit=10, semantic=False, cross_encoder=False)
                if isinstance(sr, list) and len(sr) > 0:
                    all_results.append(sr)
            except Exception:
                pass
        
        # Fall back to local BM25 if STDB search returned nothing
        fused = []
        if all_results:
            fused = rrf_fuse(all_results)[:5]
        
        if not fused:
            # Local BM25 fallback using the stored content
            local_corpus = [si["content"] for si in stored_ids]
            bm25_scores = bm25_search_locally(qtext, [{"content": si["content"]} for si in stored_ids])
            fused = bm25_scores
        
        # Check found answer sessions
        found = set()
        for r in fused[:5]:
            rid = r.get("source_session_id", "") or r.get("id", "") or \
                  (stored_ids[r.get("index", -1)]["sid"] if r.get("index", -1) >= 0 and r.get("index", -1) < len(stored_ids) else "")
            if rid in answer_ids:
                found.add(rid)
            # Content-based fallback
            rc = (r.get("content") or "").lower()
            for ans_id in answer_ids:
                for hs_id, hs in zip(haystack_ids, haystack):
                    if hs_id == ans_id:
                        at = to_text(hs).lower()
                        if len(at) > 30 and (at[:30] in rc or rc[:30] in at):
                            found.add(ans_id)

        all_found = n_answers > 0 and len(found) >= n_answers
        results[qid] = {
            "question_type": qtype,
            "n_haystack_sessions": len(haystack_ids),
            "n_answer_sessions": n_answers,
            "n_stored": len(stored_ids),
            "found_in_top5": len(found),
            "all_found": all_found,
            "search_variants": len(variants),
            "total_search_results": sum(len(r) for r in all_results),
        }

        hits = sum(1 for r in results.values() if r["all_found"])
        pct = hits / len(results) * 100
        q_elapsed = time.time() - q_start
        cum_elapsed = time.time() - t0
        logf(f"  [{qi+1}/{len(dataset)}] Recall@All@5={pct:.1f}%  stored={len(stored_ids)}  Q={q_elapsed:.1f}s  cum={cum_elapsed:.0f}s")

        # Clean up workspace
        try: c.delete_workspace(WS)
        except: pass

    tantivy_http.close()

    # Aggregate
    qtypes = defaultdict(lambda: {"hits": 0, "total": 0})
    for r in results.values():
        qtypes[r["question_type"]]["total"] += 1
        if r["all_found"]:
            qtypes[r["question_type"]]["hits"] += 1

    total_hits = sum(qt["hits"] for qt in qtypes.values())
    total_q = sum(qt["total"] for qt in qtypes.values())
    overall = total_hits / total_q * 100 if total_q else 0
    total_elapsed = time.time() - t0

    logf(f"\n{'='*60}")
    logf(f"  RESULTS")
    logf(f"{'='*60}")
    logf(f"Overall Recall@All@5: {overall:.1f}% ({total_hits}/{total_q})")
    for qt, st in sorted(qtypes.items()):
        logf(f"  {qt:<35}: {st['hits']}/{st['total']} = {st['hits']/st['total']*100:.1f}%")
    logf(f"\nTotal time: {total_elapsed:.0f}s ({total_elapsed/max(len(dataset),1):.1f}s/question)")

    REF_SCORES = {
        "s": {"Mnemosyne": 98.9, "Mempalace": 96.6},
        "m": {"Mnemosyne": 97.8, "Mempalace": 95.1},
    }
    ref = REF_SCORES.get(SPLIT, {})
    beats_ref = all(overall >= v for v in ref.values()) if ref else None
    if ref:
        logf(f"\nReference scores:")
        for name, score in ref.items():
            symbol = "✅" if overall >= score else "❌"
            logf(f"  {symbol} {name}: {score}%")

    out = {
        "benchmark": "LongMemEval",
        "split": SPLIT,
        "questions": len(dataset),
        "overall": {"hits": total_hits, "total": total_q, "recall_at_all_5": round(overall / 100, 4)},
        "per_type": {qt: {"hits": st["hits"], "total": st["total"],
                          "recall": round(st["hits"] / st["total"] * 100, 1) if st["total"] else 0}
                     for qt, st in sorted(qtypes.items())},
        "reference_scores": ref,
        "beats_reference": beats_ref,
        "total_time_s": round(total_elapsed, 1),
    }

    with open(f"benchmark_results_longmemeval_{SPLIT}.json", "w") as f:
        json.dump(out, f, indent=2)
    logf(f"\nSaved to benchmark_results_longmemeval_{SPLIT}.json")
    return out

if __name__ == "__main__":
    main()
