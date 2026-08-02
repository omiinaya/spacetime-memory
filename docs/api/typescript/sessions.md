# TypeScript Sessions API

Session lifecycle, steps, participants, tours, and semantic session search.

```typescript
import { createSession, getSessionMessages, searchSessionsSemantic } from "spacetime-memory/sessions";

await createSession(client, "ws-1", "Onboarding");
const messages = await getSessionMessages(client, sessionId);
```

## Lifecycle

### `createSession(client, workspaceId, name?)`

Creates a session (default name `""`).

### `joinSession(client, sessionId)` / `leaveSession(client, sessionId)`

Joins / leaves a session as the current peer.

### `addAgentStep(client, sessionId, step, stepType?)`

Logs an agent reasoning/tool step (default `stepType` `"action"`).

## Reads

### `getSessionSteps(client, sessionId)`

Returns `SessionStepRecord[]` from `session_step`.

### `getPeerSessions(client, peerId)`

Returns sessions a peer participates in, sorted by most recent `joined_at`.

### `getSessionMessages(client, sessionId)`

Returns messages for a session sorted by created-at ascending.

### `searchSessionsSemantic(client, query, limit?)`

Embeds the query and calls `search_sessions_semantic`, returning `session_search_result` rows sorted by score.

## Tours

### `createTour(client, workspaceId, name, description?)`

Creates a guided tour of KG nodes.

### `addTourStop(client, tourId, nodeId, sequence)` / `removeTourStop(client, tourStopId)` / `deleteTourStop(client, stopId)`

Manages tour stops (aliases for the same reducer).

### `deleteTour(client, tourId)`

Deletes a tour.

---

See also: [peers](peers.md), [types](types.md)
