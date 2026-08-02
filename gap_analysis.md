# Gap Analysis: spacetime-memory vs 10 Competitors

## Current State
- **102+ database tables**, 100+ reducers, **38 SDK mixins**, 40+ CLI commands
- **6 competitor adapters** (Mem0, Zep, Graphiti, Hindsight, Honcho, LangChain)
- **~200 test files**, 3 benchmarks (BEAM, LoCoMo, LongMemEval)
- **3 Rust sidecars** (embedder :9090, tantivy :9091, webhook)
- **~100% feature parity** with leading competitors (all gaps resolved)

## Competitive Gap Priority Matrix

### PRIORITY 1: Bi-Temporal Facts with Auto-Contradiction (Graphiti/Zep) ✅
- [x] `resolve_edge_contradictions()` LLM-based conflict detection
- [x] `detect_contradictions()` rule-based + `detect_contradictions_llm()` LLM-based
- [x] `create_edge_resolve()` all-in-one contradiction resolution
- [x] Edge provenance tracking via `kg_edge` table attributes

### PRIORITY 2: Background Memory Processing (Honcho/LangMem) ✅
- [x] **Background Deriver** — extracts explicit observations from messages
- [x] **Background Summarizer** — auto-generates session summaries at configurable thresholds
- [x] **Dreamer** (higher-level reasoning) — deduction + induction pipelines
- [x] **ReflectionExecutor** — priority queue, debouncing, deduplication per thread
- [x] Background job queue via STDB tables (`background_job`, `background_job_result`)
- [x] CLI commands to schedule/manage background jobs

### PRIORITY 3: Three-Phase Entity Resolution (Graphiti) ✅
- [x] Phase 1: Exact name match (normalized — case, punctuation, honorifics)
- [x] Phase 2: MinHash/LSH fuzzy match (3-gram shingles, 128-bit signatures, Jaccard 0.9 threshold)
- [x] Phase 3: LLM-based dedup escalation
- [x] Edge dedup pipeline with confidence-based merge
- [x] Attribute merge with schema validation (from ontology)

### PRIORITY 4: Multi-Reranker Search (Graphiti) ✅
- [x] Cross-encoder reranking (local BGE model via embedder API)
- [x] Node_distance reranker (graph distance from query entities)
- [x] MMR reranker (Maximum Marginal Relevance for diversity)
- [x] Fusion reranker (weighted linear combination of reranker scores)
- [x] Search filter DSL (node_labels, edge_types, temporal, property_filters, memory_types, entity_ids)
- [x] Pre-configured search recipes (18 recipes: keyword, semantic, hybrid, temporal, entity_focused, recency_boosted, exact_phrase, boolean, fuzzy, structured, multi_hop, semantic_graph, adaptive, conversation, factoid, summary, qa, exploratory)

### PRIORITY 5: Custom Pydantic Ontology (Zep/Graphiti) ✅
- [x] Pydantic-based entity type definitions with property schemas
- [x] LLM-driven attribute extraction into typed fields
- [x] Strict/extensible ontology modes per workspace
- [x] Type filtering in search by labels

### PRIORITY 6: Memory Manager Agent Tools (LangMem) ✅
- [x] `manage_memory` tool (create/update/delete with structured schemas)
- [x] `search_memory` tool (query + filter by type/tags/importance + pagination)
- [x] `summarize_messages` node (incremental + full summarization)
- [x] Structured memory extraction from conversations

### PRIORITY 7: Git-Backed Memory Versioning (Letta/QMD) ✅
- [x] Memory blocks stored as markdown with YAML frontmatter
- [x] Git commit history tracking per block
- [x] Block operations: create/update/delete/rename
- [x] Rollback to any historical version
- [x] Tag-based enable/disable

### PRIORITY 8: Advanced Retrieval Techniques (Mnemosyne) ✅
- [x] Polyphonic recall (RRF-based multi-signal fusion)
- [x] Query intent classification (heuristic + LLM)
- [x] Weibull temporal boost (decay modeling)
- [x] Memory compression strategies (importance, recency, diverse, LLM)
- [x] Pattern detection (temporal, content frequency, sequence)
- [x] Persona extraction system (preferences, traits, interests, communication style)

### PRIORITY 9: Session Distillation + Temporal Graph (Cognee) ✅
- [x] Session distillation (compact session history with LLM summary)
- [x] Temporal graph (event extraction + timestamp assignment)
- [x] RDF/OWL ontology import (Turtle, RDF/XML, JSON-LD)
- [x] 18 search strategy variants
- [x] Migration import bridges (Mem0, Zep, Honcho)

## Immediate Fixes
- [x] STDB energy budget: switched to SQL-only client-side reads
- [x] LoCoMo benchmark: data chunking to avoid reducer timeouts
- [x] Clean rebuild after all fixes

## Benchmark Targets
- **BEAM (82 Q)**: Beat Mem0's 85.7% accuracy
- **LoCoMo (1,540 Q)**: Beat Zep's 94.7% accuracy
- **LongMemEval (500 Q)**: Beat Zep's 90.2% accuracy
