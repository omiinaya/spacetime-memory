# Spacetime Memory — Gap Closure Roadmap v2

Current state: **~80% parity** across all 13 inspiration projects.
Target: **95%+** — fully functional drop-in for every claimed feature.

## Priority Order (highest impact first)

### P0 — Quick Wins (<50 LOC each)

| Gap | Project | LOC | Fix |
|-----|---------|-----|-----|
| CLI missing `memory get` command | CLI-Anything | ~30 | Add `@memory.command(name="get")` that calls SDK `get_memory()` → auto-reinforces |
| CLI `search` doesn't reinforce | Hindsight/RetainDB | ~5 | Auto-reinforce top-N results on search read |
| Frontend missing Tour page | Understand Anything | ~200 | New page loading tours + stops from table subscription |
| Context agent not calling LLM | RetainDB | ~100 | Wire LiteLLM / OpenAI call in `context_agent.ask()` |
| Hindsight `reflect` not calling LLM | Hindsight | ~50 | Wire LLM call in SDK reflect method |
| No `dedup_memories` export in MCP | RetainDB | ~2 | Add MCP tool alias |

### P1 — Moderate lifts (100-300 LOC)

| Gap | Project | LOC | Fix |
|-----|---------|-----|-----|
| Connectors: only RSS built | Supermemory | ~200 | Add Twitter/X, GitHub, Webhook connectors |
| OpenViking: no recursive directory retrieval | OpenViking | ~150 | `get_children(ctx, directory_id)`, `traverse_recursive` reducers |
| No browser extension | Supermemory | ~300 | Chrome extension for page clipping → API calls |
| Tour stops need UI in note editor | Understand Anything | ~150 | Tour stop can reference note blocks, preview in editor |

### P2 — Deeper features (400+ LOC)

| Gap | Project | LOC | Fix |
|-----|---------|-----|-----|
| Mem0: missing `get_history()` + `batch_update()` | Mem0 | ~100 | Add reducers + SDK methods |
| Honcho: missing metadata/location filters | Honcho | ~100 | Add filter params to search |
| Holographic: reputation decay over time | Holographic | ~150 | Add time-weighted trust scoring |
| Interactive code exploration UI | Understand Anything | ~400 | Tree view of ingested codebase |
| Visualization: retrieval trajectories | OpenViking | ~300 | Frontend view of tiered retrieval paths |

## Current scores

| Project | Score | P0 items | P1 items | P2 items |
|---------|-------|----------|----------|----------|
| Mem0 | 90% | 1 | 0 | 1 |
| Hindsight | 85% | 1 | 0 | 0 |
| Honcho | 85% | 0 | 0 | 1 |
| Graphify | 85% | 0 | 0 | 0 |
| Understand Anything | 75% | 1 | 1 | 1 |
| RetainDB | 85% | 2 | 0 | 0 |
| Holographic | 70% | 0 | 0 | 1 |
| OpenViking | 65% | 0 | 1 | 1 |
| Supermemory | 75% | 0 | 2 | 0 |
| CLI-Anything | 80% | 1 | 0 | 0 |

Execution order: all P0 items first, then P1, then P2.
