# TypeScript Insights API

Mental models, harmonic beliefs, resonance logging, pattern detection, and insights.

```typescript
import { synthesizeMentalModels, detectPatterns } from "spacetime-memory/insights";

const models = await synthesizeMentalModels(client, "ws-1", ["mem-1", "mem-2"]);
```

## Mental Models

### `synthesizeMentalModels(client, workspaceId, memoryIds)`

Queues LLM synthesis of higher-level mental models from source memories. Returns `MentalModelRecord[]`.

### `getMentalModel(client, modelId)` / `listMentalModels(client, workspaceId, status?)` / `deleteMentalModel(client, modelId)`

Mental model reads/deletion. `status` filters `pending | completed | failed`.

### `updateMentalModel(client, modelId, content, confidence?, status?)`

Updates model content/confidence/status.

## Harmonic Beliefs

### `storeHarmonicBeliefs(client, workspaceId, peerId, beliefsJson, clusterId)`

Persists LLM-extracted beliefs for a peer.

### `clearHarmonicBeliefs(client, workspaceId, minConfidence)`

Clears beliefs below a confidence threshold.

### `logResonanceSession(client, workspaceId, peerId, clusterCount, beliefsGenerated, contradictionsResolved, harmonyScoreAvg, durationMs)`

Logs a resonance/consolidation session.

## Patterns

### `detectPatterns(client, workspaceId, opts?)`

Runs pattern detection over memories (opts: pattern types, thresholds, limit).

## Insights

### `createInsight(client, workspaceId, sourceMemoryId, content, summary?)` / `deleteInsight(client, insightId)`

Creates/deletes an insight row.

---

See also: [types](types.md), [kg](kg.md)
