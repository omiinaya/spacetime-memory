"""Tests for the NewFeaturesMixin — MemoryMeta, Webhook, Observation, ContextTree, Review.

Unit tests use the ``mock_http_client`` fixture (no SpacetimeDB required).
Integration tests need a running SpacetimeDB standalone — they are marked
``pytest.mark.integration`` and are skipped when no backend is available.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from conftest import make_sql_response

# ============================================================================
# Helpers
# ============================================================================

def _reducer_resp():
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _sql_resp(rows):
    """Return a mock response for a SQL query returning the given rows."""
    payload = make_sql_response(rows)
    resp = Mock(status_code=200)
    resp.text = payload
    resp.json = lambda: {"result": payload}
    return resp


def _json_data_resp(json_str):
    """Return a mock response simulating a SQL query returning a row with a JSON field."""
    return _sql_resp([{"id": "r1", "workspace_id": "ws1", "json_data": json_str, "created_at": 1000_000_000}])

def _results_json_resp(results_json):
    """Return a mock response for context_tree_result with results_json."""
    return _sql_resp([{
        "id": "r1",
        "workspace_id": "ws1",
        "query_id": "list",
        "results_json": results_json,
        "created_at": 1000_000_000,
    }])

def _items_json_resp(items_json):
    """Return a mock response for review_result with items_json."""
    return _sql_resp([{
        "id": "r1",
        "workspace_id": "ws1",
        "user_id": "user1",
        "items_json": items_json,
        "due_count": 2,
        "created_at": 1000_000_000,
    }])


# ============================================================================
# MemoryMeta
# ============================================================================

class TestMemoryMeta:
    """MemoryMeta — set, get, batch, list."""

    def test_set_memory_meta(self, mock_http_client):
        """set_memory_meta calls the reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.set_memory_meta(
            workspace_id="ws1",
            memory_id="mem-1",
            category="preferences",
            immutable=True,
            extra_json='{"source":"user"}',
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called_once()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/set_memory_meta" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws1", "mem-1", "preferences", True, '{"source":"user"}']

    def test_set_memory_meta_defaults(self, mock_http_client):
        """set_memory_meta with minimal args uses defaults."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.set_memory_meta(
            workspace_id="ws1",
            memory_id="mem-2",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws1", "mem-2", "", False, "{}"]

    def test_get_memory_meta_found(self, mock_http_client):
        """get_memory_meta returns the metadata dict when found."""
        meta_row = {
            "id": "mm_1",
            "workspace_id": "ws1",
            "memory_id": "mem-1",
            "category": "preferences",
            "immutable": True,
            "extra_json": "{}",
            "created_at": 1000_000_000,
            "updated_at": 1000_000_000,
        }

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_memory_meta" in url:
                return _reducer_resp()
            # _query() calls query_table reducer then reads query_result
            return _sql_resp([meta_row])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.get_memory_meta(memory_id="mem-1")

        assert result is not None
        assert result["memory_id"] == "mem-1"
        assert result["category"] == "preferences"
        assert result["immutable"] is True

    def test_get_memory_meta_not_found(self, mock_http_client):
        """get_memory_meta returns None when no metadata exists."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_memory_meta" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.get_memory_meta(memory_id="nonexistent")
        assert result is None

    def test_batch_set_memory_meta(self, mock_http_client):
        """batch_set_memory_meta calls the reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        ids_json = json.dumps(["mem-1", "mem-2", "mem-3"])
        result = mock_http_client.batch_set_memory_meta(
            workspace_id="ws1",
            ids_json=ids_json,
            category="facts",
            immutable=False,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body[0] == "ws1"
        assert json.loads(body[1]) == ["mem-1", "mem-2", "mem-3"]
        assert body[2] == "facts"

    def test_list_memory_meta(self, mock_http_client):
        """list_memory_meta returns all meta rows for a workspace."""
        rows = [
            {
                "id": "mm_1",
                "workspace_id": "ws1",
                "memory_id": "mem-1",
                "category": "preferences",
                "immutable": True,
                "extra_json": "{}",
                "created_at": 1000_000_000,
                "updated_at": 1000_000_000,
            },
            {
                "id": "mm_2",
                "workspace_id": "ws1",
                "memory_id": "mem-2",
                "category": "facts",
                "immutable": False,
                "extra_json": '{"source":"tool"}',
                "created_at": 1000_000_001,
                "updated_at": 1000_000_001,
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/query_table" in url:
                return _reducer_resp()
            return _sql_resp(rows)

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_memory_meta(workspace_id="ws1")
        assert len(result) == 2
        assert result[0]["memory_id"] == "mem-1"
        assert result[1]["category"] == "facts"


# ============================================================================
# Webhook
# ============================================================================

class TestWebhook:
    """Webhook — create, update, delete, list, fire."""

    def test_create_webhook(self, mock_http_client):
        """create_webhook calls the reducer with all args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_webhook(
            workspace_id="ws1",
            name="My Webhook",
            url="https://example.com/hook",
            event_types='["memory.created"]',
            secret="my-secret",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/create_webhook" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws1", "My Webhook", "https://example.com/hook", '["memory.created"]', "my-secret"]

    def test_create_webhook_minimal(self, mock_http_client):
        """create_webhook with minimal args."""
        mock_http_client._http.post.return_value = _reducer_resp()
        result = mock_http_client.create_webhook(
            workspace_id="ws1",
            name="Catch All",
            url="https://hooks.example.com/all",
        )
        assert result["status"] == "ok"

    def test_update_webhook(self, mock_http_client):
        """update_webhook calls the reducer."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.update_webhook(
            webhook_id="wh-1",
            name="Updated Name",
            url="https://new-url.com/hook",
            is_active=False,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body[0] == "wh-1"
        assert body[1] == "Updated Name"
        assert body[4] is False

    def test_update_webhook_partial(self, mock_http_client):
        """update_webhook with only some fields."""
        mock_http_client._http.post.return_value = _reducer_resp()
        result = mock_http_client.update_webhook(webhook_id="wh-1", is_active=False)
        assert result["status"] == "ok"

    def test_delete_webhook(self, mock_http_client):
        """delete_webhook calls the reducer."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.delete_webhook(webhook_id="wh-1")

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/delete_webhook" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["wh-1"]

    def test_list_webhooks(self, mock_http_client):
        """list_webhooks returns webhook list from result table."""
        webhook_rows = [
            {
                "id": "r1",
                "webhook_id": "wh-1",
                "workspace_id": "ws1",
                "name": "Webhook One",
                "url": "https://example.com/1",
                "event_types": '["memory.created"]',
                "is_active": True,
                "created_at": 1000_000_000,
                "updated_at": 1000_000_000,
                "created_by": "user_abc",
            },
            {
                "id": "r2",
                "webhook_id": "wh-2",
                "workspace_id": "ws1",
                "name": "Webhook Two",
                "url": "https://example.com/2",
                "event_types": "[]",
                "is_active": False,
                "created_at": 1000_000_001,
                "updated_at": 1000_000_001,
                "created_by": "user_abc",
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_webhooks" in url:
                return _reducer_resp()
            return _sql_resp(webhook_rows)

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_webhooks(workspace_id="ws1")

        assert len(result) == 2
        assert result[0]["webhook_id"] == "wh-1"
        assert result[0]["name"] == "Webhook One"
        assert result[0]["is_active"] is True
        assert result[1]["webhook_id"] == "wh-2"
        assert result[1]["is_active"] is False

    def test_list_webhooks_empty(self, mock_http_client):
        """list_webhooks returns [] when no webhooks exist."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_webhooks" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect
        result = mock_http_client.list_webhooks(workspace_id="ws1")
        assert result == []

    def test_fire_webhook_event(self, mock_http_client):
        """fire_webhook_event calls the reducer."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.fire_webhook_event(
            workspace_id="ws1",
            event_type="memory.created",
            payload='{"memory_id":"mem-1"}',
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/fire_webhook_event" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws1", "memory.created", '{"memory_id":"mem-1"}']


# ============================================================================
# Observation
# ============================================================================

class TestObservation:
    """Observation — create, update, delete, list."""

    def test_create_observation(self, mock_http_client):
        """create_observation calls the reducer with all args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_observation(
            workspace_id="ws1",
            content="The agent learned to navigate the maze in 30s.",
            summary="Agent maze speed",
            evidence_json='["mem-1","mem-2"]',
            observation_type="fact",
            confidence=0.95,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/create_observation" in args[0]
        body = json.loads(kwargs["content"])
        assert body == [
            "ws1",
            "The agent learned to navigate the maze in 30s.",
            "Agent maze speed",
            '["mem-1","mem-2"]',
            "fact",
            0.95,
        ]

    def test_create_observation_defaults(self, mock_http_client):
        """create_observation with minimal args uses sensible defaults."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_observation(
            workspace_id="ws1",
            content="Basic observation.",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        # content, summary, evidence_json, type, confidence
        assert body[0] == "ws1"
        assert body[1] == "Basic observation."
        assert body[2] == ""  # default summary
        assert body[3] == "[]"  # default evidence
        assert body[4] == "fact"  # default type
        assert body[5] == 0.8  # default confidence

    def test_update_observation(self, mock_http_client):
        """update_observation calls the reducer."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.update_observation(
            id="obs-1",
            content="Updated content",
            summary="Updated summary",
            confidence=0.9,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/update_observation" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["obs-1", "Updated content", "Updated summary", 0.9]

    def test_delete_observation(self, mock_http_client):
        """delete_observation calls the reducer."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.delete_observation(id="obs-1")

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/delete_observation" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["obs-1"]

    def test_list_observations(self, mock_http_client):
        """list_observations returns parsed observations from json_data."""
        observations = [
            {
                "id": "obs-1",
                "workspace_id": "ws1",
                "content": "First observation",
                "summary": "First",
                "observation_type": "fact",
                "confidence": 0.95,
                "status": "active",
            },
            {
                "id": "obs-2",
                "workspace_id": "ws1",
                "content": "Second observation",
                "summary": "Second",
                "observation_type": "inference",
                "confidence": 0.7,
                "status": "active",
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_observations" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "json_data": json.dumps(observations),
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_observations(workspace_id="ws1")

        assert len(result) == 2
        assert result[0]["id"] == "obs-1"
        assert result[0]["observation_type"] == "fact"
        assert result[1]["id"] == "obs-2"
        assert result[1]["observation_type"] == "inference"

    def test_list_observations_empty(self, mock_http_client):
        """list_observations returns [] when no observations exist."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_observations" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect
        result = mock_http_client.list_observations(workspace_id="ws1")
        assert result == []


# ============================================================================
# ContextTree
# ============================================================================

class TestContextTree:
    """ContextTree — set, delete, list, resolve."""

    def test_set_context(self, mock_http_client):
        """set_context calls the reducer with all args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.set_context(
            workspace_id="ws1",
            path="/api/v2",
            content="API v2 context: rate limiting applies.",
            priority=1.0,
            is_global=False,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/set_context" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws1", "/api/v2", "API v2 context: rate limiting applies.", 1.0, False]

    def test_set_context_global(self, mock_http_client):
        """set_context with is_global=True."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.set_context(
            workspace_id="ws1",
            path="/",
            content="Global fallback context",
            is_global=True,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body[4] is True

    def test_delete_context(self, mock_http_client):
        """delete_context calls the reducer."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.delete_context(context_id="ctx-1")

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/delete_context" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ctx-1"]

    def test_list_contexts(self, mock_http_client):
        """list_contexts returns parsed context entries from results_json."""
        entries = [
            {
                "id": "ctx-1",
                "workspace_id": "ws1",
                "path": "/api/v2",
                "content": "API v2 context",
                "priority": 1.0,
                "is_global": False,
            },
            {
                "id": "ctx-2",
                "workspace_id": "ws1",
                "path": "/",
                "content": "Root fallback",
                "priority": 0.0,
                "is_global": True,
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_contexts" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "query_id": "list",
                "results_json": json.dumps(entries),
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.list_contexts(workspace_id="ws1")

        assert len(result) == 2
        assert result[0]["id"] == "ctx-1"
        assert result[0]["path"] == "/api/v2"
        assert result[1]["id"] == "ctx-2"
        assert result[1]["is_global"] is True

    def test_list_contexts_empty(self, mock_http_client):
        """list_contexts returns [] when no contexts exist."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/list_contexts" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect
        result = mock_http_client.list_contexts(workspace_id="ws1")
        assert result == []

    def test_resolve_context(self, mock_http_client):
        """resolve_context returns matched entries sorted by specificity."""
        matched = [
            {
                "id": "ctx-3",
                "workspace_id": "ws1",
                "path": "/api/v2/users",
                "content": "User-specific context",
                "priority": 2.0,
                "is_global": False,
            },
            {
                "id": "ctx-1",
                "workspace_id": "ws1",
                "path": "/api/v2",
                "content": "API v2 context",
                "priority": 1.0,
                "is_global": False,
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/resolve_context" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "query_id": "/api/v2/users/123",
                "results_json": json.dumps(matched),
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.resolve_context(
            workspace_id="ws1",
            path="/api/v2/users/123",
        )

        assert len(result) == 2
        assert result[0]["path"] == "/api/v2/users"
        assert result[1]["path"] == "/api/v2"

    def test_resolve_context_no_match(self, mock_http_client):
        """resolve_context returns [] when no contexts match."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/resolve_context" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "query_id": "/unknown",
                "results_json": "[]",
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect
        result = mock_http_client.resolve_context(
            workspace_id="ws1",
            path="/unknown",
        )
        assert result == []


# ============================================================================
# Review (SM-2 Spaced Repetition)
# ============================================================================

class TestReview:
    """Review — schedule, perform, get_due, get_stats."""

    def test_schedule_review(self, mock_http_client):
        """schedule_review calls the reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.schedule_review(
            workspace_id="ws1",
            memory_id="mem-1",
            user_id="user1",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/schedule_review" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws1", "mem-1", "user1"]

    def test_perform_review(self, mock_http_client):
        """perform_review calls the reducer with review_id and grade."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.perform_review(review_id="rev-1", grade=4)

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/perform_review" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["rev-1", 4]

    def test_perform_review_min_grade(self, mock_http_client):
        """perform_review with grade 0 (complete blackout)."""
        mock_http_client._http.post.return_value = _reducer_resp()
        result = mock_http_client.perform_review(review_id="rev-1", grade=0)
        assert result["status"] == "ok"

    def test_perform_review_max_grade(self, mock_http_client):
        """perform_review with grade 6 (perfect with extra ease)."""
        mock_http_client._http.post.return_value = _reducer_resp()
        result = mock_http_client.perform_review(review_id="rev-1", grade=6)
        assert result["status"] == "ok"

    def test_get_due_reviews(self, mock_http_client):
        """get_due_reviews returns parsed review items."""
        due_items = [
            {
                "id": "rev-1",
                "workspace_id": "ws1",
                "memory_id": "mem-1",
                "user_id": "user1",
                "easiness_factor": 2.5,
                "interval_days": 0,
                "repetitions": 0,
                "next_review_at": 1000_000_000,
                "last_reviewed_at": 1000_000_000,
                "is_active": True,
            },
            {
                "id": "rev-2",
                "workspace_id": "ws1",
                "memory_id": "mem-2",
                "user_id": "user1",
                "easiness_factor": 2.5,
                "interval_days": 0,
                "repetitions": 0,
                "next_review_at": 1000_000_000,
                "last_reviewed_at": 1000_000_000,
                "is_active": True,
            },
        ]

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_due_reviews" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "user_id": "user1",
                "items_json": json.dumps(due_items),
                "due_count": 2,
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.get_due_reviews(workspace_id="ws1", user_id="user1")

        assert len(result) == 2
        assert result[0]["id"] == "rev-1"
        assert result[0]["memory_id"] == "mem-1"
        assert result[1]["id"] == "rev-2"

    def test_get_due_reviews_empty(self, mock_http_client):
        """get_due_reviews returns [] when nothing is due."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_due_reviews" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "user_id": "user1",
                "items_json": "[]",
                "due_count": 0,
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect
        result = mock_http_client.get_due_reviews(workspace_id="ws1", user_id="user1")
        assert result == []

    def test_get_review_stats(self, mock_http_client):
        """get_review_stats returns parsed stats dict."""
        stats_json = json.dumps({
            "total_review_items": 10,
            "active_items": 8,
            "due_now": 3,
            "average_grade": 3.5,
            "average_easiness_factor": 2.3,
            "user_id": "user1",
        })

        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_review_stats" in url:
                return _reducer_resp()
            return _sql_resp([{
                "id": "r1",
                "workspace_id": "ws1",
                "user_id": "user1",
                "items_json": stats_json,
                "due_count": 3,
                "created_at": 1000_000_000,
            }])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.get_review_stats(workspace_id="ws1", user_id="user1")

        assert result is not None
        assert result["total_review_items"] == 10
        assert result["active_items"] == 8
        assert result["due_now"] == 3
        assert result["average_grade"] == 3.5
        assert result["average_easiness_factor"] == 2.3
        assert result["user_id"] == "user1"

    def test_get_review_stats_no_data(self, mock_http_client):
        """get_review_stats returns None when no stats available."""
        def side_effect(*args, **kwargs):
            url = str(args[0]) if args else ""
            if "/call/get_review_stats" in url:
                return _reducer_resp()
            return _sql_resp([])

        mock_http_client._http.post.side_effect = side_effect
        result = mock_http_client.get_review_stats(workspace_id="ws1", user_id="user1")
        assert result is None


# ============================================================================
# Integration tests — require a running SpacetimeDB
# ============================================================================

@pytest.mark.integration
class TestNewFeaturesIntegration:
    """End-to-end tests against a real SpacetimeDB backend.

    These tests require a running SpacetimeDB standalone with the module
    published. They are skipped when ``SPACETIMEDB_HOST`` is not set to a
    non-localhost value (or when no backend is detected).
    """

    @pytest.fixture
    def live_client(self):
        """Create a client pointed at a real SpacetimeDB instance."""
        from spacetime_memory import Client
        client = Client(
            host="127.0.0.1",
            port="3001",
            database=(
                "c20082e7643347e8d36302b550bb98c7343f9ea2a268f3bee58ee58d3c3dcbf1"
            ),
        )
        # Quick connectivity check — skip if unreachable
        health = client.ping()
        if health.get("status") != "ok":
            pytest.skip("SpacetimeDB not reachable at 127.0.0.1:3001")
        yield client

    def test_memory_meta_crud_flow(self, live_client):
        """Store a memory → set meta → get meta → verify."""
        # First create a workspace and store a memory
        ws = live_client.create_workspace("new-features-integration-test")
        ws_id = ws.get("id", "")
        assert ws_id, f"Workspace creation failed: {ws}"

        mem = live_client.store(
            workspace_id=ws_id,
            content="Integration test memory for metadata.",
            peer_id="integration-test",
        )
        mem_id = mem.get("id", "")
        assert mem_id, f"Memory storage failed: {mem}"

        # Set metadata
        meta_result = live_client.set_memory_meta(
            workspace_id=ws_id,
            memory_id=mem_id,
            category="integration-test",
            immutable=False,
            extra_json='{"source":"integration"}',
        )
        assert meta_result["status"] == "ok"

        # Get metadata
        meta = live_client.get_memory_meta(memory_id=mem_id)
        assert meta is not None, "get_memory_meta returned None"
        assert meta["category"] == "integration-test"
        assert meta["memory_id"] == mem_id

        # List all meta for workspace
        all_meta = live_client.list_memory_meta(workspace_id=ws_id)
        assert len(all_meta) >= 1
        found = [m for m in all_meta if m["memory_id"] == mem_id]
        assert len(found) >= 1

        # Batch set meta
        batch_result = live_client.batch_set_memory_meta(
            workspace_id=ws_id,
            ids_json=json.dumps([mem_id]),
            category="batch-test",
            immutable=True,
        )
        assert batch_result["status"] == "ok"

        # Verify batch update
        updated_meta = live_client.get_memory_meta(memory_id=mem_id)
        assert updated_meta is not None
        assert updated_meta["category"] == "batch-test"
        assert updated_meta["immutable"] is True

    def test_webhook_crud_flow(self, live_client):
        """Create webhook → list → update → delete."""
        ws = live_client.create_workspace("webhook-integration-test")
        ws_id = ws.get("id", "")
        assert ws_id

        # Create
        result = live_client.create_webhook(
            workspace_id=ws_id,
            name="Integration Test Hook",
            url="https://httpbin.org/post",
            event_types='["memory.created"]',
            secret="test-secret",
        )
        assert result["status"] == "ok"

        # List
        hooks = live_client.list_webhooks(workspace_id=ws_id)
        assert len(hooks) >= 1
        hook = hooks[0]
        assert hook["name"] == "Integration Test Hook"
        hook_id = hook["webhook_id"]

        # Update
        update_result = live_client.update_webhook(
            webhook_id=hook_id,
            name="Updated Integration Hook",
            is_active=False,
        )
        assert update_result["status"] == "ok"

        # Delete
        delete_result = live_client.delete_webhook(webhook_id=hook_id)
        assert delete_result["status"] == "ok"

        # Verify deleted
        hooks_after = live_client.list_webhooks(workspace_id=ws_id)
        assert all(h["webhook_id"] != hook_id for h in hooks_after)

    def test_observation_crud_flow(self, live_client):
        """Create observation → list → update → delete."""
        ws = live_client.create_workspace("obs-integration-test")
        ws_id = ws.get("id", "")
        assert ws_id

        # Create
        result = live_client.create_observation(
            workspace_id=ws_id,
            content="Integration test observation.",
            summary="Integration test",
            evidence_json="[]",
            observation_type="fact",
            confidence=0.9,
        )
        assert result["status"] == "ok"

        # List — observation_list_result uses json_data
        obs_list = live_client.list_observations(workspace_id=ws_id)
        assert len(obs_list) >= 1
        obs = obs_list[0]
        obs_id = obs["id"]

        # Update
        update_result = live_client.update_observation(
            id=obs_id,
            content="Updated observation content.",
            summary="Updated",
            confidence=0.95,
        )
        assert update_result["status"] == "ok"

        # Delete
        delete_result = live_client.delete_observation(id=obs_id)
        assert delete_result["status"] == "ok"

    def test_context_tree_flow(self, live_client):
        """Set context → list → resolve → delete."""
        ws = live_client.create_workspace("ctx-integration-test")
        ws_id = ws.get("id", "")
        assert ws_id

        # Set a few contexts
        live_client.set_context(
            workspace_id=ws_id,
            path="/api/v2",
            content="API v2 context",
            priority=1.0,
        )
        live_client.set_context(
            workspace_id=ws_id,
            path="/api/v2/users",
            content="User-specific API context",
            priority=2.0,
        )
        live_client.set_context(
            workspace_id=ws_id,
            path="/",
            content="Root fallback",
            is_global=True,
        )

        # List
        all_ctx = live_client.list_contexts(workspace_id=ws_id)
        assert len(all_ctx) >= 3

        # Find the user context to delete
        user_ctx = [c for c in all_ctx if c["path"] == "/api/v2/users"]
        assert len(user_ctx) >= 1
        ctx_id = user_ctx[0]["id"]

        # Resolve — should match /api/v2/users (exact), /api/v2 (prefix), and / (root/global)
        resolved = live_client.resolve_context(
            workspace_id=ws_id,
            path="/api/v2/users/123",
        )
        assert len(resolved) >= 2
        # Most specific first
        assert resolved[0]["path"] == "/api/v2/users"

        # Delete
        delete_result = live_client.delete_context(context_id=ctx_id)
        assert delete_result["status"] == "ok"

    def test_review_flow(self, live_client):
        """Schedule review → get due → perform → get stats."""
        ws = live_client.create_workspace("review-integration-test")
        ws_id = ws.get("id", "")
        assert ws_id

        # Need a memory first
        mem = live_client.store(
            workspace_id=ws_id,
            content="Review integration test memory.",
            peer_id="review-test",
        )
        mem_id = mem.get("id", "")
        assert mem_id

        # Schedule review
        schedule_result = live_client.schedule_review(
            workspace_id=ws_id,
            memory_id=mem_id,
            user_id="integration-tester",
        )
        assert schedule_result["status"] == "ok"

        # Get due reviews
        due = live_client.get_due_reviews(
            workspace_id=ws_id,
            user_id="integration-tester",
        )
        assert len(due) >= 1
        review_id = due[0]["id"]

        # Perform review with grade 4
        perform_result = live_client.perform_review(
            review_id=review_id,
            grade=4,
        )
        assert perform_result["status"] == "ok"

        # Get stats
        stats = live_client.get_review_stats(
            workspace_id=ws_id,
            user_id="integration-tester",
        )
        assert stats is not None
        assert stats["total_review_items"] >= 1
        assert stats["average_grade"] > 0
