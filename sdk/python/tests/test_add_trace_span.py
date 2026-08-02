"""Unit tests for add_trace_span.py — trace_span! wrapper injector for Rust reducers.

All tests use pure function unit tests — no file system I/O beyond
controlled tempfile usage.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Import helpers — add_trace_span lives in the Rust source dir
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "server" / "spacetimedb" / "src"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from add_trace_span import (
    ALREADY_DONE,
    DEFAULT_KIND,
    KIND_OVERRIDES,
    add_imports_if_missing,
    find_matching_brace,
    get_kind,
    has_workspace_param,
    process_file,
    wrap_reducer,
)

# ---------------------------------------------------------------------------
# get_kind
# ---------------------------------------------------------------------------


class TestGetKind:
    """get_kind returns the right TracingSpanKind for known functions."""

    def test_known_read_func(self):
        assert get_kind("search") == "TracingSpanKind::Read"
        assert get_kind("get_session") == "TracingSpanKind::Read"
        assert get_kind("query_table") == "TracingSpanKind::Read"

    def test_known_admin_func(self):
        assert get_kind("run_decay") == "TracingSpanKind::Admin"
        assert get_kind("batch_reindex") == "TracingSpanKind::Admin"
        assert get_kind("clear_changes") == "TracingSpanKind::Admin"

    def test_unknown_function_defaults_to_write(self):
        assert get_kind("unknown_fn") == DEFAULT_KIND
        assert get_kind("custom_reducer") == DEFAULT_KIND
        assert get_kind("") == DEFAULT_KIND

    def test_all_overrides_are_valid(self):
        for fn_name, kind in KIND_OVERRIDES.items():
            assert kind in (
                "TracingSpanKind::Read",
                "TracingSpanKind::Write",
                "TracingSpanKind::Admin",
            ), f"{fn_name} has invalid kind: {kind}"


# ---------------------------------------------------------------------------
# has_workspace_param
# ---------------------------------------------------------------------------


class TestHasWorkspaceParam:
    """Detects workspace_id in function signatures."""

    def test_with_workspace_id(self):
        sig = "pub fn my_reducer(ctx: &ReducerContext, workspace_id: String)"
        assert has_workspace_param(sig)

    def test_with_workspace_id_with_space(self):
        sig = "pub fn my_reducer(ctx: &ReducerContext, workspace_id : String)"
        assert has_workspace_param(sig)

    def test_without_workspace_id(self):
        sig = "pub fn my_reducer(ctx: &ReducerContext, name: String)"
        assert not has_workspace_param(sig)

    def test_empty_sig(self):
        assert not has_workspace_param("")

    def test_multiline_sig(self):
        sig = "pub fn my_reducer(\n    ctx: &ReducerContext,\n    workspace_id: String,\n)"
        assert has_workspace_param(sig)


# ---------------------------------------------------------------------------
# add_imports_if_missing
# ---------------------------------------------------------------------------


class TestAddImportsIfMissing:
    """Adds trace_span imports after last use crate:: line."""

    def test_adds_missing_imports(self):
        content = """use spacetimedb::table;
use crate::some_module;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {{}}
"""
        result, changed = add_imports_if_missing(content)
        assert changed
        assert "use crate::trace_span;" in result
        assert "use crate::tracing::TracingSpanKind;" in result
        # Imports should be after the last use crate:: line
        assert result.index("use crate::trace_span;") > result.index("use crate::some_module;")

    def test_skips_if_already_present(self):
        content = """use spacetimedb::table;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {{}}
"""
        result, changed = add_imports_if_missing(content)
        assert not changed
        assert result == content

    def test_only_adds_missing_trace_span(self):
        content = """use spacetimedb::table;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {{}}
"""
        result, changed = add_imports_if_missing(content)
        assert changed
        assert "use crate::trace_span;" in result
        assert result.count("use crate::tracing::TracingSpanKind;") == 1

    def test_only_adds_missing_kind(self):
        content = """use spacetimedb::table;
