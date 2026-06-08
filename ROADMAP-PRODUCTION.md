# ⚠️ SUPERSEDED — See ROADMAP.md

This document was written when the project was at v0.3.0 with 95 tests and no Docker verification.

**Current state:** v0.6.0, 181 tests, ACL with JWT, Hermes plugin, Docker compose (untested), 4 adapters.

All items from this old roadmap have been addressed or superseded:

| Old Item | Status |
|----------|--------|
| Phase 0 — Housekeeping (commit, tag v0.3.0) | ✅ Done. We're at v0.6.0 |
| Phase 1.1 — Docker Build | 🟡 Dockerfile + compose exist, never verified |
| Phase 1.2 — JWT Auth | ✅ Done. JWT support in SDK |
| Phase 1.3 — Embedder Error Propagation | ✅ Done. Warnings logged, health check |
| Phase 1.4 — CI Pipeline | ✅ Done. CI passes |
| Phase 2.1 — Full ACL | ✅ Done. JWT + anonymous bypass |
| Phase 2.2 — Backup & Restore | ✅ Done. Reducers + CLI |
| Phase 2.3 — Observability | 🟡 Structured logging added. No metrics dashboard |
| Phase 2.4 — Graceful Degradation | ✅ Done. Retry with backoff |
| Phase 3 — Adapters | 🟡 4 built, source scattered, see ROADMAP.md Q0b |

**For current priorities, see [ROADMAP.md](./ROADMAP.md).**
