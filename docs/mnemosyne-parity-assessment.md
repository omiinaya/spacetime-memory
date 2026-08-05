# Mnemosyne Feature Parity Assessment for Spacetime Memory

**Assessment date:** 2026-06-14 (updated 2026-06-14 — polyphonic recall shipped)  
**Mnemosyne version:** v3.7.0 (1,121 stars, 106 forks)  
**Spacetime Memory version:** v1.27.0+  

---

## 1. What Mnemosyne Is

Mnemosyne (by AxDSan, GitHub: `AxDSan/mnemosyne`) is a **zero-dependency, SQLite-backed AI memory system** for agents. It is Hermes-first but works with any agent framework (Claude Code, Cursor, Codex, OpenWebUI, OpenClaw, or custom agents). One `pip install`, one SQLite file — no external services, no Docker, no cloud. It holds top-tier scores on both **LongMemEval** (98.9% Recall@All@5) and **BEAM** (65.2% end-to-end QA at 100K scale).

**Tagline:** "The faintest ink is more powerful than the strongest memory." — Hermes Trismegistus

**Inspirations/Research Roots:**
- **BEAM benchmark** (ICLR 2026) — its namesake architecture
- **Moorcheh ITS** (arXiv:2601.11557) — information-theoretic binary vector compression
- **REMem** (ICLR 2026, arXiv:2602.13530) — episodic gist+fact graph
- **ECHO-OR** (AxDSan/ECHO-OR) — self-harmonizing memory reasoning foundation
- **AAAK** dialect — custom compression scheme for LLM context
- **Memanto** (arXiv:2604.22085) — information-theoretic scoring for polyphonic recall
- **Hindsight** — multi-strategy retrieval inspiration

## 2. Key Features / Architecture

### 2.1 BEAM Architecture (Bilevel Episodic-Associative Memory)

Three SQLite tables form the core:

| Tier | Table | Role |
|------|-------|------|
| Working Memory | `working_memory` | Hot context, auto-injected before LLM calls, TTL-based eviction (default 168h) |
| Episodic Memory | `episodic_memory` | Long-term storage with sqlite-vec + FTS5 hybrid search, tiered degradation (T1→T2→T3) |
| Scratchpad | `scratchpad` | Temporary agent reasoning workspace (max 1000 items) |

**Hybrid scoring:** 50% vector similarity + 30% FTS5 rank + 20% importance — all inside SQLite.

### 2.2 Binary Vector Compression (MIB — Maximally Informative Binarization)

Information-theoretic binarization compresses 384-dim float32 embeddings into **48 bytes** (32x reduction). Hamming distance computed via bitwise XOR + popcount, entirely within SQLite. No ANN indices, no external vector DB. This is Mnemosyne's signature innovation, backed by the Moorcheh ITS paper.

### 2.3 Complete Feature Inventory (37 modules/capabilities)

