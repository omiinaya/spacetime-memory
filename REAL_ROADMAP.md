# Real Roadmap — June 2026

## What actually works (no caveats)

| Component | Reality |
|-----------|---------|
| Rust module | Clean STDB module, 91 tests, zero anti-patterns. All writes through reducers, all private tables used correctly, auth on 130/130 reducers. This is the best part of the project. |
| LangGraph adapter | Actual `BaseStore` inheritance. 17/17 tests. Real drop-in. |
| Honcho adapter | Full shape match, 14/14 tests, `.aio` accessor. Honcho is simple enough that shape match IS behavioral match. |
| Consolidate cron | Identity token persistence, works across runs. Runs decay + reinforce + god nodes + communities + replication cleanup. |
| Merge dedup | Cosine similarity + Levenshtein with thresholds (≥0.85 cos, ≤30% edit dist). Legitimate approach. Requires embedder for search_index rows though. |
| Frontend | 23 pages, live data via `useTable`/`useReactiveDb`. No mock data. Real. |
| QMD parity | Hybrid search + MCP + CLI + context trees + LLM reranking + fuzzy get + glob multi-get. All covered. QMD is a Node.js CLI — this is a superset. |
| Synthesis | LLM prompt with structured context entries → cited answer + gap analysis + confidence. `response_format: json_object`. Decent implementation. |
| Dream cycle pipeline | Fetch recent memories → extract entities → cluster by proper nouns → create mental models → LLM synthesize → generate insight. Real pipeline, not a one-shot. |

## What's broken or missing

### 1. Keyword search is substring matching, not BM25

**Current:** `term_match_count()` counts how many query terms appear as substrings in the content. `contains()` on split words. No IDF, no term frequency normalization, no inverted index. Score is `matched_terms / total_terms`.

**Why it matters:** "the cat" matches "the catalog" equally as "the cat sat". Common words dominate. No relevance ranking — it's a boolean filter with a score hack.

**What to do:**
- Implement BM25 scoring in WASM (TF-IDF with saturation and length normalization)
- Add an inverted index table: `(term, workspace_id, entity_id, term_frequency)` 
- Build the index on store/update, not at query time
- Score formula: BM25(query_terms, doc) with k1=1.2, b=0.75
- ~400 lines Rust, 1 new table, migration

### 2. No result fusion across search strategies

**Current:** Each strategy independently inserts into `HybridResult` with its own score scale. Semantic: cosine 0-1. Keyword: term ratio 0-1. Graph: edge weight × 0.5. Temporal: age-based 0.5-1.0. The client reads them all and sorts by raw score — no normalization.

**Why it matters:** A temporal result (always 0.5-1.0) consistently outranks a semantic result (0.1-0.9) even when the semantic match is stronger. The "hybrid" in hybrid search is a lie — it's parallel independent searches with incompatible scores.

**What to do:**
- Add a fusion pass after all strategies run: min-max normalize each strategy's scores to [0,1], apply strategy weights (configurable), compute weighted sum
- Output fused scores into a separate `fused_result` table or update `HybridResult` scores post-fusion
- ~200 lines Rust, strategy weight config

### 3. Entity extraction is regex on proper nouns

**Current:** `extract_people()` finds two consecutive capitalized words. `extract_companies()` walks backward from a company suffix to find capitalized prefix. Noise list of 30 common words. No NER model, no co-reference, no entity linking across documents.

**What it handles:** "Garry Tan works at Y Combinator" → extracts "Garry Tan" (person), "Y Combinator" (fails — no suffix match unless "Y Combinator Inc").

**What it misses:** "Alice is the CEO" (single name), "she founded it in 2015" (pronoun), "the company raised $10M" (no named entity), "alice chen" (lowercase), "Google and Meta" (no suffix, single capitalized word).

**Why it matters:** GBrain uses LLM extraction. Mem0 uses LLM extraction. Graphiti uses LLM extraction. This is the single biggest behavioral gap vs competitors.

**What to do:**
- Option A (pragmatic): Add an LLM extraction path — call OpenAI-compatible endpoint with a structured prompt. Cache results. Fall back to regex when no API key. ~150 lines Python in SDK, 1 env var.
- Option B (hard): Integrate an ONNX NER model into the embedder sidecar (same Rust binary, same ONNX runtime). spaCy `en_core_web_sm` or similar.
- Option A first. It's what Mem0/GBrain actually do. The regex path stays as fallback.

### 4. Adapters are API facades, not behavioral replacements

**Current:** Mem0 adapter accepts `add(messages, user_id)` → calls `store_memory` once with raw text. Real Mem0 calls an LLM to extract structured memories from the conversation, embeds them, deduplicates, and stores in Qdrant.

**What to do (for each adapter):**

**Mem0:**
- `add()` with `messages` list → call LLM extraction to produce memory objects → store each
- `search()` → actually run hybrid search through the SDK, not just return shape
- `entity_store` → wire to `entity_link` table (already exists, just not exposed)
- Add `MemoryConfig` Pydantic model for real constructor parity
- ~300 lines Python

**Zep:**
- `add_memory()` → extract facts from messages via LLM, not just store raw
- `search_sessions()` → wire to `search_sessions_semantic` reducer (exists in Rust, not called from adapter)
- `get_session_messages()` → actually query by session, not return empty
- ~250 lines Python

**Graphiti:**
- `add_episode()` → call LLM entity extraction, not regex
- `build_communities()` → the Rust reducer exists but 3 tests fail. Fix the failures.
- `remove_episode()` → the 2 test failures need fixing
- ~200 lines Python + Rust bug fixes

### 5. Eval harness has no labeled data

