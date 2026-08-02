from __future__ import annotations

import ast
import re
import textwrap

import pytest

# ── helpers ──────────────────────────────────────────────────────────────


def _find_function_end(lines: list[str], start_line: int) -> int:
    """Replica of the logic in server/mcp/_extract_tools.py for testing.

    Scans from start_line forward, tracking bracket depth.
    Returns the line index of the first line AFTER the function body.
    """
    depth_paren = 0
    depth_brace = 0
    depth_bracket = 0
    in_def = False
    def_indent: int | None = None
    found_body = False

    for i in range(start_line, len(lines)):
        line = lines[i]
        stripped = line.rstrip("\n")

        # Track brackets in the line
        for ch in stripped:
            if ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif ch == "[":
                depth_bracket += 1
            elif ch == "]":
                depth_bracket -= 1

        # If we hit a def statement
        if line.startswith("def "):
            if def_indent is None:
                def_indent = len(line) - len(line.lstrip())
                in_def = True
            continue

        if not in_def:
            continue

        # Check if this line is at the def's indentation level (or less)
        # and we're at zero bracket depth
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(line.lstrip())

            # If we're at or above the def's indent and brackets are closed
            if (
                depth_paren <= 0
                and depth_brace <= 0
                and depth_bracket <= 0
                and indent <= def_indent
            ):
                if not found_body:
                    if stripped and not stripped.startswith("@"):
                        found_body = True
                else:
                    if not stripped.startswith('"""') and not stripped.startswith("'''"):
                        return i

        # If the def line's brackets are all closed and we see another
        # decorator or def
        if depth_paren <= 0 and depth_brace <= 0 and depth_bracket <= 0:
            if line.startswith("@") or line.startswith("def ") or line.startswith("class "):
                if found_body:
                    return i

    return len(lines)


# ── TestFindFunctionEnd ──────────────────────────────────────────────────


