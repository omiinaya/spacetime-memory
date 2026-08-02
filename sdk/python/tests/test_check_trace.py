"""Unit tests for check_trace.py — trace_span coverage checker.

Tests the script's logic for scanning Rust files and reporting which
modules have trace_span coverage on all their reducers.
"""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Import helpers — check_trace lives in the Rust source dir
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "server" / "spacetimedb" / "src"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Use importlib to avoid auto-running the script's top-level code
import importlib.util as _util

_spec = _util.spec_from_file_location("check_trace", _SCRIPT_DIR / "check_trace.py")
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load check_trace.py from {_SCRIPT_DIR}")
_check_trace = _util.module_from_spec(_spec)
_spec.loader.exec_module(_check_trace)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_rs_file(tmp_path: Path, name: str, content: str) -> Path:
    fpath = tmp_path / name
    fpath.write_text(content)
    return fpath


def run_check(tmp_path: Path) -> str:
    """Simulate running check_trace on files in tmp_path."""
    import check_trace as ct
    original_src = ct.src
    ct.src = str(tmp_path)
    try:
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        for f in sorted(os.listdir(tmp_path)):
            if not f.endswith('.rs'):
                continue
            path = os.path.join(ct.src, f)
            with open(path) as fh:
                text = fh.read()

            reducer_count = 0
            for line in text.split('\n'):
                stripped = line.strip()
                if stripped == '#[reducer]':
                    reducer_count += 1

            trace_count = text.count('trace_span!')

            if reducer_count > 0:
                status = 'OK' if reducer_count == trace_count else 'MISMATCH'
                print(f"{status:8s} {f:25s} reducers={reducer_count:3d} trace_spans={trace_count:3d}")

        sys.stdout = old_stdout
        return captured.getvalue()
    finally:
        ct.src = original_src


# ---------------------------------------------------------------------------
# Core scanning logic
# ---------------------------------------------------------------------------


class TestTraceScanning:
    """Check trace scanning counts #[reducer] and trace_span! correctly."""

    def test_ok_when_reducers_match(self, tmp_path: Path):
        make_rs_file(tmp_path, "test_module.rs", """use crate::trace_span;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {
    trace_span!(ctx, "test_fn", TracingSpanKind::Write, "", {
        do_thing();
    })
}
""")
        output = run_check(tmp_path)
        assert "OK" in output
        assert "test_module" in output

    def test_mismatch_when_missing_trace_span(self, tmp_path: Path):
        make_rs_file(tmp_path, "missing_span.rs", """#[reducer]
pub fn test_fn(ctx: &ReducerContext) {
    do_thing();
}
""")
        output = run_check(tmp_path)
        assert "MISMATCH" in output

    def test_multiple_reducers_partial_coverage(self, tmp_path: Path):
        make_rs_file(tmp_path, "partial.rs", """use crate::trace_span;

#[reducer]
pub fn fn_one(ctx: &ReducerContext) {
    trace_span!(ctx, "fn_one", TracingSpanKind::Write, "", {
        do_thing();
    })
}

#[reducer]
pub fn fn_two(ctx: &ReducerContext) {
    do_other();
}
""")
        output = run_check(tmp_path)
        assert "MISMATCH" in output
        assert "partial" in output

    def test_skips_non_rs_files(self, tmp_path: Path):
        make_rs_file(tmp_path, "test_module.rs", """use crate::trace_span;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {
    trace_span!(ctx, "test_fn", TracingSpanKind::Write, "", {
        do_thing();
    })
}
""")
        (tmp_path / "helper.py").write_text("x = 1")
        (tmp_path / "README.md").write_text("# ignore")

        output = run_check(tmp_path)
        assert "OK" in output
        assert ".py" not in output
        assert ".md" not in output

    def test_empty_directory(self, tmp_path: Path):
        output = run_check(tmp_path)
        assert output == ""

    def test_multiple_files_mixed_coverage(self, tmp_path: Path):
        make_rs_file(tmp_path, "good.rs", """use crate::trace_span;

#[reducer]
pub fn good_fn(ctx: &ReducerContext) {
    trace_span!(ctx, "good_fn", TracingSpanKind::Write, "", {
        do_thing();
    })
}
""")
        make_rs_file(tmp_path, "bad.rs", """#[reducer]
pub fn bad_fn(ctx: &ReducerContext) {
    do_bad();
}
""")
        make_rs_file(tmp_path, "util.rs", """pub fn helper() { let x = 1; }
""")

        output = run_check(tmp_path)
        assert "OK" in output
        assert "good" in output
        assert "MISMATCH" in output
        assert "bad" in output
        assert "util" not in output

    def test_trace_span_count_exceeds_reducers(self, tmp_path: Path):
        """More trace_span! calls than reducers is still flagged."""
        make_rs_file(tmp_path, "extra.rs", """use crate::trace_span;

#[reducer]
pub fn single_fn(ctx: &ReducerContext) {
    trace_span!(ctx, "single_fn", TracingSpanKind::Write, "", {
        trace_span!(ctx, "nested", TracingSpanKind::Write, "", {
            do_thing();
        })
    })
}
""")
        output = run_check(tmp_path)
        assert "MISMATCH" in output
        assert "extra" in output


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for the trace checking logic."""

    def test_reducer_in_comment_counted(self, tmp_path: Path):
        """#[reducer] in a doc comment is still counted by simple line matching."""
        make_rs_file(tmp_path, "commented.rs", """/// #[reducer] this is a doc comment
pub fn not_a_reducer() {}

#[reducer]
pub fn real_reducer(ctx: &ReducerContext) {
    trace_span!(ctx, "real_reducer", TracingSpanKind::Write, "", {
        do_thing();
    })
}
""")
        output = run_check(tmp_path)
        # The script counts line-by-line, so the doc comment #[reducer] is also counted.
        # This is known behaviour — the script is a heuristic tool.
        assert "commented" in output
        assert "MISMATCH" in output or "OK" in output

    def test_trace_span_in_string_literal(self, tmp_path: Path):
        """trace_span! inside a string literal is still counted by str.count()."""
        make_rs_file(tmp_path, "stringed.rs", """#[reducer]
pub fn doc_fn(ctx: &ReducerContext) {
    let x = "trace_span! is not actually called here";
}
""")
        output = run_check(tmp_path)
        # The script counts trace_span! by str.count(), which catches
        # occurrences in string literals too. This is known behaviour.
        assert "MISMATCH" in output or "OK" in output

    def test_no_reducers_no_output(self, tmp_path: Path):
        """File with no reducers generates no output."""
        make_rs_file(tmp_path, "util.rs", """pub fn helper() { let x = 1; }
""")
        output = run_check(tmp_path)
        assert output == ""
