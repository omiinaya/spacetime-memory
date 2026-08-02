# TypeScript DeltaSync API

The `DeltaSync` class provides real-time change-event polling for SpacetimeDB tables. It monitors the `change_event` table at high frequency and dispatches callbacks to local subscribers.

```typescript
import { Client } from "spacetime-memory";
// DeltaSync is available via client.deltaSync
const ds = client.deltaSync;

// Register callbacks
ds.on("memory", "insert", (event) => console.log("New memory:", event));
ds.on("kg_node", "*", (event) => console.log("Graph change:", event));

// Start polling (background interval)
ds.start();

// Later...
ds.stop();
```

The `DeltaSync` class is also directly importable:

```typescript
import { DeltaSync } from "spacetime-memory/delta_sync";
```

---

## Constructor

### `new DeltaSync(client, pollInterval?, autoStart?)`

| Param            | Type      | Default   | Description                                  |
|------------------|-----------|-----------|----------------------------------------------|
| `client`         | `Client`  | —         | An authenticated Client instance              |
| `pollInterval`   | `number`  | `0.1`     | Seconds between polls (minimum 0.01)          |
| `autoStart`      | `boolean` | `false`   | Start polling immediately on construction     |

---

## Methods

### `on(table, operation?, callback): object`

Register a callback for change events. Returns a token object to use with `off()`.

| Param       | Type                  | Default | Description                                                   |
|-------------|-----------------------|---------|---------------------------------------------------------------|
| `table`     | `string`              | —       | Table name (`"memory"`, `"kg_node"`, `"kg_edge"`, `"note"`, `"profile"`, `"document"`, or `"*"` for all) |
| `operation` | `string`              | `"*"`   | Operation (`"insert"`, `"update"`, `"delete"`, or `"*"` for all) |
| `callback`  | `(event: ChangeEvent) => void` | — | Callback invoked on each matching event                  |

**Returns:** `object` — a subscription token for use with `off()`.

### `off(token): void`

Unregister a callback by its subscription token.

| Param   | Type     | Description                       |
|---------|----------|-----------------------------------|
| `token` | `object` | The token returned by `on()`      |

### `start(): void`

Start polling the `change_event` table in a background interval. Bootstraps the initial cursor by calling the `get_latest_change_cursor` reducer before polling begins. Idempotent — safe to call multiple times.

### `stop(): void`

Stop polling and clear the background interval. Idempotent.

---

## Properties

### `stats: DeltaSyncStats`

Current polling statistics.

```typescript
{
  running: boolean;       // Whether polling is active
  cursor: number;         // Current change cursor position (monotonic μs timestamp)
  polls: number;          // Total polls completed
  errors: number;         // Total poll errors encountered
  poll_interval: number;  // Poll interval in seconds
  callbacks: number;      // Number of registered callbacks
}
```

---

## Types

### `ChangeEvent`

A single change record from the `change_event` table.

```typescript
interface ChangeEvent {
  id: string;
  workspace_id: string;
  table_name: string;      // "memory", "kg_node", "kg_edge", "note", etc.
  operation: string;       // "insert", "update", "delete"
  record_id: string;       // Primary key of the changed record
  data_json: string;       // JSON-encoded snapshot *after* the operation
  created_at: number;      // Monotonic microsecond timestamp

  data?: Record<string, unknown>;  // Deserialized record data (lazy, populated after parse)
}
```

### `ChangeCallback`

```typescript
type ChangeCallback = (event: ChangeEvent) => void;
```

### `DeltaSyncStats`

```typescript
interface DeltaSyncStats {
  running: boolean;
  cursor: number;
  polls: number;
  errors: number;
  poll_interval: number;
  callbacks: number;
}
```

---

## Usage Patterns

### Poll Multiple Tables

```typescript
client.deltaSync.on("memory", "insert", (e) => handleNewMemory(e));
client.deltaSync.on("memory", "update", (e) => handleUpdatedMemory(e));
client.deltaSync.on("kg_node", "*", (e) => handleGraphChange(e));
client.deltaSync.on("note", "*", (e) => handleNoteChange(e));
client.deltaSync.start();
```

### Wildcard Listener (All Tables, All Operations)

```typescript
client.deltaSync.on("*", "*", (e) => console.log("Change:", e.table_name, e.operation, e.record_id));
client.deltaSync.start();
```

### Start with Auto-Start

```typescript
const ds = new DeltaSync(client, 0.5, true); // 500ms poll, starts immediately
```

### Cleanup on Shutdown

```typescript
ds.stop();
ds.off(token); // Unregister individual listener
```
