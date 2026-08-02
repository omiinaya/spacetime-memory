#!/usr/bin/env python3
"""Quick test: full-context timeline vs keyword-only search."""
import json, sys, os, time, secrets, urllib.request, re
sys.path.insert(0, 'sdk/python')
import httpx

LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = "deepseek/deepseek-chat"
_API_KEYS = [v for k,v in sorted(os.environ.items()) if k.startswith("OPENROUTER_KEY_") and v]
_API_KEY_IDX = 0

def llm_call(body):
    global _API_KEY_IDX
    for a in range(3):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key: hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(LLM_ENDPOINT.rstrip("/") + "/chat/completions", headers=hdrs, json=body, timeout=30)
            if r.status_code == 429: _API_KEY_IDX += 1; time.sleep(2**a); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            time.sleep(2**a); continue
    return None

# Download data
print("Downloading...")
data = json.loads(urllib.request.urlopen("https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json", timeout=30).read())
conv = data[0]
cd = conv["conversation"]
speaker_a = cd.get("speaker_a", "A")
speaker_b = cd.get("speaker_b", "B")

# Build FULL timeline
session_keys = sorted([k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")], key=lambda x: int(x.split("_")[1]))

timeline_parts = []
for sk in session_keys:
    snum = int(sk.split("_")[1])
    dt_key = f"session_{snum}_date_time"
    dt = cd.get(dt_key, f"Session {snum}")
    timeline_parts.append(f"\n=== Session {snum} ({dt}) ===\n")
    for t in cd[sk]:
        speaker_raw = t.get("speaker", "")
        speaker = speaker_a if "a" in speaker_raw.lower() else speaker_b
        timeline_parts.append(f"{speaker}: {t.get('text','')}")

full_timeline = "\n".join(timeline_parts)
print(f"Timeline: {len(full_timeline)} chars, ~{len(full_timeline)//4} tokens")
print()

# Test first 5 questions
qa = conv.get("qa", [])[:5]
results = []

for i, q in enumerate(qa):
    question = q["question"]
    expected = q["answer"]
    category = q.get("category", 0)
    
    prompt = f"""You have the COMPLETE conversation timeline below. Answer the question based ONLY on this timeline.

TIMELINE:
{full_timeline}

QUESTION: {question}

IMPORTANT: Relative time words like "yesterday", "last week", "last year", "two days ago" are relative to the session date shown in (=== Session N (DATE) ===). Compute absolute dates.

Follow these steps:
1. Find the exact session and turn that contains the answer
2. Identify any relative time words
3. Compute the absolute date if needed
4. Give a concise answer
5. Say "I don't know" only if the timeline does not contain the answer

Answer:"""

    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 250}
    result = llm_call(body)
    answer = result["choices"][0]["message"]["content"] if result else "ERROR"
    
    # Judge
    judge_prompt = f"Question: {question}\nExpected answer: {expected}\nSystem answer: {answer}\n\nIs the system answer semantically correct? Reply Yes or No."
    jbody = {"model": LLM_MODEL, "messages": [{"role": "user", "content": judge_prompt}], "temperature": 0.0, "max_tokens": 50}
    jresult = llm_call(jbody)
    judge_text = (jresult["choices"][0]["message"]["content"] or "No") if jresult else "No"
    is_correct = judge_text.lower().startswith("yes")
    
    results.append({"q": question, "expected": expected, "answer": answer[:150], "correct": is_correct})
    
    status = "OK" if is_correct else "X"
    print(f"  {status} Q{i+1}: {question[:40]} -> {answer[:60]}")

correct = sum(1 for r in results if r["correct"])
print(f"\nAccuracy: {correct}/{len(results)} = {correct/len(results)*100:.0f}%")
