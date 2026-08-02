"""Tests for cli.stmem.commands.alias.

Covers alias set, list, and remove commands.
Uses filesystem-based aliases via tmp_path.
"""
from __future__ import annotations

import json

import pytest
from cli.stmem import cli
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.mark.unit
class TestAlias:
    """Alias commands (filesystem-based — monkeypatch ALIASES_FILE)."""

    def test_alias_set(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "set", "ll", "memory list"])
        assert result.exit_code == 0
        assert "Alias 'll' set to:" in result.output
        # Verify persistence
        assert aliases_file.exists()
        data = json.loads(aliases_file.read_text())
        assert data["ll"] == "memory list"

    def test_alias_set_override(self, runner, monkeypatch, tmp_path):
        """Setting an existing alias overwrites it."""
        aliases_file = tmp_path / "aliases.json"
        aliases_file.write_text('{"ll": "workspace list"}')
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "set", "ll", "memory list"])
        assert result.exit_code == 0
        data = json.loads(aliases_file.read_text())
        assert data["ll"] == "memory list"

    def test_alias_list_empty(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "list"])
        assert result.exit_code == 0
        assert "No aliases defined" in result.output

    def test_alias_list_with_data(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        aliases_file.write_text('{"ll": "memory list", "aa": "workspace list"}')
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "list"])
        assert result.exit_code == 0
        assert "ll" in result.output
        assert "aa" in result.output

    def test_alias_remove(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        aliases_file.write_text('{"ll": "memory list"}')
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "remove", "ll"])
        assert result.exit_code == 0
        assert "removed" in result.output
        data = json.loads(aliases_file.read_text())
        assert "ll" not in data

    def test_alias_remove_not_found(self, runner, monkeypatch, tmp_path):
        aliases_file = tmp_path / "aliases.json"
        monkeypatch.setattr("cli.stmem.root.ALIASES_FILE", str(aliases_file))
        result = runner.invoke(cli, ["alias", "remove", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_alias_help(self, runner):
        result = runner.invoke(cli, ["alias", "--help"])
        assert result.exit_code == 0
        assert "set" in result.output
        assert "list" in result.output
        assert "remove" in result.output
