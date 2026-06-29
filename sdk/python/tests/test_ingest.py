"""Tests for ingest.py — CodebaseIngester with mocked tree-sitter."""

from __future__ import annotations

import sys
from unittest.mock import Mock, MagicMock, patch

import pytest

# Mock tree-sitter modules before spacetime_memory.ingest imports them.
_mock_ts = MagicMock()
_mock_ts_pack = MagicMock()
_mock_ts_pack.get_language.return_value = MagicMock()
sys.modules["tree_sitter"] = _mock_ts
sys.modules["tree_sitter_language_pack"] = _mock_ts_pack

from spacetime_memory.ingest import CodebaseIngester, _LangConfig, _LANG_QUERIES  # noqa: E402


# ── Helpers: mock tree-sitter nodes and captures ────────────────────────


def _make_capture(names_nodes: dict[str, Mock]) -> list:
    """Build a match tuple like tree-sitter's (pattern_idx, captures_dict)."""
    return (0, names_nodes)


def _make_node(text: str, start: int = 0, end: int = 5) -> Mock:
    """Create a mock tree-sitter node with given text."""
    node = Mock()
    node.start_byte = start
    node.end_byte = end
    node.text = text.encode()
    return node


def _make_cursor_matches(*captures_list: list) -> Mock:
    """Create a mock QueryCursor that yields given matches."""
    cursor = Mock()
    cursor.matches.return_value = captures_list
    return cursor


# ── _LangConfig tests ───────────────────────────────────────────────────


class TestLangConfig:
    def test_init_compiles_queries(self):
        """_LangConfig compiles queries from _LANG_QUERIES."""
        with (
            patch("spacetime_memory.ingest.get_language") as mock_get_lang,
            patch("spacetime_memory.ingest.TSParser") as mock_parser_cls,
            patch("spacetime_memory.ingest.Query") as mock_query_cls,
        ):
            mock_lang = Mock()
            mock_get_lang.return_value = mock_lang
            mock_parser = Mock()
            mock_parser_cls.return_value = mock_parser

            cfg = _LangConfig("python")

            assert cfg.name == "python"
            assert cfg.lang is mock_lang
            assert cfg.parser is mock_parser
            mock_get_lang.assert_called_once_with("python")
            mock_parser_cls.assert_called_once_with(mock_lang)

            # Should have compiled queries for python's keys
            python_queries = _LANG_QUERIES["python"]
            assert mock_query_cls.call_count == len(python_queries)
            assert set(cfg.queries.keys()) == set(python_queries.keys())

    def test_compile_queries_handles_error(self):
        """A malformed query is skipped, not fatal."""
        with (
            patch("spacetime_memory.ingest.get_language") as mock_get_lang,
            patch("spacetime_memory.ingest.TSParser"),
            patch("spacetime_memory.ingest.Query") as mock_query_cls,
        ):
            mock_lang = Mock()
            mock_get_lang.return_value = mock_lang

            # Make Query raise for the first call, succeed for the rest
            mock_query_cls.side_effect = [RuntimeError("bad query"), Mock(), Mock(), Mock(), Mock()]

            cfg = _LangConfig("python")
            # The bad key is excluded from cfg.queries
            assert len(cfg.queries) == len(_LANG_QUERIES["python"]) - 1


# ── CodebaseIngester initialisation ─────────────────────────────────────


