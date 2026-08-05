# Security Policy

## Supported Versions

Only the current `main` branch receives security fixes. Releases are tagged
(`v1.x.y`) and are supported until the next release supersedes them.

| Version | Supported          |
|---------|--------------------|
| main    | ✅ Active development |
| v1.x    | ✅ Bugfixes via `main` |
| < 1.0   | ❌ No longer supported |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report privately via one of:

- **GitHub Private Vulnerability Reporting** — the preferred channel.
  On the repository page go to *Security → Report a vulnerability*.
- **Email** the maintainer directly (address in the git commit history /
  `git log --format='%ae'`).

Please include:

1. The affected file(s) and line number(s), or a minimal reproduction.
2. The impact (what an attacker could do).
3. Whether the issue is publicly known.

You should receive an acknowledgment within **48 hours**. We aim to ship a
fix or a mitigation within **7 days** for high-severity issues.

## Security Notes for This Project

### SpacetimeDB publishing (READ THIS)

- **Never publish with `--delete-data`** — not even `--delete-data=on-conflict`
  or `--delete-data=always`. A schema change can otherwise silently wipe
  production data. The project's `scripts/publish.sh` enforces
  `--delete-data=never` automatically.
- SpacetimeDB identity tokens (e.g. `~/.config/spacetime/cli.toml`,
  `scripts/.cron_identity_token`) are **credentials** — never commit them.
  They are gitignored; keep them that way.

### Secrets in the repo

- No API keys, tokens, or private keys are committed (verified with
  [gitleaks](https://github.com/gitleaks/gitleaks) on every release).
- `.env` files and `data/id_ecdsa*` are gitignored. If you add a new secret
  file, add it to `.gitignore` **before** committing it.

### Authentication

- The module uses PBKDF2 password hashing for accounts and per-account API
  keys (`ApiKey` table). Never log passwords, tokens, or key material.
- The optional JWT integration signs tokens with a private key configured on
  the server; rotate it on a schedule and never commit it.

## Reporting Process

1. Reporter sends a private disclosure (above).
2. Maintainer triages, confirms scope, and acknowledges within 48h.
3. Fix is developed on a private branch, then merged to `main`.
4. A patch release is tagged and the advisory is disclosed (with credit to
   the reporter if desired) after the fix ships.

## Automated Security Checks

CI runs:

- **gitleaks** secret scan on every push.
- **cargo-deny** advisory + license + ban checks on all Rust crates.
- **ruff** lint on Python (SDK + CLI).
- `cargo clippy -D warnings` on the SpacetimeDB module.
