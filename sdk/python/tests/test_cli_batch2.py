"""Tests for the stmem CLI — batch 2: directory tree, plugin lifecycle,
connector run, agent step, AAAK pipe/file input, metrics exceptions,
replication branches, veracity, SHMR resonate, main() error paths,
and other easy-to-test branches.
"""

import json
import sys
from unittest.mock import Mock

import pytest
from cli.stmem import cli

# ====================================================================
# Directory tree — traverse_directory
# ====================================================================


class TestDirectoryTree:
    """directory tree command."""

    def test_directory_tree_with_results(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.traverse_directory = Mock(
            return_value=[
                {"id": "d1", "name": "subdir", "path": "/root/subdir", "type": "directory"},
                {"id": "m1", "name": "memory_1", "memory_id": "mem1", "type": "memory"},
            ]
        )
        result = runner.invoke(cli, ["directory", "tree", "ws1", "root1"])
        assert result.exit_code == 0

    def test_directory_tree_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.traverse_directory = Mock(return_value=[])
        result = runner.invoke(cli, ["directory", "tree", "ws1", "root1"])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_directory_tree_none(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.traverse_directory = Mock(return_value=None)
        result = runner.invoke(cli, ["directory", "tree", "ws1", "root1"])
        assert result.exit_code == 0


# ====================================================================
# Plugin load / unload / reload — PluginManager branches
# ====================================================================


class TestPluginLifecycle:
    """Plugin load, unload, reload, discover."""

    def test_plugin_load_success(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        from unittest.mock import MagicMock

        mock_mgr = MagicMock()
        mock_mgr.discover = Mock()
        mock_mgr.load = Mock(return_value=True)
        monkeypatch.setattr("cli.stmem.commands.plugin._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "load", "myplugin"])
        assert result.exit_code == 0
        assert "loaded successfully" in result.output

    def test_plugin_load_fail(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.discover = Mock()
        mock_mgr.load = Mock(return_value=False)
        monkeypatch.setattr("cli.stmem.commands.plugin._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "load", "badplugin"])
        assert result.exit_code == 1
        assert "Failed to load" in result.output

    def test_plugin_unload_was_loaded(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.unload = Mock(return_value=True)
        monkeypatch.setattr("cli.stmem.commands.plugin._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "unload", "myplugin"])
        assert result.exit_code == 0
        assert "unloaded" in result.output

    def test_plugin_unload_not_loaded(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.unload = Mock(return_value=False)
        monkeypatch.setattr("cli.stmem.commands.plugin._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "unload", "missing"])
        assert result.exit_code == 1
        assert "was not loaded" in result.output

    def test_plugin_reload(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.unload_all = Mock()
        mock_mgr.load_all = Mock(return_value=["p1", "p2"])
        monkeypatch.setattr("cli.stmem.commands.plugin._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "reload"])
        assert result.exit_code == 0
        assert "Reloaded 2 plugin" in result.output


# ====================================================================
# Mental model creation — result branch
# ====================================================================


class TestMentalCreate:
    """mental create command with result."""

    def test_mental_create_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"id": "mm1"}])
        result = runner.invoke(
            cli,
            [
                "mental",
                "create",
                "ws1",
                "--memory-ids",
                "m1,m2,m3",
            ],
        )
        assert result.exit_code == 0
        assert "Mental model created" in result.output


# ====================================================================
# Mental synthesize — subprocess branching
# ====================================================================


class TestMentalSynthesize:
    """mental synthesize command with all/dry-run flags."""

    def test_mental_synthesize_all_flag(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(returncode=0)))
        monkeypatch.setattr("os.path.exists", Mock(return_value=True))
        result = runner.invoke(cli, ["mental", "synthesize", "--all"])
        assert result.exit_code == 0
        assert "Running:" in result.output

    def test_mental_synthesize_failure(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(returncode=1)))
        monkeypatch.setattr("os.path.exists", Mock(return_value=True))
        result = runner.invoke(cli, ["mental", "synthesize"])
        assert result.exit_code == 1
        assert "exited with code 1" in result.output

    def test_mental_synthesize_script_missing(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("os.path.exists", Mock(return_value=False))
        result = runner.invoke(cli, ["mental", "synthesize"])
        assert result.exit_code == 1
        # Output contains "not" and "found." but a literal \n separates them;
        # check via the raw newline-free assertion
        assert "not found" in result.output.replace("\n", " ")

    def test_mental_synthesize_dry_run(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(returncode=0)))
        monkeypatch.setattr("os.path.exists", Mock(return_value=True))
        result = runner.invoke(cli, ["mental", "synthesize", "--dry-run"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output


# ====================================================================
# Connector run — RSS import error and success branches
# ====================================================================


class TestConnectorRun:
    """connector run command."""

    def test_connector_run_no_rss(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "connector",
                "run",
                "--workspace-id",
                "ws1",
            ],
        )
        # prints warning (not exit code 1) but it's safe
        assert "No connector specified" in result.output

    def test_connector_run_rss_import_error(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setitem(sys.modules, "spacetime_memory.connectors", None)
        result = runner.invoke(
            cli,
            [
                "connector",
                "run",
                "--rss",
                "https://example.com/feed",
                "--workspace-id",
                "ws1",
            ],
        )
        assert result.exit_code == 1
        assert "Missing dep" in result.output


# ====================================================================
# Connector register — result branch
# ====================================================================


class TestConnectorRegister:
    """connector register command."""

    def test_connector_register_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value={"id": "c1"})
        result = runner.invoke(
            cli,
            [
                "connector",
                "register",
                "--name",
                "rss1",
                "--type",
                "rss",
                "--config",
                '{"url":"https://ex.com/feed"}',
                "--workspace-id",
                "ws1",
            ],
        )
        assert result.exit_code == 0


# ====================================================================
# Ingest — import error path
# ====================================================================


class TestIngestImportError:
    """ingest codebase command — import error branch."""

    def test_ingest_import_error(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setitem(sys.modules, "spacetime_memory.ingest", None)
        # Use an existing path since Click validates Path(exists=True)
        result = runner.invoke(
            cli,
            [
                "ingest",
                "codebase",
                "/tmp",
                "ws1",
            ],
        )
        assert result.exit_code == 1
        assert "pip install spacetime-memory" in result.output

    def test_ingest_success(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_ingester = Mock()
        mock_ingester.ingest = Mock(
            return_value={
                "files": 10,
                "defs": 50,
                "edges": 30,
                "errors": 2,
            }
        )
        # Avoid tree_sitter_language_pack dependency by faking the whole import
        import types

        fake_ingest = types.ModuleType("spacetime_memory.ingest")
        fake_ingest.CodebaseIngester = Mock(return_value=mock_ingester)
        monkeypatch.setitem(sys.modules, "spacetime_memory.ingest", fake_ingest)
        # Also register it on the parent package so the import works
        import spacetime_memory

        monkeypatch.setattr(spacetime_memory, "ingest", fake_ingest, raising=False)
        result = runner.invoke(
            cli,
            [
                "ingest",
                "codebase",
                "/tmp",
                "ws1",
                "--max-files",
                "100",
                "--skip-dirs",
                ".git,node_modules",
            ],
        )
        assert result.exit_code == 0
        assert "Ingestion complete" in result.output


# ====================================================================
# KG edge create and neighbors — result branches
# ====================================================================


class TestKgEdgeCreate:
    """kg edge create command with result."""

    def test_kg_edge_create_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"id": "e1"}])
        result = runner.invoke(
            cli,
            [
                "kg",
                "edge",
                "create",
                "ws1",
                "node1",
                "node2",
                "calls",
            ],
        )
        assert result.exit_code == 0

    def test_kg_neighbors_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_neighbors = Mock(
            return_value=[
                {"node_id": "n2", "relation": "calls", "weight": 1.0},
            ]
        )
        result = runner.invoke(cli, ["kg", "neighbors", "node1"])
        assert result.exit_code == 0

    def test_kg_neighbors_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_neighbors = Mock(return_value=[])
        result = runner.invoke(cli, ["kg", "neighbors", "node1"])
        assert result.exit_code == 0
        assert "No results found" in result.output


# ====================================================================
# Profile get — empty result
# ====================================================================


class TestProfileGetEmpty:
    """profile get with empty results."""

    def test_profile_get_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_profile = Mock(return_value=[])
        result = runner.invoke(cli, ["profile", "get", "peer1"])
        assert result.exit_code == 0
        assert "No results found" in result.output


# ====================================================================
# Context pack — empty result
# ====================================================================


class TestContextPackEmpty:
    """context pack with no results."""

    def test_context_pack_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client.list_context_packs = Mock(return_value=[])
        result = runner.invoke(cli, ["context", "pack", "ws1", "query text"])
        assert result.exit_code == 0
        assert "No context pack generated" in result.output


# ====================================================================
# Replication — add with auto workspace selection
# ====================================================================


class TestReplicationAddAutoWs:
    """replication add — auto workspace selection."""

    def test_replication_add_auto_workspace(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws-auto"}])
        mock_client._call = Mock(return_value=[{"status": "ok"}])
        result = runner.invoke(
            cli,
            [
                "replication",
                "add",
                "peer1",
                "http://127.0.0.10:3001",
                "remote-db",
            ],
        )
        assert result.exit_code == 0

    def test_replication_add_with_workspace_id(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"status": "ok"}])
        result = runner.invoke(
            cli,
            [
                "replication",
                "add",
                "peer1",
                "http://127.0.0.10:3001",
                "remote-db",
                "--workspace-id",
                "ws1",
            ],
        )
        assert result.exit_code == 0


# ====================================================================
# Replication peers — empty result
# ====================================================================


class TestReplicationPeersEmpty:
    """replication peers with empty results."""

    def test_replication_peers_empty_sql(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(return_value=[])
        result = runner.invoke(cli, ["replication", "peers"])
        assert result.exit_code == 0
        assert "No replication peers found" in result.output

    def test_replication_peers_empty_json(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(return_value=[{"json_data": "[]", "query_type": "peers"}])
        result = runner.invoke(cli, ["replication", "peers"])
        assert result.exit_code == 0
        assert "No replication peers found" in result.output

    def test_replication_peers_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            return_value=[
                {
                    "json_data": json.dumps(
                        [{"id": "p1", "name": "remote", "url": "http://r:3001"}]
                    ),
                    "query_type": "peers",
                }
            ]
        )
        result = runner.invoke(cli, ["replication", "peers"])
        assert result.exit_code == 0


# ====================================================================
# Replication status — output format branches
# ====================================================================


class TestReplicationStatusFormats:
    """replication status output format branching."""

    def test_replication_status_json(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            return_value=[
                {
                    "json_data": json.dumps({"status": "synced", "peers": 2}),
                    "query_type": "status",
                    "workspace_id": "ws1",
                }
            ]
        )
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "replication",
                "status",
            ],
        )
        assert result.exit_code == 0

    def test_replication_status_csv(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            return_value=[
                {
                    "json_data": json.dumps({"status": "synced", "peers": 2}),
                    "query_type": "status",
                    "workspace_id": "ws1",
                }
            ]
        )
        result = runner.invoke(
            cli,
            [
                "--output",
                "csv",
                "replication",
                "status",
            ],
        )
        assert result.exit_code == 0

    def test_replication_status_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(return_value=[])
        result = runner.invoke(cli, ["replication", "status", "--workspace-id", "ws1"])
        assert result.exit_code == 0
        assert "No replication status" in result.output


# ====================================================================
# Replication sync — import error
# ====================================================================


class TestReplicationSync:
    """replication sync command — import error path."""

    def test_replication_sync_import_error(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        # Setting sys.modules[name] = None causes ImportError on import,
        # which is the cleanest way to simulate a missing module.
        monkeypatch.setitem(sys.modules, "replication_daemon", None)
        result = runner.invoke(
            cli,
            [
                "replication",
                "sync",
                "--workspace-id",
                "ws1",
            ],
        )
        assert result.exit_code != 0
        assert "replication_daemon.py not found" in result.output


# ====================================================================
# Agent step — import + call path
# ====================================================================


class TestAgentStep:
    """agent step command."""

    def test_agent_step_basic(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            return_value=[
                {"id": "step-1", "workspace_id": "ws1"},
            ]
        )
        result = runner.invoke(
            cli,
            [
                "agent",
                "step",
                "sess1",
                "thought",
                "I should check the cache first",
                "--summary",
                "summary text",
                "--workspace-id",
                "ws1",
            ],
        )
        assert result.exit_code == 0

    def test_agent_step_no_workspace_infer(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            side_effect=[
                [{"workspace_id": "ws-inferred"}],
                [{"id": "step-2"}],
            ]
        )
        result = runner.invoke(
            cli,
            [
                "agent",
                "step",
                "sess1",
                "observation",
                "Tool returned 42",
            ],
        )
        assert result.exit_code == 0


# ====================================================================
# Agent steps — list with SQL results
# ====================================================================


class TestAgentSteps:
    """agent steps command — SQL result branches."""

    def test_agent_steps_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(return_value=[])
        result = runner.invoke(cli, ["agent", "steps", "sess1"])
        assert result.exit_code == 0
        assert "No steps found" in result.output

    def test_agent_steps_with_data(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            return_value=[
                {
                    "id": "step1",
                    "step_type": "thought",
                    "content": "thinking...",
                    "created_at": 1700000000,
                },
                {
                    "id": "step2",
                    "step_type": "action",
                    "content": "call tool",
                    "created_at": 1700000001,
                },
            ]
        )
        result = runner.invoke(cli, ["agent", "steps", "sess1"])
        assert result.exit_code == 0


# ====================================================================
# Metrics show — exception handlers
# ====================================================================


class TestMetricsExceptions:
    """metrics show command — exception handling branches."""

    def test_metrics_show_exceptions_caught(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(side_effect=[OSError("db down"), Mock()])
        mock_client._sql = Mock(side_effect=OSError("sql error"))
        mock_client.list_workspaces = Mock(side_effect=OSError("ws error"))
        result = runner.invoke(cli, ["metrics", "show"])
        assert result.exit_code == 0

    def test_metrics_show_json_output(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(return_value={"status": "ok", "latency_ms": 5})
        mock_client._sql = Mock(return_value=[{"c": 42}])
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        result = runner.invoke(cli, ["metrics", "show", "--json"])
        assert result.exit_code == 0

    def test_metrics_show_with_token(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(return_value={"status": "ok", "latency_ms": 5})
        mock_client._sql = Mock(return_value=[{"c": 42}])
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        result = runner.invoke(cli, ["metrics", "show", "-t", "fake-token"])
        assert result.exit_code == 0


# ====================================================================
# Metrics reset — token path
# ====================================================================


class TestMetricsReset:
    """metrics reset command."""

    def test_metrics_reset(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["metrics", "reset"])
        assert result.exit_code == 0
        assert "Metrics counters reset" in result.output

    def test_metrics_reset_with_token(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["metrics", "reset", "-t", "fake-token"])
        assert result.exit_code == 0


# ====================================================================
# Admin init — with token
# ====================================================================


class TestAdminInit:
    """admin init command with token."""

    def test_admin_init_with_token(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        result = runner.invoke(
            cli,
            [
                "admin",
                "init",
                "abcdef1234567890",
                "-t",
                "jwt-token",
            ],
        )
        assert result.exit_code == 0
        assert "Initial admin set" in result.output


# ====================================================================
# Replication list — alias for peers
# ====================================================================


class TestReplicationListAlias:
    """replication list (alias for peers)."""

    def test_replication_list(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(
            return_value=[
                {
                    "json_data": json.dumps(
                        [{"id": "p1", "name": "remote", "url": "http://r:3001"}]
                    ),
                    "query_type": "peers",
                }
            ]
        )
        result = runner.invoke(cli, ["replication", "list"])
        assert result.exit_code == 0


# ====================================================================
# Replication remove — result
# ====================================================================


class TestReplicationRemove:
    """replication remove with result."""

    def test_replication_remove_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"status": "ok"}])
        result = runner.invoke(cli, ["replication", "remove", "peer-id-1"])
        assert result.exit_code == 0


# ====================================================================
# Replication daemon — import error
# ====================================================================


class TestReplicationDaemon:
    """replication daemon command — import error path."""

    def test_replication_daemon_import_error(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        # Block the replication_daemon import so we hit the error path
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "replication_daemon":
                raise ImportError("No module named replication_daemon")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = runner.invoke(cli, ["replication", "daemon"])
        assert result.exit_code == 1
        assert "replication_daemon.py not found" in result.output


# ====================================================================
# MCP serve — ImportError path
# ====================================================================


class TestMcpServe:
    """mcp serve command — not yet implemented in CLI."""

    def test_mcp_command_not_found(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["mcp", "serve"])
        # Command not implemented — Click returns exit code 2
        assert result.exit_code == 2
        assert "No such command" in result.output


# ====================================================================
# AAAK — pipe and file input modes
# ====================================================================


class TestAaakCompressInput:
    """aaak compress command — pipe and file input modes."""

    def test_aaak_compress_pipe_input(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("sys.stdin.isatty", Mock(return_value=True))
        monkeypatch.setattr("sys.stdin.read", Mock(return_value="PREFERENCE: dark mode"))
        result = runner.invoke(cli, ["aaak", "compress", "--pipe"])
        assert result.exit_code == 0

    def test_aaak_compress_file_input(self, mocked_cli_runner, tmp_path):
        runner, mock_client = mocked_cli_runner
        f = tmp_path / "input.txt"
        f.write_text("PREFERENCE: dark mode")
        result = runner.invoke(cli, ["aaak", "compress", "--file", str(f)])
        assert result.exit_code == 0

    def test_aaak_compress_no_input_error(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        # CliRunner always provides stdin (empty when no input= given).
        # The function reads empty stdin and produces a table (exit 0).
        # The "provide text" error path is terminal-only (isatty check).
        result = runner.invoke(cli, ["aaak", "compress"])
        assert result.exit_code == 0
        assert "AAAK Compression" in result.output

    def test_aaak_compress_pipe_output(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("sys.stdin.isatty", Mock(return_value=True))
        monkeypatch.setattr("sys.stdin.read", Mock(return_value="PREFERENCE: dark mode"))
        result = runner.invoke(cli, ["aaak", "compress", "--pipe"])
        assert result.exit_code == 0


class TestAaakDecompressInput:
    """aaak decompress command — pipe and file input modes."""

    def test_aaak_decompress_pipe_input(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("sys.stdin.isatty", Mock(return_value=True))
        monkeypatch.setattr("sys.stdin.read", Mock(return_value="PREF:dm"))
        result = runner.invoke(cli, ["aaak", "decompress", "--pipe"])
        assert result.exit_code == 0

    def test_aaak_decompress_file_input(self, mocked_cli_runner, tmp_path):
        runner, mock_client = mocked_cli_runner
        f = tmp_path / "compressed.txt"
        f.write_text("PREF:dm")
        result = runner.invoke(cli, ["aaak", "decompress", "--file", str(f)])
        assert result.exit_code == 0

    def test_aaak_decompress_no_input_error(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        # CliRunner always provides stdin — reads empty, produces table (exit 0).
        # The error path is terminal-only.
        result = runner.invoke(cli, ["aaak", "decompress"])
        assert result.exit_code == 0
        assert "AAAK" in result.output or "Decompress" in result.output


class TestAaakRatio:
    """aaak ratio command."""

    def test_aaak_ratio_pipe_input(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setattr("sys.stdin.isatty", Mock(return_value=True))
        monkeypatch.setattr("sys.stdin.read", Mock(return_value="PREFERENCE: dark mode"))
        result = runner.invoke(cli, ["aaak", "ratio", "--pipe"])
        assert result.exit_code == 0

    def test_aaak_ratio_file_input(self, mocked_cli_runner, tmp_path):
        runner, mock_client = mocked_cli_runner
        f = tmp_path / "input.txt"
        f.write_text("PREFERENCE: dark mode")
        result = runner.invoke(cli, ["aaak", "ratio", "--file", str(f)])
        assert result.exit_code == 0


# ====================================================================
# Veracity — list and calc error paths
# ====================================================================


class TestVeracityList:
    """veracity list command."""

    def test_veracity_list(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["veracity", "list"])
        assert result.exit_code == 0


class TestVeracityCalc:
    """veracity calc command — error paths."""

    def test_veracity_calc_no_args(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["veracity", "calc"])
        assert result.exit_code == 1
        assert "provide --tier or --base" in result.output

    def test_veracity_calc_with_tier(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["veracity", "calc", "--tier", "stated", "--sources", "3"])
        assert result.exit_code == 0
        assert "Confidence:" in result.output

    def test_veracity_calc_with_base(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["veracity", "calc", "--base", "0.7", "--sources", "2"])
        assert result.exit_code == 0
        assert "Confidence:" in result.output


# ====================================================================
# Veracity compound — compound output
# ====================================================================


class TestVeracityCompound:
    """veracity compound command."""

    def test_veracity_compound(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["veracity", "compound", "--tier", "stated", "--sources", "3"])
        assert result.exit_code == 0
        # With tier "stated" (base confidence 1.00) and 3 sources:
        # compounded confidence = 1 - (1-1.00)^3 = 1.0000
        assert "Compounded" in result.output


# ====================================================================
# SHMR resonate — full path
# ====================================================================


class TestShmrResonate:
    """shmr resonate command."""

    def test_shmr_resonate(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.search = Mock(return_value=[])
        mock_client._embed = Mock(return_value=[])
        mock_client._call = Mock(return_value=[{"count": 5}])
        result = runner.invoke(
            cli,
            [
                "shmr",
                "resonate",
                "ws1",
                "--days",
                "30",
            ],
        )
        assert result.exit_code == 0

    def test_shmr_resonate_with_iterations(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.search = Mock(return_value=[])
        mock_client._embed = Mock(return_value=[])
        mock_client._call = Mock(return_value=[{"count": 10}])
        result = runner.invoke(
            cli,
            [
                "shmr",
                "resonate",
                "ws1",
                "--days",
                "7",
                "--iterations",
                "3",
            ],
        )
        assert result.exit_code == 0

    def test_shmr_resonate_json_output(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.search = Mock(return_value=[])
        mock_client._embed = Mock(return_value=[])
        mock_client._call = Mock(return_value=[{"count": 5}])
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "shmr",
                "resonate",
                "ws1",
            ],
        )
        assert result.exit_code == 0


# ====================================================================
# Memory history — result branch
# ====================================================================


class TestMemoryHistory:
    """memory history command."""

    def test_memory_history(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_memory_history = Mock(
            return_value=[
                {"id": "v1", "content": "old content", "created_at": 1700000000},
                {"id": "v2", "content": "newer content", "created_at": 1700000001},
            ]
        )
        result = runner.invoke(cli, ["memory", "history", "mem-id-12345"])
        assert result.exit_code == 0

    def test_memory_history_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_memory_history = Mock(return_value=[])
        result = runner.invoke(cli, ["memory", "history", "mem-id-12345"])
        assert result.exit_code == 0
        assert "No results found" in result.output


# ====================================================================
# Session create — result branch
# ====================================================================


class TestSessionCreate:
    """session create command with result."""

    def test_session_create_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"id": "sess-new"}])
        result = runner.invoke(
            cli,
            [
                "session",
                "create",
                "ws1",
                "my-session",
            ],
        )
        assert result.exit_code == 0

    def test_session_messages(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_session_messages = Mock(
            return_value=[
                {"id": "msg1", "role": "user", "content": "hello"},
            ]
        )
        result = runner.invoke(cli, ["session", "messages", "sess1"])
        assert result.exit_code == 0

    def test_session_messages_empty(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_session_messages = Mock(return_value=[])
        result = runner.invoke(cli, ["session", "messages", "sess1"])
        assert result.exit_code == 0
        assert "No results found" in result.output


# ====================================================================
# Recommend and peer-reputation — output format / result paths
# ====================================================================


class TestRecommendOutput:
    """recommend and peer-reputation with different outputs."""

    def test_recommend_json(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.recommend_memories = Mock(return_value=[{"id": "r1"}])
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "recommend",
                "ws1",
            ],
        )
        assert result.exit_code == 0

    def test_recommend_csv(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.recommend_memories = Mock(return_value=[{"id": "r1"}])
        result = runner.invoke(
            cli,
            [
                "--output",
                "csv",
                "recommend",
                "ws1",
            ],
        )
        assert result.exit_code == 0

    def test_peer_reputation_json(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"peer_id": "p1", "score": 0.8}])
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "peer-reputation",
                "ws1",
            ],
        )
        assert result.exit_code == 0


# ====================================================================
# Directory link / unlink — result branches
# ====================================================================


class TestDirectoryLink:
    """directory link and unlink with results."""

    def test_directory_link_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.link_memory_to_directory = Mock(return_value={"status": "ok"})
        result = runner.invoke(
            cli,
            [
                "directory",
                "link",
                "dir1",
                "mem1",
                "ws1",
            ],
        )
        assert result.exit_code == 0

    def test_directory_unlink_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.unlink_memory_from_directory = Mock(return_value={"status": "ok"})
        result = runner.invoke(
            cli,
            [
                "directory",
                "unlink",
                "dir1",
                "mem1",
            ],
        )
        assert result.exit_code == 0

    def test_directory_create_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.create_directory = Mock(return_value={"id": "dir-new"})
        result = runner.invoke(
            cli,
            [
                "directory",
                "create",
                "ws1",
                "mydir",
                "/path/mydir",
            ],
        )
        assert result.exit_code == 0


# ====================================================================
# Health — model_path line coverage
# ====================================================================


class TestHealthModelPath:
    """health command covering embedder model_path branch."""

    def test_health_with_model_path(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.health = Mock(
            return_value={
                "status": "ok",
                "database": {"status": "ok", "latency_ms": 5},
                "embedder": {"reachable": True, "model_path": "/models/bge-m3"},
                "token_configured": True,
            }
        )
        result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0
        assert "Model:" in result.output

    def test_health_degraded(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.health = Mock(
            return_value={
                "status": "degraded",
                "database": {"status": "ok", "latency_ms": 5},
                "embedder": {"reachable": False},
                "token_configured": False,
            }
        )
        result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0
        assert "System degraded" in result.output


# ====================================================================
# Diagnostics — JSON and exception paths
# ====================================================================


class TestDiagnosticsFull:
    """diagnostics command — JSON output and full paths."""

    def test_diagnostics_json(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(return_value={"status": "ok", "latency_ms": 3})
        mock_client.health = Mock(
            return_value={
                "status": "ok",
                "embedder": {"reachable": True, "model_path": "bge-m3"},
                "token_configured": True,
            }
        )
        # diagnostics sends 2 SQL queries with different projections
        def _sql_side_effect(q: str) -> list[dict]:
            if "GROUP BY memory_type" in q:
                return [{"memory_type": "experience", "c": 10}]
            if "GROUP BY tier" in q:
                return [{"tier": "L0", "c": 3}, {"tier": "L1", "c": 7}]
            return []
        mock_client._sql = Mock(side_effect=_sql_side_effect)
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        result = runner.invoke(cli, ["diagnostics", "--json"])
        assert result.exit_code == 0

    def test_diagnostics_exceptions(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(return_value={"status": "ok", "latency_ms": 3})
        mock_client.health = Mock(
            return_value={
                "status": "ok",
                "embedder": {"reachable": True},
                "token_configured": False,
            }
        )
        mock_client._sql = Mock(side_effect=OSError("mock error"))
        mock_client.list_workspaces = Mock(side_effect=OSError("mock error"))
        result = runner.invoke(cli, ["diagnostics"])
        assert result.exit_code == 0


# ====================================================================
# main() — error handling paths
# ====================================================================


class TestMainErrorPaths:
    """main() exception handlers for ClickException and httpx.ConnectError."""

    def test_main_click_exception(self, monkeypatch):
        import click

        monkeypatch.setattr("cli.stmem.root.cli", Mock(side_effect=click.ClickException("bad param")))
        with pytest.raises(SystemExit) as exc_info:
            from cli.stmem import main

            main()
        assert exc_info.value.code == 1

    def test_main_runtime_error(self, monkeypatch):
        monkeypatch.setattr("cli.stmem.root.cli", Mock(side_effect=RuntimeError("oops")))
        with pytest.raises(SystemExit) as exc_info:
            from cli.stmem import main

            main()
        assert exc_info.value.code == 1

    def test_main_httpx_connect_error(self, monkeypatch):
        import httpx

        monkeypatch.setattr(
            "cli.stmem.root.cli", Mock(side_effect=httpx.ConnectError("connection refused"))
        )
        with pytest.raises(SystemExit) as exc_info:
            from cli.stmem import main

            main()
        assert exc_info.value.code == 1


# ====================================================================
# Compounder CLI commands — lint, cross-link, suggest-connections,
# store-answer, entity-page, concept-page, comparison-page
# ====================================================================


class TestLintCLI:
    """stmem lint"""

    def test_lint_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["lint", "--help"])
        assert result.exit_code == 0
        assert "orphan" in result.output.lower() or "health-check" in result.output.lower()

    def test_lint_basic(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli, ["lint", "--workspace", "test", "--no-contradictions", "--no-crossrefs"]
        )
        assert result.exit_code == 0

    def test_lint_json_output(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli, ["--output", "json", "lint", "-w", "test", "--no-contradictions"]
        )
        assert result.exit_code == 0


class TestCrossLinkCLI:
    """stmem cross-link"""

    def test_cross_link_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["cross-link", "--help"])
        assert result.exit_code == 0

    def test_cross_link_basic(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["cross-link", "-w", "test"])
        assert result.exit_code == 0

    def test_cross_link_dry_run(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["cross-link", "-w", "test", "--dry-run"])
        assert result.exit_code == 0

    def test_cross_link_json(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["--output", "json", "cross-link", "-w", "test"])
        assert result.exit_code == 0


class TestSuggestConnectionsCLI:
    """stmem suggest-connections"""

    def test_suggest_connections_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["suggest-connections", "--help"])
        assert result.exit_code == 0

    def test_suggest_connections_basic(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["suggest-connections", "-w", "test"])
        assert result.exit_code == 0

    def test_suggest_connections_with_limit(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["suggest-connections", "-w", "test", "-n", "5"])
        assert result.exit_code == 0

    def test_suggest_connections_json(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["--output", "json", "suggest-connections", "-w", "test"])
        assert result.exit_code == 0

    def test_suggest_connections_json_with_limit(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli, ["--output", "json", "suggest-connections", "-w", "test", "-n", "10"]
        )
        assert result.exit_code == 0


class TestStoreAnswerCLI:
    """stmem store-answer"""

    def test_store_answer_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["store-answer", "--help"])
        assert result.exit_code == 0

    def test_store_answer_basic(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answer",
                "-w",
                "test",
                "--query",
                "What is testing?",
                "--answer",
                "Testing verifies behavior.",
            ],
        )
        assert result.exit_code == 0

    def test_store_answer_with_source_ids(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answer",
                "-w",
                "test",
                "-q",
                "What is testing?",
                "-a",
                "Testing verifies behavior.",
                "-s",
                "mem1,mem2",
            ],
        )
        assert result.exit_code == 0

    def test_store_answer_missing_required(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["store-answer"])
        assert result.exit_code != 0


class TestStoreAnswersBatchCLI:
    """stmem store-answers-batch"""

    def test_store_answers_batch_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["store-answers-batch", "--help"])
        assert result.exit_code == 0
        assert "Batch" in result.output or "pairs" in result.output

    def test_store_answers_batch_valid_pairs(self, mocked_cli_runner, monkeypatch):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-w",
                "test",
                "-p",
                '[["What is X?", "X is Y."], ["What is Z?", "Z is W."]]',
            ],
        )
        assert result.exit_code == 0

    def test_store_answers_batch_empty_list(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                "[]",
            ],
        )
        assert result.exit_code == 0

    def test_store_answers_batch_single_pair(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                '[["Q1", "A1"]]',
            ],
        )
        assert result.exit_code == 0

    def test_store_answers_batch_invalid_json(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                "not valid json",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid JSON" in result.output

    def test_store_answers_batch_not_a_list(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                '"just a string"',
            ],
        )
        assert result.exit_code == 1
        assert "Pairs must be" in result.output

    def test_store_answers_batch_wrong_structure(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                "[1, 2, 3]",
            ],
        )
        assert result.exit_code == 1
        assert "Pairs must be" in result.output

    def test_store_answers_batch_with_workspace(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-w",
                "custom_ws",
                "-p",
                '[["Q", "A"]]',
            ],
        )
        assert result.exit_code == 0

    def test_store_answers_batch_with_source_ids(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                '[["Q", "A"]]',
                "-s",
                "mem1,mem2,mem3",
            ],
        )
        assert result.exit_code == 0

    def test_store_answers_batch_file_input(self, mocked_cli_runner, tmp_path):
        runner, _ = mocked_cli_runner
        pairs_file = tmp_path / "pairs.json"
        pairs_file.write_text('[["Q1", "A1"], ["Q2", "A2"]]')
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                "[[ignored]]",  # --pairs is required, value overwritten by --file
                "-f",
                str(pairs_file),
            ],
        )
        assert result.exit_code == 0

    def test_store_answers_batch_file_not_found(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "store-answers-batch",
                "-p",
                "[[ignored]]",
                "-f",
                "/nonexistent/pairs.json",
            ],
        )
        assert result.exit_code == 1
        assert "File not found" in result.output


