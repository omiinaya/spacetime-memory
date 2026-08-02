#!/usr/bin/env python3
"""Check that the environment matches pinned versions.

Usage: scripts/check-version.py

Exits with code 0 if all versions match, non-zero with a message otherwise.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPACETIME_VERSION_FILE = REPO_ROOT / ".spacetime-version"
RUST_TOOLCHAIN_FILE = REPO_ROOT / "server" / "spacetimedb" / "rust-toolchain.toml"

errors: list[str] = []


def check_spacetime() -> None:
    """Check SpacetimeDB CLI version matches .spacetime-version."""
    expected = SPACETIME_VERSION_FILE.read_text().strip()

    try:
        result = subprocess.run(
            ["spacetime", "--version"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        errors.append(f"spacetime CLI not found on PATH (expected v{expected})")
        return

    if result.returncode != 0:
        errors.append(f"spacetime CLI error: {result.stderr}")
        return

    # Parse version from: "spacetimedb tool version 2.4.1; ..."
    match = re.search(r"version (\d+\.\d+\.\d+)", result.stdout)
    if not match:
        errors.append(f"Could not parse spacetime version from:\n{result.stdout}")
        return

    actual = match.group(1)
    if actual != expected:
        errors.append(
            f"Expected SpacetimeDB v{expected}, got v{actual}. "
            f"Update with: spacetime version upgrade  # or update .spacetime-version"
        )

    # Check standalone server version
    try:
        srv_result = subprocess.run(
            ["spacetime", "server", "info", "--server", "http://127.0.0.1:3001"],
            capture_output=True, text=True, timeout=10,
        )
        if srv_result.returncode == 0:
            match = re.search(r"version.*?(\d+\.\d+\.\d+)", srv_result.stdout)
            if match and match.group(1) != expected:
                errors.append(
                    f"Running SpacetimeDB standalone is v{match.group(1)}, "
                    f"expected v{expected}. Restart the server."
                )
    except Exception as e:
        errors.append(f"Could not check server version: {e}")


def check_rust() -> None:
    """Check Rust toolchain version matches rust-toolchain.toml."""
    if not RUST_TOOLCHAIN_FILE.exists():
        errors.append(f"Rust toolchain file not found at {RUST_TOOLCHAIN_FILE}")
        return

    import tomllib
    config = tomllib.loads(RUST_TOOLCHAIN_FILE.read_text())
    expected = config.get("toolchain", {}).get("channel", "")

    try:
        result = subprocess.run(
            ["rustc", "--version"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        errors.append(f"rustc not found on PATH (expected {expected})")
        return

    # Parse: "rustc 1.80.1 (3f5fd8dd4 2024-08-06)"
    match = re.search(r"rustc (\d+\.\d+)", result.stdout)
    if not match:
        errors.append(f"Could not parse rustc version from:\n{result.stdout}")
        return

    major_minor = match.group(1)
    expected_major_minor = ".".join(expected.split(".")[:2])
    if major_minor != expected_major_minor:
        errors.append(
            f"Expected rustc {expected} (major.minor {expected_major_minor}), "
            f"got {major_minor}. Run: rustup update"
        )


def main() -> int:
    print("=== Spacetime Memory — version check ===\n")
    check_spacetime()
    check_rust()

    if errors:
        print("ISSUES FOUND:\n")
        for e in errors:
            print(f"  ✗ {e}")
        print()
        return 1
    else:
        print("  ✓ All versions match pinned values.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
