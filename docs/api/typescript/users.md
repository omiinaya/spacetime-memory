# TypeScript Users API

User management — user accounts, profiles, and user-session mapping.

```typescript
import { addUser, getUser, listUsers } from "spacetime-memory/users";

await addUser(client, "user-1", "caroline@example.com", "Caroline", "Jones");
const user = await getUser(client, "user-1");
```

## CRUD

### `addUser(client, userId, email?, firstName?, lastName?, metadataJson?)`

Creates a user via the `add_user` reducer.

### `getUser(client, userId)`

Calls `get_user` and reads the scoped `user_get_result` row. Throws if not found.

### `updateUser(client, userId, email?, firstName?, lastName?, metadataJson?)`

Updates user fields.

### `deleteUser(client, userId)`

Deletes a user.

## Reads

### `listUsers(client)`

Calls `list_users` and filters `user_get_result` rows for `list_users:` query IDs.

### `getUserSessions(client, userId)`

Calls `get_user_sessions` and reads `user_session_result` scoped by query ID.

---

See also: [sessions](sessions.md), [types](types.md)
