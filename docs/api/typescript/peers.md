# TypeScript Peers API

Peer management — peers represent the agents/users whose memories are stored in a workspace.

```typescript
import { listPeers, addFact, searchFacts } from "spacetime-memory/peers";

const peers = await listPeers(client, "ws-1");
await addFact(client, "ws-1", peerId, "Caroline volunteers at the shelter");
```

## Peer CRUD

### `listPeers(client, workspaceId?)`

Returns all peers, optionally filtered by workspace. Backed by `SELECT * FROM peer`.

| Param | Type | Description |
|-------|------|-------------|
| `client` | `ClientLike` | Authenticated client |
| `workspaceId` | `string` | Optional workspace filter |

Returns `PeerRecord[]`.

### `getPeerReputation(client, peerId)`

Fetches the reputation summary for a peer from `peer_reputation_result`.

| Param | Type | Description |
|-------|------|-------------|
| `client` | `ClientLike` | Authenticated client |
| `peerId` | `string` | Peer ID |

Returns `Record<string, unknown> | null`.

## Facts

### `addFact(client, workspaceId, peerId, content, opts?)`

Adds a fact about a peer.

| Param | Type | Description |
|-------|------|-------------|
| `client` | `ClientLike` | Authenticated client |
| `workspaceId` | `string` | Workspace ID |
| `peerId` | `string` | Peer ID |
| `content` | `string` | Fact text |
| `opts` | `AddFactOptions` | `{ factType?, confidence? }` (default confidence 0.8) |

### `listFacts(client, workspaceId, peerId)`

Lists facts for a peer from `fact_result`.

### `deleteFact(client, factId)` / `updateFact(client, factId, content, confidence?)`

Removes or updates a fact.

### `searchFacts(client, workspaceId, query)`

Filters peer facts by keyword match on content.

---

See also: [types](types.md), [sessions](sessions.md), [profile](profile.md)
