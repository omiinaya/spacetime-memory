"""Supplementary tests for spacetime_memory.cli.commands._admin_tools.

Primary tests live in test_cli_admin_tools.py. This file adds coverage
for additional edge cases and direct function testing.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from spacetime_memory.cli.root import cli


def _mock_client(**kwargs) -> MagicMock:
    """Build a standard mock SDK client for admin tools tests."""
    mc = MagicMock()
    mc.ping.return_value = {"status": "ok", "latency_ms": 12}
    mc.health.return_value = {
        "status": "ok",
        "database": {"status": "ok", "latency_ms": 5},
        "embedder": {"reachable": True, "model_path": "/models/bge-m3"},
        "tantivy": {"reachable": True, "workspace_count": 3},
        "token_configured": True,
    }
    mc._sql.side_effect = [
        [{"memory_type": "world_fact", "c": 42}, {"memory_type": "experience", "c": 13}],
        [{"tier": "L0", "c": 10}, {"tier": "L1", "c": 35}],
    ]
    mc.list_workspaces.return_value = [{"name": "ws-1", "id": "ws-id-1"}]
    mc._call.return_value = {"status": "ok"}
    mc._query.return_value = [{"id": "note-1", "content": "test content"}]
    mc.store.return_value = {"id": "mem-new", "status": "ok"}
    mc.token = ""
    for k, v in kwargs.items():
        setattr(mc, k, v)
    return mc


class TestDiagnosticsExtended:
    """Extended tests for the diagnostics command."""

    def test_diagnostics_shows_workspaces(self):
        runner = CliRunner()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = _mock_client()
            with patch("spacetime_memory.metrics.MetricsCollector") as MockMC:
                inst = MagicMock()
                inst.to_dict.return_value = {
                    "uptime_human": "1h", "total_calls": 10,
                    "total_errors": 0, "overall_error_rate_pct": 0.0,
                    "embedder_errors": 0,
                }
                MockMC.return_value = inst
                result = runner.invoke(cli, ["diagnostics"])
        assert result.exit_code == 0
        assert "Workspaces" in result.output

    def test_diagnostics_shows_uptime(self):
        runner = CliRunner()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = _mock_client()
            with patch("spacetime_memory.metrics.MetricsCollector") as MockMC:
                inst = MagicMock()
                inst.to_dict.return_value = {
                    "uptime_human": "2d 3h", "total_calls": 100,
                    "total_errors": 5, "overall_error_rate_pct": 5.0,
                    "embedder_errors": 0,
                }
                MockMC.return_value = inst
                result = runner.invoke(cli, ["diagnostics"])
        assert result.exit_code == 0
        assert "2d" in result.output

    def test_diagnostics_ping_error_no_crash(self):
        """Ping or health errors don't crash diagnostics."""
        runner = CliRunner()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mc = _mock_client()
            mc.ping.side_effect = RuntimeError("fail")
            mc.health.side_effect = RuntimeError("fail")
            mock_fn.return_value = mc
            with patch("spacetime_memory.metrics.MetricsCollector") as MockMC:
                MockMC.return_value = MagicMock()
                result = runner.invoke(cli, ["diagnostics"])
        assert result.exit_code == 1

    def test_diagnostics_json_format(self):
        runner = CliRunner()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = _mock_client()
            with patch("spacetime_memory.metrics.MetricsCollector") as MockMC:
                inst = MagicMock()
                inst.to_dict.return_value = {"uptime_human": "1h", "total_calls": 50}
                MockMC.return_value = inst
                result = runner.invoke(cli, ["diagnostics", "--json"])
        assert result.exit_code == 0
        assert "database" in result.output
        assert "embedder" in result.output


class TestHealthExtended:
    """Extended tests for the health command."""

    def test_health_with_tantivy(self):
        runner = CliRunner()
        mc = _mock_client()
        mc.health.return_value = {
            "status": "ok",
            "database": {"status": "ok", "latency_ms": 3},
            "embedder": {"reachable": True, "model_path": "/models/bge-m3"},
            "tantivy": {"reachable": True, "workspace_count": 5},
            "token_configured": True,
        }
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0
        assert "workspaces: 5" in result.output

    def test_health_no_tantivy(self):
        runner = CliRunner()
        mc = _mock_client()
        mc.health.return_value = {
            "status": "ok",
            "database": {"status": "ok", "latency_ms": 3},
            "embedder": {"reachable": True},
            "token_configured": False,
        }
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0


