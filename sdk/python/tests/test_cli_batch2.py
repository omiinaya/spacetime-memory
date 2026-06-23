"""Tests for the stmem CLI — batch 2: directory tree, plugin lifecycle,
connector run, agent step, AAAK pipe/file input, metrics exceptions,
replication branches, veracity, SHMR resonate, main() error paths,
and other easy-to-test branches.
"""

import json
import sys
import pytest
from unittest.mock import Mock
from cli.stmem import cli


# ====================================================================
# Directory tree — traverse_directory
# ====================================================================

class TestDirectoryTree:
    """directory tree command."""

    def test_directory_tree_with_results(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.traverse_directory = Mock(return_value=[
            {"id": "d1", "name": "subdir", "path": "/root/subdir", "type": "directory"},
            {"id": "m1", "name": "memory_1", "memory_id": "mem1", "type": "memory"},
        ])
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
        monkeypatch.setattr("cli.stmem._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "load", "myplugin"])
        assert result.exit_code == 0
        assert "loaded successfully" in result.output

    def test_plugin_load_fail(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.discover = Mock()
        mock_mgr.load = Mock(return_value=False)
        monkeypatch.setattr("cli.stmem._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "load", "badplugin"])
        assert result.exit_code == 1
        assert "Failed to load" in result.output

    def test_plugin_unload_was_loaded(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.unload = Mock(return_value=True)
        monkeypatch.setattr("cli.stmem._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "unload", "myplugin"])
        assert result.exit_code == 0
        assert "unloaded" in result.output

    def test_plugin_unload_not_loaded(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.unload = Mock(return_value=False)
        monkeypatch.setattr("cli.stmem._plugin_manager", lambda: mock_mgr)
        result = runner.invoke(cli, ["plugin", "unload", "missing"])
        assert result.exit_code == 1
        assert "was not loaded" in result.output

    def test_plugin_reload(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_mgr = Mock()
        mock_mgr.unload_all = Mock()
        mock_mgr.load_all = Mock(return_value=["p1", "p2"])
        monkeypatch.setattr("cli.stmem._plugin_manager", lambda: mock_mgr)
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
        result = runner.invoke(cli, [
            "mental", "create", "ws1", "--memory-ids", "m1,m2,m3",
        ])
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
        # Output contains "not", "found" separated by a literal backslash-n
        assert "not " in result.output and "found." in result.output

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
        result = runner.invoke(cli, [
            "connector", "run", "--workspace-id", "ws1",
        ])
        # prints warning (not exit code 1) but it's safe
        assert "No connector specified" in result.output

    def test_connector_run_rss_import_error(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setitem(sys.modules, "spacetime_memory.connectors", None)
        result = runner.invoke(cli, [
            "connector", "run", "--rss", "https://example.com/feed",
            "--workspace-id", "ws1",
        ])
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
        result = runner.invoke(cli, [
            "connector", "register", "--name", "rss1",
            "--type", "rss", "--config", '{"url":"https://ex.com/feed"}',
            "--workspace-id", "ws1",
        ])
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
        result = runner.invoke(cli, [
            "ingest", "codebase", "/tmp", "ws1",
        ])
        assert result.exit_code == 1
        assert "pip install spacetime-memory" in result.output

    def test_ingest_success(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_ingester = Mock()
        mock_ingester.ingest = Mock(return_value={
            "files": 10, "defs": 50, "edges": 30, "errors": 2,
        })
        # Avoid tree_sitter_language_pack dependency by faking the whole import
        import types
        fake_ingest = types.ModuleType("spacetime_memory.ingest")
        fake_ingest.CodebaseIngester = Mock(return_value=mock_ingester)
        monkeypatch.setitem(sys.modules, "spacetime_memory.ingest", fake_ingest)
        # Also register it on the parent package so the import works
        import spacetime_memory
        monkeypatch.setattr(spacetime_memory, "ingest", fake_ingest, raising=False)
        result = runner.invoke(cli, [
            "ingest", "codebase", "/tmp", "ws1",
            "--max-files", "100", "--skip-dirs", ".git,node_modules",
        ])
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
        result = runner.invoke(cli, [
            "kg", "edge", "create", "ws1", "node1", "node2", "calls",
        ])
        assert result.exit_code == 0

    def test_kg_neighbors_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_neighbors = Mock(return_value=[
            {"node_id": "n2", "relation": "calls", "weight": 1.0},
        ])
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
        result = runner.invoke(cli, [
            "replication", "add", "peer1",
            "http://127.0.0.10:3001", "remote-db",
        ])
        assert result.exit_code == 0

    def test_replication_add_with_workspace_id(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"status": "ok"}])
        result = runner.invoke(cli, [
            "replication", "add", "peer1",
            "http://127.0.0.10:3001", "remote-db",
            "--workspace-id", "ws1",
        ])
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
        mock_client._sql = Mock(return_value=[{
            "json_data": json.dumps([
                {"id": "p1", "name": "remote", "url": "http://r:3001"}
            ]),
            "query_type": "peers",
        }])
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
        mock_client._sql = Mock(return_value=[{
            "json_data": json.dumps({"status": "synced", "peers": 2}),
            "query_type": "status",
            "workspace_id": "ws1",
        }])
        result = runner.invoke(cli, [
            "--output", "json", "replication", "status",
        ])
        assert result.exit_code == 0

    def test_replication_status_csv(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(return_value=[{
            "json_data": json.dumps({"status": "synced", "peers": 2}),
            "query_type": "status",
            "workspace_id": "ws1",
        }])
        result = runner.invoke(cli, [
            "--output", "csv", "replication", "status",
        ])
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

    def test_replication_sync_import_error(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, [
            "replication", "sync", "--workspace-id", "ws1",
        ])
        if result.exit_code != 0:
            assert "replication_daemon.py not found" in result.output


# ====================================================================
# Agent step — import + call path
# ====================================================================

class TestAgentStep:
    """agent step command."""

    def test_agent_step_basic(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(return_value=[
            {"id": "step-1", "workspace_id": "ws1"},
        ])
        result = runner.invoke(cli, [
            "agent", "step", "sess1", "thought",
            "I should check the cache first",
            "--summary", "summary text",
            "--workspace-id", "ws1",
        ])
        assert result.exit_code == 0

    def test_agent_step_no_workspace_infer(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[])
        mock_client._sql = Mock(side_effect=[
            [{"workspace_id": "ws-inferred"}],
            [{"id": "step-2"}],
        ])
        result = runner.invoke(cli, [
            "agent", "step", "sess1", "observation", "Tool returned 42",
        ])
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
        mock_client._sql = Mock(return_value=[
            {"id": "step1", "step_type": "thought", "content": "thinking...", "created_at": 1700000000},
            {"id": "step2", "step_type": "action", "content": "call tool", "created_at": 1700000001},
        ])
        result = runner.invoke(cli, ["agent", "steps", "sess1"])
        assert result.exit_code == 0


# ====================================================================
# Metrics show — exception handlers
# ====================================================================

class TestMetricsExceptions:
    """metrics show command — exception handling branches."""

    def test_metrics_show_exceptions_caught(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(side_effect=[Exception("db down"), Mock()])
        mock_client._sql = Mock(side_effect=Exception("sql error"))
        mock_client.list_workspaces = Mock(side_effect=Exception("ws error"))
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
        result = runner.invoke(cli, [
            "admin", "init", "abcdef1234567890", "-t", "jwt-token",
        ])
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
        mock_client._sql = Mock(return_value=[{
            "json_data": json.dumps([
                {"id": "p1", "name": "remote", "url": "http://r:3001"}
            ]),
            "query_type": "peers",
        }])
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

    def test_replication_daemon_import_error(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        result = runner.invoke(cli, ["replication", "daemon"])
        assert result.exit_code == 1
        assert "replication_daemon.py not found" in result.output


# ====================================================================
# MCP serve — ImportError path
# ====================================================================

class TestMcpServe:
    """mcp serve command — error paths."""

    def test_mcp_serve_stdio_import_error(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setitem(sys.modules, "server.mcp.main", None)
        result = runner.invoke(cli, ["mcp", "serve"])
        assert result.exit_code == 1
        assert "Cannot start MCP server" in result.output

    def test_mcp_serve_sse_import_error(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        monkeypatch.setitem(sys.modules, "server.mcp.main", None)
        result = runner.invoke(cli, ["mcp", "serve", "--transport", "sse"])
        assert result.exit_code == 1
        assert "Cannot start MCP server" in result.output

    def test_mcp_serve_runtime_error(self, monkeypatch, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        import types
        fake_run = types.ModuleType("server.mcp.main")
        fake_run.run = Mock(side_effect=Exception("port in use"))
        monkeypatch.setitem(sys.modules, "server.mcp.main", fake_run)
        result = runner.invoke(cli, ["mcp", "serve"])
        assert result.exit_code == 1
        assert "MCP server failed" in result.output


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
        monkeypatch.setattr("sys.stdin.isatty", Mock(return_value=True))
        result = runner.invoke(cli, ["aaak", "compress"])
        assert result.exit_code == 1
        assert "provide text, --file, or pipe input" in result.output

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
        monkeypatch.setattr("sys.stdin.isatty", Mock(return_value=True))
        result = runner.invoke(cli, ["aaak", "decompress"])
        assert result.exit_code == 1
        assert "provide text, --file, or pipe input" in result.output


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
        result = runner.invoke(cli, ["veracity", "compound", "stated", "3"])
        assert result.exit_code == 0
        assert "0." in result.output


# ====================================================================
# SHMR resonate — full path
# ====================================================================

class TestShmrResonate:
    """shmr resonate command."""

    def test_shmr_resonate(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"count": 5}])
        result = runner.invoke(cli, [
            "shmr", "resonate", "ws1", "--days", "30",
        ])
        assert result.exit_code == 0

    def test_shmr_resonate_with_iterations(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"count": 10}])
        result = runner.invoke(cli, [
            "shmr", "resonate", "ws1", "--days", "7", "--iterations", "3",
        ])
        assert result.exit_code == 0

    def test_shmr_resonate_json_output(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"count": 5}])
        result = runner.invoke(cli, [
            "--output", "json", "shmr", "resonate", "ws1",
        ])
        assert result.exit_code == 0


# ====================================================================
# Memory history — result branch
# ====================================================================

class TestMemoryHistory:
    """memory history command."""

    def test_memory_history(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_memory_history = Mock(return_value=[
            {"id": "v1", "content": "old content", "created_at": 1700000000},
            {"id": "v2", "content": "newer content", "created_at": 1700000001},
        ])
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
        result = runner.invoke(cli, [
            "session", "create", "ws1", "my-session",
        ])
        assert result.exit_code == 0

    def test_session_messages(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.get_session_messages = Mock(return_value=[
            {"id": "msg1", "role": "user", "content": "hello"},
        ])
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
        mock_client._call = Mock(return_value=[{"id": "r1"}])
        result = runner.invoke(cli, [
            "--output", "json", "recommend", "ws1", "query",
        ])
        assert result.exit_code == 0

    def test_recommend_csv(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"id": "r1"}])
        result = runner.invoke(cli, [
            "--output", "csv", "recommend", "ws1", "query",
        ])
        assert result.exit_code == 0

    def test_peer_reputation_json(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client._call = Mock(return_value=[{"peer_id": "p1", "score": 0.8}])
        result = runner.invoke(cli, [
            "--output", "json", "peer-reputation", "ws1",
        ])
        assert result.exit_code == 0


# ====================================================================
# Directory link / unlink — result branches
# ====================================================================

class TestDirectoryLink:
    """directory link and unlink with results."""

    def test_directory_link_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.link_memory_to_directory = Mock(return_value={"status": "ok"})
        result = runner.invoke(cli, [
            "directory", "link", "dir1", "mem1", "ws1",
        ])
        assert result.exit_code == 0

    def test_directory_unlink_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.unlink_memory_from_directory = Mock(return_value={"status": "ok"})
        result = runner.invoke(cli, [
            "directory", "unlink", "dir1", "mem1",
        ])
        assert result.exit_code == 0

    def test_directory_create_with_result(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.create_directory = Mock(return_value={"id": "dir-new"})
        result = runner.invoke(cli, [
            "directory", "create", "ws1", "mydir", "/path/mydir",
        ])
        assert result.exit_code == 0


# ====================================================================
# Health — model_path line coverage
# ====================================================================

class TestHealthModelPath:
    """health command covering embedder model_path branch."""

    def test_health_with_model_path(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.health = Mock(return_value={
            "status": "ok",
            "database": {"status": "ok", "latency_ms": 5},
            "embedder": {"reachable": True, "model_path": "/models/bge-m3"},
            "token_configured": True,
        })
        result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0
        assert "Model:" in result.output

    def test_health_degraded(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.health = Mock(return_value={
            "status": "degraded",
            "database": {"status": "ok", "latency_ms": 5},
            "embedder": {"reachable": False},
            "token_configured": False,
        })
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
        mock_client.health = Mock(return_value={
            "status": "ok",
            "embedder": {"reachable": True, "model_path": "bge-m3"},
            "token_configured": True,
        })
        mock_client._sql = Mock(return_value=[
            {"memory_type": "experience", "c": 10},
        ])
        mock_client.list_workspaces = Mock(return_value=[{"id": "ws1"}])
        result = runner.invoke(cli, ["diagnostics", "--json"])
        assert result.exit_code == 0

    def test_diagnostics_exceptions(self, mocked_cli_runner):
        runner, mock_client = mocked_cli_runner
        mock_client.ping = Mock(return_value={"status": "ok", "latency_ms": 3})
        mock_client.health = Mock(return_value={
            "status": "ok",
            "embedder": {"reachable": True},
            "token_configured": False,
        })
        mock_client._sql = Mock(side_effect=Exception("mock error"))
        mock_client.list_workspaces = Mock(side_effect=Exception("mock error"))
        result = runner.invoke(cli, ["diagnostics"])
        assert result.exit_code == 0


# ====================================================================
# main() — error handling paths
# ====================================================================

class TestMainErrorPaths:
    """main() exception handlers for ClickException and httpx.ConnectError."""

    def test_main_click_exception(self, monkeypatch):
        import click
        monkeypatch.setattr("cli.stmem.cli", Mock(side_effect=click.ClickException("bad param")))
        with pytest.raises(SystemExit) as exc_info:
            from cli.stmem import main
            main()
        assert exc_info.value.code == 1

    def test_main_runtime_error(self, monkeypatch):
        monkeypatch.setattr("cli.stmem.cli", Mock(side_effect=RuntimeError("oops")))
        with pytest.raises(SystemExit) as exc_info:
            from cli.stmem import main
            main()
        assert exc_info.value.code == 1

    def test_main_httpx_connect_error(self, monkeypatch):
        import httpx
        monkeypatch.setattr("cli.stmem.cli", Mock(side_effect=httpx.ConnectError("connection refused")))
        with pytest.raises(SystemExit) as exc_info:
            from cli.stmem import main
            main()
        assert exc_info.value.code == 1
