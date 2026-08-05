# Spacetime Memory — Improvement Backlog (July 2, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Recently Completed

*(None pending cleanup — 9 completed items verified in-tree and removed 2026-08-05:
the 7-item July 2026 batch (NoteRecord TS interface fields, user-management
SDK wrappers, OTel metrics reader, connector/entity-extraction/harmonic-beliefs
SDK+CLI, `search_by_tags`, semantic-strategy client-side cosine, `batch_tag_memories`
/`batch_untag_memories`), plus the STDB 2% fatal-error concurrency fix (commit
46300149, 12,500 concurrent stores → 0 fatal) and the Frontend/Web UI (client/
SPA, 34 vitest files / 97 tests passing, `dist/` built).)*

---

## Pending

*(No pending items at this time.)*

---

## Deferred / Blocked

### P1: TypeScript — Publish to npm (BLOCKED — scope/account ownership, not secrets)
The original blocker is RESOLVED: NPM_TOKEN has been set in GitHub secrets (2026-07-16).
Re-running the workflow (run 28841505323) now passes auth, build, and all 338 vitest tests,
but `npm publish` fails with `404 Not Found - PUT https://registry.npmjs.org/@omiinaya/spacetime-memory`.
The `@omiinaya` scope has 0 packages on the registry and the token's npm account does not
own the scope. Fix options (owner decision): publish under the token account's own
user-scope name, rename the package (e.g. unscoped `spacetime-memory` — name is available),
or create/join an `@omiinaya` npm org with the token's account as a maintainer.
Files: sdk/typescript/package.json, .github/workflows/npm-publish.yml
Difficulty: Easy
Est: 15min

### No managed cloud (BLOCKED — strategic decision, not code)
Every competitor has a managed option. Self-hosting is correct for current use case.
Difficulty: Hard
