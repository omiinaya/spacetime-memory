"""Tests for server/mcp/tools/directory.py — MCP directory tool wrappers.

The tools are thin wrappers around Client directory methods that return
JSON strings / confirmation messages. We mock the client (get_client) so no
live SpacetimeDB is required.
"""
import json

import pytest

from server.mcp.tools import directory


class FakeClient:
    """Records calls; returns canned rows for each directory method."""

    def __init__(self):
        self.calls = []

    def create_directory(self, workspace_id, name, path, parent_id="", description=""):
        self.calls.append(("create_directory", workspace_id, name, path, parent_id, description))

    def traverse_directory(self, workspace_id, root_directory_id):
        self.calls.append(("traverse_directory", workspace_id, root_directory_id))
        return [{"id": "d1", "name": "root", "children": []}]

    def list_directory(self, directory_id):
        self.calls.append(("list_directory", directory_id))
        return [{"id": "d2", "name": "child", "type": "memory"}]

    def get_directory(self, workspace_id, path_or_id):
        self.calls.append(("get_directory", workspace_id, path_or_id))
        return [{"id": "d3", "path": path_or_id, "workspace_id": workspace_id}]

    def link_memory_to_directory(self, directory_id, memory_id, workspace_id):
        self.calls.append(("link_memory_to_directory", directory_id, memory_id, workspace_id))

    def unlink_memory_from_directory(self, directory_id, memory_id):
        self.calls.append(("unlink_memory_from_directory", directory_id, memory_id))

    def search_directory_contents(self, workspace_id, directory_path):
        self.calls.append(("search_directory_contents", workspace_id, directory_path))
        return {
            "directory_id": "d1",
            "subdirectory_ids_json": "[]",
            "memory_ids_json": '["m1"]',
            "directory_path": directory_path,
            "workspace_id": workspace_id,
            "id": "d1",
            "created_at": 0,
        }


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(directory, "get_client", lambda: client)
    return client


# ---------------------------------------------------------------------------
# create_directory
# ---------------------------------------------------------------------------


def test_create_directory_returns_confirmation(fake_client):
    out = directory.create_directory("ws1", "projects", "/projects", "parent-1", "top level")
    assert out == "Directory 'projects' created."
    assert fake_client.calls == [
        ("create_directory", "ws1", "projects", "/projects", "parent-1", "top level")
    ]


def test_create_directory_defaults_empty_parent_and_description(fake_client):
    directory.create_directory("ws1", "docs", "/docs")
    assert fake_client.calls == [
        ("create_directory", "ws1", "docs", "/docs", "", "")
    ]


# ---------------------------------------------------------------------------
# traverse_directory
# ---------------------------------------------------------------------------


def test_traverse_directory_returns_json_rows(fake_client):
    out = directory.traverse_directory("ws1", "root-1")
    parsed = json.loads(out)
    assert parsed == [{"id": "d1", "name": "root", "children": []}]
    assert fake_client.calls == [("traverse_directory", "ws1", "root-1")]


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


def test_list_directory_returns_json_rows(fake_client):
    out = directory.list_directory("d1")
    parsed = json.loads(out)
    assert parsed[0]["name"] == "child"
    assert fake_client.calls == [("list_directory", "d1")]


# ---------------------------------------------------------------------------
# get_directory — by id or path
# ---------------------------------------------------------------------------


def test_get_directory_by_id(fake_client):
    out = directory.get_directory("ws1", "dir-abc")
    parsed = json.loads(out)
    assert parsed == [{"id": "d3", "path": "dir-abc", "workspace_id": "ws1"}]
    assert fake_client.calls == [("get_directory", "ws1", "dir-abc")]


def test_get_directory_by_path(fake_client):
    out = directory.get_directory("ws1", "/projects/ai")
    parsed = json.loads(out)
    assert parsed[0]["path"] == "/projects/ai"


# ---------------------------------------------------------------------------
# link / unlink memory
# ---------------------------------------------------------------------------


def test_link_memory_to_directory(fake_client):
    # 16-char prefixes are shown in the confirmation message
    out = directory.link_memory_to_directory("d" * 16, "m" * 16, "ws1")
    assert out == f"Memory {'m' * 16}... linked to directory {'d' * 16}..."
    assert fake_client.calls == [
        ("link_memory_to_directory", "d" * 16, "m" * 16, "ws1")
    ]


def test_link_memory_truncates_long_ids(fake_client):
    out = directory.link_memory_to_directory("a" * 40, "b" * 40, "ws1")
    # Truncated to 16 chars in the message
    assert out == f"Memory {'b' * 16}... linked to directory {'a' * 16}..."


def test_unlink_memory_from_directory(fake_client):
    out = directory.unlink_memory_from_directory("dir-1", "mem-1")
    assert out == "Memory mem-1... unlinked from directory dir-1..."
    assert fake_client.calls == [("unlink_memory_from_directory", "dir-1", "mem-1")]


# ---------------------------------------------------------------------------
# search_directory_contents
# ---------------------------------------------------------------------------


def test_search_directory_contents_returns_full_result(fake_client):
    out = directory.search_directory_contents("ws1", "/projects/ai")
    parsed = json.loads(out)
    assert parsed["directory_path"] == "/projects/ai"
    assert parsed["workspace_id"] == "ws1"
    assert parsed["memory_ids_json"] == '["m1"]'
    assert fake_client.calls == [("search_directory_contents", "ws1", "/projects/ai")]
