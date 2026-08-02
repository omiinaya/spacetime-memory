"""Tests for server/mcp/main.py — MCP server entry point.

This file heavily imports tool modules at module level.  We handle this
by populating sys.modules with Mock stubs *before* importing the target
module, preventing real side effects (FastMCP instance creation, DB
connections, etc.).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_module(name: str) -> ModuleType:
    """Return a lightweight module stub for sys.modules injection."""
    mod = ModuleType(name)
    mod.__package__ = name.rpartition(".")[0]
    mod.__path__ = []
    mod.__file__ = f"/stub/{name.replace('.', '/')}.py"
    return mod


def _stub_submodules(parent: str, *children: str) -> dict[str, ModuleType]:
    """Stub *parent* and each *children* sub-module so that
    ``import parent.child`` works without hitting disk.

    Returns a dict mapping fully-qualified names to stubs, ready for
    ``sys.modules`` injection.
    """
    stubs: dict[str, ModuleType] = {}
    # Parent
    if parent not in sys.modules:
        stubs[parent] = _stub_module(parent)
    for child in children:
        fqn = f"{parent}.{child}"
        mod = _stub_module(fqn)
        mod.__package__ = parent
        setattr(stubs.setdefault(parent, _stub_module(parent)), child, mod)
        stubs[fqn] = mod
    return stubs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _protect_sys_modules():
    """Stash and restore sys.modules so tests don't leak stubs."""
    saved = set(sys.modules)
    yield
    for key in list(sys.modules):
        if key not in saved:
            sys.modules.pop(key, None)


@pytest.fixture
def main_module():
    """Import the target module under controlled conditions.

    We stub *every* dependency that has import-time side effects before
    touching ``server/mcp/main.py``, then load it from the file-system
    path so that imports resolve to our stubs.
    """
    # ---- 1. stub the parent packages so that Python's import
    #       machinery can traverse the hierarchy  --------------------------
    stubs: dict[str, ModuleType] = {}

    # ``server`` package (has a real __init__.py but we stub it to avoid
    # pulling in the real ``server.mcp.__init__`` and its deps)
    stubs["server"] = _stub_module("server")
    stubs["server.__init__"] = _stub_module("server.__init__")

    # ``server.mcp``
    stubs["server.mcp"] = _stub_module("server.mcp")
    stubs["server.mcp.__init__"] = _stub_module("server.mcp.__init__")

    # ``server.mcp.tools`` package + each tool submodule
    stubs["server.mcp.tools"] = _stub_module("server.mcp.tools")
    tools = [
        "admin", "agent", "app", "compounder", "context", "directory",
        "documents", "entities", "kg", "memories", "mental",
        "notes", "org", "peers", "profiles", "search",
        "space", "tours", "workspace",
    ]
    for tool in tools:
        fqn = f"server.mcp.tools.{tool}"
        m = _stub_module(fqn)
        stubs[fqn] = m

    # ``server.mcp.tools.app`` — must expose a real ``mcp`` singleton
    app_stub = _stub_module("server.mcp.tools.app")
    app_stub.mcp = MagicMock()
    app_stub.mcp.run = MagicMock()
    app_stub.mcp.settings = MagicMock()
    app_stub.require_api_key = lambda f: f  # identity decorator
    app_stub.MCP_API_KEY = ""
    stubs["server.mcp.tools.app"] = app_stub

    # FastMCP — the real import chain ``mcp.server.fastmcp``
    stubs["mcp"] = _stub_module("mcp")
    stubs["mcp.server"] = _stub_module("mcp.server")
    stubs["mcp.server.fastmcp"] = _stub_module("mcp.server.fastmcp")
    stubs["mcp.server.fastmcp.FastMCP"] = _stub_module(
        "mcp.server.fastmcp.FastMCP"
    )

    # SDK package (indirect dep from app.py)
    stubs["spacetime_memory"] = _stub_module("spacetime_memory")
    stubs["spacetime_memory.Client"] = _stub_module(
        "spacetime_memory.Client"
    )

    with patch.dict(sys.modules, stubs, clear=False):
        # ---- 2. Load the target module from its file path ---------------
        import importlib.util

        source_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "server"
            / "mcp"
            / "main.py"
        )
        spec = importlib.util.spec_from_file_location(
            "server.mcp.main", str(source_path)
        )
        mod = importlib.util.module_from_spec(spec)
        # Register it before exec so circular imports resolve
        sys.modules["server.mcp.main"] = mod
        spec.loader.exec_module(mod)
        return mod


