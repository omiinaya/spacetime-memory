# Spacetime Memory — Improvement Backlog (July 2, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Recently Completed

*(None pending cleanup — 7 completed items from the July 2026 batch verified
in-tree and removed 2026-08-05: NoteRecord TS interface fields, user-management
SDK wrappers, OTel metrics reader, connector/entity-extraction/harmonic-beliefs
SDK+CLI, `search_by_tags`, semantic-strategy client-side cosine, `batch_tag_memories`
/`batch_untag_memories`.)*

---

## Pending

*(No pending items at this time.)*

---

## Deferred / Blocked

### P1: TypeScript — Publish to npm (BLOCKED — needs GitHub secrets)
npm publish workflow exists but NPM_TOKEN hasn't been set in GitHub secrets.
Files: sdk/typescript/package.json, .github/workflows/npm-publish.yml
Difficulty: Easy
Est: 15min

### STDB 2% fatal error under heavy concurrent load (BLOCKED — no live STDB for stress testing)
Remaining root cause appears to be STDB-level WASM limitation.
Deferred until live STDB infrastructure is available.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard

### Frontend / Web UI (BLOCKED — not started, 1-2 week effort)
Zero web UI code exists. React/Vite SPA needed for dashboard, workspace management, KG explorer, note editor.
No code to block on — just not started.
Difficulty: Hard

### No managed cloud (BLOCKED — strategic decision, not code)
Every competitor has a managed option. Self-hosting is correct for current use case.
Difficulty: Hard