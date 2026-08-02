#!/usr/bin/env python3
"""Shim for the stmem CLI package.

Allows running the CLI via `python cli/stmem.py --help` (legacy entry point).
The actual CLI implementation lives in the `cli/stmem/` package.
"""
import sys
from pathlib import Path

# Ensure the cli package is importable
cli_dir = Path(__file__).resolve().parent
if str(cli_dir) not in sys.path:
    sys.path.insert(0, str(cli_dir))

from stmem import cli  # noqa: E402  (sys.path bootstrap above)

if __name__ == "__main__":
    cli()
