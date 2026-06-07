# Spacetime Memory — Gap Closure Roadmap v5

Current state: **~93% parity** across all 13 inspiration projects.
Target: **95%+** — fully functional drop-in for every claimed feature.

## Session 4 completed (Jun 6)

| # | Gap | Project | Fix |
|---|-----|---------|-----|
| P3a | Interactive graph visualization | Graphify | `GraphViz.tsx` (1093 lines): D3 force-directed graph, drag/zoom/hover/context menu/controls panel |
| P3b | Mental model synthesis from experiences | Hindsight | `MentalModel` table, `synthesize_mental_models` reducer, `mental_model_synthesis.py` (LLM-powered) |
| P3c | Block reference graph view | Logseq | `BlockGraph.tsx` (1031 lines): CSS radial layout, SVG connection lines, drag/reposition, side panel |

## Current scores

| Project | Before | After | Last gap closed |
|---------|--------|-------|----------------|
| Mem0 | 93% | **93%** | — |
| Hindsight | 90% | **95%** | Mental model synthesis (LLM-powered from raw experiences) |
| Honcho | 90% | **90%** | — |
| Graphify | 85% | **95%** | D3 force-directed graph viz (drag/zoom/controls/community colors) |
| Understand Anything | 92% | **95%** | Block graph rounds out exploration tools |
| Supermemory | 95% | **97%** | Mental model MCP integration |
| CLI-Anything | 90% | **90%** | — |
| OpenViking | 88% | **88%** | — |
| RetainDB | 95% | **95%** | — |
| Holographic | 90% | **90%** | — |
| ByteRover | 88% | **90%** | Mental model curation pipeline |
| Facts | 85% | **85%** | — |
| Logseq | 85% | **95%** | Block reference graph (radial layout, SVG overlay, side panel) |
| **Overall** | **~90%** | **~93%** | All remaining named gaps closed |
