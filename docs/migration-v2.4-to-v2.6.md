# Migration Guide: SpacetimeDB v2.4 → v2.6

Upgrading Spacetime Memory from STDB v2.4.x to v2.6.x. This guide covers
the breaking changes, infrastructure updates, and verification steps.

> **Why v2.6?** STDB v2.6 brings performance improvements, fixes several
> scheduler reliability issues, and is the minimum version required for
> ongoing module development. See the [SpacetimeDB
> changelog](https://github.com/clockworklabs/SpacetimeDB/releases) for
> the full upstream release notes.

---

## Overview

| Item | v2.4.x | v2.6.x |
|------|--------|--------|
| spacetimedb crate | `=2.4.1` | `"2.6"` |
| CLI binary | v2.4.1 | v2.6.0+ |
| Server image | `clockworklabs/spacetimedb:v2.4.1` | `clockworklabs/spacetimedb:v2.6.1` |
| Value-returning reducers | Supported | **Removed** |
| `scheduled(reducer_name)` | Works in most cases | Fully supported, verified |

---

## Breaking Changes

### 1. Value-Returning Reducers Removed

v2.6 no longer supports reducers that return values to the caller.
Any existing value-returning reducer must be converted to a void
reducer, and the caller must use `_query` instead.

**Affected code** — `list_tags` in `server/spacetimedb/src/tag.rs`:

```rust
// v2.4: value-returning
#[reducer]
pub fn list_tags(ctx: &ReducerContext, workspace_id: String) -> Result<Vec<Tag>, String> {
    // ...
}
```

```rust
// v2.6: void reducer — SDK queries the `tag` table directly
#[reducer]
pub fn list_tags(ctx: &ReducerContext, _workspace_id: String) -> Result<(), String> {
    trace_span!(ctx, "list_tags", TracingSpanKind::Read, &_workspace_id, {
        let _account = require_auth(ctx)?;
        // Auth-gated identity verification only.
        // SDK now uses `_query("tag", workspace_id=ws, columns=[...])`.
        Ok(())
    })
}
```

**SDK migration** — replace reducer calls with direct table queries:

```python
# v2.4
tags = client._call("list_tags", [workspace_id])

# v2.6
tags = client._call("_query", [
    "tag",
    workspace_id,
    {"columns": ["tag_id", "name", "color", "created_at"]}
])
```

### 2. `scheduled()` Syntax Confirmed

The v2.6 SDK validates the `scheduled(reducer_name)` attribute.
Ensure your scheduled reducers use the correct syntax:

```rust
#[spacetimedb::table(name = maintenance_schedule, scheduled(run_maintenance))]
pub struct MaintenanceSchedule {
    #[primary_key]
    pub schedule_id: u64,
    pub interval_secs: u64,
    // ...
}
```

This was already verified working in this codebase — the
`maintenance_schedule` reducer runs `run_maintenance` which triggers
decay + dedup. The `require_admin` guard was removed from the scheduled
reducer because the scheduler calls with module identity, not a
registered admin account.

---

## Step-by-Step Migration

### Step 1: Update the SpacetimeDB CLI

```bash
# Download v2.6.0+ (adjust URL for your architecture)
curl -fsSL \
  https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.6.0/spacetime-x86_64-unknown-linux-gnu.tar.gz \
  | tar xz -C /usr/local/bin/

# Verify
spacetime version
```

### Step 2: Update `.spacetime-version`

The repo root file pins the expected CLI version:

```bash
echo "2.6.1" > .spacetime-version
```

### Step 3: Update `Cargo.toml`

```toml
# server/spacetimedb/Cargo.toml
[dependencies]
spacetimedb = { version = "2.6" }
```

If pinned to an exact version, unpin:

```toml
# OLD: spacetimedb = { version = "=2.4.1" }
# NEW: spacetimedb = { version = "2.6" }
```

### Step 4: Resolve the Lockfile

```bash
cd server/spacetimedb
cargo update -p spacetimedb
```

This regenerates `Cargo.lock` with v2.6 dependencies. If `cargo update`
hits resolution failures, check that all transitive dependencies are
compatible with the v2.6 SDK.

### Step 5: Handle Breaking Changes

**Check for value-returning reducers.** Scan the Rust source for
reducers that return a non-`Result<(), String>` type:

```bash
cd server/spacetimedb/src
grep -rn 'pub fn [a-z_]\+.*-> Result<[^,], String>' --include='*.rs'
```

Each match must be converted to a void reducer (see Breaking Changes
above). Update corresponding SDK callers to use `_query` instead.

**Check for `require_admin` on scheduled reducers.** The scheduler
identity (module) is not an admin account. Remove `require_admin`
guards from any `#[scheduled]` reducer:

```bash
# Find scheduled reducers
grep -rn 'scheduled(' --include='*.rs'
```

### Step 6: Verify Scheduled Reducer Syntax

If you deleted the database between v2.4 and v2.6 (e.g. on dev/staging),
the scheduled reducer table will be recreated on publish. Verify the
syntax compiles:

```bash
cd server/spacetimedb
cargo build --release --target wasm32-unknown-unknown 2>&1 | \
  grep -E 'error|warning|scheduled|maintenance'
```

### Step 7: Rebuild and Publish the WASM Module

```bash
# Build the WASM module
CARGO_BUILD_JOBS=2 cargo build --release --target wasm32-wasip1

# Publish
spacetime publish --project-path server/spacetimedb spacetime-memory

# Verify reducers are registered
spacetime logs
```

### Step 8: Update Docker Infrastructure

**`Dockerfile`** — update both download URLs:

```dockerfile
# Stage 2 (module-builder)
RUN curl -fsSL \
  https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.6.0/spacetime-x86_64-unknown-linux-gnu.tar.gz \
  | tar xz -C /usr/local/bin/

# Stage 4 (runtime)
RUN curl -fsSL \
  https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.6.0/spacetime-x86_64-unknown-linux-gnu.tar.gz \
  | tar xz -C /usr/local/bin/
```

**`compose.yaml`** — update the default version variable:

```yaml
# SPACETIMEDB_VERSION — SpacetimeDB version (default: 2.6.1)
```

**`docker-compose.yml`** — update production image tag:

```yaml
services:
  spacetimedb:
    image: clockworklabs/spacetimedb:v2.6.1
```

### Step 9: Update CI Configuration

In `.github/workflows/ci.yml`, update the cache key and download URL:

```yaml
- name: Cache SpacetimeDB binary
  uses: actions/cache@v4
  with:
    path: /usr/local/bin/spacetime
    key: stdb-${{ runner.os }}-v2.6.0

- name: Install SpacetimeDB
  run: |
    curl -sSL \
      https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.6.0/spacetime-x86_64-unknown-linux-gnu.tar.gz \
      | sudo tar xz -C /usr/local/bin
```

### Step 10: Update DEPLOYMENT.md

Replace all v2.4.1 references with v2.6.1:

```markdown
- SpacetimeDB CLI v2.6+ (see `.spacetime-version`)
```

```bash
curl -fsSL \
  https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.6.1/spacetime-linux-x86_64.tgz \
  | tar xz -C /usr/local/bin/
```

And in the production hardening section:

```yaml
image: clockworklabs/spacetimedb:v2.6.1
```

---

## Verification Checklist

- [ ] `spacetime version` shows v2.6.x
- [ ] `cargo build --release --target wasm32-unknown-unknown` succeeds
- [ ] Module publishes without errors (`spacetime publish`)
- [ ] `spacetime logs` shows all expected reducers registered
- [ ] Python SDK integration tests pass: `make test-integration`
- [ ] Python SDK unit tests pass: `make test`
- [ ] Docker build succeeds: `docker build -t spacetime-memory .`
- [ ] Frontend connects and queries work
- [ ] Value-returning reducers (e.g. `list_tags`) no longer called
- [ ] Scheduled reducers fire correctly (check `maintenance_schedule`)
- [ ] Embedder + Tantivy sidecars respond to health checks

---

## Rollback

If the upgrade fails, revert to v2.4.1:

```bash
# CLI
curl -fsSL \
  https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.4.1/spacetime-x86_64-unknown-linux-gnu.tar.gz \
  | tar xz -C /usr/local/bin/

# Cargo.toml
spacetimedb = { version = "=2.4.1" }

# Rebuild with old SDK
cargo update -p spacetimedb
cargo build --release --target wasm32-unknown-unknown

# Server — restart with v2.4.1 Docker image
docker compose down
# Update compose.yaml image tag to v2.4.1
docker compose up -d

# Re-publish the v2.4.1 module
spacetime publish --project-path server/spacetimedb spacetime-memory
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `cargo update` fails | Transitive dep incompatible with v2.6 | Pause workspace crates, update individually |
| WASM build fails with `spacetimedb-lib` errors | CLI version mismatch | Ensure `spacetime version` shows v2.6.x |
| `scheduled` reducer not firing | DB was created with old module state | Verify `maintenance_schedule` table exists after publish |
| Python SDK returns `ReducerError` for `list_tags` | Caller still using value-returning call | Replace with `_query("tag", ...)` |
| Docker build downloads wrong CLI | URL not updated in Dockerfile | Check both `module-builder` and `runtime` stages |
