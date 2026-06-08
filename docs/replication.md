# Replication

Spacetime-Memory supports **bi-directional replication** between SpacetimeDB
instances.  Mutations (inserts, updates, deletes) on the `memory`, `kg_node`,
`kg_edge`, `note`, and `profile` tables are tracked in a `replication_log`
table and pushed/pulled to/from registered peers.

## Architecture

```
┌──────────────┐         HTTP         ┌──────────────┐
│  Instance A  │ ◄──────────────────► │  Instance B  │
│              │   sync (push/pull)   │              │
│  replication_log  ◄──────────────►  replication_log
│  replication_peer                    replication_peer
└──────────────┘                      └──────────────┘
```

- Each instance maintains its own `replication_log` of unsynced mutations.
- The **Replication Daemon** periodically polls for unsynced entries, sends
  them to peers, and marks them synced.
- Incoming entries are applied with **last-write-wins** conflict resolution
  (inserts that conflict with existing records are skipped).

## Tables

| Table | Purpose |
|-------|---------|
| `replication_peer` | Registered remote instances (url, auth, active flag) |
| `replication_log` | Mutation log (table, operation, record_id, JSON payload, synced flag) |
| `replication_result` | Query result cache for CLI list/status commands |

## CLI Commands

### Register a peer

```bash
stmem replication add-peer http://127.0.0.10:3001 \
  --workspace-id <ws-id> \
  --name my-remote \
  --remote-db spacetime-memory \
  --auth-token "<token>"
```

Or with positional args:

```bash
stmem replication add my-remote http://127.0.0.10:3001 spacetime-memory \
  --workspace-id <ws-id>
```

### List registered peers

```bash
# Alias for 'peers'
stmem replication list --workspace-id <ws-id>

# Original command
stmem replication peers --workspace-id <ws-id>
```

### Show replication status

```bash
stmem replication status --workspace-id <ws-id>

# Watch mode (poll every 5s)
stmem replication status --workspace-id <ws-id> --watch

# JSON output
stmem replication status --workspace-id <ws-id> --output json
```

### Remove a peer

```bash
stmem replication remove <peer-id>
```

### Run a one-time sync

```bash
stmem replication sync --workspace-id <ws-id> --mode both
```

### Start the daemon

```bash
# Foreground
stmem replication daemon --interval 60 --mode both

# Daemonize (fork to background)
stmem replication daemon --interval 60 --mode both --daemonize
```

## Sync Modes

| Mode | Direction |
|------|-----------|
| `push` | Send local unsynced entries → remote |
| `pull` | Fetch remote entries → apply locally |
| `both` | Push then pull (bi-directional) |

## Reducers (Server-Side)

Callable via the SDK's `_call()` method:

| Reducer | Args | Description |
|---------|------|-------------|
| `add_replication_peer` | workspace_id, name, remote_url, remote_db, auth_token | Register a peer |
| `remove_replication_peer` | id | Remove a peer by ID |
| `list_replication_peers` | workspace_id | List peers (result in `replication_result`) |
| `get_replication_status` | workspace_id | Get peer/log counts (result in `replication_result`) |
| `mark_log_synced` | log_ids_json | Mark log entries as synced |
| `get_unsynced_entries` | workspace_id, limit | Get unsynced log entries |
| `replicate_incoming` | workspace_id, peer_id, entries_json | Apply incoming replication data |
| `cleanup_replication_log` | workspace_id | Remove synced entries older than 7 days |

## Setup Guide

### 1. Prerequisites

Two running SpacetimeDB instances (each with the `spacetime-memory` module
published).  Instances must be network-reachable to each other.

### 2. Configure Instance A

```bash
# Register Instance B as a peer on Instance A
stmem replication add-peer http://127.0.0.10:3001 \
  --workspace-id $(stmem workspace list --output json | jq -r '.[0].id') \
  --name instance-b
```

### 3. Configure Instance B (repeat on the other instance)

```bash
stmem replication add-peer http://127.0.0.10:3000 \
  --workspace-id <ws-id-on-b> \
  --name instance-a
```

### 4. Start the daemon on both instances

```bash
stmem replication daemon --interval 30 --mode both
```

The daemon polls the `replication_log` for unsynced entries and exchanges
them with registered peers at the configured interval.

### 5. Verify

```bash
stmem replication status --workspace-id <ws-id>
```

Expected output shows connected peers and unsynced log count approaching zero.

## Security

- Peers are scoped to a **workspace** — each workspace has its own peer list
  and replication log.
- Auth tokens are stored per-peer and sent as `Authorization: Bearer` headers
  on sync requests.
- Use `--auth-token` when registering peers that require authentication.