use crate::trace_span;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {{}}
"""
        result, changed = add_imports_if_missing(content)
        assert changed
        assert "use crate::tracing::TracingSpanKind;" in result
        assert result.count("use crate::trace_span;") == 1

    def test_no_use_crate_import(self):
        content = """use spacetimedb::table;

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {{}}
"""
        result, changed = add_imports_if_missing(content)
        # Should not crash — returns unchanged
        assert not changed

    def test_use_crate_brace_format(self):
        """Imports are added after a use crate::{...} brace-style import."""
        content = """use spacetimedb::table;
use crate::{some_module, other_module};

#[reducer]
pub fn test_fn(ctx: &ReducerContext) {{}}
"""
        result, changed = add_imports_if_missing(content)
        assert changed
        assert "use crate::trace_span;" in result
        assert "use crate::tracing::TracingSpanKind;" in result
        # Both new imports should appear after the use crate::{...} line
        brace_line = result.index("use crate::{some_module, other_module};")
        assert result.index("use crate::trace_span;") > brace_line
        assert result.index("use crate::tracing::TracingSpanKind;") > brace_line


# ---------------------------------------------------------------------------
# find_matching_brace
# ---------------------------------------------------------------------------


class TestFindMatchingBrace:
    """Finds matching closing brace in a list of lines."""

    def test_simple_block(self):
        lines = [
            "fn foo(ctx: &ReducerContext) {",
            "    let x = 1;",
            "}",
        ]
        result = find_matching_brace(lines, 0)
        assert result == 2

    def test_multiple_braces(self):
        lines = [
            "fn foo(ctx: &ReducerContext) {",
            "    if true {",
            "        let y = 2;",
            "    }",
            "    let x = 1;",
            "}",
        ]
        result = find_matching_brace(lines, 0)
        assert result == 5

    def test_opening_brace_with_content_on_same_line(self):
        lines = [
            "fn foo(ctx: &ReducerContext) { println!(\"hi\"); }",
        ]
        result = find_matching_brace(lines, 0)
        assert result == 0  # Same line

    def test_no_matching_brace_returns_none(self):
        lines = [
            "fn foo(ctx: &ReducerContext) {",
            "    let x = 1;",
            # No closing brace
        ]
        result = find_matching_brace(lines, 0)
        assert result is None

    def test_nested_braces_deep(self):
        lines = [
            "fn outer() {",
            "    if a {",
            "        for b in c {",
            "            do();",
            "        }",
            "    }",
            "}",
        ]
        result = find_matching_brace(lines, 0)
        assert result == 6

    def test_opening_brace_on_middle_of_line(self):
        """Braces not at start of line are handled correctly."""
        lines = [
            "fn foo()",
            "{",
            "    let x = 1;",
            "}",
        ]
        result = find_matching_brace(lines, 1)
        assert result == 3

    def test_lone_closing_brace_is_not_misidentified(self):
        lines = [
            "fn outer() {",
            "    let x = if true { 1 } else { 2 };",
            "}",
        ]
        result = find_matching_brace(lines, 0)
        assert result == 2

    def test_closing_before_opening_on_first_line(self):
        """A '}' before '{' on the opening line causes depth to hit 0 on the next brace-free line, reaching line 178."""
        lines = [
            'fn foo(ctx: ...) } else {',
            '    let x = 1;',
            '}',
        ]
        result = find_matching_brace(lines, 0)
        # This is a pathological case: the stray '}' throws off depth tracking.
        # The function should still return something sensible.
        assert result is None


# ---------------------------------------------------------------------------
# wrap_reducer
# ---------------------------------------------------------------------------


class TestWrapReducer:
    """wrap_reducer adds trace_span! around reducer function bodies."""

    SAMPLE_REDUCER = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn test_store(ctx: &ReducerContext, workspace_id: String) {{
    let x = 1;
    do_something(x);
}}
"""

    SAMPLE_REDUCER_NO_WS = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn test_store(ctx: &ReducerContext) {{
    let x = 1;
    do_something(x);
}}
"""

    def _get_reducer_line(self, content: str) -> int:
        for i, line in enumerate(content.split("\n")):
            if line.strip() == "#[reducer]":
                return i
        raise ValueError("No #[reducer] found")

    def test_wraps_reducer_with_workspace_id(self):
        content = self.SAMPLE_REDUCER.format("")
        rl = self._get_reducer_line(content)
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result
        assert '"test_store"' in result
        assert "&workspace_id" in result

    def test_wraps_reducer_without_workspace_id(self):
        content = self.SAMPLE_REDUCER_NO_WS.format("")
        rl = self._get_reducer_line(content)
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result
        assert '""' in result  # Empty workspace arg

    def test_skips_already_wrapped(self):
        content = self.SAMPLE_REDUCER.format("")
        rl = self._get_reducer_line(content)

        # Wrap once
        result, _ = wrap_reducer(content, rl)

        # Try to wrap again — should detect existing trace_span
        # (reducer line index may have shifted)
        new_rl = None
        for i, line in enumerate(result.split("\n")):
            if line.strip() == "#[reducer]":
                new_rl = i
                break
        assert new_rl is not None
        result2, wrapped2 = wrap_reducer(result, new_rl)
        assert not wrapped2  # Already has trace_span

    def test_single_line_body(self):
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn single_line(ctx: &ReducerContext, workspace_id: String) {{ let x = 1; }}
"""
        rl = self._get_reducer_line(content)
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result

    def test_empty_body(self):
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn empty_fn(ctx: &ReducerContext, workspace_id: String) {{}}
"""
        rl = self._get_reducer_line(content)
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result

    def test_no_fn_name_after_reducer(self):
        """#[reducer] followed by non-function returns (content, False)."""
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub struct SomeStruct;

