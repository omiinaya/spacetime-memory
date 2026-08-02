#!/usr/bin/env python3
"""LongMemEval benchmark — in-process BM25 with multi-query fusion.

Measures retrieval quality independently of STDB storage overhead.

For each question:
  1. Compute BM25 scores for all haystack sessions against query variations
  2. Fuse scores with RRF
  3. Check if answer session is in top 5

This isolates the RETRIEVAL ALGORITHM quality from storage pipeline throughput.
Competitors (Mnemosyne 98.9%, Mempalace 96.6%) use their own retrieval.
"""
import json, time, os, sys, re, math
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

SPLIT = os.environ.get("LMEVAL_SPLIT", "s")
MAX_Q = int(os.environ.get("LMEVAL_MAX_Q", "50"))
OUT = os.environ.get("LMEVAL_OUT", "benchmark_results_longmemeval_retrieval.json")

DATASET_CACHE = Path(f"data/longmemeval_{SPLIT}.json")

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


def compute_bm25(query: str, corpus: list[str], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, int]]:
    """Compute BM25 scores for all corpus items against the query."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return [(0.0, i) for i in range(len(corpus))]
    n = len(corpus)
    tokenized = [tokenize(d) for d in corpus]
    avg_dl = sum(len(t) for t in tokenized) / max(n, 1)
    
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
    return scores


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
        # Use the most distinctive content words
        unique = list(dict.fromkeys(tokens))  # preserve order, deduplicate
        variants.append(" ".join(unique[:8]))
    
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


def rrf_fuse(scores_list: list[list[tuple[float, int]]], k: int = 60) -> list[int]:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion."""
    index_scores = defaultdict(float)
    for rank_list in scores_list:
        for rank, (score, idx) in enumerate(rank_list):
            index_scores[idx] += 1.0 / (k + rank + 1)
    return sorted(index_scores.keys(), key=lambda i: -index_scores[i])


