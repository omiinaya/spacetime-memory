#!/usr/bin/env python3
"""Self-test for scripts/audit_schema_history.py — the git-history append-only
audit (SCHEMA_EVOLUTION_POLICY.md "Non-Additive Changes (Breaking)").

Builds throwaway git repos with synthetic module history and asserts the
audit's exit codes:

  * append-only growth                       -> 0
  * allowed T -> Option<T> transition        -> 0
  * breaking change, no exception            -> 1 (detected)
  * breaking change, VALID exception         -> 0 (documented + restored)
  * breaking change, INVALID (not restored)  -> 1 (cannot hide a live break)
  * STALE exception (matches nothing)        -> 1 (allowlist hygiene)
  * table removal                            -> 1 (detected)

Negative cases prove the detector still distinguishes clean from breaking;
positive exception cases prove the allowlist only forgives documented,
restored corrections.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "scripts" / "audit_schema_history.py"
LIB_SRC = REPO / "sdk" / "python" / "tests" / "schema_policy_lib.py"


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--repo", str(repo), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def make_repo(base: Path, commits: list[tuple[str, str]]) -> Path:
    """Create a temp repo with one lib.rs per commit.

    commits: [(subject, lib_rs_content), ...] — each becomes a commit.
    """
    repo = base / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Self Test")
    src = repo / "server" / "spacetimedb" / "src"
    src.mkdir(parents=True)
    for subject, content in commits:
        (src / "lib.rs").write_text(content, encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", subject)
    # the audit imports schema_policy_lib from the target repo
    (repo / "sdk" / "python" / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copy2(LIB_SRC, repo / "sdk" / "python" / "tests" / "schema_policy_lib.py")
    return repo


def write_exceptions(repo: Path, exceptions: list[dict]) -> None:
    data = repo / "sdk" / "python" / "tests" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "schema_history_transient_exceptions.json").write_text(
        json.dumps({"_doc": "self-test", "exceptions": exceptions}, indent=2),
        encoding="utf-8",
    )


T1 = "#[table(name = thing, public)]\nstruct Thing {\n    pub id: u64,\n    pub name: String,\n}\n"
T1_PLUS_AGE = T1.replace("    pub name: String,", "    pub name: String,\n    pub age: u32,")
T1_NAME_OPTION = T1.replace("pub name: String,", "pub name: Option<String>,")
T1_NO_NAME = T1.replace("    pub name: String,\n", "")
T1_NAME_U64 = T1.replace("pub name: String,", "pub name: u64,")


def main() -> int:
    if shutil.which("git") is None or not AUDIT.exists():
        print("SKIP: git or audit script not available")
        return 0

    failures: list[str] = []

    def expect(desc: str, rc: int, proc: subprocess.CompletedProcess) -> None:
        if proc.returncode != rc:
            failures.append(
                f"{desc}: expected rc={rc}, got {proc.returncode}\n"
                f"  stdout: {proc.stdout.strip()}\n  stderr: {proc.stderr.strip()}"
            )
        else:
            print(f"  ok: {desc}")

    with tempfile.TemporaryDirectory(prefix="schemahist-selftest-") as td:
        td = Path(td)

        print("1. append-only growth")
        r = make_repo(td / "a", [("c1", T1), ("c2", T1_PLUS_AGE)])
        expect("append-only -> 0", 0, run(r))

        print("2. allowed T -> Option<T>")
        r = make_repo(td / "b", [("c1", T1), ("c2", T1_NAME_OPTION)])
        expect("required->optional allowed -> 0", 0, run(r))

        print("3. field removal, no exception")
        r = make_repo(td / "c", [("c1", T1), ("c2", T1_NO_NAME)])
        expect("field removed -> 1", 1, run(r))

        print("4. type change, no exception")
        r = make_repo(td / "d", [("c1", T1), ("c2", T1_NAME_U64)])
        expect("type changed -> 1", 1, run(r))

        print("5. type change WITH valid exception (restored)")
        r = make_repo(td / "e", [
            ("c1", T1),
            ("c2", T1_NAME_U64),                 # breaking flip
            ("c3", T1),                          # restored
        ])
        write_exceptions(r, [{
            "id": "test-flip",
            "kind": "type_changed",
            "table": "Thing",
            "field": "name",
            "from": "String",
            "to": "u64",
            "both_directions": True,   # round trip: flip + restore are both transient
            "restored_type": "String",
            "why": "self-test transient flip, corrected in c3",
        }])
        expect("valid exception -> 0", 0, run(r))

        print("6. type change WITH invalid exception (NOT restored)")
        r = make_repo(td / "f", [
            ("c1", T1),
            ("c2", T1_NAME_U64),                 # breaking flip stays
        ])
        write_exceptions(r, [{
            "id": "test-live-break",
            "kind": "type_changed",
            "table": "Thing",
            "field": "name",
            "from": "String",
            "to": "u64",
            "restored_type": "String",           # false claim
            "why": "self-test: exception must NOT hide an un-restored break",
        }])
        expect("invalid (un-restored) exception -> 1", 1, run(r))

        print("7. STALE exception (matches nothing)")
        r = make_repo(td / "g", [("c1", T1), ("c2", T1_PLUS_AGE)])
        write_exceptions(r, [{
            "id": "stale",
            "kind": "type_changed",
            "table": "Ghost",
            "field": "nope",
            "from": "u64",
            "to": "String",
            "restored_type": "u64",
            "why": "self-test stale entry",
        }])
        expect("stale exception -> 1", 1, run(r))

        print("8. table removal, no exception")
        T2_EMPTY = "#[table(name = gone, public)]\nstruct Gone { pub x: u64, }\n"
        r = make_repo(td / "h", [
            ("c1", T1 + "\n" + T2_EMPTY),
            ("c2", T1),                          # table Gone removed
        ])
        expect("table removed -> 1", 1, run(r))

    if failures:
        print(f"\nSELF-TEST FAILED ({len(failures)}):")
        for f in failures:
            print("  - " + f.replace("\n", "\n    "))
        return 1
    print("\nSELF-TEST OK: detector flags all breaking cases, accepts append-only "
          "growth, and the transient-exception allowlist only forgives documented, "
          "restored corrections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