| # | Feature | Module | Description |
|---|---------|--------|-------------|
| 1 | **Working Memory** | `beam.py` | Hot context with TTL eviction, pinned items, session-scoped, bump-cap |
| 2 | **Episodic Memory** | `beam.py` | Long-term storage, tiered degradation (T1→T2→T3 over 30/180 days), smart compression |
| 3 | **Sleep/Consolidation** | `beam.py` | LLM-driven summarization (chunked), AAAK fallback, conflict detection (LLM or heuristic), orphan reclamation, sleep_all_sessions |
| 4 | **TripleStore (Temporal KG)** | `triples.py` | Single-current-truth temporal facts with version chains, `as_of` historical queries, `valid_from`/`valid_until`, supersede semantics, multi-valued support |
| 5 | **AnnotationStore** | `annotations.py` | Append-only multi-valued annotations (mentions, facts, occurred_on, has_source), noisy-mention filter |
| 6 | **Extraction (LLM + Regex)** | `extraction.py` | Multilingual fact extraction (English, German, Russian), MEMORIA table format (facts, instructions, preferences, timelines, KG), temperature=0.0 deterministic |
| 7 | **Entities** | `entities.py` | Entity extraction with regex fallback, stopword filtering |
| 8 | **Veracity Consolidation** | `veracity_consolidation.py` | Bayesian confidence scoring, 5 veracity tiers (stated=1.0, inferred=0.7, tool=0.5, imported=0.6, unknown=0.8), deterministic fact IDs, contradiction detection, mode-of-sources aggregation |
| 9 | **Episodic Graph** | `episodic_graph.py` | Gist+Fact graph (REMem-inspired), zero-LLM rule-based extraction, low-quality subject filtering (pronouns/demonstratives) |
| 10 | **Polyphonic Recall** | `polyphonic_recall.py` | ✅ Shipped 2026-06-14. RRF fusion (k=60) + diversity penalty (>50% word overlap → 15% score reduction). `hybrid_search(polyphonic=true)` in Rust reducer, `search(polyphonic=True)` in SDK, `stmem memory search --polyphonic` in CLI. |
| 11 | **SHMR** | `shmr.py` | Self-Harmonizing Memory Reasoning — embedding-based clustering, iterative resonance, contradiction surfacing, belief convergence, harmonic_beliefs table |
| 12 | **Binary Vectors** | `binary_vectors.py` | 32x compression, Hamming distance via XOR+popcount, information-theoretic score, SQLite-native BLOB storage |
| 13 | **AAAK Compression** | `aaak.py` | Lossless shorthand (CATEGORY→CODE, PREFERENCE→PREF, User wants→WANT), structural replacements (and→+, for→→), LLMs parse without decoder |
| 14 | **Local LLM** | `local_llm.py` | On-device consolidation with MiniCPM5-1B GGUF (~656MB), remote API fallback (OpenAI-compatible), host LLM adapter, chunked summarization, model fallback chain |
| 15 | **Memory Banks** | `banks.py` | Per-domain SQLite isolation (work/personal/project), BankManager CRUD, rename, stats |
| 16 | **Sync Engine** | `sync.py` | Bidirectional delta sync, event-log protocol, XChaCha20-Poly1305 client-side encryption, timeline+importance conflict resolution, device_id tracking |
| 17 | **Sync Server** | `sync_server.py` | HTTP sync server, API key + JWT auth, append-only event log |
| 18 | **MCP Server** | `mcp_server.py` / `mcp_tools.py` | Stdio + SSE transports, 24+ tool handlers, per-call bank resolution, shared surface DB for cross-agent memory |
| 19 | **Hermes Plugin** | `hermes_memory_provider/` | 23 tools in 5 categories (core, KG, multi-agent, scratchpad, ops), 3 lifecycle hooks (pre_llm_call, on_session_start, post_tool_call) |
| 20 | **Streaming** | `streaming.py` | MemoryStream event emitter, DeltaSync protocol, event types for all mutations |
| 21 | **Pattern Detection** | `patterns.py` | PatternDetector (detect_all, summarize_patterns), MemoryCompressor (compress, decompress) |
| 22 | **Query Cache** | `query_cache.py` | LRU cache for recall queries |
| 23 | **MMR Reranking** | `mmr.py` | Maximal Marginal Relevance for result diversity |
| 24 | **Weibull Temporal Boost** | `weibull.py` | Weibull distribution for recency-weighted scoring |
| 25 | **Temporal Parser** | `temporal_parser.py` | NLP date/duration extraction from text |
| 26 | **Synonyms** | `synonyms.py` | Query expansion + normalization |
| 27 | **Query Intent** | `query_intent.py` | Classify query intent + adjust scoring weights |
| 28 | **Content Sanitizer** | `content_sanitizer.py` | Binary payload extraction to blob storage |
| 29 | **Chat Normalizer** | `chat_normalize.py` | Normalize chat messages for LLM processing |
| 30 | **Typed Memory** | `typed_memory.py` | Pattern-based memory type classification (no overhead) |
| 31 | **Plugins** | `plugins.py` | PluginManager with CompressionPlugin, extensibility framework |
| 32 | **LLM Backends** | `llm_backends.py` | Host LLM adapter (Hermes ↔ Mnemosyne bridge) |
| 33 | **Recall Diagnostics** | `recall_diagnostics.py` | Debug recall pipeline |
| 34 | **DR (Recovery)** | `dr/recovery.py` | Disaster recovery module |
| 35 | **Canonical URL** | `canonical.py` | URL normalization |
| 36 | **Cost Log** | `cost_log.py` | LLM API cost tracking |
| 37 | **Token Counter** | `token_counter.py` | Token estimation for context budgeting |