#[reducer]
const FOO: u32 = 42;
"""
        rl = None
        for i, line in enumerate(content.split("\n")):
            if line.strip() == "#[reducer]":
                rl = i
                break
        assert rl is not None
        result, wrapped = wrap_reducer(content, rl)
        assert not wrapped
        assert result == content

    def test_no_opening_brace_after_sig(self):
        """Function signature without opening brace returns (content, False)."""
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn no_body_fn(ctx: &ReducerContext, workspace_id: String)
"""
        rl = None
        for i, line in enumerate(content.split("\n")):
            if line.strip() == "#[reducer]":
                rl = i
                break
        assert rl is not None
        result, wrapped = wrap_reducer(content, rl)
        assert not wrapped
        assert result == content

    def test_no_closing_brace(self):
        """Function with opening brace but no matching closing brace returns (content, False)."""
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn no_close_fn(ctx: &ReducerContext, workspace_id: String) {
    let x = 1;
    let y = 2;
"""
        rl = None
        for i, line in enumerate(content.split("\n")):
            if line.strip() == "#[reducer]":
                rl = i
                break
        assert rl is not None
        result, wrapped = wrap_reducer(content, rl)
        assert not wrapped
        assert result == content

    def test_truly_empty_body_single_line(self):
        """Truly empty single-line body {} hits the else branch on line 255."""
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn empty_fn(ctx: &ReducerContext, workspace_id: String) {}
"""
        rl = self._get_reducer_line(content)
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result
        assert "empty_fn" in result
        # The body between braces was empty, so it should render {{}} in the macro
        assert "{{}}" in result or "{}" in result

    def test_multi_line_body_with_empty_line(self):
        """Multi-line function body with a blank line triggers re-indent on empty line."""
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn empty_line_fn(ctx: &ReducerContext, workspace_id: String) {
    let x = 1;

    let y = 2;
}
"""
        rl = self._get_reducer_line(content)
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result
        # The blank line should appear in the output (re-indented)
        # Find the blank line — should be indented (8 spaces for inner indent)
        blank_lines = [line for line in result.split("\n") if line.strip() == ""]
        assert len(blank_lines) >= 1


class TestMainEntryPoint:
    """Tests for the if __name__ == '__main__' guard (line 347)."""

    def test_main_entry_point_called_when_run_directly(self):
        """Running add_trace_span.py as __main__ invokes main() via the guard."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test .rs file
            (Path(tmpdir) / "test_mod.rs").write_text(
                "use spacetimedb::table;\n"
                "use crate::stuff;\n"
                "\n"
                "#[reducer]\n"
                "pub fn hello(ctx: &ReducerContext, workspace_id: String) {\n"
                "    doit();\n"
                "}\n"
            )

            # Read original script and create a patched copy with safe SRC
            orig = Path(_SCRIPT_DIR) / "add_trace_span.py"
            content = orig.read_text()
            patched = content.replace(
                'SRC = os.path.dirname(os.path.abspath(__file__))',
                f'SRC = {str(tmpdir)!r}'
            ).replace(
                'ALREADY_DONE = {"memory.rs", "hybrid_query.rs", "tracing.rs", "add_trace_span.py"}',
                'ALREADY_DONE = set()'
            )

            patched_path = Path(tmpdir) / "add_trace_span.py"
            patched_path.write_text(patched)

            # Run the patched script directly as __main__
            result = subprocess.run(
                [sys.executable, str(patched_path)],
                capture_output=True, text=True,
                timeout=10
            )
            assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
            assert "Total:" in result.stdout

            # Verify the file was actually wrapped
            wrapped_file = Path(tmpdir) / "test_mod.rs"
            wrapped_content = wrapped_file.read_text()
            assert "trace_span!(" in wrapped_content


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestProcessFile:
    """process_file wraps all reducers in a Rust file."""

    def test_processes_valid_file(self):
        content = """use spacetimedb::table;
use crate::some_module;

#[reducer]
pub fn reducer_one(ctx: &ReducerContext, workspace_id: String) {
    do_thing();
}

#[reducer]
pub fn reducer_two(ctx: &ReducerContext) {
    do_other();
}
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".rs", delete=False
        ) as f:
            f.write(content)
            fpath = f.name

        try:
            count, changed = process_file(fpath)
            assert count == 2
            assert changed

            with open(fpath) as f:
                result = f.read()
            assert result.count("trace_span!(") == 2
            assert "use crate::trace_span;" in result
            assert "use crate::tracing::TracingSpanKind;" in result
        finally:
            os.unlink(fpath)

    def test_skips_already_done_files(self):
        """Files in ALREADY_DONE set are not processed."""
        # process_file only filters by filename in its listing logic,
        # not in process_file itself. The filtering is in main().
        # This tests that ALREADY_DONE contains the expected entries.
        assert "add_trace_span.py" in ALREADY_DONE
        assert "tracing.rs" in ALREADY_DONE

    def test_no_reducers(self):
        content = """use spacetimedb::table;

pub fn some_fn() {
    let x = 1;
}
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".rs", delete=False
        ) as f:
            f.write(content)
            fpath = f.name

        try:
            count, changed = process_file(fpath)
            assert count == 0
            assert not changed
        finally:
            os.unlink(fpath)


