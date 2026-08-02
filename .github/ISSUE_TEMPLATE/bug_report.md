---
name: Bug Report
about: Report a bug or unexpected behaviour
title: "[Bug] "
labels: bug
assignees: ''

---

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behaviour:

1. Run command '...'
2. With input '...'
3. See error

**Expected behaviour**
What you expected to happen instead.

**Screenshots / Logs**
If applicable, attach logs or error output.  Enable verbose mode with `-v`.

**Environment (please complete):**
- OS: [e.g. Ubuntu 24.04, macOS 14]
- SpacetimeDB version: `spacetime version`
- stmem version: `stmem --version`
- Python version: `python3 --version`
- Rust version (if building): `rustc --version`

**Configuration**
```json
# Sanitise any sensitive values before pasting
{
  "host": "localhost",
  "port": 3001,
  "db": "spacetime-memory"
}
```

**Additional context**
Any other context about the problem (e.g. network setup, workspace size,
recent changes).
