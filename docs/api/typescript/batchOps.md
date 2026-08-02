# batchOps

Source: `sdk/typescript/src/batchOps.ts`

## API Reference

### batchUpdateMemories

BatchOps — batch memory operations (Phase 2 reducer implementations).
Wraps the corresponding SpacetimeDB reducers for each domain.
/
import type { ClientLike } from "./types";
// ---------------------------------------------------------------------------
// BatchOps — batch memory operations using dedicated reducers
// ---------------------------------------------------------------------------
/**
Batch-update multiple memories with the same set of field changes.
Uses the Phase 2 dedicated reducer instead of client-side iteration.

---

### batchDeleteMemories

Batch-delete (deactivate) multiple memories by ID.
Uses the Phase 2 reducer with workspace scoping.

---

### batchSetCategory

Batch-set the category/metadata field on multiple memories at once.

---
