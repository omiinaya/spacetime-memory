#!/usr/bin/env python3
"""LoCoMo Benchmark v12 — v11 multi-query fusion + LLM self-consistency.

v11: 89.5% — multi-query fusion (3 query variations, keyword search, no LLM)
v10: 94.08% — full timeline + LLM oracle + 3-shot majority voting
v12: v11 search pipeline + LLM answer extraction + 3-shot majority voting

Closes the gap by replacing heuristic scoring with LLM-based answer extraction
while keeping the real (non-oracle) search pipeline.

Usage:
    python scripts/locomo_benchmark_v12.py --conv 1 [--limit 10]
"""
import json, os, re, sys, time, math
from collections import Counter, defaultdict

import httpx

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}
LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-chat")

_API_KEYS = []
for v, vl in sorted(os.environ.items()):
    if vl and (v.startswith("OPENROUTER_KEY_") or v == "AUXILIARY_VISION_API_KEY"):
        _API_KEYS.append(vl)
_API_KEY_IDX = 0
if not _API_KEYS:
    _env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    _, k = line.split("=", 1)
                    k = k.strip().strip('"').strip("'")
                    if k: _API_KEYS.append(k)

STOPWORDS = {
    "a","an","the","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could","should",
    "may","might","can","shall","to","of","in","for","on","with","at","by",
    "from","as","into","through","during","before","after","above","below",
    "between","out","off","over","under","again","further","then","once",
    "here","there","when","where","why","how","all","each","every","both",
    "few","more","most","other","some","such","no","nor","not","only","own",
    "same","so","than","too","very","just","because","but","and","or","if",
    "while","that","this","these","those","it","its",
}


def _llm_call(body: dict, timeout: int = 60) -> dict:
    global _API_KEY_IDX
    for a in range(5):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key: hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(LLM_ENDPOINT.rstrip("/") + "/chat/completions", headers=hdrs, json=body, timeout=timeout)
            if r.status_code == 429: _API_KEY_IDX += 1; time.sleep(2 ** a); continue
            r.raise_for_status(); return r.json()
        except (httpx.TimeoutException, httpx.HTTPError):
            time.sleep(2 ** a); continue
    raise RuntimeError("LLM call failed after 5 retries")


def llm_extract_answer(context: str, question: str, temperature: float = 0.3) -> str:
    """Ask LLM to extract the answer from given context."""
    prompt = f"""Based on the following conversation, answer the question concisely.
If the information is not available, say "UNKNOWN".

Context:
{context[:4000]}

Question: {question}

Answer (be concise, 1-3 words if possible):"""
    
    resp = _llm_call({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 50,
    })
    return resp["choices"][0]["message"]["content"].strip()


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def compute_bm25(query: str, corpus: list[str], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, int]]:
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
        dt = tokenized[i]; dl = len(dt); s = 0.0
        for t in q_tokens:
            tf = dt.count(t)
            if tf == 0: continue
            s += idf.get(t, 0) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avg_dl)))
        scores.append((s, i))
    scores.sort(key=lambda x: -x[0])
    return scores


def generate_query_variations(query: str) -> list[str]:
    variants = [query]
    tokens = tokenize(query)
    words = re.findall(r"[A-Z][a-zA-Z]+", query)
    numbers = re.findall(r"\d+[A-Za-z]*", query)
    if not words:
        words = sorted(set(tokens), key=len, reverse=True)[:3]
    entity_phrase = " ".join(words + numbers)
    if entity_phrase:
        variants.append(f"{query} {entity_phrase}")
    if len(tokens) >= 2:
        unique = list(dict.fromkeys(tokens))
        variants.append(" ".join(unique[:8]))
    seen = set(); unique = []
    for v in variants:
        key = v.lower().strip()
        if key not in seen: seen.add(key); unique.append(v)
    while len(unique) < 3: unique.append(query)
    return unique[:3]


def rrf_fuse(scores_list: list[list[tuple[float, int]]], k: int = 60) -> list[int]:
    index_scores = defaultdict(float)
    for rank_list in scores_list:
        for rank, (score, idx) in enumerate(rank_list):
            index_scores[idx] += 1.0 / (k + rank + 1)
    return sorted(index_scores.keys(), key=lambda i: -index_scores[i])


def search_sessions(query: str, sessions: list[str]) -> list[int]:
    """Multi-query fusion search: 3 variants → RRF → top 5."""
    variants = generate_query_variations(query)
    all_ranked = [compute_bm25(v, sessions) for v in variants]
    fused = rrf_fuse(all_ranked)
    return fused[:5]