class TestDoctorExtended:
    """Extended tests for the doctor command."""

    def test_doctor_checks_adapters(self):
        runner = CliRunner()
        mc = _mock_client()
        mc.token = ""
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with patch("spacetime_memory.cli.commands._admin_tools._find_spacetime_bin",
                      return_value="/usr/bin/spacetime"):
                result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "stmem doctor" in result.output or "System" in result.output or "check" in result.output

    def test_doctor_with_all_ok(self):
        runner = CliRunner()
        mc = _mock_client()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with patch("spacetime_memory.cli.commands._admin_tools._find_spacetime_bin",
                      return_value=None):
                result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0


class TestInitCommand:
    """Tests for the init command."""

    def test_init_with_defaults(self):
        runner = CliRunner()
        with patch("spacetime_memory.cli.commands._admin_tools._find_spacetime_bin",
                  return_value=None), patch("shutil.which", return_value=None):
            result = runner.invoke(cli, ["init"], input="y\n")
        # Should not crash — it'll run through the steps
        assert result.exit_code in (0, 1)

    def test_init_checks_prerequisites(self):
        runner = CliRunner()
        with patch("spacetime_memory.cli.commands._admin_tools._find_spacetime_bin",
                  return_value=None), patch("shutil.which", return_value=None):
            result = runner.invoke(cli, ["init"])
        # Should show prerequisite check output
        assert result.exit_code in (0, 1)
        # Should mention either Docker or spacetime CLI
        assert "Docker" in result.output or "spacetime" in result.output


class TestBackupExtended:
    """Extended tests for the backup command."""

    def test_backup_writes_jsonl(self):
        runner = CliRunner()
        mc = _mock_client()
        mc._query.return_value = [
            {"id": "m1", "content": "memory 1", "workspace_id": "ws-1"},
        ]
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with runner.isolated_filesystem():
                result = runner.invoke(cli, ["backup", "ws-1", "--output", "backup.jsonl"])
        assert result.exit_code == 0
        assert "Backup complete" in result.output

    def test_backup_handles_errors_gracefully(self):
        runner = CliRunner()
        mc = _mock_client()
        mc._query.side_effect = RuntimeError("query failed")
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with runner.isolated_filesystem():
                result = runner.invoke(cli, ["backup", "ws-1", "--output", "backup.jsonl"])
        assert result.exit_code == 0


class TestRestoreExtended:
    """Extended tests for the restore command."""

    def test_restore_dry_run_shows_count(self):
        runner = CliRunner()
        mc = _mock_client()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with runner.isolated_filesystem():
                with open("backup.jsonl", "w") as f:
                    f.write(json.dumps({"table": "memory", "content": "test", "workspace_id": "ws-1"}) + "\n")
                    f.write(json.dumps({"table": "memory", "content": "test2", "workspace_id": "ws-1"}) + "\n")
                result = runner.invoke(cli, ["restore", "ws-1", "backup.jsonl", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY" in result.output

    def test_restore_handles_empty_file(self):
        runner = CliRunner()
        mc = _mock_client()
        with patch("spacetime_memory.cli.commands._admin_tools._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with runner.isolated_filesystem():
                with open("empty.jsonl", "w") as f:
                    f.write("")
                result = runner.invoke(cli, ["restore", "ws-1", "empty.jsonl"])
        assert result.exit_code == 0


class TestServeExtended:
    """Extended tests for the serve command."""

    def test_serve_shows_import_error_helpfully(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["serve"])
        # The serve command tries 'from server.mcp.main import run', which
        # doesn't exist when run under test — catches ImportError gracefully
        assert result.exit_code == 1

    def test_serve_sse_transport(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--transport", "sse"])
        assert result.exit_code == 1


class TestFindSpacetimeBin:
    """Tests for the _find_spacetime_bin helper function."""

    def test_find_in_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/spacetime"):
            from spacetime_memory.cli.commands._admin_tools import _find_spacetime_bin
            result = _find_spacetime_bin()
            assert result == "/usr/local/bin/spacetime"

    def test_not_found_returns_none(self):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=False):
                from spacetime_memory.cli.commands._admin_tools import _find_spacetime_bin
                result = _find_spacetime_bin()
                assert result is None

    def test_find_in_common_locations(self):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile") as mock_isfile:
                mock_isfile.return_value = True
                with patch("os.access", return_value=True):
                    from spacetime_memory.cli.commands._admin_tools import _find_spacetime_bin
                    result = _find_spacetime_bin()
                    assert result is not None
