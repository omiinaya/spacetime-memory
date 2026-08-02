# TypeScript Profile API

Profile queries — static facts, dynamic context, and profile search per peer.

```typescript
import { getProfile, searchProfiles, upsertProfile } from "spacetime-memory/profile";

const profile = await getProfile(client, peerId);
await upsertProfile(client, peerId, "Lives in Toronto", "Currently job hunting");
```

## Queries

### `getProfile(client, peerId)`

Reads the profile row for a peer from the `profile` table.

| Param | Type | Description |
|-------|------|-------------|
| `client` | `ClientLike` | Authenticated client |
| `peerId` | `string` | Peer ID |

Returns `Record<string, unknown> | null`.

### `listProfiles(client, workspaceId)`

Lists profiles joined against `peer` for a workspace.

### `searchProfiles(client, workspaceId, query, limit?)`

Filters profiles by substring match on `static_facts_json` / `dynamic_context_json`. Default limit 20.

## Mutations

### `upsertProfile(client, peerId, staticFacts?, dynamicContext?, preferences?, tags?)`

Creates or updates a peer profile.

### `getProfileContext(client, peerId)`

Calls the `get_profile_context` reducer and reads `profile_context_result`.

### `addProfileFact(client, peerId, fact)` / `addDynamicContext(client, peerId, context)`

Appends a fact or dynamic context entry to the profile.

---

See also: [peers](peers.md), [types](types.md)
