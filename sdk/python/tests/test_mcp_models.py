"""Tests for server/mcp/_models.py — data models and type aliases module.

This module is a thin re-export wrapper around ``typing.Any``.  Tests verify
structural soundness and the public API.
"""

from __future__ import annotations

from typing import Any as _Any

_any = _Any  # avoid F821 in the assertions below


class TestModuleImport:
    """Verify the _models module can be imported and is structurally sound."""

    def test_can_import(self):
        from server.mcp import _models

        assert _models is not None

    def test_docstring_present(self):
        from server.mcp import _models

        doc = _models.__doc__
        assert doc is not None
        assert "Data models" in doc
        assert "type aliases" in doc
        assert "spacetime-memory MCP server" in doc

    def test_future_annotations_imported(self):
        from server.mcp import _models

        hints = getattr(_models, "__annotations__", {})
        assert isinstance(hints, dict)

    def test_all_exports_any(self):
        from server.mcp import _models

        assert hasattr(_models, "__all__")
        assert "Any" in _models.__all__

    def test_any_is_re_exported(self):
        from typing import Any as _Any

        from server.mcp import _models

        assert _models.Any is _Any
        assert _models.Any is _any

    def test_module_has_no_other_public_names(self):
        from server.mcp import _models

        public = sorted(
            n for n in dir(_models)
            if not n.startswith("_")
        )
        # Only "annotations" (from __future__ import annotations) and "Any"
        assert public == ["Any", "annotations"]

    def test_module_file_attribute(self):
        from server.mcp import _models

        assert _models.__file__ is not None
        assert "_models.py" in _models.__file__