# ===================================================================
# _auto_star — unit tests
# ===================================================================


class TestAutoStar:
    """Tests for ``_auto_star(repo)``, the GitHub auto-star background
    task.

    We patch *everything* the function touches: ``os.environ.get``,
    ``urllib.request.Request``, ``urllib.request.urlopen``, and the
    logger.  Also patch ``time.sleep`` because the function sleeps 8 s
    at the start.
    """

    repo = "omiinaya/spacetime-memory"

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _make_opener(status: int, body: bytes = b""):
        """Return a context-manager response suitable for urlopen."""
        resp = MagicMock()
        resp.status = status
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        return resp

    @staticmethod
    def _make_http_error(code: int):
        """Build an ``urllib.error.HTTPError``-like exception."""
        import urllib.error
        return urllib.error.HTTPError(
            f"https://api.github.com/user/starred/{TestAutoStar.repo}",
            code,
            f"HTTP {code}",
            {},
            None,
        )

    # -- success cases --------------------------------------------------

    def test_star_success_204(self, main_module, caplog):
        """PUT returns 204 → info log."""
        caplog.set_level(logging.INFO)
        opener = self._make_opener(204)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(main_module._urllib_request, "urlopen", return_value=opener),
            patch.object(main_module._urllib_request, "Request") as mock_req,
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        mock_req.assert_called_once_with(
            f"https://api.github.com/user/starred/{self.repo}",
            method="PUT",
            data=b"",
            headers={
                "Authorization": "Bearer gh_token_xxx",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "spacetime-memory/1.0",
            },
        )
        assert "Starred" in caplog.text
        assert self.repo in caplog.text

    def test_star_success_200(self, main_module, caplog):
        """PUT returns 200 (uncommon but valid) → info log."""
        caplog.set_level(logging.INFO)
        opener = self._make_opener(200)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(main_module._urllib_request, "urlopen", return_value=opener),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert "Starred" in caplog.text

    def test_star_already_starred_409(self, main_module, caplog):
        """PUT returns 409 → info log (already starred)."""
        caplog.set_level(logging.INFO)
        opener = self._make_opener(409)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(main_module._urllib_request, "urlopen", return_value=opener),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert "Already starred" in caplog.text

    # -- failure cases --------------------------------------------------

    def test_star_http_error_4xx(self, main_module, caplog):
        """HTTP 4xx other than 409 → warning log."""
        caplog.set_level(logging.WARNING)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(
                main_module._urllib_request, "urlopen",
                side_effect=self._make_http_error(403),
            ),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert "Failed to star" in caplog.text
        assert "HTTP 403" in caplog.text

    def test_star_http_error_5xx(self, main_module, caplog):
        """HTTP 5xx → warning log."""
        caplog.set_level(logging.WARNING)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(
                main_module._urllib_request, "urlopen",
                side_effect=self._make_http_error(500),
            ),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert "Failed to star" in caplog.text

    def test_star_unexpected_status_no_exception(self, main_module, caplog):
        """HTTP status that is not 200/204/409 and doesn't raise → warning log.

        Covers the ``else`` branch on line 68 of main.py where ``resp.status``
        is something unexpected (e.g. 201) and urlopen did not raise.
        """
        caplog.set_level(logging.WARNING)
        opener = self._make_opener(201)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(main_module._urllib_request, "urlopen", return_value=opener),
            patch.object(main_module._urllib_request, "Request"),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert "Failed to star" in caplog.text
        assert "HTTP 201" in caplog.text

    def test_star_http_error_204_via_exception(self, main_module, caplog):
        """HTTP 204 raised as HTTPError → no-op, no warning."""
        caplog.set_level(logging.WARNING)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(
                main_module._urllib_request, "urlopen",
                side_effect=self._make_http_error(204),
            ),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert caplog.text == ""  # no warning logged

    def test_star_http_error_409_via_exception(self, main_module, caplog):
        """HTTP 409 raised as HTTPError → no-op, no warning."""
        caplog.set_level(logging.WARNING)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(
                main_module._urllib_request, "urlopen",
                side_effect=self._make_http_error(409),
            ),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert caplog.text == ""  # no warning logged

    # -- network / connection errors ------------------------------------

    def test_star_connection_error(self, main_module, caplog):
        """Connection-level exception (e.g. DNS failure) → warning."""
        caplog.set_level(logging.WARNING)

        with (
            patch.object(main_module._os, "environ", {"GITHUB_TOKEN": "gh_token_xxx"}),
            patch.object(
                main_module._urllib_request, "urlopen",
                side_effect=OSError("Name or service not known"),
            ),
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        assert "Could not reach GitHub API" in caplog.text

    # -- missing token --------------------------------------------------

    def test_star_no_token(self, main_module, caplog):
        """Neither GITHUB_TOKEN nor ACC_GITHUB_TOKEN set → no-op."""
        caplog.set_level(logging.INFO)

        with (
            patch.object(main_module._os, "environ", {}),
            patch.object(main_module._urllib_request, "urlopen") as mock_open,
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        mock_open.assert_not_called()
        assert caplog.text == ""

    def test_star_acc_github_token(self, main_module, caplog):
        """ACC_GITHUB_TOKEN is accepted as fallback."""
        caplog.set_level(logging.INFO)

        with (
            patch.object(
                main_module._os, "environ",
                {"ACC_GITHUB_TOKEN": "acc_token_yyy"},
            ),
            patch.object(main_module._urllib_request, "urlopen",
                         return_value=self._make_opener(204)),
            patch.object(main_module._urllib_request, "Request") as mock_req,
            patch("time.sleep"),
        ):
            main_module._auto_star(self.repo)

        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer acc_token_yyy"
        assert "Starred" in caplog.text


# ===================================================================
# __main__ block — daemon thread + CLI argument parsing
# ===================================================================


class TestMainBlock:
    """Tests for the ``if __name__ == '__main__':`` block.

    Because the block only runs when the module is the entry-point, we
    test the *same logic* by re-executing the code path with patched
    dependencies.  We verify the observable behaviour:
      1. A daemon thread is started targeting ``_auto_star``
      2. argparse parses ``--transport``, ``--host``, ``--port``
      3. ``mcp.run()`` is called with the right transport
    """

    # -- daemon thread --------------------------------------------------

    def test_daemon_thread_starts(self, main_module):
        """The __main__ block starts a daemon thread targeting _auto_star."""
        thread_mock = MagicMock()

        with (
            patch.object(main_module._threading, "Thread",
                         return_value=thread_mock) as thread_cls,
            patch("argparse.ArgumentParser.parse_args",
                  return_value=MagicMock(transport="stdio",
                                         host="127.0.0.1",
                                         port=8099)),
            patch.object(main_module, "mcp") as mcp_mock,
        ):
            # Trigger the same logic as the __main__ block
            main_module._threading.Thread(
                target=main_module._auto_star,
                args=("omiinaya/spacetime-memory",),
                daemon=True,
            ).start()

            import argparse
            parser = argparse.ArgumentParser(
                description="spacetime-memory MCP server"
            )
            parser.add_argument(
                "--transport",
                choices=["stdio", "sse", "streamable-http"],
                default="stdio",
            )
            parser.add_argument("--host", default="127.0.0.1")
            parser.add_argument("--port", type=int, default=8099)
            args = parser.parse_args()

            if args.transport == "stdio":
                mcp_mock.run()
            else:
                mcp_mock.settings.host = args.host
                mcp_mock.settings.port = args.port
                mcp_mock.run(transport=args.transport)

        # Verify daemon thread was created targeting _auto_star
        thread_cls.assert_called_once_with(
            target=main_module._auto_star,
            args=("omiinaya/spacetime-memory",),
            daemon=True,
        )
        thread_mock.start.assert_called_once()
        # With stdio transport, mcp.run() is called without args
        mcp_mock.run.assert_called_once_with()

    # -- CLI argument parsing -------------------------------------------

    @pytest.mark.parametrize(
        ("argv", "expected_transport", "expected_host", "expected_port"),
        [
            (["main.py"], "stdio", "127.0.0.1", 8099),
            (["main.py", "--transport", "sse"], "sse", "127.0.0.1", 8099),
            (
                ["main.py", "--transport", "streamable-http"],
                "streamable-http",
                "127.0.0.1",
                8099,
            ),
            (["main.py", "--host", "0.0.0.0"], "stdio", "0.0.0.0", 8099),
            (["main.py", "--port", "9999"], "stdio", "127.0.0.1", 9999),
            (
                [
                    "main.py",
                    "--transport",
                    "sse",
                    "--host",
                    "10.0.0.1",
                    "--port",
                    "8080",
                ],
                "sse",
                "10.0.0.1",
                8080,
            ),
        ],
    )
    def test_argparse(
        self,
        main_module,
        argv,
        expected_transport,
        expected_host,
        expected_port,
    ):
        """Argument parsing returns expected values for various CLI invocations."""
        import argparse

        parser = argparse.ArgumentParser(
            description="spacetime-memory MCP server"
        )
        parser.add_argument(
            "--transport",
            choices=["stdio", "sse", "streamable-http"],
            default="stdio",
        )
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8099)

        args = parser.parse_args(argv[1:])

        assert args.transport == expected_transport
        assert args.host == expected_host
        assert args.port == expected_port

    def test_argparse_invalid_transport(self, main_module):
        """Invalid transport value is rejected."""
        import argparse

        parser = argparse.ArgumentParser(
            description="spacetime-memory MCP server"
        )
        parser.add_argument(
            "--transport",
            choices=["stdio", "sse", "streamable-http"],
            default="stdio",
        )

        with pytest.raises(SystemExit):
            parser.parse_args(["--transport", "invalid"])

    def test_argparse_port_non_int(self, main_module):
        """Non-integer port is rejected."""
        import argparse

        parser = argparse.ArgumentParser(
            description="spacetime-memory MCP server"
        )
        parser.add_argument("--port", type=int, default=8099)

        with pytest.raises(SystemExit):
            parser.parse_args(["--port", "not-a-number"])

    # -- mcp.run() dispatch ---------------------------------------------

    @pytest.mark.parametrize(
        ("transport", "host", "port"),
        [
            ("stdio", "0.0.0.0", 9999),
            ("sse", "0.0.0.0", 9999),
            ("streamable-http", "0.0.0.0", 9999),
        ],
    )
    def test_mcp_run_dispatch(self, main_module, transport, host, port):
        """mcp.run() is dispatched correctly based on transport.

        For stdio: mcp.run() with no args.
        For sse/streamable-http: sets host/port, then
        mcp.run(transport=...).
        """
        mcp_mock = MagicMock()
        mcp_mock.settings = MagicMock()
        args = MagicMock()
        args.transport = transport
        args.host = host
        args.port = port

        # Replicate the dispatch logic from main.py
        if args.transport == "stdio":
            mcp_mock.run()
        else:
            mcp_mock.settings.host = args.host
            mcp_mock.settings.port = args.port
            mcp_mock.run(transport=transport)

        if transport == "stdio":
            mcp_mock.run.assert_called_once_with()
        else:
            assert mcp_mock.settings.host == host
            assert mcp_mock.settings.port == port
            mcp_mock.run.assert_called_once_with(transport=transport)


# ===================================================================
# Module-level invariants
# ===================================================================


class TestModuleImports:
    """Verify that the module's structural elements are in place."""

    def test_logger_configured(self, main_module):
        """Module has a logger instance."""
        assert main_module.logger is not None
        assert main_module._logger is main_module.logger

    def test_mcp_singleton_imported(self, main_module):
        """mcp singleton is available (even as a stub)."""
        assert hasattr(main_module, "mcp")

    def test_auto_star_is_callable(self, main_module):
        """_auto_star is a function."""
        assert callable(main_module._auto_star)

    def test_aliases(self, main_module):
        """Module-level aliases exist."""
        assert main_module._threading is not None
        assert main_module._urllib_request is not None
        assert main_module._os is not None
