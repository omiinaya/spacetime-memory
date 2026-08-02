# reflectionLoop

Source: `sdk/typescript/src/reflectionLoop.ts`

## API Reference

### createReflectionSession

Reflection Loop — structured self-reflection sessions for AI agents.
Each session is a multi-cycle process where an agent reflects on memories,
stores insights by type (patterns, contradictions, gaps, observations,
connections, syntheses), and completes with a summary status.
Wraps the corresponding SpacetimeDB reducers.
/
import type { ClientLike } from "./types";
// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------
export interface ReflectionSessionRecord {
id: string;
workspace_id: string;
peer_id: string;
config_json: string;
cycles_completed: number;
status: string;
insight_count: number;
started_at: number;
completed_at: number | null;
created_at: number;
}
export interface ReflectionInsightRecord {
id: string;
workspace_id: string;
session_id: string;
content: string;
confidence: number;
insight_type: string;
source_memory_ids: string;
source_note_ids: string;
cycle: number;
created_at: number;
}
export type InsightType =
| "pattern"
| "contradiction"
| "gap"
| "observation"
| "connection"
| "synthesis";
// ---------------------------------------------------------------------------
// Reflection Session CRUD
// ---------------------------------------------------------------------------
/**
Create a new reflection session.
Returns the created session record.

---

### startReflectionCycle

Start (or advance) a reflection cycle within a session.
Returns the updated session state.

---

### storeReflectionInsight

Store a reflection insight for a session.
sourceMemoryIds and sourceNoteIds are arrays of IDs serialised as JSON.

---

### completeReflectionSession

Complete a reflection session with a final status
(e.g. "completed", "aborted", "archived").

---

### getReflectionSessions

Get all reflection sessions for a workspace.

---

### getReflectionInsights

Get all insights belonging to a specific reflection session.

---

### deleteReflectionSession

Delete a reflection session and all its associated insights.

---
