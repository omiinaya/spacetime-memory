# TypeScript Admin API

Admin operations — admin management, backup/restore, health, maintenance, dedup, and metrics.

```typescript
import { health, backup, promoteAdmin } from "spacetime-memory/admin";

const status = await health(client);
await backup(client, "/tmp/memory-backup.json");
```

## Admins

### `promoteAdmin(client, targetIdentity)` / `demoteAdmin(client, targetIdentity)` / `listAdmins(client)`

Promotes/demotes an identity to admin, or lists current admins.

## Backup / Restore

### `backup(client, outputPath?)`

Exports the full database state to JSON.

### `restore(client, inputJson | object)`

Restores from a backup JSON string or object.

## Health

### `ping(client)` / `health(client)` / `checkEmbedderHealth(client)` / `checkTantivyHealth(client)`

Health probes for STDB, embedder sidecar, and Tantivy BM25 sidecar.

## Maintenance

### `runMaintenance(client)` / `dedup(client, workspaceId)`

Runs periodic maintenance (expire/decay/dedup) or workspace dedup.

### `suggestMerges(client, workspaceId, threshold?)` / `approveMerge(client, suggestionId)` / `rejectMerge(client, suggestionId)`

Merge-suggestion lifecycle.

## Metrics

### `setMetricsCollector(client, collector)` / `getMetrics(client)`

Attaches/retrieves an in-process metrics collector.

---

See also: [auth](auth.md), [client](client.md), [types](types.md)
