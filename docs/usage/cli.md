# CLI Commands

The `stmem` CLI provides terminal access to all Spacetime Memory features.

## Installation

```bash
pip install -e sdk/python
# CLI is available as `stmem`
stmem --help
```

## Global Options

| Flag | Description |
|------|-------------|
| `--output, -o` | Output format: `table` (default), `json`, or `csv` |
| `--quiet, -q` | Suppress non-error output |
| `--no-header` | Skip header row in CSV output |
| `--compact-json` | Compact JSON output (no indentation) |
| `--no-color` | Disable colored output |
| `--verbose, -v` | Show raw error messages instead of friendly ones |

## Configuration

The CLI reads these environment variables:

- `STMEM_HOST` / `SPACETIMEDB_HOST` (default: `localhost`)
- `STMEM_PORT` / `SPACETIMEDB_PORT` (default: `3001`)
- `STMEM_DB` / `SPACETIMEDB_DB` (default: `spacetime-memory`)
- `EMBEDDER_URL` (default: `http://localhost:9090`)

## Workspace Commands

```bash
# Create a workspace
stmem workspace create my-app "My application workspace"

# List workspaces
stmem workspace list
```

## Peer Commands

```bash
# Create a peer (user, agent, or entity)
stmem peer create <workspace-id> alice user

# List peers in a workspace
stmem peer list <workspace-id>
```

## Memory Commands

```bash
# Store a memory
stmem memory store <workspace-id> <peer-id> "I like pizza"

# With options
stmem memory store <ws-id> <peer-id> "I like pizza" \
    --memory-type experience \
    --summary "Food preference" \
    --confidence 0.9 \
    --tier L1

# Search memories
stmem memory search <workspace-id> "food preferences"

# Watch mode (poll every 5s)
stmem memory search <workspace-id> "food preferences" --watch

# With filters
stmem memory search <ws-id> "pizza" --memory-type experience --tier L1 --limit 20
```

## Session Commands

```bash
# Create a session
stmem session create <workspace-id> <session-id>

# List sessions
stmem session list <workspace-id>

# Send a message
stmem session message <workspace-id> <session-id> <peer-id> "Hello!"
```

## Knowledge Graph Commands

```bash
# Create a node
stmem kg node create <workspace-id> Alice person '{"key": "value"}'

# List nodes
stmem kg node list <workspace-id>

# Create an edge
stmem kg edge create <workspace-id> <src-id> <tgt-id> likes 0.95

# Search the graph
stmem kg search <workspace-id> "Alice"

# Traverse (BFS)
stmem kg bfs <workspace-id> <node-id> --max-hops 3
```

## Profile Commands

```bash
# Upsert a profile
stmem profile upsert <workspace-id> <peer-id>

# Add a fact to a profile
stmem profile fact <workspace-id> <peer-id> "Likes hiking"

# Get dynamic context
stmem profile context <workspace-id> <peer-id>
```

## Space Commands (Permissions)

```bash
# List members in a workspace
stmem space members <workspace-id>

# Grant access
stmem space grant <workspace-id> <peer-id> editor

# Revoke access
stmem space revoke <workspace-id> <peer-id>
```

## Connector Commands

```bash
# List available connectors
stmem connector list

# Run a connector
stmem connector run discord

# Start a connector in daemon mode
stmem connector start discord
```

## Alias Management

```bash
# Create an alias
stmem alias set ll "memory list --tier L0"

# List aliases
stmem alias list

# Remove an alias
stmem alias remove ll
```

## Shell Completion

```bash
# Generate completion script for your shell
eval "$(stmem completion bash)"   # bash
eval "$(stmem completion zsh)"    # zsh
stmem completion fish | source    # fish
```

## Output Formats

All commands support `--output json` for programmatic use:

```bash
stmem memory search <ws-id> "pizza" --output json
stmem workspace list --output csv
```