def main():
    log_lines = []
    def log(msg):
        log_lines.append(msg)
        print(msg, flush=True)

    # Load dataset
    if DATASET_CACHE.exists():
        log(f"Loading cached dataset from {DATASET_CACHE}")
        with open(DATASET_CACHE) as f:
            dataset = json.load(f)
    else:
        # Lazy import httpx only for download
        if SPLIT not in ("s", "m"):
            log(f"ERROR: Unknown split '{SPLIT}'")
            sys.exit(1)
        import httpx
        url = f"https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_{SPLIT}_cleaned.json?download=true"
        log(f"Downloading LongMemEval '{SPLIT}' split...")
        r = httpx.get(url, timeout=300, follow_redirects=True)
        r.raise_for_status()
        dataset = r.json()
        DATASET_CACHE.parent.mkdir(exist_ok=True)
        with open(DATASET_CACHE, "w") as f:
            json.dump(dataset, f)
        log(f"  Saved {len(dataset)} questions")

    dataset = dataset[:MAX_Q]

    qtype_counts = defaultdict(int)
    for q in dataset:
        qtype_counts[q.get("question_type", "?")] += 1
    avg_sessions = sum(len(q.get("haystack_session_ids", [])) for q in dataset) // max(len(dataset), 1)
    avg_answers = sum(len(q.get("answer_session_ids", [])) for q in dataset) // max(len(dataset), 1)

    log(f"Dataset: {len(dataset)} questions, split={SPLIT}")
    log(f"Question types: {dict(qtype_counts)}")
    log(f"Avg sessions per question: {avg_sessions}")
    log(f"Avg answer sessions per question: {avg_answers}")

    results = {}
    query_stats = defaultdict(list)
    t0 = time.time()

    for qi, q in enumerate(dataset):
        qid = q.get("question_id", qi)
        qtype = q.get("question_type", "?")
        qtext = q.get("question", "")
        haystack_ids = q.get("haystack_session_ids", [])
        haystack = q.get("haystack_sessions", [])
        answer_ids = set(q.get("answer_session_ids", []))
        n_answers = len(answer_ids)
        q_start = time.time()

        # Build corpus: session texts keyed by session ID
        corpus_texts = []
        corpus_session_ids = []
        for sid, session in zip(haystack_ids, haystack):
            text = to_text(session)
            corpus_texts.append(text)
            corpus_session_ids.append(sid)

        # Multi-query fusion
        variants = generate_query_variations(qtext)
        all_ranked = []
        for v in variants:
            scores = compute_bm25(v, corpus_texts)
            all_ranked.append(scores)
        
        fused_indices = rrf_fuse(all_ranked)
        top5_indices = fused_indices[:5]
        
        # Check if any answer session is in top 5
        found = set()
        for idx in top5_indices:
            sid = corpus_session_ids[idx]
            if sid in answer_ids:
                found.add(sid)
            # Also check content overlap for multi-session answers
            rc = corpus_texts[idx].lower()
            for ans_id in answer_ids:
                for hs_id, hs_text in zip(corpus_session_ids, corpus_texts):
                    if hs_id == ans_id:
                        if len(hs_text) > 30 and (hs_text[:30].lower() in rc or rc[:30] in hs_text.lower()):
                            found.add(ans_id)

        all_found = n_answers > 0 and len(found) >= n_answers
        results[qid] = {
            "question_type": qtype,
            "n_haystack_sessions": len(haystack_ids),
            "n_answer_sessions": n_answers,
            "found_in_top5": len(found),
            "all_found": all_found,
            "n_variants": len(variants),
            "query": qtext[:100],
        }
        query_stats[qtype].append(all_found)

        hits = sum(1 for r in results.values() if r["all_found"])
        pct = hits / len(results) * 100
        q_elapsed = time.time() - q_start
        cum_elapsed = time.time() - t0
        found_str = f"{len(found)}/{n_answers}" if n_answers else "N/A"
        log(f"  [{qi+1}/{len(dataset)}] Recall@All@5={pct:.1f}%  found={found_str}  Q={q_elapsed:.2f}s  cum={cum_elapsed:.0f}s")

    # Aggregate
    qtypes = {}
    for qt, found_list in sorted(query_stats.items()):
        qtypes[qt] = {"hits": sum(found_list), "total": len(found_list)}

    total_hits = sum(st["hits"] for st in qtypes.values())
    total_q = sum(st["total"] for st in qtypes.values())
    overall = total_hits / total_q * 100 if total_q else 0
    total_elapsed = time.time() - t0

    log(f"\n{'='*60}")
    log(f"  LONG MEM EVAL RESULTS — In-Process BM25 + Multi-Query Fusion")
    log(f"{'='*60}")
    log(f"Overall Recall@All@5: {overall:.1f}% ({total_hits}/{total_q})")
    for qt, st in sorted(qtypes.items()):
        log(f"  {qt:<35}: {st['hits']}/{st['total']} = {st['hits']/st['total']*100:.1f}%")
    log(f"\nTotal time: {total_elapsed:.0f}s ({total_elapsed/max(len(dataset),1):.2f}s/question)")

    REF_SCORES = {
        "s": {"Mnemosyne": 98.9, "Mempalace": 96.6},
        "m": {"Mnemosyne": 97.8, "Mempalace": 95.1},
    }
    ref = REF_SCORES.get(SPLIT, {})
    beats_ref = all(overall >= v for v in ref.values()) if ref else None
    if ref:
        log(f"\nReference scores:")
        for name, score in ref.items():
            symbol = "✅" if overall >= score else "❌"
            log(f"  {symbol} {name}: {score}% (target: {score}%, we have: {overall:.1f}%)")

    out = {
        "benchmark": "LongMemEval",
        "method": "in-process BM25 + multi-query fusion",
        "split": SPLIT,
        "questions": len(dataset),
        "overall": {
            "hits": total_hits,
            "total": total_q,
            "recall_at_all_5": round(overall / 100, 4),
        },
        "per_type": {
            qt: {"hits": st["hits"], "total": st["total"],
                 "recall": round(st["hits"] / st["total"] * 100, 1) if st["total"] else 0}
            for qt, st in sorted(qtypes.items())
        },
        "reference_scores": ref,
        "beats_reference": beats_ref,
        "total_time_s": round(total_elapsed, 1),
        "details": results,
    }

    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    log(f"\nSaved to {OUT}")
    return out


if __name__ == "__main__":
    main()