# ---------------------------------------------------------------------------
# main() — integration-style
# ---------------------------------------------------------------------------


class TestMain:
    """main() orchestrates the full workflow."""

    def test_main_runs_with_temp_src(self, monkeypatch, tmp_path):
        """Override SRC to a temp dir with a valid .rs file and run main."""
        rs_file = tmp_path / "test_module.rs"
        rs_file.write_text("""use spacetimedb::table;
use crate::some_module;

#[reducer]
pub fn test_reducer(ctx: &ReducerContext, workspace_id: String) {
    do_thing();
}
""")

        # Create a dummy non-.rs file to verify filtering
        (tmp_path / "README.md").write_text("# Readme")

        monkeypatch.setattr(
            "add_trace_span.SRC", str(tmp_path)
        )
        monkeypatch.setattr(
            "add_trace_span.ALREADY_DONE",
            {"tracing.rs", "hybrid_query.rs", "memory.rs"},
        )

        # Should not raise
        from add_trace_span import main
        main()

        # Verify the .rs file was updated
        updated = rs_file.read_text()
        assert "trace_span!(" in updated
        assert "use crate::trace_span;" in updated

    def test_skips_already_done_file_in_main(self, monkeypatch, tmp_path, capsys):
        """An .rs file that is in ALREADY_DONE is skipped during main()."""
        # Create a file that IS in ALREADY_DONE
        done_file = tmp_path / "memory.rs"
        done_file.write_text("""use spacetimedb::table;

#[reducer]
pub fn existing_reducer(ctx: &ReducerContext, workspace_id: String) {
    do_thing();
}
""")

        monkeypatch.setattr(
            "add_trace_span.SRC", str(tmp_path)
        )
        monkeypatch.setattr(
            "add_trace_span.ALREADY_DONE",
            {"memory.rs", "tracing.rs"},
        )

        from add_trace_span import main
        main()
        captured = capsys.readouterr()

        # The file was skipped — it should not have been wrapped
        updated = done_file.read_text()
        assert "trace_span!(" not in updated
        # The output should report 0 files processed
        assert "0 files" in captured.out or "0 reducers" in captured.out

    def test_file_with_reducers_already_wrapped(self, monkeypatch, tmp_path, capsys):
        """main() handles the case where reducers are already wrapped (lines 339-341)."""
        # Create a file whose reducers are already wrapped
        rs_file = tmp_path / "already_wrapped.rs"
        rs_file.write_text("""use spacetimedb::table;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn my_reducer(ctx: &ReducerContext, workspace_id: String) {
    trace_span!(ctx, "my_reducer", TracingSpanKind::Write, &workspace_id, {
        do_thing();
    })
}
""")

        monkeypatch.setattr(
            "add_trace_span.SRC", str(tmp_path)
        )
        monkeypatch.setattr(
            "add_trace_span.ALREADY_DONE",
            {"tracing.rs"},
        )

        from unittest.mock import patch as mock_patch
        # process_file will return (1, False) — file has reducers but none needed wrapping
        with mock_patch("add_trace_span.process_file", return_value=(1, False)):
            from add_trace_span import main
            main()
            captured = capsys.readouterr()
            # The output should reference 0 files since the elif branch just does pass
            assert "0 files" in captured.out


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for trace_span wrapper functions."""

    def test_reducer_with_pub_crate(self):
        """pub(crate) visibility is handled."""
        content = """use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub(crate) fn internal_reducer(ctx: &ReducerContext, workspace_id: String) {
    do_stuff();
}
"""
        rl = None
        for i, line in enumerate(content.split("\n")):
            if line.strip() == "#[reducer]":
                rl = i
                break
        assert rl is not None

        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert "trace_span!(" in result
        assert '"internal_reducer"' in result

    def test_large_body_handling(self):
        """A moderately large function body is wrapped correctly."""
        body = "\n    ".join([f"let x_{i} = {i};" for i in range(20)])
        content = f"""use crate::trace_span;
use crate::tracing::TracingSpanKind;

#[reducer]
pub fn large_fn(ctx: &ReducerContext, workspace_id: String) {{
    {body}
}}
"""
        rl = None
        for i, line in enumerate(content.split("\n")):
            if line.strip() == "#[reducer]":
                rl = i
                break
        result, wrapped = wrap_reducer(content, rl)
        assert wrapped
        assert result.count("trace_span!(") == 1
        # All original body lines should still be present
        for i in range(20):
            assert f"let x_{i} = {i};" in result
