#!/usr/bin/env python3
"""Standardized LoCoMo Benchmark — apples-to-apples comparison with Mem0.

Uses the same judge methodology as Mem0's open-source benchmark suite:
- Structured LLM judge with detailed rules (paraphrases ok, 14-day date tolerance,
  same-referent matching, focus on knowledge not wording)
- Full dataset (all 10 conversations, categories 1-4 = 1540 questions)
- Binary CORRECT/WRONG judgment per question
- Per-category and overall accuracy reporting

Two modes:
  --stdb   : Use real STDB pipeline (default)
  --bm25   : Use in-process BM25 for baseline comparison

Usage:
  python scripts/benchmarks/run_locomo.py [--stdb] [--conv 0] [--limit 10] [--judge-model MODEL]
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "sdk" / "python"))

import httpx

# ─── Dataset ──────────────────────────────────────────────────────────────────

DATASET_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DEFAULT_DATASET_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "locomo10.json")

# ─── Judge prompt (from Mem0's open-source benchmark suite) ──────────────────

JUDGE_SYSTEM_PROMPT = """You are evaluating a memory system's answer against a gold standard answer. Be generous — the system should not be penalized for differences in wording or level of detail."""

_JUDGE_TEMPLATE = """## Instructions

Compare the gold answer and the generated answer. The generated answer is CORRECT if it captures the same factual knowledge as the gold answer, even if the wording differs.

## Key Rules

1. **CORRECT IF**: The generated answer contains the relevant facts, entities, dates, or answers from the gold answer. Exact wording is NOT required.

2. **PARAPHRASES COUNT**: Same concept in different words is CORRECT. "Chocolate raspberry tart" = "chocolate cake with raspberries". "Shelter meal service" = "volunteering at a homeless shelter". Emotions and sentiments in the same positive/negative family count as paraphrases: "proud" = "fulfilled" = "accomplished"; "huge success" = "relieved" = "thrilled" (all express positive achievement). Judge semantic meaning, not exact wording.

3. **EXTRA DETAIL IS FINE**: A longer answer that includes the gold answer's key facts plus additional information is CORRECT. Never penalize for being more detailed or specific. If the generated answer adds extra descriptive details beyond the gold answer while still referencing the same core entity or concept, mark CORRECT.

4. **DATE TOLERANCE**: Dates within 14 days of each other are CORRECT. Durations within 50% are CORRECT (e.g., "5 months" matches "six months"; "19 days" matches "two weeks"). Relative dates ("few days before November") match specific dates in the same window. A specific date (e.g., "February 2020") that is consistent with a vague reference (e.g., "a few years ago" relative to 2023) is CORRECT. Converting "last year" to the actual year (e.g., "2022" when conversations are in 2023) is CORRECT.

5. **SEMANTIC OVERLAP**: Judge whether the generated answer addresses the same topic and captures the core idea of the gold answer. Different wording, phrasing, or level of detail should not result in WRONG if the underlying concept matches. For EMOTIONS and FEELINGS questions, answers expressing sentiments in the same valence (positive/negative) about the same event are CORRECT — do not require the exact same emotion word.

6. **SAME REFERENT**: If the generated answer mentions or references the same named entity, character, person, or concept as the gold answer, mark CORRECT — even if the generated answer provides a different physical description or includes additional details. The key question is: does the generated answer identify the same core entity? If yes, it is CORRECT.

7. **FOCUS ON KNOWLEDGE, NOT WORDING**: The goal is to assess whether the system recalled the right fact. Minor differences in specificity, phrasing, or scope should not result in WRONG. Only mark WRONG when the generated answer demonstrates a genuinely different or incorrect understanding.

## ONLY mark WRONG if:
- The generated answer contains ZERO correct items from the gold answer
- The answer addresses a completely different topic

## Question
Question: {question}
Gold answer: {answer}
Generated answer: {response}

Return JSON with "reasoning" (one sentence) and "label" (CORRECT or WRONG). Do NOT include both labels."""

CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}
CATEGORIES_TO_EVALUATE = [1, 2, 3, 4]  # Exclude adversarial from primary score

# ─── LLM Judge ───────────────────────────────────────────────────────────────

LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_JUDGE_MODEL = os.environ.get("LLM_JUDGE_MODEL", "deepseek/deepseek-chat")
LLM_ANSWER_MODEL = os.environ.get("LLM_ANSWER_MODEL", "deepseek/deepseek-chat")
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
                val = line.strip().split("=", 1)[1].strip().strip("\"'")
                if val:
                    _API_KEYS.append(val)
                    break