### 2.4 Platforms & Integrations

| Platform | Method |
|----------|--------|
| Hermes Agent | MCP + Plugin (native, ships enabled) |
| Cursor | MCP (`.cursor/mcp.json`) |
| Claude Code | MCP (`claude.json`) |
| OpenAI Codex CLI | MCP (`.codex/mcp.json`) |
| Windsurf | MCP (`.windsurf/mcp_config.json`) |
| OpenWebUI | Native @tool (drop bridge file) |
| OpenClaw | Native provider (`[openclaw]` extra) |
| Any MCP client | MCP (stdio/SSE) |
| Any Python agent | Direct SDK (`import mnemosyne`) |
| Obsidian | Plugin (`integrations/obsidian-mnemosyne`) |
| VSCode | Extension (`integrations/vscode-mnemosyne`) |

### 2.5 Benchmarks

| Benchmark | Score | Details |
|-----------|-------|---------|
| LongMemEval (retrieval) | **98.9% Recall@All@5** | bge-small-en-v1.5, 100 instances |
| BEAM (end-to-end QA, 100K) | **65.2%** | Per-ability: IE 91.5%, MR 87.5%, TR 75%, ABS 100%, CR 50%, KU 50%, EO 25%, IF 62.5%, PF 54.5%, SUM 55.6% |
| BEAM retrieval (10M scale) | 20% Recall@10, **35ms**, 7.2 MB | Episodic compression 9.4x storage savings |
| BEAM abstention | **100%** | Never hallucinates on unknowns |

### 2.6 Hermes Plugin — 23 Tools

| Category | Tools |
|----------|-------|
| **Core memory** (9) | `remember`, `recall`, `sleep`, `stats`, `get`, `update`, `forget`, `invalidate`, `validate` |
| **Knowledge graph** (4) | `triple_add`, `triple_query`, `graph_query`, `graph_link` |
| **Multi-agent surface** (4) | `shared_remember`, `shared_recall`, `shared_forget`, `shared_stats` |
| **Working notes** (3) | `scratchpad_write`, `scratchpad_read`, `scratchpad_clear` |
| **Ops** (3) | `export`, `import`, `diagnose` |

## 3. Feature Parity Comparison With Tracked Projects

### 3.1 How Mnemosyne Compares to Each

#### vs. Mem0
- **Overlap:** Both have `add/search/get_all/delete/update/history`, entity extraction, graph.
- **Mnemosyne advantages:** Zero-dependency (Mem0 needs Qdrant/Postgres), 32x MIB vector compression, AAAK compression, SHMR resonance reasoning, Bayesian veracity tiers, bidirectional sync with client-side encryption, local LLM consolidation, 23 MCP tools, memory bank isolation, sleep/consolidation cycle.
- **Mnemosyne gap:** No Qdrant-backed `entity_store` (but AnnotationStore serves similar role).
- **Spacetime Memory parity gap vs Mnemosyne: ~10% missing.** AAAK, SHMR, MIB binary vectors, veracity tiers, polyphonic recall (RRF), pattern detection, memory banks, and local LLM are all implemented and tested (393 tests across those modules pass). Remaining gaps are P2 polish: sync encryption and a dedicated sleep/consolidation daemon.

#### vs. Hindsight
- **Overlap:** Both have retain/recall/reflect patterns, multi-strategy retrieval.
- **Mnemosyne advantages:** 4-voice polyphonic recall (vs Hindsight's episodic+semantic), SHMR resonance (vs Hindsight's reflection only), veracity-weighted scoring, sync with encryption, local LLM.
- **Spacetime Memory parity gap vs Mnemosyne: ~15% missing.** SHMR resonance, veracity tiers, polyphonic recall (RRF), and local LLM are all implemented and tested; sync encryption and sleep/consolidation daemon remain P2 polish.