class TestCodebaseIngesterInit:
    def test_init(self):
        """Basic initialisation."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)
        assert ingester.client is mock_client
        assert ingester._parsers == {}
        assert ingester._stats == {"files": 0, "defs": 0, "edges": 0, "errors": 0}

    def test_ext_lang_mapping(self):
        """EXT_LANG maps file extensions to language names."""
        assert CodebaseIngester.EXT_LANG[".py"] == "python"
        assert CodebaseIngester.EXT_LANG[".js"] == "javascript"
        assert CodebaseIngester.EXT_LANG[".ts"] == "typescript"
        assert CodebaseIngester.EXT_LANG[".rs"] == "rust"
        assert CodebaseIngester.EXT_LANG[".go"] == "go"

    def test_skip_dirs(self):
        """SKIP_DIRS contains common directories to skip."""
        assert ".git" in CodebaseIngester.SKIP_DIRS
        assert "node_modules" in CodebaseIngester.SKIP_DIRS
        assert "__pycache__" in CodebaseIngester.SKIP_DIRS


# ── _parser method ─────────────────────────────────────────────────────


class TestParser:
    def test_creates_and_caches(self):
        """_parser creates _LangConfig on first call, caches thereafter."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        with patch("spacetime_memory.ingest._LangConfig") as mock_lc:
            cfg1 = Mock()
            mock_lc.return_value = cfg1

            result1 = ingester._parser("python")
            assert result1 is cfg1
            mock_lc.assert_called_once_with("python")

            # Second call uses cache
            result2 = ingester._parser("python")
            assert result2 is cfg1
            mock_lc.assert_called_once()  # still only once

    def test_handles_error_and_returns_none(self):
        """When _LangConfig raises, _parser returns None."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        with patch("spacetime_memory.ingest._LangConfig", side_effect=RuntimeError("nope")):
            result = ingester._parser("unknown_lang")
            assert result is None

    def test_returns_cached_on_error(self):
        """Once parsed successfully, subsequent error doesn't affect cache."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        with patch("spacetime_memory.ingest._LangConfig") as mock_lc:
            cfg1 = Mock()
            mock_lc.return_value = cfg1

            result1 = ingester._parser("python")
            assert result1 is cfg1

            # Cache hit; _LangConfig is not called again
            mock_lc.reset_mock()
            result2 = ingester._parser("python")
            assert result2 is cfg1
            mock_lc.assert_not_called()


# ── ingest method ───────────────────────────────────────────────────────


class TestIngest:
    def test_not_a_directory(self, tmp_path):
        """Raises NotADirectoryError when path is not a directory."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)
        file_path = tmp_path / "file.txt"
        file_path.write_text("hello")

        with pytest.raises(NotADirectoryError, match="Not a directory"):
            ingester.ingest(str(file_path), "ws1")

    def test_empty_directory(self, tmp_path):
        """Ingesting an empty directory returns zero stats."""
        mock_client = Mock()
        mock_client.detect_communities.return_value = None

        ingester = CodebaseIngester(mock_client)
        stats = ingester.ingest(str(tmp_path), "ws1")
        assert stats == {"files": 0, "defs": 0, "edges": 0, "errors": 0}

    def test_max_files_limit(self, tmp_path):
        """max_files limits the number of processed files."""
        mock_client = Mock()
        mock_client.detect_communities.return_value = None
        mock_client.query_graph.return_value = []
        mock_client.create_node.return_value = None
        mock_client.create_edge.return_value = None

        ingester = CodebaseIngester(mock_client)

        # Create 5 Python files
        for i in range(5):
            (tmp_path / f"file_{i}.py").write_text(f"x{i} = {i}")

        with (
            patch("spacetime_memory.ingest.get_language") as mock_get_lang,
            patch("spacetime_memory.ingest.TSParser") as mock_parser_cls,
            patch("spacetime_memory.ingest.Query") as mock_query_cls,
        ):
            # Set up mock language and parser
            mock_lang = Mock()
            mock_get_lang.return_value = mock_lang
            mock_parser = Mock()
            mock_parser_cls.return_value = mock_parser

            # Mock the tree
            mock_tree = Mock()
            mock_root = Mock()
            mock_parser.parse.return_value = mock_tree
            mock_tree.root_node = mock_root

            # Mock QueryCursor for defs and calls
            mock_query = Mock()
            mock_query_cls.return_value = mock_query

            with patch("spacetime_memory.ingest.QueryCursor") as mock_cursor_cls:
                mock_cursor = Mock()
                mock_cursor.matches.return_value = []
                mock_cursor_cls.return_value = mock_cursor

                stats = ingester.ingest(str(tmp_path), "ws1", max_files=2)

                assert stats["files"] <= 2

    def test_skip_dirs(self, tmp_path):
        """Directories in skip_dirs are skipped."""
        mock_client = MagicMock()
        mock_client.query_graph.return_value = []
        mock_client.detect_communities.return_value = None

        ingester = CodebaseIngester(mock_client)

        # Create a skipped directory with a Python file
        skip_dir = tmp_path / ".git"
        skip_dir.mkdir()
        (skip_dir / "should_skip.py").write_text("x = 1")

        # Create a regular file
        (tmp_path / "included.py").write_text("y = 2")

        with (
            patch("spacetime_memory.ingest.get_language") as mock_get_lang,
            patch("spacetime_memory.ingest.TSParser") as mock_parser_cls,
            patch("spacetime_memory.ingest.Query") as mock_query_cls,
            patch("spacetime_memory.ingest.QueryCursor") as mock_cursor_cls,
        ):
            mock_lang = Mock()
            mock_get_lang.return_value = mock_lang
            mock_parser = Mock()
            mock_parser_cls.return_value = mock_parser
            mock_tree = Mock()
            mock_root = Mock()
            mock_parser.parse.return_value = mock_tree
            mock_tree.root_node = mock_root
            mock_query = Mock()
            mock_query_cls.return_value = mock_query
            mock_cursor = Mock()
            mock_cursor.matches.return_value = []
            mock_cursor_cls.return_value = mock_cursor

            stats = ingester.ingest(str(tmp_path), "ws1")

            # Only included.py should be processed
            assert stats["files"] == 1

    def test_community_detection_error_is_swallowed(self, tmp_path):
        """If detect_communities fails, it's logged but not fatal."""
        mock_client = Mock()
        mock_client.detect_communities.side_effect = RuntimeError("comm fail")

        ingester = CodebaseIngester(mock_client)
        stats = ingester.ingest(str(tmp_path), "ws1")
        assert stats["files"] == 0

    def test_file_error_increments_error_count(self, tmp_path):
        """If processing a file raises, error count increments."""
        mock_client = Mock()
        mock_client.detect_communities.return_value = None

        ingester = CodebaseIngester(mock_client)

        (tmp_path / "bad.py").write_text("x = 1")

        # Make _process_file raise
        with patch.object(ingester, "_process_file", side_effect=RuntimeError("fail")):
            stats = ingester.ingest(str(tmp_path), "ws1")
            assert stats["errors"] == 1

    def test_unknown_extension_skipped_in_loop(self, tmp_path):
        """Files with unknown extensions are skipped by the ingest loop."""
        mock_client = Mock()
        mock_client.detect_communities.return_value = None

        ingester = CodebaseIngester(mock_client)

        # Create files with unknown extensions
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "data.csv").write_text("a,b,c")

        stats = ingester.ingest(str(tmp_path), "ws1")
        assert stats["files"] == 0  # both skipped


