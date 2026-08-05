## Description

<!-- What does this PR do? Why? -->

Fixes #...

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change (schema, reducer signature, or API surface)
- [ ] Documentation
- [ ] Benchmark / performance
- [ ] Refactor (no behaviour change)

## Checklist

### Quality gates
- [ ] `make test-unit` passes (Python SDK unit tests, no STDB required)
- [ ] `make test-rust` passes (Rust module tests)
- [ ] `make lint` passes (ruff + clippy)
- [ ] `cargo deny check` passes in `server/spacetimedb`, `server/embedder`, and `server/tantivy-sidecar` (if Rust changed)
- [ ] `npx vitest run` passes in `sdk/typescript` and `client` (if TS changed)

### Schema changes (if any)
- [ ] Schema changes are **additive only** — see [SCHEMA_EVOLUTION_POLICY.md](SCHEMA_EVOLUTION_POLICY.md)
- [ ] New fields have reducer-level defaults; no migrations introduced
- [ ] `tests/data/schema_baseline.json` updated via `scripts/update_schema_baseline.py`
- [ ] New/changed reducers are covered by tests

### Security
- [ ] No secrets, tokens, API keys, or private IPs introduced (repo is scanned by gitleaks in CI)
- [ ] No `--delete-data` anywhere in publish instructions or scripts
- [ ] No `/home/<user>` or machine-specific absolute paths added

### Docs
- [ ] README / CONFIG / relevant docs updated if user-facing behaviour changed
- [ ] CHANGELOG.md entry added (if applicable)

### Commit hygiene
- [ ] Author AND committer are both `omiinaya <omiinaya@gmail.com>`
- [ ] No unrelated changes mixed in

## Test plan

<!-- What did you run to verify this works? Include commands + output summaries. -->

## Related issues / PRs