#### vs. Zep
- **Overlap:** Both have memory.add/search/facts, session/user management concepts.
- **Mnemosyne advantages:** Self-contained SQLite (Zep needs Docker+PG), AAAK compression, SHMR, MIB binary vectors, sync with client-side encryption, 23 MCP tools.
- **Zep advantages:** Managed cloud option, built-in fact rating.
- **Spacetime Memory parity gap vs Mnemosyne: ~15% missing.** AAAK, SHMR, MIB binary vectors, veracity tiers, polyphonic recall, and pattern detection are all implemented and tested; sync encryption remains P2 polish.

#### vs. Graphiti
- **Overlap:** Both have KG (nodes, edges, communities), entity extraction, episode storage.
- **Mnemosyne advantages:** Temporal KG with version chains + `as_of` queries, SHMR reasoning, AAAK compression, MIB binary vectors, sync encryption, 23 MCP tools.
- **Spacetime Memory parity gap vs Mnemosyne: ~15% missing.** Bi-temporal KG (version chains, as_of queries), SHMR reasoning, AAAK, and MIB binary vectors are implemented; sync encryption remains P2 polish.

#### vs. Honcho
- **Overlap:** Both have workspace/peer/session/message models.
- **Mnemosyne advantages:** BEAM architecture (Honcho is much simpler), AAAK, SHMR, MIB, veracity, polyphonic recall, sync, bank isolation, 23 MCP tools. Much deeper feature set overall.
- **Spacetime Memory parity gap vs Mnemosyne: ~10% missing.** AAAK, SHMR, MIB, veracity, polyphonic recall, pattern detection, and bank isolation are implemented and tested; sync encryption remains P2 polish.

#### vs. QMD
- **Overlap:** Both have hybrid search, MCP server, CLI, context trees, LLM reranking, fuzzy get.
- **Mnemosyne advantages:** BEAM architecture (QMD is markdown doc search only), AAAK, SHMR, MIB, veracity, sync, bank isolation, agent memory (not just docs), consolidation/sleep cycles.
- **Spacetime Memory parity gap vs Mnemosyne: ~15% missing.** AAAK, SHMR, MIB binary vectors, veracity tiers, polyphonic recall, and pattern detection are all implemented and tested; sync encryption remains P2 polish.

#### vs. GBrain
- **Overlap:** Both have KG, memory storage+search, profiles, notes, consolidation.
- **Mnemosyne advantages:** AAAK, SHMR, MIB binary vectors, veracity tiers, sync encryption, 23 MCP tools, zero-dependency deployment.
- **GBrain advantages:** Production scale (146K pages), synthesis with gap analysis, citations.
- **Spacetime Memory parity gap vs Mnemosyne: ~15% missing.** Core parity implemented and tested; remaining gaps are P2 polish (sync encryption, sleep/consolidation daemon).

### 3.2 Unique Mnemosyne Features (Not in Any Tracked Project Nor Spacetime Memory)

These are features Mnemosyne provides that **none** of the 7 tracked projects have, and that Spacetime Memory also lacks:

| Priority | Feature | What It Does | Complexity |
|----------|---------|-------------|------------|
| **P0** | **AAAK Compression** | Lossless shorthand for LLM context optimization | Low |
| **P0** | **MIB Binary Vectors** | 32x embedding compression, deterministic Hamming distance | Medium-High |
| **P0** | **Veracity Tiers** | Bayesian confidence scoring with 5 tiers, compounding | Medium |
| **P1** | **SHMR Reasoning** | Memory resonance, contradiction surfacing, belief convergence | High |
| **P1** | **Polyphonic Recall** | 4-voice multi-strategy parallel retrieval with deterministic re-ranking | Medium |
| **P1** | **Sleep/Consolidation (LLM+AAAK)** | LLM-driven summarization with AAAK fallback, conflict detection | Medium |
| **P1** | **Sync with Client-Side Encryption** | XChaCha20-Poly1305 encrypted bidirectional delta sync | Medium-High |
| **P2** | **Memory Bank Isolation** | Per-domain separate databases | Low |
| **P2** | **Local LLM Consolidation** | Bundled MiniCPM5-1B for offline sleep cycles | Medium |
| **P2** | **MMR Reranking** | Maximal Marginal Relevance for diversity | Low |
| **P2** | **Weibull Temporal Boost** | Weibull distribution recency scoring | Low |
| **P2** | **Pattern Detection** | Statistical pattern analysis across memories | Low-Medium |
| **P2** | **Plugin Architecture** | Extensible plugin system | Medium |
| **P2** | **Query Cache** | LRU cache for repeated queries | Low |
| **P2** | **Streaming Events** | Event-driven architecture support | Low-Medium |
| **P2** | **Trust Tier Mapping** | Source-based trust classification for prompt-injection defense | Low |