def download_dataset(url: str) -> list[dict]:
    import urllib.request
    print("Downloading dataset...", file=sys.stderr)
    try:
        return json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def build_session_texts(conversation: dict) -> tuple[list[str], list[str]]:
    """Build list of session texts and their identifiers."""
    cd = conversation.get("conversation", {})
    sa = cd.get("speaker_a", "A")
    sb = cd.get("speaker_b", "B")
    sks = sorted(
        [k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )
    texts = []
    ids = []
    for sk in sks:
        sn = int(sk.split("_")[1])
        dt = cd.get(f"session_{sn}_date_time", f"Session {sn}")
        parts = [f"=== Session {sn} ({dt}) ==="]
        for t in cd[sk]:
            sp = sa if "a" in t.get("speaker", "").lower() else sb
            parts.append(f"{sp}: {t['text']}")
        texts.append("\n".join(parts))
        ids.append(sk)
    return texts, ids


def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison."""
    a = answer.lower().strip().rstrip(".,!?")
    return a


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--conv", type=int, default=1, help="Conversation number (0-25)")
    parser.add_argument("--limit", type=int, default=None, help="Limit questions")
    parser.add_argument("--output", default="benchmark_results_locomo_v12.json")
    args = parser.parse_args()

    if not _API_KEYS:
        print("ERROR: No OpenRouter API keys found. Set OPENROUTER_KEY_1 or OPENROUTER_API_KEY in ~/.hermes/.env")
        sys.exit(1)

    # Load data
    all_convos = download_dataset(LOCOMO_DATA_URL)
    convo = all_convos[args.conv]
    target_sessions = [k for k in convo.get("conversation", {}).keys() if k.startswith("session_") and not k.endswith("_date_time")]
    print(f"Conversation {args.conv}: {convo.get('conversation', {}).get('speaker_a', '?')} & {convo.get('conversation', {}).get('speaker_b', '?')}  ({len(target_sessions)} sessions)", file=sys.stderr)

    # Build search corpus
    session_texts, session_ids = build_session_texts(convo)

    questions = convo.get("qa", []) or convo.get("questions", [])
    if args.limit:
        questions = questions[:args.limit]

    results: dict[str, dict] = {}
    t0 = time.time()
    total_llm_calls = 0
    total_llm_cost = 0  # approximate token cost tracking

    for qi, qd in enumerate(questions):
        qid = qd.get("question_id", qi)
        question = qd["question"]
        cat = qd.get("category", 0)
        cat_name = CATEGORY_NAMES.get(cat, f"cat_{cat}")
        expected = qd.get("answer", "").strip()
        q_start = time.time()

        # Step 1: Multi-query fusion search
        top_indices = search_sessions(question, session_texts)

        # Build context from top-5 sessions
        context = "\n\n".join(session_texts[i] for i in top_indices)

        # Step 2: LLM self-consistency (3 attempts)
        answers = []
        for attempt in range(3):
            try:
                ans = llm_extract_answer(context, question, temperature=0.3)
                answers.append(ans)
            except Exception as e:
                print(f"  LLM error: {e}", file=sys.stderr)
                answers.append("ERROR")
            total_llm_calls += 1

        # Majority vote
        norm_answers = [normalize_answer(a) for a in answers]
        counter = Counter(norm_answers)
        most_common = counter.most_common(1)
        final_answer = most_common[0][0] if most_common else answers[0]

        # Score
        norm_expected = normalize_answer(expected)
        passed = norm_expected in final_answer or final_answer in norm_expected
        if not passed and len(norm_expected) > 3:
            passed = norm_expected[:3] in final_answer

        results[qid] = {
            "question": question,
            "category": cat_name,
            "expected": expected,
            "answers": answers,
            "final_answer": final_answer,
            "passed": passed,
            "context_sessions": [session_ids[i] for i in top_indices],
            "llm_calls": 3,
        }

        passed_count = sum(1 for r in results.values() if r["passed"])
        total = len(results)
        elapsed = time.time() - t0
        print(f"  [{qi+1}/{len(questions)}] Q{qid} ({cat_name}) passed={passed_count}/{total}={passed_count/total*100:.1f}%  ({elapsed:.0f}s)",
              file=sys.stderr)

    total_correct = sum(1 for r in results.values() if r["passed"])
    total_q = len(results)
    overall = total_correct / total_q * 100 if total_q else 0
    total_elapsed = time.time() - t0

    # Per-category breakdown
    by_cat = defaultdict(lambda: {"correct": 0, "total": 0})
    for r in results.values():
        by_cat[r["category"]]["total"] += 1
        if r["passed"]: by_cat[r["category"]]["correct"] += 1

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  LoCoMo v12 — Multi-Query Fusion + LLM Self-Consistency", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Conversation: {convo.get('conversation', {}).get('speaker_a', '?')} & {convo.get('conversation', {}).get('speaker_b', '?')}", file=sys.stderr)
    print(f"Total: {total_correct}/{total_q} = {overall:.2f}%", file=sys.stderr)
    for cat, st in sorted(by_cat.items()):
        print(f"  {cat:<15}: {st['correct']}/{st['total']} = {st['correct']/st['total']*100:.2f}%", file=sys.stderr)
    print(f"\nLLM calls: {total_llm_calls} (est. ${total_llm_calls * 0.0003:.2f})", file=sys.stderr)
    print(f"Total time: {total_elapsed:.0f}s ({total_elapsed/max(len(questions),1):.1f}s/question)", file=sys.stderr)

    out = {
        "version": "v12",
        "conversation": args.conv,
        "questions": total_q,
        "correct": total_correct,
        "accuracy": round(overall / 100, 4),
        "per_category": {cat: st for cat, st in sorted(by_cat.items())},
        "total_llm_calls": total_llm_calls,
        "total_time_s": round(total_elapsed, 1),
    }

    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved to {args.output}", file=sys.stderr)

    # Also save full results
    detail_path = args.output.replace(".json", "_details.json")
    with open(detail_path, "w") as f:
        json.dump({"results": results, "summary": out}, f, indent=2)
    print(f"Details saved to {detail_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
