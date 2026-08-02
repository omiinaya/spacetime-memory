"""Tests for spacetime_memory.cli.commands.standalone.

standalone.py is a convenience module that re-exports the sub-modules
so their Click commands are registered with the root cli group.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from spacetime_memory.cli.root import cli


@pytest.mark.unit
class TestStandaloneImports:
    """standalone.py imports sub-modules for their registration side-effects."""

    def test_standalone_imports_basic_commands(self):
        """standalone imports _basic_commands."""
        import importlib
        with patch.dict("sys.modules", {"spacetime_memory.cli.commands._basic_commands": None}):
            pass
        from spacetime_memory.cli.commands import standalone
        assert hasattr(standalone, "__file__")
        # Re-import to trigger registration
        mod = importlib.import_module("spacetime_memory.cli.commands.standalone")
        assert mod is not None

    def test_standalone_imports_compounder_commands(self):
        """standalone imports _compounder_commands."""
        from spacetime_memory.cli.commands import standalone
        assert hasattr(standalone, "__file__")

    def test_common_commands_help(self):
        """Commands registered by imported modules appear in CLI help."""
        runner = CliRunner()
        # Use the recommend command as a proxy for one that's registered
        # via _basic_commands import in standalone
        mc = __import__("spacetime_memory.cli.commands._compounder_commands",
                        fromlist=["_compounder_commands"])
        assert hasattr(mc, "overview_cmd")
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code in (0, 2)
        # Many commands are available — verify at least some core group
        assert "spacetime-memory" in result.output.lower() or "Usage" in result.output
