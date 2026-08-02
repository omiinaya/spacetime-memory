"""Tests for GitHubConnector — mock-based HTTP tests.

Covers: all event types, pagination, rate limiting, error handling,
_parse_next_link, _format_event, _summarize_event.
"""

import os
import shutil
from unittest.mock import Mock, patch

_conn_cursor_dir = os.path.expanduser("~/.spacetime-memory/connectors")


def _clear_cursor():
    if os.path.exists(_conn_cursor_dir):
        shutil.rmtree(_conn_cursor_dir, ignore_errors=True)


_clear_cursor()

from spacetime_memory.connectors import (
    GitHubConnector,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_gh_event(
    event_id,
    event_type,
    actor="octocat",
    repo_name="octocat/repo",
    payload=None,
    created_at="2024-01-01T00:00:00Z",
):
    """Build a GitHub API event dict."""
    return {
        "id": event_id,
        "type": event_type,
        "actor": {"login": actor},
        "repo": {"name": repo_name},
        "payload": payload or {},
        "created_at": created_at,
    }


def _mock_response(status_code=200, json_data=None, headers=None):
    """Create a mock httpx response."""
    resp = Mock(status_code=status_code)
    resp.json.return_value = json_data
    resp.headers = headers or {}
    return resp


# ── Event Formatting ─────────────────────────────────────────────────


class TestGitHubFormatEvent:
    """_format_event for all event types."""

    def test_push_event(self):
        result = GitHubConnector._format_event(
            "PushEvent",
            "alice",
            "alice/repo",
            {
                "ref": "refs/heads/main",
                "commits": [
                    {"message": "fix: bug"},
                    {"message": "feat: add thing"},
                ],
            },
            "2024-01-01",
        )
        assert "alice pushed to main in alice/repo" in result
        assert "fix: bug" in result
        assert "feat: add thing" in result

    def test_push_event_many_commits(self):
        """More than 5 commits shows truncation message."""
        commits = [{"message": f"commit {i}"} for i in range(10)]
        result = GitHubConnector._format_event(
            "PushEvent",
            "bob",
            "bob/repo",
            {"ref": "refs/heads/dev", "commits": commits},
            "2024-01-01",
        )
        assert "... and 5 more commits" in result

    def test_push_event_no_ref(self):
        """Push with empty ref is handled."""
        result = GitHubConnector._format_event(
            "PushEvent",
            "cat",
            "cat/repo",
            {"ref": "", "commits": []},
            "2024-01-01",
        )
        assert "pushed to" in result

    def test_issues_event(self):
        result = GitHubConnector._format_event(
            "IssuesEvent",
            "alice",
            "alice/repo",
            {
                "action": "closed",
                "issue": {
                    "title": "Bug report",
                    "number": 42,
                    "html_url": "https://github.com/alice/repo/issues/42",
                },
            },
            "2024-01-01",
        )
        assert "alice closed issue #42" in result
        assert "Bug report" in result
        assert "https://github.com/alice/repo/issues/42" in result

    def test_create_event_branch(self):
        result = GitHubConnector._format_event(
            "CreateEvent",
            "dev",
            "dev/repo",
            {"ref_type": "branch", "ref": "feature-x"},
            "2024-01-01",
        )
        assert "created branch 'feature-x'" in result

    def test_create_event_tag(self):
        result = GitHubConnector._format_event(
            "CreateEvent",
            "dev",
            "dev/repo",
            {"ref_type": "tag"},
            "2024-01-01",
        )
        assert "created tag" in result

    def test_watch_event(self):
        result = GitHubConnector._format_event(
            "WatchEvent",
            "star",
            "cool/repo",
            {"action": "started"},
            "2024-01-01",
        )
        assert "star started watching cool/repo" in result

    def test_fork_event(self):
        result = GitHubConnector._format_event(
            "ForkEvent",
            "forker",
            "orig/repo",
            {"forkee": {"full_name": "forker/repo"}},
            "2024-01-01",
        )
        assert "forker forked orig/repo to forker/repo" in result

    def test_pull_request_event(self):
        result = GitHubConnector._format_event(
            "PullRequestEvent",
            "contributor",
            "main/repo",
            {
                "action": "opened",
                "pull_request": {
                    "title": "Add new feature",
                    "number": 100,
                    "html_url": "https://github.com/main/repo/pull/100",
                },
            },
            "2024-01-01",
        )
        assert "contributor opened PR #100" in result
        assert "Add new feature" in result

    def test_issue_comment_event(self):
        result = GitHubConnector._format_event(
            "IssueCommentEvent",
            "commenter",
            "main/repo",
            {
                "action": "created",
                "issue": {"number": 55},
            },
            "2024-01-01",
        )
        assert "commenter created comment on issue #55" in result

    def test_unknown_event(self):
        result = GitHubConnector._format_event(
            "SomeUnknownEvent",
            "user",
            "repo/x",
            {},
            "2024-01-01",
        )
        assert "triggered SomeUnknownEvent in repo/x" in result


# ── Event Summarization ──────────────────────────────────────────────


class TestGitHubSummarizeEvent:
    """_summarize_event coverage."""

    def test_known_types(self):
        assert "Pushed to" in GitHubConnector._summarize_event("PushEvent", "r")
        assert "Issue activity" in GitHubConnector._summarize_event("IssuesEvent", "r")
        assert "Created reference" in GitHubConnector._summarize_event("CreateEvent", "r")
        assert "Starred" in GitHubConnector._summarize_event("WatchEvent", "r")
        assert "Forked" in GitHubConnector._summarize_event("ForkEvent", "r")
        assert "PR activity" in GitHubConnector._summarize_event("PullRequestEvent", "r")
        assert "Comment on issue" in GitHubConnector._summarize_event("IssueCommentEvent", "r")

    def test_unknown_type(self):
        assert "Activity in" in GitHubConnector._summarize_event("UnknownEvent", "repo")


# ── Link Header Parsing ──────────────────────────────────────────────


class TestGitHubParseNextLink:
    """_parse_next_link static method."""

    def test_empty_header(self):
        assert GitHubConnector._parse_next_link("") is None

    def test_header_with_next(self):
        header = (
            '<https://api.github.com/users/octocat/events?page=2>; rel="next", '
            '<https://api.github.com/users/octocat/events?page=4>; rel="last"'
        )
        result = GitHubConnector._parse_next_link(header)
        assert result == "https://api.github.com/users/octocat/events?page=2"

    def test_header_without_next(self):
        header = '<https://api.github.com/page=1>; rel="prev"'
        assert GitHubConnector._parse_next_link(header) is None

    def test_malformed_no_brackets(self):
        assert GitHubConnector._parse_next_link('rel="next" something') is None


# ── Poll Integration ─────────────────────────────────────────────────


class TestGitHubPollIntegration:
    """poll() with mocked HTTP client."""

    def setup_method(self):
        """Clear cursor state before each test to prevent cross-test pollution."""
        _clear_cursor()

    def test_poll_multiple_event_types(self):
        """Poll returns Events for multiple event types."""
        events_data = [
            _make_gh_event(
                "multi-1", "PushEvent", "a", "a/r", {"ref": "refs/heads/main", "commits": []}
            ),
            _make_gh_event(
                "multi-2",
                "IssuesEvent",
                "b",
                "b/r",
                {"action": "opened", "issue": {"title": "x", "number": 1}},
            ),
            _make_gh_event("multi-3", "WatchEvent", "c", "c/r"),
        ]
        mock_resp = _mock_response(200, events_data, {"Link": ""})

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert len(events) == 3

    def test_poll_with_pagination(self):
        """Follows Link header to next page."""
        page1 = _mock_response(
            200,
            [
                _make_gh_event(
                    "pag-1", "PushEvent", "a", "a/r", {"ref": "refs/heads/main", "commits": []}
                )
            ],
            {"Link": '<https://api.github.com/page2>; rel="next"'},
        )
        page2 = _mock_response(
            200,
            [_make_gh_event("pag-2", "WatchEvent", "b", "b/r")],
            {"Link": ""},
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [page1, page2]

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert len(events) == 2

    def test_poll_stops_at_30_events(self):
        """fetched counter limits HTTP page count, not items per page."""
        # All 35 events are in a single response → all 35 are returned
        events_data = [_make_gh_event(f"bulk-{i}", "WatchEvent", "a", "a/r") for i in range(35)]
        mock_resp = _mock_response(200, events_data, {"Link": ""})

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        # All 35 new events from single page are returned; the 30-limit
        # is on HTTP request count, not per-response item count
        assert len(events) == 35

    def test_poll_deduplication(self):
        """Previously seen events are skipped."""
        events_data = [
            _make_gh_event(
                "dup-1", "PushEvent", "a", "a/r", {"ref": "refs/heads/main", "commits": []}
            )
        ]
        mock_resp = _mock_response(200, events_data, {"Link": ""})

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            e1 = connector.poll()
            e2 = connector.poll()

        assert len(e1) == 1
        assert len(e2) == 0

    def test_poll_rate_limit_exhausted(self):
        """403 with X-RateLimit-Remaining=0 triggers sleep and retry."""
        import time

        rate_limited = Mock(status_code=403)
        rate_limited.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(time.time()) + 2),
        }
        success = _mock_response(
            200,
            [_make_gh_event("rl-1", "WatchEvent", "a", "a/r")],
            {"Link": ""},
        )

        with patch("httpx.Client") as MockClient, patch("time.sleep") as mock_sleep:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [rate_limited, success]

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert mock_sleep.called
        assert len(events) == 1

    def test_poll_rate_limit_invalid_reset_epoch(self):
        """Rate limit with non-integer reset epoch falls back to 60s sleep."""
        rate_limited = Mock(status_code=403)
        rate_limited.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "not-a-number",
        }
        success = _mock_response(
            200,
            [_make_gh_event("rl-bad-1", "WatchEvent", "a", "a/r")],
            {"Link": ""},
        )

        with patch("httpx.Client") as MockClient, patch("time.sleep") as mock_sleep:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [rate_limited, success]

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert mock_sleep.called
        assert len(events) == 1

    def test_poll_rate_limit_unknown(self):
        """403 without RateLimit-Remaining=0 breaks immediately."""
        forbidden = Mock(status_code=403)
        forbidden.headers = {"X-RateLimit-Remaining": "100"}

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = forbidden

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert events == []

    def test_poll_404_user_not_found(self):
        """404 breaks and returns empty."""
        mock_resp = Mock(status_code=404)

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = GitHubConnector(
                token="tok",
                username="nobody",
                workspace_id="ws",
            )
            events = connector.poll()

        assert events == []

    def test_poll_unexpected_status(self):
        """Non-200/403/404 status breaks and returns empty."""
        mock_resp = Mock(status_code=500)

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert events == []

    def test_poll_http_error_after_retries(self):
        """RequestError after retries returns empty list."""
        import httpx

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = httpx.RequestError("network down")

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            events = connector.poll()

        assert events == []

    def test_cursor_persistence(self):
        """Cursor saves seen IDs across polls."""
        import json
        import os

        events_data = [
            _make_gh_event("c1", "PushEvent", "a", "a/r", {"ref": "refs/heads/main", "commits": []})
        ]
        mock_resp = _mock_response(200, events_data, {"Link": ""})

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = GitHubConnector(
                token="tok",
                username="u",
                workspace_id="ws",
            )
            connector.poll()

        # Check that cursor file was written with seen_ids
        cursor_file = os.path.expanduser(
            "~/.spacetime-memory/connectors/GitHubConnector_cursor.json"
        )
        assert os.path.exists(cursor_file)
        with open(cursor_file) as f:
            data = json.load(f)
        assert "c1" in data.get("seen_ids", [])