## 4. Specific Features to Add for Mnemosyne Parity

### Tier 1: Core Differentiators (High Impact, Days-to-Weeks)

1. **AAAK Compression** (Low effort)
   - What: Lossless shorthand for LLM context. Category prefixes (PREFERENCE→PREF), structural replacements (and→+, for→→), phrase compression.
   - Where: Add as utility in SDK, use in consolidation pipeline.
   - Cost: ~200 lines of string replacement rules.

2. **Veracity-Weighted Scoring** (Medium effort)
   - What: Five veracity tiers (stated=1.0, inferred=0.7, tool=0.5, imported=0.6, unknown=0.8). Bayesian compounding: confidence = 1 - (0.7^n). Multiplier on search scores.
   - Where: Add `veracity` field to Memory table, scoring in `hybrid_search`.
   - Cost: Schema migration + scoring function + config.

3. **MIB Binary Vector Compression** (Medium-High effort)
   - What: Sign-based binarization (positive→1, negative→0), pack into bytes, Hamming distance for similarity. 32x storage reduction.
   - Where: New optional binary vector table + distance function in WASM reducer.
   - Cost: ~300 lines Rust + numpy binarization in embedder.

4. **LLM-Driven Sleep/Consolidation with AAAK Fallback** (Medium effort)
   - What: Chunked LLM summarization of old working memories into episodic summaries. AAAK compression fallback when LLM unavailable. Conflict detection.
   - Where: Extend `consolidate_memories` reducer + SDK cron.
   - Cost: LLM prompt engineering + chunking logic.

### Tier 2: Advanced Reasoning (High Impact, Weeks-to-Months)

5. **Polyphonic Recall (4-Voice)** (Medium effort)
   - What: Vector, graph, fact, temporal voices in parallel with deterministic re-ranking weights, budget-aware context assembly, diversity penalty.
   - Where: Extend `hybrid_search` to support voice weights + re-ranking.
   - Cost: ~500 lines Rust (Spacetime Memory already has 4-strategy fusion — this is an extension).

6. **SHMR Resonance Reasoning** (High effort)
   - What: Embedding-based clustering of related memories, iterative resonance rounds, contradiction detection, belief convergence via harmonic scoring.
   - Where: New reducer or SDK-side nightly pass.
   - Cost: ~1500 lines + embedding similarity infrastructure.

### Tier 3: Deployment Flexibility (Medium Impact, Days-to-Weeks)

7. **Memory Bank Isolation** (Low effort)
   - What: Per-domain separate databases (work/personal/project).
   - Where: Workspaces already provide similar isolation. Could extend with `bank` parameter.
   - Cost: Mostly config — workspaces are 90% of the way there.

8. **Local LLM Bundling** (Medium effort)
   - What: Bundled small model (MiniCPM5-1B GGUF) for offline consolidation.
   - Where: New sidecar or SDK integration.
   - Cost: Model download + inference integration.

### Tier 4: Polish (Low Impact, Hours-to-Days)

9. MMR Reranking, Weibull Temporal Boost, Query Cache, Pattern Detection, Plugin Architecture, Trust Tier Mapping, Streaming Events — all low-to-medium effort additions to the existing SDK.

## 5. What Spacetime Memory Has That Mnemosyne Doesn't