# ── _process_file method ────────────────────────────────────────────────


class TestProcessFile:
    def test_process_file_basic(self, tmp_path):
        """_process_file creates a file node and extracts defs."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.query_graph.return_value = [{"id": "file-node-1", "label": "test.py"}]

        ingester = CodebaseIngester(mock_client)

        py_file = tmp_path / "test.py"
        py_file.write_text("def foo(): pass\n")

        file_nodes: dict = {}
        def_nodes: dict = {}

        with patch("spacetime_memory.ingest._LangConfig"):
            mock_cfg = Mock()
            mock_cfg.name = "python"
            mock_cfg.parser = Mock()
            mock_tree = Mock()
            mock_root = Mock()
            mock_cfg.parser.parse.return_value = mock_tree
            mock_tree.root_node = mock_root
            mock_cfg.queries = {"defs": Mock(), "calls": Mock()}

            # Mock QueryCursor to return no matches
            with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
                mock_cursor = Mock()
                mock_cursor.matches.return_value = []
                mock_cc.return_value = mock_cursor

                ingester._parser = Mock(return_value=mock_cfg)

                ingester._process_file(py_file, tmp_path, "ws1", file_nodes, def_nodes)

        # File node created
        assert py_file in file_nodes
        assert ingester._stats["files"] == 1
        mock_client.create_node.assert_called()

    def test_process_file_skips_unknown_extension(self, tmp_path):
        """Files with unknown extensions are skipped."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("hello")
        file_nodes: dict = {}
        def_nodes: dict = {}

        ingester._process_file(txt_file, tmp_path, "ws1", file_nodes, def_nodes)

        assert txt_file not in file_nodes
        assert ingester._stats["files"] == 0

    def test_process_file_skips_empty_file(self, tmp_path):
        """Empty source files are skipped."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        py_file = tmp_path / "empty.py"
        py_file.write_text("   \n  \n")
        file_nodes: dict = {}
        def_nodes: dict = {}

        ingester._process_file(py_file, tmp_path, "ws1", file_nodes, def_nodes)

        assert py_file not in file_nodes

    def test_process_file_no_parser(self, tmp_path):
        """When _parser returns None, file is skipped."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        # Add .py to EXT_LANG so it passes the extension check
        py_file = tmp_path / "noparse.py"
        py_file.write_text("x = 1")
        file_nodes: dict = {}
        def_nodes: dict = {}

        ingester._parser = Mock(return_value=None)
        ingester._process_file(py_file, tmp_path, "ws1", file_nodes, def_nodes)

        assert py_file not in file_nodes
        assert ingester._stats["files"] == 0

    def test_process_file_create_node_error(self, tmp_path):
        """RuntimeError from create_node is caught and logged."""
        mock_client = Mock()
        mock_client.create_node.side_effect = RuntimeError("db down")
        mock_client.query_graph.return_value = [{"id": "f1", "label": "test.py"}]

        ingester = CodebaseIngester(mock_client)

        py_file = tmp_path / "test.py"
        py_file.write_text("def foo(): pass\n")

        file_nodes: dict = {}
        def_nodes: dict = {}

        with patch("spacetime_memory.ingest._LangConfig"):
            mock_cfg = Mock()
            mock_cfg.name = "python"
            mock_cfg.parser = Mock()
            mock_tree = Mock()
            mock_root = Mock()
            mock_cfg.parser.parse.return_value = mock_tree
            mock_tree.root_node = mock_root
            mock_cfg.queries = {"defs": Mock(), "calls": Mock()}

            with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
                mock_cursor = Mock()
                mock_cursor.matches.return_value = []
                mock_cc.return_value = mock_cursor

                ingester._parser = Mock(return_value=mock_cfg)
                ingester._process_file(py_file, tmp_path, "ws1", file_nodes, def_nodes)

        # File should still be registered and stats incremented
        assert py_file in file_nodes
        assert ingester._stats["files"] == 1

    def test_process_file_progress_every_50(self, tmp_path):
        """Progress is printed every 50 files."""
        mock_client = Mock()
        mock_client.detect_communities.return_value = None
        mock_client.query_graph.return_value = []
        mock_client.create_node.return_value = None

        ingester = CodebaseIngester(mock_client)

        # Create 51 Python files
        for i in range(51):
            (tmp_path / f"file_{i}.py").write_text(f"x{i} = {i}")

        with (
            patch("spacetime_memory.ingest.get_language") as mock_get_lang,
            patch("spacetime_memory.ingest.TSParser") as mock_parser_cls,
            patch("spacetime_memory.ingest.Query") as mock_query_cls,
            patch("spacetime_memory.ingest.QueryCursor") as mock_cursor_cls,
        ):
            mock_lang = Mock()
            mock_get_lang.return_value = mock_lang
            mock_parser = Mock()
            mock_parser_cls.return_value = mock_parser
            mock_tree = Mock()
            mock_root = Mock()
            mock_parser.parse.return_value = mock_tree
            mock_tree.root_node = mock_root
            mock_query = Mock()
            mock_query_cls.return_value = mock_query
            mock_cursor = Mock()
            mock_cursor.matches.return_value = []
            mock_cursor_cls.return_value = mock_cursor

            stats = ingester.ingest(str(tmp_path), "ws1")

        assert stats["files"] == 51


