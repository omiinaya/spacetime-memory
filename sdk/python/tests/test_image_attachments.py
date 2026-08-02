"""Tests for multi-modal image attachment support in store/store_batch.

Covers _normalize_images(), store(images=...), store_batch(items with images).
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, Mock

import pytest

from spacetime_memory import Client
from spacetime_memory.client._memories import _normalize_images

# ============================================================================
# _normalize_images() — handles URLs, file paths, lists, JSON strings
# ============================================================================


class TestNormalizeImages:
    """Unit tests for the _normalize_images() helper."""

    def test_none_returns_empty(self):
        """images=None, images_json='' -> ''"""
        assert _normalize_images(images=None, images_json="") == ""

    def test_empty_string_returns_empty(self):
        """images='', images_json='' -> ''"""
        assert _normalize_images(images="", images_json="") == ""

    def test_empty_list_returns_empty(self):
        """images=[], images_json='' -> ''"""
        assert _normalize_images(images=[], images_json="") == ""

    def test_fallback_to_images_json(self):
        """images='', images_json='["url"]' -> passthrough images_json"""
        assert _normalize_images(images="", images_json='["url"]') == '["url"]'

    def test_single_url_string(self):
        """images='https://example.com/img.png' -> JSON array with URL"""
        result = _normalize_images(images="https://example.com/img.png")
        assert json.loads(result) == ["https://example.com/img.png"]

    def test_already_json_array(self):
        """images='["https://ex.com/a.png"]' -> passthrough"""
        inp = '["https://ex.com/a.png"]'
        assert _normalize_images(images=inp) == inp

    def test_list_of_urls(self):
        """images=['url1', 'url2'] -> JSON array with both"""
        result = _normalize_images(
            images=["https://ex.com/a.png", "https://ex.com/b.png"]
        )
        assert json.loads(result) == [
            "https://ex.com/a.png",
            "https://ex.com/b.png",
        ]

    def test_file_path_converts_to_data_uri(self):
        """images='/path/to/existing.png' -> data: URI"""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
            tmp_path = f.name
        try:
            result = _normalize_images(images=tmp_path)
            parsed = json.loads(result)
            assert len(parsed) == 1
            assert parsed[0].startswith("data:image/png;base64,")
        finally:
            os.unlink(tmp_path)

    def test_file_path_in_list_converts(self):
        """images=['/path/to/img.png', 'url'] -> mixture"""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
            tmp_path = f.name
        try:
            result = _normalize_images(
                images=[tmp_path, "https://ex.com/b.png"]
            )
            parsed = json.loads(result)
            assert len(parsed) == 2
            assert parsed[0].startswith("data:image/jpeg;base64,")
            assert parsed[1] == "https://ex.com/b.png"
        finally:
            os.unlink(tmp_path)

    def test_images_overrides_images_json(self):
        """images=url beats images_json when both provided"""
        result = _normalize_images(
            images="https://ex.com/override.png",
            images_json='["https://ex.com/ignored.png"]',
        )
        assert json.loads(result) == ["https://ex.com/override.png"]

    def test_context_param_no_side_effect(self):
        """context param doesn't change results (logging hint only)"""
        a = _normalize_images(images="https://ex.com/a.png", context="store")
        b = _normalize_images(images="https://ex.com/a.png", context="batch")
        assert a == b


# ============================================================================
# store() with image attachments
# ============================================================================