class TestEntityPageCLI:
    """stmem entity-page"""

    def test_entity_page_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["entity-page", "--help"])
        assert result.exit_code == 0

    def test_entity_page_basic(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "entity-page",
                "--name",
                "Neural Network",
                "--description",
                "A computational model inspired by biological neurons.",
                "-w",
                "test",
            ],
        )
        assert result.exit_code == 0

    def test_entity_page_with_type(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "entity-page",
                "-n",
                "Alan Turing",
                "-d",
                "British mathematician and computer scientist.",
                "-t",
                "person",
                "--tags",
                "AI,history",
                "--related",
                "Turing Test,Enigma",
            ],
        )
        assert result.exit_code == 0

    def test_entity_page_json(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "entity-page",
                "-n",
                "Test",
                "-d",
                "A test entity.",
            ],
        )
        assert result.exit_code == 0

    def test_entity_page_missing_required(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["entity-page"])
        assert result.exit_code != 0


class TestConceptPageCLI:
    """stmem concept-page"""

    def test_concept_page_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["concept-page", "--help"])
        assert result.exit_code == 0

    def test_concept_page_basic(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "concept-page",
                "--concept",
                "Backpropagation",
                "--definition",
                "Algorithm for computing gradients in neural networks.",
                "-w",
                "test",
            ],
        )
        assert result.exit_code == 0

    def test_concept_page_with_related(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "concept-page",
                "-c",
                "Gradient Descent",
                "-d",
                "First-order iterative optimization algorithm.",
                "--related",
                "Backpropagation,Learning Rate",
            ],
        )
        assert result.exit_code == 0

    def test_concept_page_json(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "concept-page",
                "-c",
                "Test",
                "-d",
                "A test concept.",
            ],
        )
        assert result.exit_code == 0

    def test_concept_page_missing_required(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["concept-page"])
        assert result.exit_code != 0


class TestComparisonPageCLI:
    """stmem comparison-page"""

    def test_comparison_page_help(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["comparison-page", "--help"])
        assert result.exit_code == 0

    def test_comparison_page_basic(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "comparison-page",
                "--title",
                "PyTorch vs TensorFlow",
                "--items",
                "PyTorch,TensorFlow",
                "-w",
                "test",
            ],
        )
        assert result.exit_code == 0

    def test_comparison_page_with_criteria(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "comparison-page",
                "-t",
                "React vs Vue vs Svelte",
                "-i",
                "React,Vue,Svelte",
                "-c",
                "performance,learning curve,ecosystem,bundle size",
            ],
        )
        assert result.exit_code == 0

    def test_comparison_page_json(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(
            cli,
            [
                "--output",
                "json",
                "comparison-page",
                "-t",
                "Test",
                "-i",
                "A,B",
            ],
        )
        assert result.exit_code == 0

    def test_comparison_page_missing_required(self, mocked_cli_runner):
        runner, _ = mocked_cli_runner
        result = runner.invoke(cli, ["comparison-page"])
        assert result.exit_code != 0
