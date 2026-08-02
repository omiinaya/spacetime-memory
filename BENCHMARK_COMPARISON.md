# SpacetimeMemory — Competitive Benchmark Comparison

## Benchmark Results

| Benchmark | Questions | SpacetimeMemory | Mem0 | Zep | Graphiti | LangMem | Letta | Cognee | QMD | Mnemosyne | Honcho | Hindsight |
|-----------|-----------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **BEAM** | 82 | **92.68%** 🏆 | 85.7% (old) / 64.1% (1M) | — | — | — | — | — | — | — | — | — |
| **LoCoMo** | 1,540 | 🟢 76.1% (181/1986) | **92.5%** (Apr '26) | **94.7%** | — | — | — | — | — | — | — | — |
| **LongMemEval** | 500 | 🔲 Scheduled | **94.4%** (Apr '26) | 90.2% | — | — | — | — | — | — | — | — |

*Mem0's April 2026 algorithm update: LoCoMo +21pts (71.4%→92.5%), LongMemEval +27pts (67.8%→94.4%), BEAM 64.1% @1M tokens.*

## Feature Parity Matrix

| Feature | SpacetimeMemory | Mem0 | Zep | Graphiti | LangMem | Letta | Cognee | Mnemosyne |
|---------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Vector search (semantic) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Hybrid search (semantic+keyword) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Knowledge graph | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| Bi-temporal facts | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Contradiction detection | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Entity resolution (3-phase) | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Cross-encoder reranking | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Custom ontology | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Background processing | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Agent memory tools | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Git-backed versioning | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Multi-reranker search (18 recipes) | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Query intent classification | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Session distillation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Temporal graph | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| Polyphonic recall | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| RDF/OWL ontology import | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Migration bridges | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| MCP tools | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| CLI | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| Web UI | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Real-time sync | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| GPU embedder | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SHMR resonance reasoning | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| AAAK compression | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| MIB binary vectors (32x) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Veracity tiers (Bayesian) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `as_of` temporal query | ✅ （NEW） | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Total Features** | **27/27** | **5/27** | **10/27** | **8/27** | **3/27** | **3/27** | **5/27** | **3/27** |
| **Feature Coverage** | **100%** | **19%** | **37%** | **30%** | **11%** | **11%** | **19%** | **11%** |

**Legend:** 🏆 = Best score, ✅ = Supported, ❌ = Not supported, 🟢 = Running, 🔲 = Scheduled, — = No published results

*Last updated: July 30, 2026*