class TestStoreWithImages:
    """store() accepts images via images and images_json params."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])  # empty → skip post-store indexing
        c._emit_event = Mock()
        # Mock _query to avoid real SQL calls and provide memory ID resolution
        c._query = Mock(return_value=[])
        c._query_cache = None
        c.plugin_manager = None
        c._tantivy_index = Mock()
        c._binary_cache = {}
        c._ensure_identity = Mock()
        c._record_embedder_error = Mock()
        c._check_error_rate_alert = Mock()
        return c

    def test_store_with_images_json(self, client):
        """store passes images_json to the reducer."""
        client.store("ws1", content="hello", images_json='["https://ex.com/img.png"]')
        args_list = client._call.call_args[0][1]
        # images_json is index 10 in reducer args
        assert args_list[10] == '["https://ex.com/img.png"]'

    def test_store_with_images_url(self, client):
        """store accepts a plain URL via images param and normalizes it."""
        client.store("ws1", content="hello", images="https://ex.com/img.png")
        args_list = client._call.call_args[0][1]
        assert json.loads(args_list[10]) == ["https://ex.com/img.png"]

    def test_store_with_images_list(self, client):
        """store accepts a list of URLs via images param."""
        client.store(
            "ws1",
            content="hello",
            images=["https://ex.com/a.png", "https://ex.com/b.png"],
        )
        args_list = client._call.call_args[0][1]
        assert json.loads(args_list[10]) == [
            "https://ex.com/a.png",
            "https://ex.com/b.png",
        ]

    def test_store_images_overrides_images_json(self, client):
        """images param overrides images_json when both provided."""
        client.store(
            "ws1",
            content="hello",
            images="https://ex.com/winner.png",
            images_json='["https://ex.com/ignored.png"]',
        )
        args_list = client._call.call_args[0][1]
        assert json.loads(args_list[10]) == ["https://ex.com/winner.png"]

    def test_store_images_passed_to_reducer(self, client):
        """store() passes images_json to the reducer — no post-hoc context call needed."""
        # Make _query return a matching memory after the store_memory reducer
        client._query.return_value = [
            {"id": "mem-1", "content": "hello with image"}
        ]

        client.store(
            "ws1",
            content="hello with image",
            images_json='["https://ex.com/img.png"]',
        )

        # Verify set_memory_context was NOT called (handled inline in reducer)
        ctx_calls = [
            c
            for c in client._call.call_args_list
            if c[0][0] == "set_memory_context"
        ]
        assert len(ctx_calls) == 0

        # Verify images_json was passed to store_memory reducer at arg index 10
        store_calls = [
            c for c in client._call.call_args_list
            if c[0][0] == "store_memory"
        ]
        assert len(store_calls) == 1
        assert store_calls[0][0][1][10] == '["https://ex.com/img.png"]'

    def test_store_no_images_sends_empty_string(self, client):
        """store with no image params sends empty string for images_json."""
        client.store("ws1", content="hello")
        args_list = client._call.call_args[0][1]
        assert args_list[10] == ""


# ============================================================================
# store_batch() with image attachments
# ============================================================================


class TestStoreBatchWithImages:
    """store_batch() accepts images per item — context is now inline."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        # Mock embedder to return fake embeddings
        c._http = MagicMock()
        c._http.post.return_value = Mock(
            status_code=200,
            json=lambda: {"embeddings": [[0.1, 0.2], [0.3, 0.4]]},
        )
        c._emit_event = Mock()
        c._query_cache = None
        # Mock _query to return memories that match content prefixes
        c._query = Mock(
            return_value=[
                {"id": "mem-1", "content": "first item with image", "created_at": 100},
                {"id": "mem-2", "content": "second item with image", "created_at": 200},
            ]
        )
        c._tantivy_index_batch = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._ensure_identity = Mock()
        c._record_embedder_error = Mock()
        c._check_error_rate_alert = Mock()
        return c

    def _get_batch_items_payload(self, client):
        """Extract the items JSON passed to store_memory_batch reducer."""
        for call_args in client._call.call_args_list:
            if call_args[0][0] == "store_memory_batch":
                items_json = call_args[0][1][0]
                return json.loads(items_json)
        return None

    def test_batch_with_images_json_per_item(self, client):
        """store_batch items with images_json — context passed inline."""
        items = [
            {
                "content": "first item with image",
                "images_json": '["https://ex.com/a.png"]',
            },
            {
                "content": "second item with image",
                "images_json": '["https://ex.com/b.png"]',
            },
        ]
        client.store_batch("ws1", items)
        payload = self._get_batch_items_payload(client)
        assert payload is not None
        assert payload[0]["context"] == '["https://ex.com/a.png"]'
        assert payload[1]["context"] == '["https://ex.com/b.png"]'
        # No set_memory_context calls (handled inline by reducer)
        ctx_calls = [
            c for c in client._call.call_args_list
            if c[0][0] == "set_memory_context"
        ]
        assert len(ctx_calls) == 0

    def test_batch_with_images_url_per_item(self, client):
        """store_batch items with images field (URL) — normalized in context."""
        items = [
            {"content": "first item with image", "images": "https://ex.com/a.png"},
            {"content": "second item with image", "images": "https://ex.com/b.png"},
        ]
        client.store_batch("ws1", items)
        payload = self._get_batch_items_payload(client)
        assert payload is not None
        assert json.loads(payload[0]["context"]) == ["https://ex.com/a.png"]
        assert json.loads(payload[1]["context"]) == ["https://ex.com/b.png"]

    def test_batch_mixed_images_and_no_images(self, client):
        """Items without images have empty context in payload."""
        items = [
            {"content": "item with image", "images": "https://ex.com/a.png"},
            {"content": "item without image"},
            {"content": "another with image", "images": "https://ex.com/c.png"},
        ]
        client.store_batch("ws1", items)
        payload = self._get_batch_items_payload(client)
        assert payload is not None
        assert json.loads(payload[0]["context"]) == ["https://ex.com/a.png"]
        assert payload[1]["context"] == ""
        assert json.loads(payload[2]["context"]) == ["https://ex.com/c.png"]

    def test_batch_empty_content_skipped(self, client):
        """Items with empty content are skipped entirely (no crash)."""
        items = [
            {"content": "valid item", "images": "https://ex.com/a.png"},
            {"content": "", "images": '["https://ex.com/b.png"]'},
            {"content": "another valid", "images": "https://ex.com/c.png"},
        ]
        result = client.store_batch("ws1", items)
        assert len(result) == 2

    def test_batch_embedder_unavailable_still_stores_images(self, client):
        """When the embedder is down, images are still in context payload."""
        import httpx
        client._http.post.side_effect = httpx.ConnectError("embedder down")

        items = [
            {"content": "item after embedder fail", "images": "https://ex.com/a.png"},
            {"content": "another after fail", "images": "https://ex.com/b.png"},
        ]
        client.store_batch("ws1", items)
        payload = self._get_batch_items_payload(client)
        assert payload is not None
        assert json.loads(payload[0]["context"]) == ["https://ex.com/a.png"]
        assert json.loads(payload[1]["context"]) == ["https://ex.com/b.png"]

    def test_batch_images_overrides_images_json(self, client):
        """When both images and images_json are set, images wins."""
        items = [
            {
                "content": "override test",
                "images": "https://ex.com/winner.png",
                "images_json": '["https://ex.com/loser.png"]',
            },
        ]
        client.store_batch("ws1", items)
        payload = self._get_batch_items_payload(client)
        assert payload is not None
        assert json.loads(payload[0]["context"]) == ["https://ex.com/winner.png"]