# ── _extract_defs method ────────────────────────────────────────────────


class TestExtractDefs:
    def test_extracts_function_definition(self, tmp_path):
        """A function_definition match creates a def node."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.query_graph.return_value = [{"id": "def-node-1", "label": "test.py:my_func"}]

        ingester = CodebaseIngester(mock_client)
        source = "def my_func(): pass\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_root = Mock()
        mock_tree.root_node = mock_root

        # Simulate a "func" capture
        name_node = Mock()
        name_node.start_byte = 4
        name_node.end_byte = 11  # "my_func"

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "func": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        assert ingester._stats["defs"] == 1
        assert "test.py" in def_nodes
        assert def_nodes["test.py"][0]["name"] == "my_func"

    def test_extracts_class_definition(self, tmp_path):
        """A class_definition match creates a class def node."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.query_graph.return_value = [{"id": "cls-node-1", "label": "test.py:MyClass"}]

        ingester = CodebaseIngester(mock_client)
        source = "class MyClass:\n    pass\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 6
        name_node.end_byte = 13  # "MyClass"

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "class": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        assert ingester._stats["defs"] == 1
        assert def_nodes["test.py"][0]["name"] == "MyClass"

    def test_extracts_call(self, tmp_path):
        """A call match is recorded but not as a separate node."""
        mock_client = Mock()
        mock_client.create_node.return_value = None

        ingester = CodebaseIngester(mock_client)
        source = "print('hello')\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"calls": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 0
        name_node.end_byte = 5  # "print"

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "call": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        assert "test.py" in def_nodes
        assert def_nodes["test.py"][0]["call"] == "print"

    def test_skips_def_without_name_node(self, tmp_path):
        """Matches without a 'name' capture are skipped."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)
        source = "x = 1\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            # Match has a 'var' capture but no 'name'
            mock_cursor.matches.return_value = [(0, {"var": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        # No defs should be added (setdefault creates the key with empty list)
        assert "test.py" in def_nodes
        assert def_nodes["test.py"] == []

    def test_create_node_error_is_handled(self, tmp_path):
        """RuntimeError from create_node is caught."""
        mock_client = Mock()
        mock_client.create_node.side_effect = RuntimeError("db error")
        mock_client.query_graph.return_value = [{"id": "d1", "label": "test.py:foo"}]

        ingester = CodebaseIngester(mock_client)
        source = "def foo(): pass\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 4
        name_node.end_byte = 7

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "func": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        # Def should still be recorded despite create_node failure
        assert ingester._stats["defs"] == 1

    def test_interface_type_detection(self, tmp_path):
        """Type label detection for trait/iface."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.query_graph.return_value = [{"id": "d1", "label": "test.py:MyTrait"}]

        ingester = CodebaseIngester(mock_client)
        source = "trait MyTrait {}\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 6
        name_node.end_byte = 13

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "trait": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        assert ingester._stats["defs"] == 1

    def test_typealias_detection(self, tmp_path):
        """Type label for typealias/typedef."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.query_graph.return_value = [{"id": "d1", "label": "test.py:MyType"}]

        ingester = CodebaseIngester(mock_client)
        source = "type MyType = int\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 5
        name_node.end_byte = 11

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "typealias": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        assert ingester._stats["defs"] == 1

    def test_skips_when_no_file_node_id(self, tmp_path):
        """When file_node_id is empty, contains edge is not created."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.query_graph.return_value = [{"id": "d1", "label": "test.py:func"}]

        ingester = CodebaseIngester(mock_client)
        source = "def func(): pass\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 4
        name_node.end_byte = 8

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "func": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "",  # empty file_node_id
                def_nodes,
            )

        # create_edge should not be called for contains
        mock_client.create_edge.assert_not_called()

    def test_contains_edge_error_is_handled(self, tmp_path):
        """RuntimeError from create_edge in _extract_defs is caught."""
        mock_client = Mock()
        mock_client.create_node.return_value = None
        mock_client.create_edge.side_effect = RuntimeError("edge fail")
        mock_client.query_graph.return_value = [{"id": "d1", "label": "test.py:foo"}]

        ingester = CodebaseIngester(mock_client)
        source = "def foo(): pass\n"

        mock_cfg = Mock()
        mock_cfg.queries = {"defs": Mock()}
        mock_tree = Mock()
        mock_tree.root_node = Mock()

        name_node = Mock()
        name_node.start_byte = 4
        name_node.end_byte = 7

        with patch("spacetime_memory.ingest.QueryCursor") as mock_cc:
            mock_cursor = Mock()
            mock_cursor.matches.return_value = [(0, {"name": [name_node], "func": [Mock()]})]
            mock_cc.return_value = mock_cursor

            def_nodes: dict = {}
            ingester._extract_defs(
                mock_cfg,
                mock_tree,
                source,
                "test.py",
                "ws1",
                "file-node-1",
                def_nodes,
            )

        # Def should still be recorded despite edge creation failure
        assert ingester._stats["defs"] == 1