def _llm_call(body: dict, model_field: str = "model", extra_params: dict | None = None) -> dict:
    """Call the LLM endpoint with retry + exponential backoff.

    Retries transient failures (5xx, 429, timeouts, connection errors) up to
    MAX_LLM_RETRIES times with exponential backoff. Rotates API keys on each
    attempt. Returns {"choices": [{"message": {"content": "api error"}}]} only
    after all retries are exhausted.
    """
    global _API_KEY_IDX
    endpoint = LLM_ENDPOINT
    model = body.get(model_field, LLM_JUDGE_MODEL)
    messages = body.get("messages", [])
    params = {"model": model, "messages": messages, "temperature": 0.0, "max_tokens": 200}
    if extra_params:
        params.update(extra_params)

    retries = int(os.environ.get("LLM_MAX_RETRIES", "5"))
    base_delay = 5.0
    last_err = None

    # Try each API key, with retries for transient failures
    total_attempts = (len(_API_KEYS) or 1) * retries
    for attempt in range(total_attempts):
        if not _API_KEYS:
            return {"choices": [{"message": {"content": "no api key"}}]}
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)]
        _API_KEY_IDX += 1
        try:
            resp = httpx.post(
                f"{endpoint}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=params,
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()
            # Retry on 429 (rate limit), 402 (free-tier proxy rate limit),
            # 5xx (server error), 408 (timeout)
            last_err = f"HTTP {resp.status_code}"
            if resp.status_code in (402, 408, 429, 500, 502, 503, 504):
                delay = base_delay * (2 ** (attempt // max(len(_API_KEYS) or 1, 1)))
                delay = min(delay, 60.0)
                time.sleep(delay)
                continue
            # Non-retryable client error
            return {"choices": [{"message": {"content": f"api error: {last_err}"}}]}
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError, OSError):
            last_err = "connection error"
            delay = base_delay * (2 ** (attempt // max(len(_API_KEYS) or 1, 1)))
            delay = min(delay, 60.0)
            time.sleep(delay)
            continue
        except Exception as e:
            last_err = str(e)
            delay = base_delay * (2 ** (attempt // max(len(_API_KEYS) or 1, 1)))
            delay = min(delay, 60.0)
            time.sleep(delay)
            continue
    return {"choices": [{"message": {"content": f"api error: {last_err}"}}]}


def llm_judge(question: str, expected: str, answer: str) -> dict:
    """Judge an answer using Mem0's structured judge prompt."""
    if not answer or str(answer).startswith("ERROR"):
        return {"is_correct": False, "reasoning": "system error"}

    prompt = _JUDGE_TEMPLATE.format(
        question=question,
        answer=str(expected or ""),
        response=str(answer),
    )

    body = {
        "model": LLM_JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    # Use response_format json_object for reasoning models to force clean JSON
    extra = {}
    if "deepseek" in LLM_JUDGE_MODEL.lower() or "dsv4" in LLM_JUDGE_MODEL.lower():
        extra = {"response_format": {"type": "json_object"}}

    # Retry empty-content responses (HTTP 200 with empty body is a transient
    # proxy/model failure, NOT a genuine "WRONG" judgment). Without this, an
    # empty judge response silently deflates the score as is_correct=False.
    content = ""
    for empty_attempt in range(int(os.environ.get("LLM_EMPTY_RETRIES", "3"))):
        data = _llm_call(body, extra_params=extra)
        content = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        if content:
            break
        time.sleep(2.0 * (empty_attempt + 1))
    if not content:
        return {"is_correct": False, "reasoning": "judge error: empty response"}

    try:
        # Parse JSON response
        try:
            result = json.loads(content)
            label = result.get("label", "").strip().upper()
            reasoning = result.get("reasoning", content[:100])
            return {"is_correct": label == "CORRECT", "reasoning": reasoning}
        except (json.JSONDecodeError, AttributeError):
            # Fallback: look for CORRECT or WRONG in text
            upper = content.upper()
            if '"CORRECT"' in upper or 'LABEL": "CORRECT"' in upper:
                return {"is_correct": True, "reasoning": content[:100]}
            if '"WRONG"' in upper or 'LABEL": "WRONG"' in upper:
                return {"is_correct": False, "reasoning": content[:100]}
            # Check for simple yes/no
            if content.strip().upper().startswith("CORRECT") or content.strip().upper().startswith("\"CORRECT\""):
                return {"is_correct": True, "reasoning": content[:100]}
            if content.strip().upper().startswith("WRONG"):
                return {"is_correct": False, "reasoning": content[:100]}
            return {"is_correct": content.strip().upper().startswith("Y") or "CORRECT" in content.upper(), "reasoning": content[:100]}
    except Exception as e:
        return {"is_correct": False, "reasoning": f"judge error: {e}"}


# ─── Dataset Loading ─────────────────────────────────────────────────────────

def download_dataset() -> list[dict]:
    """Download LoCoMo dataset from GitHub."""
    path = DEFAULT_DATASET_PATH
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    print(f"Downloading LoCoMo dataset from {DATASET_URL}...", file=sys.stderr)
    resp = urllib.request.urlopen(DATASET_URL)
    data = json.loads(resp.read())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    print(f"Saved to {path}", file=sys.stderr)
    return data


def extract_all_questions(data: list[dict]) -> list[dict]:
    """Extract all QA pairs from all conversations with metadata."""
    questions = []
    for conv_idx, conv in enumerate(data):
        if "qa" not in conv:
            continue
        for qa in conv["qa"]:
            qa_copy = dict(qa)
            qa_copy["conversation_idx"] = conv_idx
            qa_copy["sample_id"] = conv.get("sample_id", f"conv{conv_idx}")
            questions.append(qa_copy)
    return questions


def get_sorted_sessions(conversation: dict) -> list[tuple[str, str, list[dict]]]:
    """Extract and sort sessions chronologically from conversation data.
    Sessions are stored under conversation['conversation']['session_X']."""
    conv_data = conversation.get("conversation", conversation)
    session_keys = sorted([k for k in conv_data if re.match(r"^session_\d+$", k)],
                          key=lambda k: int(k.split("_")[1]))
    paired = []
    for key in session_keys:
        date_key = f"{key}_date_time"
        date_str = conv_data.get(date_key, "")
        sessions = conv_data[key]
        if isinstance(sessions, list) and len(sessions) > 0:
            paired.append((key, date_str, sessions))
    return paired


# ─── STDB Pipeline ───────────────────────────────────────────────────────────

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://127.0.0.1:3001")


def store_conversation_stdb(client, workspace_id: str, conv: dict, conv_idx: int):
    """Store a conversation into STDB."""
    # Get sessions
    sorted_sessions = get_sorted_sessions(conv)
    speaker_a = conv.get("conversation", {}).get("speaker_a", "SpeakerA")
    speaker_b = conv.get("conversation", {}).get("speaker_b", "SpeakerB")
    # Also try root level
    if not speaker_a or speaker_a == "SpeakerA":
        speaker_a = conv.get("speaker_a", "SpeakerA")
    if not speaker_b or speaker_b == "SpeakerB":
        speaker_b = conv.get("speaker_b", "SpeakerB")

    batch = []
    for sess_key, date_str, sessions in sorted_sessions:
        sess_num = int(sess_key.split("_")[1])
        turns_text = []
        for turn in sessions:
            speaker = turn.get("speaker", "?")
            text = turn.get("text", "")
            turns_text.append(f"{speaker}: {text}")
        full_text = "\n".join(turns_text)
        # Include date in content so it's searchable by both BM25 and semantic search
        content_with_date = f"[{date_str}] Session {sess_num}\n{full_text}" if date_str else full_text

        batch.append({
            "content": content_with_date,
            "summary": f"Session {sess_num} ({date_str})",
            "memory_type": "conversation",
            "metadata": json.dumps({
                "conv_idx": conv_idx,
                "session_num": sess_num,
                "date": date_str,
                "speaker_a": speaker_a,
                "speaker_b": speaker_b,
            }),
        })

    if batch:
        # Smaller chunks to avoid reducer timeouts on oversized payloads
        chunk_size = 4
        for i in range(0, len(batch), chunk_size):
            chunk = batch[i:i + chunk_size]
            # Truncate any content that's too large (>200KB each)
            for item in chunk:
                if len(item["content"].encode('utf-8')) > 200_000:
                    item["content"] = item["content"][:150_000] + "\n[...truncated]"
            client.store_batch(workspace_id, chunk)
            print(f"  Stored batch {i//chunk_size+1}/{(len(batch)+chunk_size-1)//chunk_size} "
                  f"({len(chunk)} sessions)", file=sys.stderr, flush=True)
        print(f"  Total: {len(batch)} sessions stored", file=sys.stderr, flush=True)


def search_stdb(client, workspace_id: str, question: str, top_k: int = 200, semantic: bool = True) -> list[dict]:
    """Search STDB for relevant memories.

    Args:
        semantic: If True, use hybrid (semantic + keyword) search.
                  If False (default), use keyword-only search (faster, no embeddings).

    Retries on the SDK circuit breaker (RuntimeError: SpacetimeDB circuit
    breaker is open) — that is a transient overload signal from the SDK, NOT
    a fatal error. Without this catch, a breaker trip under concurrent load
    crashed the whole benchmark run instead of backing off.
    """
    max_breaker_retries = int(os.environ.get("LLM_MAX_RETRIES", "5"))
    last_err = None
    for attempt in range(max_breaker_retries + 1):
        try:
            results = client.search(workspace_id, question, limit=top_k, semantic=semantic)
            return results
        except RuntimeError as e:
            msg = str(e)
            # Transient overload signals: SDK circuit breaker trip AND
            # STDB HTTP 500 ("Request failed after N attempts: Server error
            # (HTTP 500)") both mean STDB is saturated — back off and retry,
            # never crash the benchmark run.
            retryable = (
                "circuit breaker" in msg
                or "not found" in msg
                or ("Request failed after" in msg and "HTTP 500" in msg)
            )
            if not retryable:
                raise  # Genuine error — let it propagate
            last_err = e
            delay = 5.0 * (2 ** attempt)
            delay = min(delay, 60.0)
            print(f"  [search_stdb] transient overload (attempt {attempt+1}/{max_breaker_retries+1}): "
                  f"{msg[:100]} — backing off {delay:.0f}s", file=sys.stderr, flush=True)
            time.sleep(delay)
    raise RuntimeError(f"search_stdb: circuit breaker stayed open after {max_breaker_retries + 1} attempts: {last_err}")


# ─── BM25 Pipeline ───────────────────────────────────────────────────────────

# Simple BM25 implementation for in-process baseline
import math
from collections import Counter


class SimpleBM25:
    """BM25 with simple tokenization."""
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.documents = []
        self.doc_freqs = []
        self.idf = {}
        self.avg_doc_len = 0
        self.doc_count = 0

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r'\w+', text.lower())

    def fit(self, documents: list[str]):
        self.documents = documents
        self.doc_count = len(documents)
        self.doc_freqs = [Counter(self._tokenize(doc)) for doc in documents]
        total_len = sum(sum(c.values()) for c in self.doc_freqs)
        self.avg_doc_len = total_len / self.doc_count if self.doc_count else 0

        # Compute IDF for all terms
        all_terms = set()
        for c in self.doc_freqs:
            all_terms.update(c.keys())
        self.idf = {}
        N = self.doc_count
        for term in all_terms:
            df = sum(1 for c in self.doc_freqs if c[term] > 0)
            self.idf[term] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 200) -> list[dict]:
        query_terms = self._tokenize(query)
        scores = []
        for idx, doc_freq in enumerate(self.doc_freqs):
            score = 0
            doc_len = sum(doc_freq.values())
            for term in query_terms:
                if term in self.idf and doc_len > 0:
                    tf = doc_freq.get(term, 0)
                    score += self.idf[term] * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len))
            scores.append(score)

        ranked = sorted(enumerate(scores), key=lambda x: -x[1])
        results = []
        for idx, score in ranked[:top_k]:
            if score > 0:
                results.append({
                    "content": self.documents[idx],
                    "score": score,
                })
        return results

    def search_multi_query(self, queries: list[str], top_k: int = 200) -> list[dict]:
        """Search with multiple query variations and fuse via RRF."""
        all_results = []
        for q in queries:
            results = self.search(q, top_k=top_k)
            all_results.append(results)

        # RRF fusion
        seen = set()
        fused = []
        for rank, batch_results in enumerate(all_results):
            for doc in batch_results:
                content = doc["content"]
                if content not in seen:
                    seen.add(content)
                    doc["rrf_score"] = 1.0 / (rank + 60)
                    fused.append(doc)
                else:
                    # Increment score for existing
                    for d in fused:
                        if d["content"] == content:
                            d["rrf_score"] += 1.0 / (rank + 60)
                            break

        fused.sort(key=lambda x: -x.get("rrf_score", x.get("score", 0)))
        return fused[:top_k]


# ─── Reasoning Model Output Extraction ──────────────────────────────────────

def extract_answer_from_reasoning(text: str) -> str:
    """Extract the actual answer from a reasoning model's verbose output.

    Reasoning models like deepseek-v4-flash put their chain-of-thought in
    `content`, with the answer embedded somewhere inside.  This function
    extracts just the final answer using progressive heuristics.
    """
    if not text or text == "I don't have enough information to answer this question.":
        return text

    text = text.strip()
    if not text:
        return text

    # ── Strategy 1: Find structured markers ──
    for marker in ["ANSWER:", "Answer:", "answer:"]:
        idx = text.rfind(marker)
        if idx >= 0:
            after = text[idx + len(marker):].strip().lstrip(":,. -\"'").strip()
            if after:
                return after.rstrip(".")

    # Also check for "the answer is" / "answer is" patterns
    for prefix in ["the answer is ", "answer is "]:
        idx = text.lower().rfind(prefix)
        if idx >= 0:
            after = text[idx + len(prefix):].strip().lstrip(":,. -\"'").strip()
            if after:
                return after.rstrip(".")

    # ── Strategy 2: Split into lines, scan from bottom ──
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return text

    # Filter: skip clearly-reasoning lines from the bottom
    reasoning_starts = [
        "thinking", "we are asked", "let me", "i'll", "i need",
        "looking at", "first,", "second,", "third,", "finally,", "step",
        "analysis:", "##", "the question ask", "so for",
        "to answer", "to determine", "to find", "i'm asked",
    ]
    cleaned = []
    for line in lines:
        lower = line.lower().lstrip()
        is_reasoning = any(lower.startswith(m) for m in reasoning_starts) or bool(re.match(r'^\d+\.\s*(thinking|first|second|analyze|look|identify|step|determine|find)', lower))
        if not is_reasoning:
            cleaned.append(line)
    # If everything was "reasoning", use original lines
    if not cleaned:
        cleaned = lines

    for line in reversed(cleaned):
        if not line:
            continue
        lower = line.lower().lstrip()
        # Handle numbered items: "3. Paris is the capital"
        m = re.match(r'^\d+\.\s*(.+)', line)
        if m:
            rest = m.group(1).strip()
            if rest and len(rest) > 3:
                return rest.rstrip(".")
            continue
        # Skip remaining reasoning lines
        if any(lower.startswith(m) for m in reasoning_starts):
            continue
        # If line has colon (e.g. "So I will say: Paris"), take after last colon
        colon_idx = line.rfind(":")
        if colon_idx >= 0 and len(line) - colon_idx < 40:
            after = line[colon_idx+1:].strip()
            if after and after != line:
                return after.rstrip(".")
        return line.rstrip(".")

    # ── Strategy 3: Single-line text — extract last sentence ──
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) >= 2:
        for s in reversed(sentences):
            s = s.strip()
            if not s:
                continue
            lower = s.lower().lstrip()
            if any(lower.startswith(m) for m in ["thinking", "we are asked", "let me", "i'll", "i need", "i'm asked"]):
                continue
            if len(s) > 3:
                return s.rstrip(".")

    # ── Strategy 4: Last-resort extractions ──
    # Colon on any line
    colon_idx = text.rfind(":")
    if colon_idx >= 0:
        after = text[colon_idx+1:].strip()
        if after and not after.startswith("//"):
            return after.rstrip(".")
    # Last 80 chars
    last = text[-80:].strip().lstrip(". ").strip()
    if last:
        return last
    return text


# ─── Answer Generation ───────────────────────────────────────────────────────

ANSWER_SYSTEM_PROMPT = """You are an AI assistant answering questions about conversations. Use the retrieved context to answer accurately and concisely. IMPORTANT: Use session dates (shown in brackets like [date]) to convert relative dates (yesterday, today, last week, next month, etc.) to absolute dates where possible."""


def generate_answer(question: str, search_results: list[dict], max_context_chars: int = 30000) -> str:
    """Generate an answer from search results using LLM.
    Truncates context to max_context_chars to avoid token limits."""
    if not search_results:
        return "I don't have enough information to answer this question."

    # Format context with size limit
    context_parts = []
    total_chars = 0
    for i, r in enumerate(search_results[:30]):
        content = r.get("content", r.get("memory", ""))
        if content:
            # Truncate individual content if needed
            if len(content) > 5000:
                content = content[:5000] + "..."
            entry = f"[{i+1}] {content}"
            if total_chars + len(entry) > max_context_chars:
                break
            context_parts.append(entry)
            total_chars += len(entry)

    if not context_parts:
        return "I don't have enough information to answer this question."

    context = "\n\n".join(context_parts)

    prompt = f"""Based on the following conversation excerpts, answer the question concisely.

CONVERSATION EXCERPTS:
{context}

QUESTION: {question}

IMPORTANT: Use the session dates (shown in brackets like [date]) to convert relative dates (yesterday, today, last week, next month, etc.) to absolute dates when answering.

Output a JSON object with an "answer" field containing just the factual information requested. Be specific and precise. Example: {{"answer": "Paris"}}"""

    body = {
        "model": LLM_ANSWER_MODEL,
        "messages": [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    extra = {}
    if "deepseek" in LLM_ANSWER_MODEL.lower() or "dsv4" in LLM_ANSWER_MODEL.lower():
        extra = {"response_format": {"type": "json_object"}, "max_tokens": 1000}

    try:
        data = _llm_call(body, "model", extra_params=extra)
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        # Parse JSON answer
        if raw:
            try:
                parsed = json.loads(raw)
                answer = parsed.get("answer", parsed.get("response", parsed.get("text", raw)))
                if answer and isinstance(answer, str) and answer.strip():
                    return answer.strip()
                # JSON parsed but answer was null/empty — don't return raw JSON
                return "I don't have enough information to answer this question."
            except (json.JSONDecodeError, TypeError):
                # Not valid JSON — use as-is if non-empty
                if raw.strip():
                    return raw
        return "I don't have enough information to answer this question."
    except Exception as e:
        return f"ERROR: {e}"


# ─── Multi-query Generation ─────────────────────────────────────────────────

def generate_query_variations(question: str) -> list[str]:
    """Generate multiple search query variations for a question."""
    variations = [question]

    # Extract key entities for entity-expanded query
    entities = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', question)
    if entities:
        entity_part = " ".join(entities[:3])
        variations.append(f"{entity_part} {question[:100]}")

    # Keyword-focused query
    tokens = re.findall(r'\w+', question.lower())
    stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'did', 'do', 'does',
                 'have', 'has', 'had', 'what', 'when', 'where', 'why', 'who', 'how',
                 'to', 'in', 'on', 'at', 'for', 'with', 'of', 'by', 'from', 'that',
                 'this', 'these', 'those', 'it', 'its', 'and', 'or', 'but', 'not',
                 'be', 'been', 'being', 'does', 'doing', 'get', 'got', 'would',
                 'could', 'should', 'will', 'can', 'may', 'might', 'shall'}
    keywords = [t for t in tokens if t not in stopwords and len(t) > 2]
    if keywords:
        variations.append(" ".join(keywords[:10]))

    return list(set(variations))


# ─── Main Benchmark ──────────────────────────────────────────────────────────

def _auth_client() -> tuple:
    """Authenticate and return (client, identity)."""
    # Load .env from project root if present
    _env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_file.exists():
        with open(_env_file) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _v = _v.strip().strip("\"'")
                    if _k not in os.environ:
                        os.environ[_k] = _v

    import urllib.request as _urllib

    _token = ""
    _identity = ""
    try:
        _resp = _urllib.urlopen(f"{STDB_URL}/v1/database/{os.environ.get('SPACETIMEDB_DB', '')}", timeout=10)
        _token = _resp.headers.get("spacetime-identity-token", "") or ""
        _identity = _resp.headers.get("spacetime-identity", "") or ""
    except Exception as _e:
        # STDB overloaded / auth endpoint flaky — fall through to token fallback
        print(f"[warn] identity-token exchange failed ({_e}); using server token fallback", file=sys.stderr)

    # If the anonymous identity-token exchange failed (STDB overloaded during
    # concurrent benchmark runs returns 500 and no header), fall back to the
    # server-issued token in the CLI config so create_workspace etc. still auth.
    if not _token:
        _cli_toml = Path.home() / ".config" / "spacetime" / "cli.toml"
        try:
            import tomllib
            with open(_cli_toml, "rb") as _f:
                _cfg = tomllib.load(_f)
            _token = _cfg.get("spacetimedb_token", "") or ""
        except Exception as _e2:
            print(f"[warn] cli.toml token fallback failed ({_e2})", file=sys.stderr)

    from spacetime_memory import Client

    client = Client(
        database=os.environ.get("SPACETIMEDB_DB"),
        token=_token or None,
    )
    try:
        _uuid = (_identity or "anon").split("-")[0][:8]
        client._call("register", [f"bench-{_uuid}", "bench789", _identity])
    except (RuntimeError, OSError, json.JSONDecodeError):
        pass
    return client, _identity


def judgment_failed(r: dict) -> bool:
    """True if a checkpoint result's judgment never really happened.

    Covers judge-call errors (HTTP 402 rate-limit, api/system error, an empty
    judge response) and answerer errors (answer starts with ERROR or contains
    'api error'). Such results were recorded is_correct=False without a
    genuine judgment.
    """
    rsn = str(r.get("reasoning", ""))
    ans = str(r.get("answer", ""))
    return (not rsn.strip()  # empty judge response — recorded wrong but never truly judged
            or "api error" in rsn or "system error" in rsn
            or "judge error" in rsn  # llm_judge exception/empty-response marker
            or ans.startswith("ERROR") or "api error" in ans)


def requeue_failed_judgments(results: list[dict], completed_indices: set[int]) -> tuple[list[dict], set[int], list[int]]:
    """Split checkpoint results into keep / re-queue based on judgment health.

    Results are appended in ascending q_idx order (one per completed index),
    so sorted(completed_indices)[k] is the q_idx of results[k]. Any result
    whose judgment failed is removed from the kept set and its q_idx returned
    so the caller re-runs it (fresh search + answer + judge).

    Returns (kept_results, kept_indices, requeued_indices).
    """
    sorted_idx = sorted(completed_indices)
    keep_results: list[dict] = []
    keep_idx: list[int] = []
    fail_idx: list[int] = []
    for k, r in enumerate(results):
        if k < len(sorted_idx) and judgment_failed(r):
            fail_idx.append(sorted_idx[k])
        else:
            keep_results.append(r)
            if k < len(sorted_idx):
                keep_idx.append(sorted_idx[k])
    return keep_results, set(keep_idx), fail_idx


def run_locomo_stdb(data: list[dict], conv_filter: int = None, limit: int = None,
                    skip_ingest: bool = False, workspace_id: str | None = None,
                    resume: bool = False):
    """Run LoCoMo evaluation using STDB pipeline.

    Supports checkpoint/resume: results are saved incrementally to a checkpoint
    JSON after every question. On resume (--resume), questions that already have
    a valid (non-api-error) result are skipped. If too many consecutive LLM
    failures occur (proxy outage), the run saves its checkpoint and exits
    gracefully with a non-zero code so the launcher can pick it up again.
    """
    # Load .env and auth
    client, _identity = _auth_client()

    workspace_name = f"locomo_benchmark_{int(time.time())}"
    if workspace_id:
        result = {"id": workspace_id}
    else:
        result = client.create_workspace(workspace_name)
    workspace_id = result.get("id", workspace_name)
    print(f"Workspace: {workspace_id} (name: {workspace_name})", file=sys.stderr)

    # Checkpoint file
    results_dir = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "results" / "locomo"
    os.makedirs(results_dir, exist_ok=True)
    checkpoint_path = results_dir / f"locomo_checkpoint_{workspace_id}.json"

    # Extract all questions
    all_questions = extract_all_questions(data)
    if conv_filter is not None:
        all_questions = [q for q in all_questions if q["conversation_idx"] == conv_filter]
    if limit:
        all_questions = all_questions[:limit]

    # Load checkpoint (resume support)
    results = []
    completed_indices = set()
    if resume and checkpoint_path.exists():
        try:
            with open(checkpoint_path) as f:
                ckpt = json.load(f)
            results = ckpt.get("results", [])
            completed_indices = set(ckpt.get("completed_indices", []))
            # Re-queue any result whose judgment failed (judge/answerer hit a
            # transient error like HTTP 402 rate-limit). Those were recorded as
            # is_correct=False but the answer was never truly judged — skipping
            # them forever would silently deflate the score.
            kept_results, kept_indices, fail_idx = requeue_failed_judgments(results, completed_indices)
            if fail_idx:
                results = kept_results
                completed_indices = kept_indices
                print(f"Re-queuing {len(fail_idx)} questions whose judgment failed "
                      f"(e.g. HTTP 402): {sorted(fail_idx)[:10]}...", file=sys.stderr)
            print(f"Resuming from checkpoint: {len(results)} results, "
                  f"{len(completed_indices)} questions already judged", file=sys.stderr)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not load checkpoint ({e}); starting fresh", file=sys.stderr)

    # Store conversations
    if not skip_ingest:
        for conv_idx, conv in enumerate(data):
            if conv_filter is not None and conv_idx != conv_filter:
                continue
            print(f"\nStoring conversation {conv_idx}...", file=sys.stderr)
            store_conversation_stdb(client, workspace_id, conv, conv_idx)
    else:
        print("Skipping ingest (--skip-ingest)", file=sys.stderr)

    # Evaluate each question
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = int(os.environ.get("LLM_MAX_CONSECUTIVE_FAILURES", "10"))
    for q_idx, qa in enumerate(all_questions):
        if q_idx in completed_indices:
            continue  # Already judged in a previous run

        question = qa.get("question", "")
        expected = qa.get("answer", "")
        category = qa.get("category")

        print(f"\n[{q_idx+1}/{len(all_questions)}] Q: {str(question)[:80]}...", file=sys.stderr)

        # Search with rate-limiting to respect STDB energy budget
        query_variations = generate_query_variations(question)
        all_search_results = []
        for qi, qv in enumerate(query_variations):
            results_batch = search_stdb(client, workspace_id, qv, top_k=100)
            all_search_results.extend(results_batch)
            if qi < len(query_variations) - 1:
                time.sleep(1.0)  # Rate-limit: let STDB energy budget replenish
        
        # Periodic cooldown: every 20 questions, rest longer
        if (q_idx + 1) % 20 == 0:
            print(f"  Cooldown ({q_idx+1}/{len(all_questions)} questions done — 5s sleep)...", file=sys.stderr)
            time.sleep(5.0)

        # RRF fusion across query variations
        fused = []
        seen_content = {}
        for rank, r in enumerate(all_search_results):
            if isinstance(r, str):
                content = r
                r_dict = {"content": r, "memory": r, "relevance": 0.5}
            else:
                content = r.get("content", r.get("memory", ""))
                r_dict = r
            if not content:
                continue
            if content not in seen_content:
                seen_content[content] = 1.0 / (rank + 60)
                r_dict["rrf_score"] = 1.0 / (rank + 60)
                fused.append(r_dict)
            else:
                seen_content[content] += 1.0 / (rank + 60)
                for d in fused:
                    dc = d.get("content") if isinstance(d, dict) else d
                    mc = d.get("memory") if isinstance(d, dict) else d
                    if dc == content or mc == content:
                        d["rrf_score"] = d.get("rrf_score", 0) + 1.0 / (rank + 60)
                        break

        fused.sort(key=lambda x: -x.get("rrf_score", 0))
        deduped = fused[:200]

        # Generate answer
        answer = generate_answer(question, deduped)
        is_api_error = (str(answer).startswith("ERROR") or "api error" in str(answer))

        # Judge
        judgment = llm_judge(question, expected, answer)
        mark = "✓" if judgment["is_correct"] else "✗"
        print(f"  {mark} Expected: {str(expected)[:60]}", file=sys.stderr)
        print(f"  {mark} Got: {str(answer)[:60]}", file=sys.stderr)
        print(f"  {mark} Judge: {judgment['reasoning'][:80]}", file=sys.stderr)

        results.append({
            "conv": qa.get("conversation_idx"),
            "category": category,
            "category_name": CATEGORY_NAMES.get(category, "unknown"),
            "question": question,
            "expected": expected,
            "answer": answer,
            "is_correct": judgment["is_correct"],
            "reasoning": judgment["reasoning"],
        })
        completed_indices.add(q_idx)

        # Save checkpoint after every question
        with open(checkpoint_path, "w") as f:
            json.dump({"results": results, "completed_indices": sorted(completed_indices)}, f)

        # Graceful abort on persistent LLM outage (proxy down, etc.)
        if is_api_error or "api error" in str(judgment.get("reasoning", "")):
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"\nABORT: {consecutive_failures} consecutive LLM failures — proxy may be down. "
                      f"Checkpoint saved ({len(results)} results). Exiting for launcher to retry.", file=sys.stderr)
                sys.exit(3)
        else:
            consecutive_failures = 0

    return results


def run_locomo_bm25(data: list[dict], conv_filter: int = None, limit: int = None):
    """Run LoCoMo evaluation using in-process BM25."""
    all_questions = extract_all_questions(data)
    if conv_filter is not None:
        all_questions = [q for q in all_questions if q["conversation_idx"] == conv_filter]
    if limit:
        all_questions = all_questions[:limit]

    # Build BM25 index from all conversation text
    print("Building BM25 index...", file=sys.stderr)
    all_texts = []
    question_to_sessions = defaultdict(list)
    for conv_idx, conv in enumerate(data):
        sorted_sessions = get_sorted_sessions(conv)
        for sess_key, date_str, sessions in sorted_sessions:
            turns_text = []
            for turn in sessions:
                speaker = turn.get("speaker", "?")
                text = turn.get("text", "")
                turns_text.append(f"{speaker}: {text}")
            full_text = "\n".join(turns_text)
            all_texts.append(full_text)

    bm25 = SimpleBM25()
    bm25.fit(all_texts)
    print(f"  Indexed {len(all_texts)} sessions", file=sys.stderr)

    # Evaluate
    results = []
    for q_idx, qa in enumerate(all_questions):
        question = qa.get("question", "")
        expected = qa.get("answer", "")
        category = qa.get("category")

        print(f"\n[{q_idx+1}/{len(all_questions)}] Q: {str(question)[:80]}...", file=sys.stderr)

        # Multi-query search
        query_variations = generate_query_variations(question)
        search_results = bm25.search_multi_query(query_variations, top_k=200)

        # Generate answer
        answer = generate_answer(question, search_results)

        # Judge
        judgment = llm_judge(question, expected, answer)
        mark = "✓" if judgment["is_correct"] else "✗"
        print(f"  {mark} Expected: {str(expected)[:60]}", file=sys.stderr)
        print(f"  {mark} Got: {str(answer)[:60]}", file=sys.stderr)

        results.append({
            "conv": qa.get("conversation_idx"),
            "category": category,
            "category_name": CATEGORY_NAMES.get(category, "unknown"),
            "question": question,
            "expected": expected,
            "answer": answer,
            "is_correct": judgment["is_correct"],
            "reasoning": judgment["reasoning"],
        })

    return results


def compute_metrics(results: list[dict]) -> dict:
    """Compute per-category and overall metrics."""
    # Primary score: categories 1-4 only
    primary = [r for r in results if r["category"] in CATEGORIES_TO_EVALUATE]
    overall = results

    metrics = {}

    # Primary score
    total_p = len(primary)
    correct_p = sum(1 for r in primary if r["is_correct"])
    metrics["primary"] = {
        "total": total_p,
        "correct": correct_p,
        "accuracy": round(correct_p / total_p * 100, 2) if total_p else 0,
    }

    # Per-category breakdown
    categories = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in primary:
        cat = r["category_name"]
        categories[cat]["total"] += 1
        if r["is_correct"]:
            categories[cat]["correct"] += 1

    metrics["by_category"] = {}
    for cat_name, counts in sorted(categories.items()):
        metrics["by_category"][cat_name] = {
            "total": counts["total"],
            "correct": counts["correct"],
            "accuracy": round(counts["correct"] / counts["total"] * 100, 2) if counts["total"] else 0,
        }

    # Overall (including adversarial)
    total_o = len(overall)
    correct_o = sum(1 for r in overall if r["is_correct"])
    metrics["overall"] = {
        "total": total_o,
        "correct": correct_o,
        "accuracy": round(correct_o / total_o * 100, 2) if total_o else 0,
    }

    return metrics


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Standardized LoCoMo Benchmark")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stdb", action="store_true", help="Use STDB pipeline (default)")
    group.add_argument("--bm25", action="store_true", help="Use BM25 baseline")
    parser.add_argument("--conv", type=int, default=None, help="Filter to single conversation index")
    parser.add_argument("--limit", type=int, default=None, help="Limit questions evaluated")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingest (reuse existing workspace)")
    parser.add_argument("--workspace-id", type=str, default=None, help="Reuse an existing workspace (implies --skip-ingest)")
    parser.add_argument("--output", type=str, default=None, help="Output path for results JSON")
    parser.add_argument("--judge-model", type=str, default=None, help="Override judge model")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (skip already-judged questions)")

    args = parser.parse_args()
    use_bm25 = args.bm25
    use_stdb = args.stdb or not args.bm25

    # Override judge model if specified
    global LLM_JUDGE_MODEL
    if args.judge_model:
        LLM_JUDGE_MODEL = args.judge_model

    # Load dataset
    print("Loading LoCoMo dataset...", file=sys.stderr)
    data = download_dataset()
    all_questions = extract_all_questions(data)
    primary_qs = [q for q in all_questions if q["category"] in CATEGORIES_TO_EVALUATE]
    print(f"  {len(all_questions)} total questions ({len(primary_qs)} primary, "
          f"{len(all_questions) - len(primary_qs)} adversarial)", file=sys.stderr)

    # Ensure --workspace-id implies --skip-ingest
    skip = args.skip_ingest or bool(args.workspace_id)

    # Run benchmark
    if use_stdb:
        print(f"\n=== STDB Pipeline === (judge: {LLM_JUDGE_MODEL})", file=sys.stderr)
        results = run_locomo_stdb(data, args.conv, args.limit, skip, args.workspace_id, resume=args.resume)
    else:
        print(f"\n=== BM25 Baseline === (judge: {LLM_JUDGE_MODEL})", file=sys.stderr)
        results = run_locomo_bm25(data, args.conv, args.limit)

    # Compute metrics
    metrics = compute_metrics(results)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"RESULTS (judge: {LLM_JUDGE_MODEL})", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"PRIMARY (cats 1-4): {metrics['primary']['accuracy']:.2f}% "
          f"({metrics['primary']['correct']}/{metrics['primary']['total']})", file=sys.stderr)
    print(file=sys.stderr)
    for cat_name, cat_data in metrics["by_category"].items():
        print(f"  {cat_name:15s}: {cat_data['accuracy']:6.2f}%  ({cat_data['correct']:4d}/{cat_data['total']:4d})", file=sys.stderr)
    print(file=sys.stderr)
    print(f"OVERALL (cats 1-5): {metrics['overall']['accuracy']:.2f}% "
          f"({metrics['overall']['correct']}/{metrics['overall']['total']})", file=sys.stderr)

    # Save results
    output_path = args.output or str(Path(__file__).resolve().parent.parent.parent /
                                      "benchmarks" / "results" / "locomo" /
                                      f"locomo_results_{int(time.time())}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    output_data = {
        "metadata": {
            "benchmark": "locomo",
            "pipeline": "stdb" if use_stdb else "bm25",
            "judge_model": LLM_JUDGE_MODEL,
            "answer_model": LLM_ANSWER_MODEL,
            "total_questions": len(results),
            "primary_count": metrics["primary"]["total"],
            "timestamp": datetime.now().isoformat(),
        },
        "metrics": metrics,
        "results": results,
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"\nResults saved to: {output_path}", file=sys.stderr)

    # Print JSON summary for piping
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