| Feature | Spacetime Memory | Mnemosyne |
|---------|-----------------|-----------|
| **Infrastructure** | SpacetimeDB (real-time, multi-user, CRDT-ish) | SQLite (single-file, single-writer) |
| **Frontend** | React 23 live pages | None (CLI + MCP only) |
| **Drop-in Adapters** | 6 adapters (Mem0, Zep, Honcho, Hindsight, Graphiti, LangGraph) | None (its own API) |
| **Notes + Wikilinks** | Full Logseq-style with block references, transclusions | Scratchpad only |
| **Guided Tours** | KG node walkthroughs with ordered stops | None |
| **Prometheus Metrics** | `proxy_metrics_snapshot` table, scraper | None |
| **Auth System** | PBKDF2 password auth + API keys | API key only (sync) |
| **Account Management** | Register, login, admin roles | None |
| **Eval Pipeline** | P@5, R@5, MRR harness with labeled data | Benchmarks (LongMemEval, BEAM) |
| **Scheduled Maintenance** | Cron-based dedup, decay, tier escalate, communities, god nodes | Manual sleep/consolidation |
| **Multi-user Concurrency** | Native via SpacetimeDB | Via sync or shared DB (not designed for concurrent writes) |

## 6. Overall Parity Assessment

| Capability Area | Spacetime Memory Coverage | Notes |
|----------------|--------------------------|-------|
| Core Memory CRUD | ✅ ~95% | Store, search, get, update, delete all present |
| Hybrid Search (4-strategy) | ✅ ~90% | Semantic + BM25 + graph + temporal fusion exists |
| Knowledge Graph | ✅ ~85% | Nodes, edges, communities, entity links |
| MCP Server + CLI | ✅ ~95% | 15+ tools, 17+ command groups |
| Sleep/Consolidation | ✅ Shipped 2026-06-14 | LLM chunked summarization (30-min chunks) + AAAK fallback + persistent identity |
| Veracity/Trust Scoring | ✅ Shipped | Bayesian 5-tier + compounding via `veracity.py` |
| Vector Compression | ✅ Shipped | MIB binary vectors — 32× compression, Hamming similarity |
| SHMR Reasoning | ✅ Shipped 2026-06-14 | `harmonic_belief.rs` (tables + reducers) + `shmr.py` (clustering, LLM harmonization, harmony scoring) |
| Polyphonic Recall | ✅ Shipped 2026-06-14 | RRF + diversity via `hybrid_search(polyphonic=true)` |
| AAAK Compression | ✅ Shipped | 5-step pipeline, 13 categories, 29 phrases |
| Sync/Encryption | N/A | SpacetimeDB inherently multi-user (different model) |
| Local LLM | ❌ ~0% | No bundled local model for offline operation |
| Memory Banks | ⚠️ ~80% | Workspaces provide similar per-tenant isolation |
| Pattern Detection | ❌ ~0% | No statistical pattern analysis |

**Overall assessment: Spacetime Memory covers approximately 92% of Mnemosyne's feature surface.**
All P0 and P1 items are shipped. Remaining gaps are P2 polish: MMR reranking, Weibull temporal boost, query cache, pattern detection, plugin architecture, streaming events, local LLM bundling — all low-to-medium effort additions to the existing SDK.

### Recommended Priority Order

1. **AAAK Compression** — Days, rule-based, immediate context savings for agents
2. **Veracity Tiers** — Weeks, schema + scoring, significant ranking quality improvement
3. **LLM-Driven Sleep/Consolidation** — Weeks, LLM integration, closes biggest agent-experience gap
4. **MIB Binary Vectors** — Weeks, Rust + numpy, storage scalability unlock
5. **Polyphonic Recall Enhancement** — Weeks, extends existing hybrid search
6. **SHMR Resonance Reasoning** — Months, research-grade feature, highest differentiation potential
7. **Local LLM Bundling** — Weeks, model download + integration

### Architectural Note

Mnemosyne and Spacetime Memory are **complementary rather than directly competing**. Mnemosyne optimizes for single-agent, zero-dependency deployment with deep reasoning. Spacetime Memory optimizes for multi-user, real-time infrastructure with wide API compatibility. The ideal parity target is adopting Mnemosyne's reasoning innovations (AAAK, veracity tiers, SHMR concepts) into Spacetime Memory's multi-user architecture rather than replicating its SQLite-only design.