# ── _create_dependency_edges ────────────────────────────────────────────


class TestCreateDependencyEdges:
    def test_creates_call_edge(self):
        """When a call matches a definition name, a 'calls' edge is created."""
        mock_client = Mock()
        mock_client.create_edge.return_value = None

        ingester = CodebaseIngester(mock_client)

        def_nodes = {
            "a.py": [
                {"call": "helper", "id": "caller-id", "file": "a.py"},
            ],
            "b.py": [
                {"name": "helper", "id": "callee-id", "file": "b.py"},
            ],
        }

        ingester._create_dependency_edges("ws1", def_nodes)

        mock_client.create_edge.assert_called_once_with(
            "ws1",
            "caller-id",
            "callee-id",
            "calls",
            weight=1.0,
        )
        assert ingester._stats["edges"] == 1

    def test_no_edge_when_call_has_no_id(self):
        """If the caller has no id, no edge is created."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        def_nodes = {
            "a.py": [
                {"call": "helper", "file": "a.py"},  # no id
            ],
            "b.py": [
                {"name": "helper", "id": "callee-id", "file": "b.py"},
            ],
        }

        ingester._create_dependency_edges("ws1", def_nodes)

        mock_client.create_edge.assert_not_called()
        assert ingester._stats["edges"] == 0

    def test_no_edge_when_same_id(self):
        """Self-calls are skipped (same src_id and tgt_id)."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        def_nodes = {
            "a.py": [
                {"call": "recurse", "id": "node-1", "file": "a.py"},
                {"name": "recurse", "id": "node-1", "file": "a.py"},
            ],
        }

        ingester._create_dependency_edges("ws1", def_nodes)

        mock_client.create_edge.assert_not_called()

    def test_skips_non_call_defs(self):
        """Defs without a 'call' key are ignored."""
        mock_client = Mock()
        ingester = CodebaseIngester(mock_client)

        def_nodes = {
            "a.py": [
                {"name": "foo", "id": "id1", "file": "a.py"},  # not a call
            ],
        }

        ingester._create_dependency_edges("ws1", def_nodes)

        mock_client.create_edge.assert_not_called()

    def test_multiple_edges(self):
        """Multiple matching calls create multiple edges."""
        mock_client = Mock()
        mock_client.create_edge.return_value = None

        ingester = CodebaseIngester(mock_client)

        def_nodes = {
            "a.py": [
                {"call": "f1", "id": "a1", "file": "a.py"},
                {"call": "f2", "id": "a2", "file": "a.py"},
            ],
            "b.py": [
                {"name": "f1", "id": "b1", "file": "b.py"},
                {"name": "f2", "id": "b2", "file": "b.py"},
            ],
        }

        ingester._create_dependency_edges("ws1", def_nodes)

        assert mock_client.create_edge.call_count == 2

    def test_edge_creation_error_is_handled(self):
        """RuntimeError from create_edge is caught."""
        mock_client = Mock()
        mock_client.create_edge.side_effect = RuntimeError("fail")

        ingester = CodebaseIngester(mock_client)

        def_nodes = {
            "a.py": [
                {"call": "helper", "id": "a1", "file": "a.py"},
            ],
            "b.py": [
                {"name": "helper", "id": "b1", "file": "b.py"},
            ],
        }

        # Should not raise
        ingester._create_dependency_edges("ws1", def_nodes)


