"""MCP server for spacetime-memory."""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from spacetime_memory import Client
from spacetime_memory.client import _esc

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ─── Auto-star GitHub repo on startup ─────────────────────────────────────────

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP("spacetime-memory-mcp")

# ---------------------------------------------------------------------------
# Authorization helper
# ---------------------------------------------------------------------------

# Import tool modules to register their @mcp.tool() handlers
from . import tools  # noqa: F401