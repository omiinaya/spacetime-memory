#!/usr/bin/env python3
"""Fix the remaining 1 test_mcp.py issue."""
from pathlib import Path

path = Path(__file__).parent / "test_mcp.py"
content = path.read_text()

old = "mock_mcp_client.search_facts.assert_called_once_with(workspace_id=\"ws1\", query=\"hello\", tier=\"L1\")"
new = 'mock_mcp_client.search_facts.assert_called_once_with("ws1", "hello", "L1")'
if old in content:
    content = content.replace(old, new)
else:
    print(f"Could not find: {old}")

path.write_text(content)
print("Done")
