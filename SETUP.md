# Setup — for agents

## Prerequisites

- Python 3.10+
- Rust toolchain (rustup)
- wasm32-unknown-unknown target (`rustup target add wasm32-unknown-unknown`)
- SpacetimeDB CLI
- Node.js 20+ (for MCP server)

## Step-by-Step

```bash
# 1. Clone the repo
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory

# 2. Install Python SDK
cd sdk/python
pip install -e .

# 3. Build STDB module
cd ../..
make build-module

# 4. Start SpacetimeDB
make start-stdb

# 5. Run tests
make test
```

## CLI Usage

```bash
# Install CLI
pip install -e sdk/python

# Use stmem
stmem --help
```

## Connector Setup

Spacetime Memory includes a **connector framework** that polls external data
sources (Discord, Notion, GitHub, Slack, Telegram, Twitter/X, RSS, webhooks,
org-mode) and persists events as memories or knowledge-graph nodes.

See the full **[Connector Setup Guide](docs/usage/connectors.md)** for
step-by-step instructions on obtaining and configuring API credentials for
every built-in connector.

For production deployment (Docker, Kubernetes, backups, monitoring, TLS), see the **[Deployment Guide](DEPLOYMENT.md)**.

For more details, see [AGENTS.md](./AGENTS.md).