**Current:** `DEFAULT_QUERIES` has no `relevant_ids`. Every query returns P@5=0.0, R@5=0.0, MRR=0.0. The "24% P@5" from earlier was a manual run with hand-picked IDs on 5 memories. The ROADMAP compared this to GBrain's 49.1% (from 146K pages with real labeled data).

**What to do:**
- Create a labeled dataset: 50 queries × 5-10 relevant memory IDs each
- Label against a reasonably populated workspace (100+ memories)
- Run eval weekly and track regression
- Target: P@5 ≥ 40%, R@5 ≥ 90% on the labeled set
- ~1 day of manual labeling + 50 lines harness config

### 6. No multi-user performance characteristics

**Current:** Every `hybrid_search` does full table scans in WASM. `search_index`, `memory`, `kg_node`, `kg_edge` — all iterated linearly with `.filter()` closures. STDB v2.4 doesn't support indexes or query planning.

**Why it matters:** Works for 100 memories. Breaks at 10,000. GBrain runs on 146K pages. Mem0 runs on Qdrant with HNSW indexes.

**What to do:**
- Short term: Add `MAX_RESULTS` caps on all strategies (already done for temporal, missing from semantic/keyword/graph per-strategy loops)
- Medium term: Pre-filter `search_index` by `workspace_id` before cosine loop (reduce scan scope)
- Long term: Wait for STDB indexing support, or shard by workspace across multiple STDB instances
- ~50 lines Rust (caps + pre-filter)

### 7. No error recovery or degraded mode

**Current:** If the embedder sidecar is down, semantic search silently returns nothing. Keyword still works but `hybrid_search` doesn't fall back gracefully — it just skips the semantic strategy with `continue`. The client gets partial results with no indication.

**What to do:**
- Add a `/health` endpoint to the embedder sidecar
- Python SDK: ping embedder health before calling `hybrid_search` with embeddings
- If embedder is down, set `strategies_json` to `["keyword","graph","temporal"]` and log a warning
- Return a `degraded: true` flag in search results
- ~100 lines Python, 20 lines Rust (health endpoint)

### 8. Dream cycle has no persistent feedback loop

**Current:** Dream cycle runs, creates mental models, generates an insight. Next night it runs again from scratch. No comparison against previous cycles, no tracking of whether yesterday's insights were useful, no learning from user feedback on mental models.

**What to do:**
- Compare new clusters against previous night's clusters — flag new/merged/split clusters
- Track which mental models get accessed (via `access_count` on insights)
- Skip re-extraction on memories already processed
- ~200 lines Python

### 9. Consolidation doesn't use semantic dedup by default

**Current:** `dedup_memories` requires embeddings in `search_index` — memory rows without embeddings are skipped. The embedder only runs when explicitly called from the Python SDK during `store`. Cron-based consolidation works, but only on memories that were stored with embeddings.

**What to do:**
- Add an embedding backfill pass to `consolidate.py`: for memories without `search_index` rows, call embedder and insert
- Rate-limit to avoid hammering the embedder (batch of 50 per tick)
- ~80 lines Python

### 10. No backup/restore or migration tooling

**Current:** `scripts/backup.py` exists but was flagged as a placeholder in earlier audits. No `stmem backup` CLI command. No restore path.

**What to do:**
- `stmem backup <workspace_id>` — dump all tables to JSONL
- `stmem restore <workspace_id> <backup_file>` — replay JSONL through reducers
- ~150 lines Python + CLI wiring

---

## Priority order

| # | What | Effort | Impact |
|---|------|--------|--------|
| 1 | BM25 search indexing | Medium | **Critical** — keyword search is fake right now |
| 2 | Result fusion (strategy normalization) | Small | **Critical** — hybrid is a lie without it |
| 3 | LLM entity extraction path | Small | **High** — biggest behavioral gap vs competitors |
| 4 | Labeled eval dataset | Medium | **High** — can't measure progress without it |
| 5 | Adapter behavioral parity (Mem0/Zep/Graphiti) | Medium | **Medium** — adapters currently facades |
| 6 | Embedder health check + degraded mode | Small | **Medium** — prevents silent failures |
| 7 | MAX_RESULTS caps on all strategy loops | Small | **Medium** — prevents runaway scans |
| 8 | Dream cycle persistent feedback | Small | **Low** — nice to have, not blocking |
| 9 | Embedding backfill in consolidation | Small | **Low** — consolidation already works for embedded memories |
| 10 | Backup/restore CLI | Small | **Low** — needed before anyone depends on this |

---

## What to stop doing

- **Stop claiming adapter percentages.** The adapters are shape matches. Say "API-compatible drop-in — your existing code won't crash, but search quality and extraction intelligence depend on configuration."
- **Stop self-scoring against custom rubrics.** The 98% score was me grading my own homework. Delete it.
- **Stop calling regex entity extraction "GBrain-style."** GBrain uses LLM extraction. Say "regex-based entity extraction (LLM extraction available with API key)."
- **Stop labeling deployment tasks as P2 blockers to inflate the completion percentage.** Docker smoke test and PyPI publish are nice-to-haves, not the 2% gap.

---

## What's actually good (keep doing this)

- The Rust module is solid. Keep the anti-pattern scans, keep the test discipline, keep auth on every reducer.
- The frontend has real live data. Keep the `useTable` pattern, keep zero mock data.
- The consolidator identity token persistence was a good fix. Apply this pattern to dream cycle too.
- The `merge_suggestion` → `approve_merge` workflow is a real feature. Build the frontend UI for it.
- The synthesis `response_format: json_object` with structured gap analysis is legitimate. The citations work.
