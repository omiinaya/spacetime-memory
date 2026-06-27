# spacetime-memory MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes
[spacetime-memory](https://github.com/nousresearch/spacetime-memory) as MCP tools
for any MCP-compatible agent (Claude Code, Codex, Cline, etc.).

## Architecture

```
┌──────────────┐    stdio     ┌──────────────┐    HTTP     ┌────────────────┐
│  MCP Client  │ ──────────►  │  MCP Server  │ ──────────► │  SpacetimeDB   │
│  (Agent)     │ ◄──────────  │  (this tool) │ ◄────────── │  (v2.6, WASM)  │
└──────────────┘              └──────────────┘              └────────────────┘
```

The MCP server translates tool calls into SQL queries and reducer calls against
the SpacetimeDB HTTP API (`/v1/database/{db}/sql` and `/v1/database/{db}/call/{reducer}`).

## Configuration

Set these environment variables (or accept defaults):

| Variable | Default | Description |
|---|---|---|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB hostname |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database name |

## Tools — Complete Catalog (128 tools)

### 🔧 Workspace

| Tool | Description | Parameters |
|---|---|---|
| `create_workspace` | Create a new workspace | `name`, `description` |
| `list_workspaces` | List all workspaces | _(none)_ |
| `delete_workspace` | Delete a workspace and all its data | `workspace_id` |

### 🧠 Memory — CRUD

| Tool | Description | Parameters |
|---|---|---|
| `store_memory` | Store a new memory with optional tier override | `workspace_id`, `peer_id`, `observer_id`, `memory_type`, `content`, `summary`, `entities_json`, `confidence`, `source_session_id`, `source_message_id`, `tier` |
| `get_memory` | Retrieve a single memory by its ID (auto-reinforces) | `id` |
| `update_memory` | Update a memory's content, summary, and/or confidence | `memory_id`, `content`, `summary`, `confidence` |
| `delete_memory` | Hard-delete a memory by ID | `memory_id` |
| `list_memories` | List active memories, newest first | `workspace_id`, `memory_type`, `limit` |
| `store_batch` | Store multiple memories in a single batch call | `items_json`, `workspace_id` |
| `get_memory_history` | Get version history for a memory | `memory_id` |
| `reinforce_memory` | Increment access_count and bump strength | `memory_id` |
| `rate_memory` | Rate a memory 1-5 to adjust trust score | `memory_id`, `rating`, `peer_id` |

### 🔄 Memory — Management

| Tool | Description | Parameters |
|---|---|---|
| `escalate_memories` | Batch-escalate memory tiers (L2→L1→L0) | `workspace_id`, `l2_to_l1`, `l1_to_l0` |
| `dedup_memories` | Dedup near-duplicate memories (cosine ≥0.85 + edit dist ≤30%) | `workspace_id` |
| `suggest_merges` | Find candidate merge pairs | `workspace_id`, `threshold` |
| `approve_merge` | Approve a pending merge | `suggestion_id` |
| `reject_merge` | Reject a pending merge | `suggestion_id` |
| `set_memory_scope` | Set user-scope on a memory for user-level isolation | `memory_id`, `user_scope` |
| `batch_update_memories` | Batch-update multiple memories with same field changes | `workspace_id`, `memory_ids_json`, `updates_json` |

### 🔍 Search

| Tool | Description | Parameters |
|---|---|---|
| `search_memories` | Keyword search with optional filters | `workspace_id`, `query_text`, `memory_type`, `tier`, `limit`, `rerank`, `entity_types`, `before`, `after` |
| `hybrid_search` | Multi-strategy hybrid search (memories + KG + temporal) | `workspace_id`, `query_text`, `memory_type`, `tier`, `limit`, `strategies`, `rerank`, `entity_types`, `before`, `after` |
| `search_with_filters` | Search with metadata + location filters | `workspace_id`, `query`, `memory_type`, `tier`, `metadata_filter`, `location_filter`, `limit` |
| `fuzzy_get` | Closest-matching memory via difflib string similarity | `workspace_id`, `name`, `field`, `threshold`, `limit` |
| `glob_get` | Find memories matching a glob (fnmatch) pattern | `workspace_id`, `pattern`, `field`, `limit` |
| `recommend_memories` | Recommend memories needing attention | `workspace_id`, `limit`, `min_urgency` |
| `find_near_duplicates` | Find semantically similar memories to given text | `content`, `workspace_id`, `threshold`, `limit` |
| `search_sessions_semantic` | Semantic search across all sessions | `query`, `limit` |
| `search_profiles` | Search profiles via static_facts / dynamic_context | `workspace_id`, `query`, `limit` |

### 🧩 Pattern Detection

| Tool | Description | Parameters |
|---|---|---|
| `detect_patterns` | Run pattern detection (clusters, terms, co-occurrence) | `workspace_id`, `limit`, `include_clusters`, `include_terms`, `include_co_occur` |

### 🌲 Context Management (QMD-style)

| Tool | Description | Parameters |
|---|---|---|
| `set_workspace_context` | Attach context to a workspace | `workspace_id`, `context` |
| `set_memory_context` | Attach context to a memory | `memory_id`, `context` |
| `get_context_chain` | Return context chain: workspace + memory context | `memory_id` |
| `list_context_packs` | List all context packs in a workspace | `workspace_id` |
| `list_context_entries` | List entries in a context pack | `pack_id` |
| `list_context_deltas` | List delta entries between two context packs | `previous_pack_id` |

### 📝 Notes (LLM Wiki)

| Tool | Description | Parameters |
|---|---|---|
| `create_note` | Create a wiki note (auto-embeds if `embed=True`) | `workspace_id`, `title`, `content`, `note_date`, `embed` |
| `get_note` | Get a note by ID | `note_id` |
| `update_note` | Update a wiki note (re-embeds on content change if embed=True) | `note_id`, `title`, `content`, `embed` |
| `delete_note` | Delete a note by ID | `note_id` |
| `list_notes` | List all notes in a workspace | `workspace_id` |
| `get_note_by_title` | Find a note by title | `title` |
| `get_note_by_date` | Find notes by ISO-8601 date | `note_date` |
| `get_note_history` | Get revision history for a note | `note_id` |
| `get_backlinks` | Get [[wiki-links]] backlinks pointing to a note | `note_id` |
| `get_outgoing_links` | Get outgoing [[wiki-links]] from a note | `note_id` |

### 📄 Documents

| Tool | Description | Parameters |
|---|---|---|
| `create_document` | Create a document with auto-chunking | `workspace_id`, `title`, `content`, `content_type`, `file_path`, `source_url`, `metadata_json` |
| `get_document` | Get a document by ID | `doc_id` |
| `list_documents` | List all documents in a workspace | `workspace_id` |
| `get_document_chunks` | Get all chunks for a document | `doc_id` |
| `delete_document` | Delete a document + all chunks (cascading) | `doc_id` |

### 👤 Profile

| Tool | Description | Parameters |
|---|---|---|
| `get_profile` | Retrieve a peer's profile | `peer_id` |
| `upsert_profile` | Create or update a peer profile | `peer_id`, `static_facts_json`, `dynamic_context_json`, `preferences_json`, `tags_json` |
| `list_profiles` | List all profiles in a workspace | `workspace_id` |
| `add_dynamic_context` | Add dynamic context mid-session | `peer_id`, `context` |
| `add_profile_fact` | Append a fact to a peer's profile | `peer_id`, `fact` |
| `get_profile_context` | Get computed profile context for a peer | `peer_id` |
| `get_peer_reputation` | Get reputation stats for a peer | `peer_id` |

### 🕸️ Knowledge Graph — Base

| Tool | Description | Parameters |
|---|---|---|
| `create_node` | Create a KG node and index for semantic search | `workspace_id`, `label`, `node_type`, `summary`, `metadata_json` |
| `update_node` | Update a KG node's mutable fields | `node_id`, `label`, `node_type`, `summary`, `metadata_json`, `source_memory_id` |
| `create_edge` | Create a directed, typed KG edge | `workspace_id`, `source_node_id`, `target_node_id`, `relation`, `weight`, `confidence`, `metadata_json`, `source_memory_id` |
| `add_node_citation` | Link a KG node to a supporting memory | `workspace_id`, `node_id`, `memory_id`, `description` |
| `add_edge_citation` | Link a KG edge to a supporting memory | `workspace_id`, `edge_id`, `memory_id`, `description` |
| `get_citations` | Get all citations for a KG entity | `workspace_id`, `entity_id`, `entity_type` |
| `query_graph` | Search KG nodes by label | `workspace_id`, `query` |
| `get_node` | Get a KG node by ID | `id` |
| `get_neighbors` | Get all edges (neighbors) for a node | `node_id` |
| `get_community` | Get community details + node list | `community_id` |

### 📊 KG — Analytics

| Tool | Description | Parameters |
|---|---|---|
| `compute_pagerank` | Compute PageRank centrality for all nodes | `workspace_id`, `damping`, `max_iterations` |
| `compute_community_hierarchy` | Build hierarchical community dendrogram | `workspace_id` |
| `compute_kg_stats` | Compute KG statistics | `workspace_id` |
| `detect_communities` | Run label-propagation community detection | `workspace_id` |
| `seed_communities` | Seed unassigned nodes into new communities | `workspace_id` |
| `detect_bridge_nodes` | Detect bridge nodes connecting communities | `workspace_id`, `limit`, `min_communities` |

### 🔗 Graph Traversal

| Tool | Description | Parameters |
|---|---|---|
| `graph_bfs` | BFS traverse the KG from a node | `workspace_id`, `start_node_id`, `max_depth` |
| `shortest_path` | Find shortest path between two KG nodes | `workspace_id`, `source_id`, `target_id`, `max_hops` |

### 👤 Entity Resolution

| Tool | Description | Parameters |
|---|---|---|
| `resolve_entity` | Resolve an entity name within a workspace | `workspace_id`, `name` |
| `add_alias` | Add an alias to an existing entity link | `entity_link_id`, `alias` |
| `create_entity_link` | Create a canonical entity link (mem0-style) | `workspace_id`, `canonical_name`, `entity_type`, `description` |

### 🗺️ Tours

| Tool | Description | Parameters |
|---|---|---|
| `create_tour` | Create a guided tour through KG nodes | `workspace_id`, `title`, `description` |
| `add_tour_stop` | Add a stop to an existing tour | `tour_id`, `node_id`, `heading`, `description` |
| `delete_tour` | Delete a tour and all its stops | `tour_id` |
| `delete_tour_stop` | Remove a single stop from a guided tour | `stop_id` |

### 💬 Sessions

| Tool | Description | Parameters |
|---|---|---|
| `get_peer_sessions` | List sessions for a peer | `peer_id` |
| `get_session_messages` | Get messages for a session | `session_id` |
| `add_agent_step` | Record an agent reasoning step | `session_id`, `workspace_id`, `step_type`, `content`, `summary` |
| `get_session_steps` | Get all reasoning steps for a session | `session_id` |
| `get_agent_context` | Retrieve context for an agent prompt | `workspace_id`, `query`, `session_id`, `top_k` |

### 🧠 Mental Models

| Tool | Description | Parameters |
|---|---|---|
| `synthesize_mental_models` | Synthesize a mental model from source memories | `workspace_id`, `memory_ids_json` |
| `get_mental_model` | Get a mental model by ID | `id` |
| `list_mental_models` | List mental models (filtered by status) | `workspace_id`, `status` |

### 📋 Facts

| Tool | Description | Parameters |
|---|---|---|
| `add_fact` | Add a fact about a peer | `workspace_id`, `peer_id`, `content`, `fact_type`, `category`, `confidence`, `source`, `tier` |
| `list_facts` | List facts with optional filters | `workspace_id`, `peer_id`, `fact_type`, `tier`, `category` |

### 📂 Directory (Context Directory Tree)

| Tool | Description | Parameters |
|---|---|---|
| `create_directory` | Create a directory in the context tree | `workspace_id`, `name`, `path`, `parent_id`, `description` |
| `traverse_directory` | Recursively traverse directory tree | `workspace_id`, `root_directory_id` |
| `list_directory` | List children of a directory | `directory_id` |
| `get_directory` | Get directory by ID or path | `workspace_id`, `path_or_id` |
| `link_memory_to_directory` | Link a memory to a directory | `directory_id`, `memory_id`, `workspace_id` |
| `unlink_memory_from_directory` | Unlink a memory from a directory | `directory_id`, `memory_id` |

### 🔐 Access Control

| Tool | Description | Parameters |
|---|---|---|
| `grant_space_access` | Grant a peer access to a workspace | `workspace_id`, `peer_id`, `permission` |
| `revoke_space_access` | Revoke a peer's access to a workspace | `workspace_id`, `peer_id` |
| `list_space_members` | List members + permissions for a workspace | `workspace_id` |
| `create_api_key` | Create a new API key | `workspace_id`, `name`, `permissions` |
| `deactivate_api_key` | Revoke an API key | `key_id` |
| `list_api_keys` | List API keys | `workspace_id` |

### 🧩 Compounder (LLM Wiki)

| Tool | Description | Parameters |
|---|---|---|
| `ingest_source` | Full LLM Wiki ingest: summarize, extract entities, create KG nodes, link, ripple, contradictions | `source_text`, `source_title`, `workspace_id`, `source_type` |
| `create_entity_page` | Create entity wiki page + KG node with YAML frontmatter | `name`, `description`, `entity_type`, `workspace_id` |
| `update_entity_page` | Update existing entity wiki page + KG node | `name`, `description`, `entity_type`, `workspace_id` |
| `create_concept_page` | Create concept wiki page with [[wiki-links]] | `concept`, `definition`, `workspace_id`, `related_concepts` |
| `create_comparison_page` | Create comparison wiki page with markdown table | `title`, `items`, `workspace_id`, `criteria` |
| `lint_workspace` | Health-check the workspace wiki | `workspace_id`, `check_contradictions` |
| `generate_overview` | Generate _overview synthesis page | `workspace_id` |
| `search_entities` | Search KG entities with flexible filters | `workspace_id`, `label`, `node_type`, `semantic_query`, `limit` |
| `cross_link` | Auto-link related but unconnected memories | `workspace_id` |
| `suggest_connections` | Find KG node pairs that should be linked | `workspace_id` |
| `store_answer` | Persist an LLM-synthesized answer as wiki page | `query`, `answer`, `workspace_id`, `source_memory_ids` |
| `store_answers_batch` | Batch-persist multiple LLM answers as wiki pages | `qa_pairs_json`, `workspace_id`, `source_memory_ids` |
| `export_workspace` | Export notes as markdown files with YAML frontmatter | `output_dir`, `workspace_id`, `include_kg`, `include_system_notes` |

### 🔧 Maintenance

| Tool | Description | Parameters |
|---|---|---|
| `run_maintenance` | Trigger periodic maintenance routines | _(none)_ |
| `check_embedder_health` | Check if the embedder sidecar is running | _(none)_ |
| `backup` | Backup user data tables to a JSON file | `workspace_id`, `output_path` |
| `restore` | Restore data from a backup JSON file | `input_path` |
| `org_sync` | One-shot sync of .org files to wiki | `workspace_id`, `directory`, `dry_run` |

### 📈 Decay Model

| Tool | Description | Parameters |
|---|---|---|
| `set_decay_model` | Configure the decay model for a workspace | `workspace_id`, `model`, `decay_rate`, `max_days`, `weibull_shape`, `weibull_scale` |
| `get_decay_config` | Get current decay configuration | `workspace_id` |

### 🌐 Peers

| Tool | Description | Parameters |
|---|---|---|
| `list_peers` | List all peers (filtered by workspace) | `workspace_id` |
| `get_user_memories` | Get memories scoped to a user | `user_scope`, `workspace_id` |

### ⚙️ System

| Tool | Description | Parameters |
|---|---|---|
| `health_check` | Check health of all system components | _(none)_ |
| `get_metrics` | Get operational metrics for monitoring | _(none)_ |
| `ping` | Check connectivity to SpacetimeDB | _(none)_ |

## Running

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run (stdio transport)
python3 main.py
```

For testing with an MCP client:

```bash
# Check the server starts and prints its capabilities
python3 -c "import json, subprocess; p=subprocess.run(['python3','main.py'], input=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'0.1.0'}}})+'\n", capture_output=True, text=True); print(p.stdout[:2000]); print(p.stderr[:500])"
```

## Requirements

- Python 3.10+
- `mcp` (MCP SDK)
- `httpx` (HTTP client)
- A running SpacetimeDB instance with the spacetime-memory module published
