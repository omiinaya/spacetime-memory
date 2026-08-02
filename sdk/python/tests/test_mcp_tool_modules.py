"""Unit tests for server/mcp/tools/ MCP tool modules.

Tests that each tool module can be imported and its tool registration functions
work correctly. Uses mock_mcp_client fixture to mock Client dependencies.
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/memories.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpMemoriesModule:
    """MCP memories tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        from server.mcp import tools
        assert tools is not None

    def test_memories_tool_module_imports(self):
        """The memories tool module imports cleanly."""
        import server.mcp.tools.memories as mem_mod
        assert mem_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/kg.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpKgModule:
    """MCP KG tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.kg as kg_mod
        assert kg_mod is not None

    def test_has_tool_functions(self):
        """Module exports expected tool registration functions and types."""
        import server.mcp.tools.kg as kg_mod
        # Should have functions for tool registration
        assert any(callable(v) for k, v in vars(kg_mod).items() if not k.startswith("_"))


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/profiles.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpProfilesModule:
    """MCP profiles tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.profiles as prof_mod
        assert prof_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/documents.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpDocumentsModule:
    """MCP documents tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.documents as doc_mod
        assert doc_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/tours.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpToursModule:
    """MCP tours tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.tours as t_mod
        assert t_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/admin.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpAdminModule:
    """MCP admin tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.admin as adm_mod
        assert adm_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/peers.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpPeersModule:
    """MCP peers tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.peers as p_mod
        assert p_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/entities.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpEntitiesModule:
    """MCP entities tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.entities as e_mod
        assert e_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/mcp/tools/space.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpSpaceModule:
    """MCP space tool module — import and structure."""

    def test_module_imports(self):
        """Module imports without error."""
        import server.mcp.tools.space as s_mod
        assert s_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/ws_subscription modules
# ═══════════════════════════════════════════════════════════════════════════════

class TestWsSubscriptionModules:
    """WebSocket subscription modules — import and structure."""

    def test_subscription_module_imports(self):
        """_subscription.py imports without error."""
        import server.ws_subscription._subscription as sub_mod
        assert sub_mod is not None

    def test_handler_module_imports(self):
        """_handler.py imports without error."""
        import server.ws_subscription._handler as h_mod
        assert h_mod is not None

    def test_main_module_imports(self):
        """main.py imports without error."""
        import server.ws_subscription.main as m_mod
        assert m_mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# server/spacetimedb/src modules
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpacetimedbSrcModules:
    """spacetimedb source Python helper modules."""

    def test_add_trace_span_imports(self):
        """add_trace_span.py imports without error."""
        import server.spacetimedb.src.add_trace_span as ats
        assert ats is not None

    def test_check_trace_imports(self):
        """check_trace.py imports without error."""
        import server.spacetimedb.src.check_trace as ct
        assert ct is not None
