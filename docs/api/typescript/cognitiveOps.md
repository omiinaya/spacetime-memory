# cognitiveOps

Source: `sdk/typescript/src/cognitiveOps.ts`

## API Reference

### registerCognitiveOp

Cognitive operations — named abstraction wrapping pipeline stages (Cognee parity).
Operations have types: observe, filter, extract, transform, classify, rank, store.
They can be registered, executed individually, or composed into pipelines.
/
import type { ClientLike } from "./types";
// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface CognitiveOp {
id: string;
workspace_id: string;
name: string;
op_type: string;
description: string;
config_json: string;
pipeline_stage_type: string;
created_at: number;
updated_at: number;
}
export interface CognitiveOpResult {
id: string;
workspace_id: string;
data: string;
created_at: number;
}
// ---------------------------------------------------------------------------
// CRUD operations
// ---------------------------------------------------------------------------
/** Register a new cognitive operation.

---
