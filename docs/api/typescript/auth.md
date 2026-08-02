# TypeScript Auth API

Accounts, sessions, and API keys.

```typescript
import { register, login, createApiKey } from "spacetime-memory/auth";

await register(client, "caroline", "Caroline", "s3cret");
await login(client, "caroline", "s3cret");
```

## Accounts

### `register(client, username, displayName?, password?)`

Registers a new identity with the STDB `register` reducer.

### `login(client, username, password)` / `logout(client)`

Session login/logout.

### `updateAccount(client, displayName?, currentPassword?, newPassword?)` / `deactivateAccount(client, password)`

Account update / deactivation.

## API Keys

### `createApiKey(client, workspaceId, name, permissions?)`

Creates a scoped API key for a workspace.

### `deactivateApiKey(client, keyId)` / `listApiKeys(client, workspaceId)` / `verifyApiKey(client, rawKey)`

Key lifecycle and verification.

---

See also: [admin](admin.md), [client](client.md), [types](types.md)