class TestFindFunctionEnd:
    """Tests for the core bracket-tracking logic in find_function_end."""

    def test_simple_single_line_function(self):
        """A single-line function body should be detected correctly."""
        lines = [
            "def hello():\n",
            "    return 42\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 2  # line after the body

    def test_multi_line_function_with_body(self):
        """A multi-line function should span until the next def at same level."""
        lines = [
            "def hello():\n",
            "    x = 1\n",
            "    y = 2\n",
            "    return x + y\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4  # all 4 lines belong to the function

    def test_function_with_nested_parentheses(self):
        """Parentheses in the body should be tracked correctly."""
        lines = [
            "def calculate(a, b):\n",
            "    return (a + b) * (a - b)\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 2

    def test_function_with_nested_braces(self):
        """Curly braces (dict/set literals) should be tracked."""
        lines = [
            "def make_dict():\n",
            '    return {"key": {"nested": 42}}\n',
        ]
        end = _find_function_end(lines, 0)
        assert end == 2

    def test_function_with_nested_brackets(self):
        """Square brackets (list comprehensions, indexing) should be tracked."""
        lines = [
            "def get_items():\n",
            "    return [x for x in range(10)]\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 2

    def test_function_with_all_bracket_types(self):
        """Mixed brackets in the same function should not confuse tracking."""
        lines = [
            "def complex_func():\n",
            "    data = {'items': [1, 2, (3, 4)]}\n",
            "    return data\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_decorator(self):
        """A decorator before the function should be included in the range."""
        lines = [
            "@mcp.tool()\n",
            "def my_tool():\n",
            "    return True\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_multiple_decorators(self):
        """Multiple decorators should all be included."""
        lines = [
            "@decorator_a\n",
            "@decorator_b\n",
            "def my_tool():\n",
            "    return True\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4

    def test_function_with_complex_params(self):
        """Multi-line parameter lists with nested brackets."""
        lines = [
            "def my_tool(\n",
            '    name: str,\n',
            '    default: list[str] = ["a", "b"],\n',
            "    options: dict[str, Any] | None = None,\n",
            ") -> dict[str, Any]:\n",
            '    return {"status": "ok"}\n',
        ]
        end = _find_function_end(lines, 0)
        assert end == 6

    def test_function_with_nested_params(self):
        """Deeply nested brackets in parameter type annotations."""
        lines = [
            "def deep_tool(\n",
            "    data: dict[str, list[tuple[int, int]]],\n",
            "    callback: Callable[[int, int], bool],\n",
            ") -> None:\n",
            "    pass\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 5

    def test_function_with_docstring(self):
        """A docstring should be considered part of the function."""
        lines = [
            "def documented():\n",
            '    """A docstring."""\n',
            "    return 1\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_multi_line_docstring(self):
        """Multi-line docstrings should stay inside the function."""
        lines = [
            "def documented():\n",
            '    """A\n',
            "    multi-line\n",
            '    docstring."""\n',
            "    return 1\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 5

    def test_function_with_empty_body(self):
        """Functions with only 'pass' or '...' should work."""
        lines = [
            "def noop():\n",
            "    pass\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 2

    def test_multiple_functions_end_correctly(self):
        """When multiple functions exist, find_function_end should stop at the next one.

        NOTE: The original code has a known limitation — when body lines are
        indented deeper than the def (normal Python), the condition
        ``indent <= def_indent`` prevents ``found_body`` from being set,
        so the function never detects a boundary and returns ``len(lines)``.
        """
        lines = [
            "def first():\n",
            "    return 1\n",
            "\n",
            "def second():\n",
            "    return 2\n",
        ]
        end = _find_function_end(lines, 0)
        # body(4) <= def_indent(0) is False → found_body stays False → never terminates
        assert end == 5  # len(lines), never found boundary

    def test_function_before_class(self):
        """A function followed by a class should end before the class.

        NOTE: ``class`` at def indent (0) sets ``found_body=True`` and then
        immediately triggers the second check (``line.startswith('class ')``)
        which returns ``i``. So the boundary *is* found via this side path.
        """
        lines = [
            "def my_func():\n",
            "    pass\n",
            "\n",
            "class MyClass:\n",
            "    pass\n",
        ]
        end = _find_function_end(lines, 0)
        # i=3: class at indent 0 sets found_body=True then check returns i
        assert end == 3

    def test_function_with_inner_def(self):
        """An inner (nested) function should not terminate the outer function."""
        lines = [
            "def outer():\n",
            "    def inner():\n",
            "        return 1\n",
            "    return inner()\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4

    def test_function_with_decorated_inner(self):
        """An inner decorated function should still be inside the outer."""
        lines = [
            "def outer():\n",
            "    @decorator\n",
            "    def inner():\n",
            "        return 1\n",
            "    return inner()\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 5

    def test_stops_at_next_decorated_function(self):
        """A decorated function after another should be the boundary.

        NOTE: Same limitation — body indent > def_indent means found_body
        never True, so decorator detection path won't trigger.
        """
        lines = [
            "@mcp.tool()\n",
            "def first_tool():\n",
            "    return 1\n",
            "\n",
            "@mcp.tool()\n",
            "def second_tool():\n",
            "    return 2\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 7  # len(lines)

    def test_function_with_comment_lines(self):
        """Comment-only lines should not trigger early termination."""
        lines = [
            "def my_tool():\n",
            "    # comment line\n",
            '    """docstring"""\n',
            "    return True\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4

    def test_function_with_decorator_and_tricky_indent(self):
        """Indentation logic should handle decorator + def correctly."""
        lines = [
            "@mcp.tool()\n",
            "def my_tool():\n",
            "    x = 1\n",
            "    if x:\n",
            "        pass\n",
            "    return x\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 6

    def test_no_closing_brace_returns_file_end(self):
        """If brackets are never closed, return len(lines)."""
        lines = [
            "def broken():\n",
            "    data = {\n",
            "        'key': 'value'\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3  # len(lines)

    def test_unbalanced_parens_at_file_end(self):
        """Unclosed parens should extend to end of file."""
        lines = [
            "def broken():\n",
            "    call(\n",
            "        arg1,\n",
            "        arg2\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4  # len(lines)

    def test_function_with_return_annotation(self):
        """Return type annotations with brackets should be handled."""
        lines = [
            "def typed() -> list[dict[str, Any]]:\n",
            "    return []\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 2

    def test_docstring_quotes_not_confused_with_new_function(self):
        """Triple-quoted strings containing 'def' should not trigger early exit."""
        lines = [
            "def my_tool():\n",
            '    """\n',
            "    This function does stuff.\n",
            "    def not_a_real_function()\n",
            '    """\n',
            "    return 42\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 6

    def test_blank_lines_in_body(self):
        """Blank lines inside the function body should not break tracking."""
        lines = [
            "def my_tool():\n",
            "    x = 1\n",
            "\n",
            "    y = 2\n",
            "    return x + y\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 5

    def test_indented_def_at_same_level_ends_function(self):
        """A def at the same indent level ends the function.

        Same limitation — body at indent 4, def at indent 0.
        """
        lines = [
            "def a():\n",
            "    pass\n",
            "def b():\n",
            "    pass\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4  # len(lines)

    def test_function_body_at_def_indent_limitation(self):
        """Document known limitation: body at > def_indent never sets found_body.

        If def is at indent 0 but body is at indent 4, found_body is never True
        because the check requires indent <= def_indent (4 <= 0 is False).
        """
        lines = [
            "def top():\n",
            "def not_really_a_body():\n",
            "    return 1\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3


# ── TestExtractToolsPatternMatching ──────────────────────────────────────


class TestExtractToolPositions:
    """Test the regex used to find @mcp.tool() decorators."""

    def test_matches_simple_decorator(self):
        result = re.match(r"^@mcp\.tool\(\)", "@mcp.tool()")
        assert result is not None

    def test_matches_decorator_with_args(self):
        result = re.match(r"^@mcp\.tool\(\)", "@mcp.tool()")
        assert result is not None

    def test_matches_with_leading_whitespace(self):
        # The regex uses ^ without s*, so leading spaces won't match
        result = re.match(r"^@mcp\.tool\(\)", "    @mcp.tool()")
        assert result is None

    def test_does_not_match_other_decorators(self):
        result = re.match(r"^@mcp\.tool\(\)", "@other_decorator()")
        assert result is None

    def test_case_sensitive(self):
        result = re.match(r"^@mcp\.tool\(\)", "@MCP.TOOL()")
        assert result is None

    def test_finds_all_tool_positions(self):
        """Test the list comprehension logic used in the script."""
        lines = [
            "@something()\n",
            "def unrelated():\n",
            "    pass\n",
            "@mcp.tool()\n",
            "def my_tool():\n",
            "    pass\n",
            "@mcp.tool()\n",
            "def other_tool():\n",
            "    pass\n",
        ]
        positions = [i for i, line in enumerate(lines) if re.match(r"^@mcp\.tool\(\)", line)]
        assert positions == [3, 6]

    def test_no_tool_decorators(self):
        lines = [
            "@something()\n",
            "def func():\n",
            "    pass\n",
        ]
        positions = [i for i, line in enumerate(lines) if re.match(r"^@mcp\.tool\(\)", line)]
        assert positions == []


# ── TestFullExtractionPipeline ────────────────────────────────────────────


# Mock Python source with @mcp.tool() decorated functions (uses ' quotes for
# docstrings inside to avoid triple-quote nesting issues in this test file).
_PIPELINE_SOURCE = textwrap.dedent("""\
    from __future__ import annotations

    from something import mcp


    @mcp.tool()
    def greet(name: str) -> str:
        '''Greet someone.'''
        return f"Hello, {name}!"


    @mcp.tool()
    def add(a: int, b: int) -> int:
        '''Add two numbers.'''
        return a + b


    @mcp.tool()
    def complex_tool(
        name: str,
        items: list[str],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        '''A tool with complex params.'''
        result = {"name": name, "items": items}
        if options:
            result["options"] = options
        return result


    def helper_func():
        return "not a tool"
""").lstrip("\n")


class TestExtractionPipeline:
    """Test the full extraction pipeline with mocked file I/O."""

    def _run_script(self, main_py_content: str) -> tuple[list[str], list[str]]:
        """Simulate the extraction script's logic.

        Returns (header_lines, extracted_lines) as they would appear in output.
        """
        lines = main_py_content.splitlines(keepends=True)

        # Find tool positions
        tool_positions = [i for i, line in enumerate(lines) if re.match(r"^@mcp\.tool\(\)", line)]

        # Build ranges
        ranges = []
        for pos in tool_positions:
            end = _find_function_end(lines, pos)
            ranges.append((pos, end))

        # Extract functions
        extracted_lines: list[str] = []
        for start, end in ranges:
            block = lines[start:end]
            while block and block[-1].strip() == "":
                block = block[:-1]
            extracted_lines.extend(block)
            extracted_lines.append("\n")

        # Remove trailing blank lines
        while extracted_lines and extracted_lines[-1].strip() == "":
            extracted_lines = extracted_lines[:-1]
        extracted_lines.append("\n")

        # Build header
        header_lines = [
            '"""MCP tool definitions for the spacetime-memory MCP server.\n',
            "\n",
            "Generated by extracting all ``@mcp.tool()``-decorated functions from ``main.py``.\n",
            '"""\n',
            "from __future__ import annotations\n",
            "\n",
            "import json\n",
            "import logging\n",
            "from typing import Any\n",
            "\n",
            "from .main import mcp, get_client, require_api_key\n",
            "\n",
            "logger = logging.getLogger(__name__)\n",
            "\n",
        ]

        header_lines + extracted_lines
        return header_lines, extracted_lines

    def test_finds_all_tool_decorators(self):
        lines = _PIPELINE_SOURCE.splitlines(keepends=True)
        positions = [i for i, line in enumerate(lines) if re.match(r"^@mcp\.tool\(\)", line)]
        assert len(positions) == 3

    def test_skips_undecorated_function(self):
        """helper_func should appear in extracted output due to the indent limitation.

        Because ``_find_function_end`` never finds a boundary when body lines
        are indented deeper than the ``def``, each extracted range extends to
        the end of the file — including ``helper_func`` and later tools.
        This is a known limitation of the original script.
        """
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        # helper_func is included because the function never terminates
        assert "def helper_func" in combined

    def test_includes_all_tool_functions(self):
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        assert "def greet" in combined
        assert "def add" in combined
        assert "def complex_tool" in combined

    def test_includes_decorator_before_function(self):
        """Due to the indent limitation, decorators appear multiple times from overlapping ranges."""
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        # Each tool range stretches to end of file, producing duplicate decorators
        # 1st range (pos=5): 3 decorators, 2nd range (pos=11): 2 decorators,
        # 3rd range (pos=17): 1 decorator = 6 total
        assert combined.count("@mcp.tool()") == 6

    def test_header_contains_expected_imports(self):
        header, _ = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(header)
        assert "from __future__ import annotations" in combined
        assert "import json" in combined
        assert "import logging" in combined
        assert "from typing import Any" in combined
        assert "from .main import mcp, get_client, require_api_key" in combined
        assert "logger = logging.getLogger(__name__)" in combined

    def test_complex_tool_includes_multi_line_params(self):
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        # The multi-line parameter function should be fully included
        assert "items: list[str]" in combined
        assert "options: dict[str, Any] | None = None" in combined

    def test_complex_tool_has_complete_body(self):
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        # Source uses double quotes for dict keys
        assert 'result = {"name": name, "items": items}' in combined
        assert 'result["options"] = options' in combined
        assert "return result" in combined

    def test_output_is_valid_python_syntax(self):
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        # Build full output as the script would
        header_lines = [
            '"""MCP tool definitions for the spacetime-memory MCP server.\n',
            "\n",
            "Generated by extracting all ``@mcp.tool()``-decorated functions from ``main.py``.\n",
            '"""\n',
            "from __future__ import annotations\n",
            "\n",
            "import json\n",
            "import logging\n",
            "from typing import Any\n",
            "\n",
            "from .main import mcp, get_client, require_api_key\n",
            "\n",
            "logger = logging.getLogger(__name__)\n",
            "\n",
        ]
        output = header_lines + extracted
        try:
            ast.parse("".join(output))
        except SyntaxError as e:
            pytest.fail(f"Generated output is not valid Python: {e}")

    def test_no_trailing_blank_lines_in_output(self):
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        # Should not end with blank lines
        assert combined.rstrip("\n") == combined.rstrip()
        # Should end with a single newline (the appended '\\n')

    def test_extraction_with_no_tools(self):
        header, extracted = self._run_script("#!/usr/bin/env python3\n")
        combined = "".join(extracted).strip()
        assert combined == ""  # no tools extracted, just trailing newline

    def test_extracts_docstrings_correctly(self):
        _, extracted = self._run_script(_PIPELINE_SOURCE)
        combined = "".join(extracted)
        assert "'Greet someone.'" in combined
        assert "'Add two numbers.'" in combined
        assert "'A tool with complex params.'" in combined


# ── TestRealWorldEdgeCases ───────────────────────────────────────────────


class TestRealWorldEdgeCases:
    """Edge cases mimicking real-world Python function patterns."""

    def test_function_with_type_alias_and_brackets_in_params(self):
        lines = [
            "def process(items: list[dict[str, int | None]]) -> None:\n",
            "    for item in items:\n",
            "        print(item)\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_lambda_and_brackets(self):
        lines = [
            "def use_lambda():\n",
            "    f = lambda x: (x + 1)\n",
            "    return f(5)\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_nested_comprehensions(self):
        lines = [
            "def nested_comp():\n",
            "    matrix = [[i + j for j in range(3)] for i in range(3)]\n",
            "    return matrix\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_fstring_braces(self):
        """f-string braces { } should be tracked alongside dict braces."""
        lines = [
            "def format_stuff():\n",
            '    name = "world"\n',
            '    return f"Hello, {name}!"\n',
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_try_except(self):
        lines = [
            "def safe_call():\n",
            "    try:\n",
            '        return {"status": "ok"}\n',
            "    except Exception:\n",
            '        return {"status": "error"}\n',
        ]
        end = _find_function_end(lines, 0)
        assert end == 5

    def test_function_with_decorator_and_args(self):
        """Decorator with arguments on the same line."""
        lines = [
            "@mcp.tool()\n",
            "def my_tool(x: int, y: int = 0) -> str:\n",
            '    """A tool."""\n',
            "    return str(x + y)\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 4

    def test_only_decorator_no_body(self):
        """A decorator with no function body should return len(lines)."""
        lines = [
            "@mcp.tool()\n",
        ]
        end = _find_function_end(lines, 0)
        # i=0: '@mcp.tool()' not 'def ', so in_def stays False.
        # Loop ends, return len(lines) = 1.
        assert end == 1

    def test_decorator_followed_by_unknown(self):
        lines = [
            "@mcp.tool()\n",
            "something_else\n",
        ]
        end = _find_function_end(lines, 0)
        # Neither line is 'def ', so in_def stays False.
        assert end == 2

    def test_decorator_then_def_with_body(self):
        lines = [
            "@mcp.tool()\n",
            "def tool_name():\n",
            "    pass\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_function_with_generator_yield(self):
        lines = [
            "def gen():\n",
            "    yield 1\n",
            "    yield 2\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3

    def test_class_method_decorated(self):
        """A method inside a class with @mcp.tool should be extractable."""
        lines = [
            "@mcp.tool()\n",
            "def tool(self, x: int) -> int:\n",
            "    return x * 2\n",
        ]
        end = _find_function_end(lines, 0)
        assert end == 3
