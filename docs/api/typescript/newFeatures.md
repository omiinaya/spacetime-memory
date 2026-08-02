# newFeatures

Source: `sdk/typescript/src/newFeatures.ts`

## API Reference

### setMemoryMeta

New features — MemoryMeta, Webhook, Observation, ContextTree, Review.
Wraps the corresponding SpacetimeDB reducers for each domain.
/
import type { ClientLike } from "./types";
// ---------------------------------------------------------------------------
// MemoryMeta — extensible metadata on memories
// ---------------------------------------------------------------------------
/** Set or update metadata on a memory (upsert).

---