# ── _resolve_node method ────────────────────────────────────────────────


class TestResolveNode:
    def test_resolves_by_label(self):
        """Returns the id when query_graph finds a matching label."""
        mock_client = Mock()
        mock_client.query_graph.return_value = [
            {"id": "node-xyz", "label": "my_label"},
        ]

        ingester = CodebaseIngester(mock_client)
        result = ingester._resolve_node("ws1", "my_label")
        assert result == "node-xyz"

    def test_returns_empty_when_not_found(self):
        """Returns empty string when no matching label."""
        mock_client = Mock()
        mock_client.query_graph.return_value = [
            {"id": "node-xyz", "label": "other_label"},
        ]

        ingester = CodebaseIngester(mock_client)
        result = ingester._resolve_node("ws1", "my_label")
        assert result == ""

    def test_returns_empty_on_exception(self):
        """Returns empty string when query_graph raises."""
        mock_client = Mock()
        mock_client.query_graph.side_effect = RuntimeError("bad")

        ingester = CodebaseIngester(mock_client)
        result = ingester._resolve_node("ws1", "my_label")
        assert result == ""

    def test_returns_empty_on_empty_response(self):
        """Returns empty string when query_graph returns nothing."""
        mock_client = Mock()
        mock_client.query_graph.return_value = []

        ingester = CodebaseIngester(mock_client)
        result = ingester._resolve_node("ws1", "my_label")
        assert result == ""
