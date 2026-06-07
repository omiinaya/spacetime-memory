"""Connector framework for spacetime-memory.

Connectors poll external data sources and persist them as memories or
KG nodes.  Each connector is a Python class that implements ``poll()``
and is run via a cron job or the CLI.

Built-in connectors:

* ``RssFeedConnector`` — poll an RSS/Atom feed URL, store entries as memories.
* ``GitHubConnector`` — poll GitHub API for user events.
* ``TwitterConnector`` — poll Twitter/X API v2 for tweets.
* ``WebhookConnector`` — receive events via HTTP webhook.
"""

from __future__ import annotations

import hmac
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx


# ── Connector base ──────────────────────────────────────────────────


class Connector(ABC):
    """Base class for all spacetime-memory connectors.

    Subclasses must implement ``poll()``, which should yield ``Event``
    objects.  The framework calls ``on_event()`` to persist each event
    as either a memory or a KG node.
    """

    @abstractmethod
    def poll(self) -> list[Event]:
        """Fetch new data from the external source.

        Returns a list of ``Event`` objects.  The framework calls
        ``on_event()`` for each one.  Call repeatedly to get new data.
        """
        ...

    def on_event(self, event: Event, client: Any) -> None:
        """Default handler: store the event's content as a memory.

        Override to customise (e.g. create KG nodes instead).
        Always called from within the run loop.
        """
        client.store(
            workspace_id=event.workspace_id,
            content=event.content,
            summary=event.summary or event.content[:200],
            memory_type=event.memory_type or "experience",
            peer_id=event.peer_id or "connector",
            source_session_id=event.session_id or "",
        )

    def run(
        self,
        client: Any,
        *,
        interval_secs: int = 300,
        max_per_tick: int = 10,
        stop_after: int | None = None,
    ) -> None:
        """Continuous poll loop.

        Args:
            client: A ``spacetime_memory.Client`` instance.
            interval_secs: Seconds between polls.
            max_per_tick: Max events to process per poll.
            stop_after: If set, run this many ticks then return.
        """
        ticks = 0
        while stop_after is None or ticks < stop_after:
            try:
                events = self.poll()[:max_per_tick]
                for ev in events:
                    try:
                        self.on_event(ev, client)
                    except Exception as e:
                        print(f"  [event error] {e}")
                if events:
                    print(f"  polled {len(events)} events")
            except Exception as e:
                print(f"  [poll error] {e}")

            ticks += 1
            if stop_after is not None and ticks >= stop_after:
                break
            time.sleep(interval_secs)


# ── Event data ──────────────────────────────────────────────────────


@dataclass
class Event:
    """A single event from a connector."""

    content: str
    workspace_id: str = ""
    summary: str = ""
    memory_type: str = "experience"
    peer_id: str = "connector"
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ── RSS Feed Connector ──────────────────────────────────────────────


class RssFeedConnector(Connector):
    """Poll an RSS/Atom feed and store entries as memories.

    Usage::

        client = Client()
        connector = RssFeedConnector("https://example.com/feed.xml", workspace_id="...")
        connector.run(client, interval_secs=600)
    """

    def __init__(
        self,
        feed_url: str,
        workspace_id: str,
        peer_id: str = "rss-bot",
    ):
        self.feed_url = feed_url
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set()

    def poll(self) -> list[Event]:
        """Fetch the feed and return new (unseen) entries as Events."""
        import feedparser  # optional dep; pip install feedparser

        parsed = feedparser.parse(self.feed_url)
        events: list[Event] = []

        for entry in parsed.entries[:10]:  # max 10 per poll
            entry_id = entry.get("id") or entry.get("link", "")
            if entry_id in self._seen:
                continue
            self._seen.add(entry_id)

            title = entry.get("title", "")
            content = entry.get("summary", entry.get("description", ""))
            link = entry.get("link", "")

            full = f"{title}\n\n{content}\n\nSource: {link}"
            events.append(Event(
                content=full,
                workspace_id=self.workspace_id,
                summary=title,
                memory_type="experience",
                peer_id=self.peer_id,
            ))

        return events


# ── GitHub Connector ────────────────────────────────────────────────


class GitHubConnector(Connector):
    """Poll GitHub API for public events from a user.

    Queries ``/users/{username}/events`` and supports pagination up to
    30 events per poll.  Deduplicates by event ID.

    Usage::

        connector = GitHubConnector(
            token="ghp_...",
            username="octocat",
            workspace_id="ws-1",
        )
        connector.run(client, interval_secs=600)
    """

    def __init__(
        self,
        token: str,
        username: str,
        workspace_id: str,
        peer_id: str = "github-bot",
    ):
        self.token = token
        self.username = username
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set()

    def poll(self) -> list[Event]:
        """Fetch user events from the GitHub API and return new Events."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "spacetime-memory-connector",
        }
        url: str | None = (
            f"https://api.github.com/users/{self.username}/events"
        )

        events: list[Event] = []
        fetched = 0

        with httpx.Client() as client:
            while url and fetched < 30:
                try:
                    resp = client.get(url, headers=headers, timeout=30)
                except httpx.RequestError as e:
                    print(f"  [GitHub HTTP error] {e}")
                    break

                if resp.status_code == 403:
                    print("  [GitHub] Rate limited or forbidden")
                    break
                if resp.status_code == 404:
                    print(f"  [GitHub] User '{self.username}' not found")
                    break
                if resp.status_code != 200:
                    print(
                        f"  [GitHub] Unexpected status {resp.status_code}"
                    )
                    break

                data = resp.json()
                if not data:
                    break

                for item in data:
                    event_id = str(item.get("id", ""))
                    if event_id in self._seen:
                        continue
                    self._seen.add(event_id)
                    fetched += 1

                    event_type: str = item.get("type", "UnknownEvent")
                    repo_name: str = (
                        item.get("repo", {}).get("name", "unknown")
                    )
                    actor: str = (
                        item.get("actor", {}).get("login", self.username)
                    )
                    created_at: str = item.get("created_at", "")
                    payload: dict[str, Any] = item.get("payload", {})

                    content = self._format_event(
                        event_type, actor, repo_name, payload, created_at,
                    )
                    summary = self._summarize_event(event_type, repo_name)

                    events.append(Event(
                        content=content,
                        workspace_id=self.workspace_id,
                        summary=summary,
                        memory_type="experience",
                        peer_id=self.peer_id,
                        metadata={
                            "source": "github",
                            "event_type": event_type,
                            "repo": repo_name,
                        },
                    ))

                # Follow pagination via Link header
                link_header = resp.headers.get("Link", "")
                url = self._parse_next_link(link_header)

        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_next_link(link_header: str) -> str | None:
        """Extract the URL for the next page from a Link header."""
        if not link_header:
            return None
        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                start = part.find("<")
                end = part.find(">")
                if start != -1 and end != -1:
                    return part[start + 1 : end]
        return None

    @staticmethod
    def _format_event(
        event_type: str,
        actor: str,
        repo: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> str:
        """Format a GitHub event into a readable text description."""
        if event_type == "PushEvent":
            commits = payload.get("commits", [])
            ref = payload.get("ref", "").replace("refs/heads/", "")
            lines = [f"{actor} pushed to {ref} in {repo}"]
            for c in commits[:5]:
                msg = c.get("message", "").split("\n")[0]
                lines.append(f"  - {msg}")
            if len(commits) > 5:
                lines.append(f"  ... and {len(commits) - 5} more commits")
            return "\n".join(lines) + f"\nDate: {created_at}"

        elif event_type == "IssuesEvent":
            action = payload.get("action", "opened")
            issue = payload.get("issue", {})
            title = issue.get("title", "")
            number = issue.get("number", "")
            url = issue.get("html_url", "")
            return (
                f"{actor} {action} issue #{number} in {repo}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Date: {created_at}"
            )

        elif event_type == "CreateEvent":
            ref_type = payload.get("ref_type", "unknown")
            ref_name = payload.get("ref", "")
            if ref_type == "branch":
                desc = f"branch '{ref_name}'"
            else:
                desc = ref_type
            return f"{actor} created {desc} in {repo}\nDate: {created_at}"

        elif event_type == "WatchEvent":
            action = payload.get("action", "started")
            return f"{actor} {action} watching {repo}\nDate: {created_at}"

        elif event_type == "ForkEvent":
            forkee = payload.get("forkee", {})
            fork_name = forkee.get("full_name", "unknown")
            return (
                f"{actor} forked {repo} to {fork_name}\n"
                f"Date: {created_at}"
            )

        elif event_type == "PullRequestEvent":
            action = payload.get("action", "opened")
            pr = payload.get("pull_request", {})
            title = pr.get("title", "")
            number = pr.get("number", "")
            url = pr.get("html_url", "")
            return (
                f"{actor} {action} PR #{number} in {repo}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Date: {created_at}"
            )

        elif event_type == "IssueCommentEvent":
            action = payload.get("action", "created")
            issue = payload.get("issue", {})
            number = issue.get("number", "")
            return (
                f"{actor} {action} comment on issue #{number} in {repo}\n"
                f"Date: {created_at}"
            )

        else:
            return (
                f"{actor} triggered {event_type} in {repo}\n"
                f"Date: {created_at}"
            )

    @staticmethod
    def _summarize_event(event_type: str, repo: str) -> str:
        """Generate a short summary line for the event."""
        summaries = {
            "PushEvent": f"Pushed to {repo}",
            "IssuesEvent": f"Issue activity in {repo}",
            "CreateEvent": f"Created reference in {repo}",
            "WatchEvent": f"Starred {repo}",
            "ForkEvent": f"Forked {repo}",
            "PullRequestEvent": f"PR activity in {repo}",
            "IssueCommentEvent": f"Comment on issue in {repo}",
        }
        return summaries.get(event_type, f"Activity in {repo}")


# ── Twitter/X Connector ─────────────────────────────────────────────


class TwitterConnector(Connector):
    """Poll Twitter/X API v2 for tweets from a user or list.

    Provide *either* ``user_id`` (for ``/2/users/{id}/tweets``) *or*
    ``list_id`` (for ``/2/lists/{id}/tweets``).  Deduplicates by tweet
    ID and handles rate-limits gracefully.

    Usage::

        # By user ID
        connector = TwitterConnector(
            bearer_token="AAAA...",
            user_id="123456789",
            workspace_id="ws-1",
        )

        # By list ID
        connector = TwitterConnector(
            bearer_token="AAAA...",
            list_id="123456789",
            workspace_id="ws-1",
        )
    """

    def __init__(
        self,
        bearer_token: str,
        workspace_id: str,
        user_id: str | None = None,
        list_id: str | None = None,
        peer_id: str = "twitter-bot",
    ):
        if not user_id and not list_id:
            raise ValueError("Either user_id or list_id must be provided")
        self.bearer_token = bearer_token
        self.user_id = user_id
        self.list_id = list_id
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set()

    def poll(self) -> list[Event]:
        """Fetch recent tweets and return new Events."""
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": "spacetime-memory-connector",
        }

        if self.user_id:
            url = (
                f"https://api.twitter.com/2/users/{self.user_id}/tweets"
            )
        else:
            url = (
                f"https://api.twitter.com/2/lists/{self.list_id}/tweets"
            )

        params = {
            "max_results": 30,
            "tweet.fields": "created_at,author_id",
        }

        events: list[Event] = []

        with httpx.Client() as client:
            try:
                resp = client.get(
                    url, headers=headers, params=params, timeout=30,
                )
            except httpx.RequestError as e:
                print(f"  [Twitter HTTP error] {e}")
                return events

            if resp.status_code == 429:
                print("  [Twitter] Rate limited")
                return events
            if resp.status_code == 401:
                print(
                    "  [Twitter] Unauthorized — check bearer token"
                )
                return events
            if resp.status_code != 200:
                print(
                    f"  [Twitter] Unexpected status {resp.status_code}:"
                    f" {resp.text[:200]}"
                )
                return events

            data = resp.json()
            tweets = data.get("data", [])
            if not tweets:
                return events

            for tweet in tweets:
                tweet_id: str = tweet.get("id", "")
                if tweet_id in self._seen:
                    continue
                self._seen.add(tweet_id)

                text: str = tweet.get("text", "")
                author_id: str = tweet.get("author_id", "")
                created_at: str = tweet.get("created_at", "")

                content = text
                if created_at:
                    content = f"{text}\n\nDate: {created_at}"

                events.append(Event(
                    content=content,
                    workspace_id=self.workspace_id,
                    summary=text[:200],
                    memory_type="experience",
                    peer_id=self.peer_id,
                    metadata={
                        "source": "twitter",
                        "tweet_id": tweet_id,
                        "author_id": author_id,
                    },
                ))

        return events


# ── Webhook Connector ───────────────────────────────────────────────


class WebhookConnector(Connector):
    """Receive events via HTTP webhook.

    This connector does **not** poll.  Instead, call ``handle()`` from
    your HTTP handler to process incoming POST data.

    Generic field mapping (first match wins):

    * content ← ``body["content"]`` | ``body["text"]`` | ``body["message"]``
    * summary ← ``body["summary"]`` | ``body["title"]`` | content[:200]
    * metadata ← the full body dict

    If ``secret`` is provided, requests are verified with HMAC-SHA256
    (supports ``X-Hub-Signature-256``, ``X-Signature-Sha256``, and
    ``X-Webhook-Signature`` headers).

    Usage (FastAPI example)::

        connector = WebhookConnector(
            path="/webhook",
            workspace_id="ws-1",
            secret="my-hmac-secret",
        )

        @app.post("/webhook")
        async def webhook(request: Request):
            body = await request.json()
            events = connector.handle(body, dict(request.headers))
            # persist events via client or registry...
    """

    def __init__(
        self,
        path: str,
        workspace_id: str,
        peer_id: str = "webhook",
        secret: str | None = None,
    ):
        self.path = path
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self.secret = secret

    def poll(self) -> list[Event]:
        """Not applicable for WebhookConnector — returns an empty list."""
        return []

    def handle(
        self,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> list[Event]:
        """Process an incoming webhook payload and return Events.

        Args:
            body: The parsed JSON body of the webhook request.
            headers: Optional HTTP headers (used for HMAC verification).

        Returns:
            A list containing zero or one ``Event`` derived from the body.
        """
        if self.secret:
            self._verify_hmac(body, headers or {})

        # Determine content from common fields
        if isinstance(body, dict):
            content = (
                body.get("content")
                or body.get("text")
                or body.get("message")
                or str(body)
            )
            summary = (
                body.get("summary")
                or body.get("title")
                or str(content)[:200]
            )
            metadata = dict(body)
        else:
            content = str(body)
            summary = content[:200]
            metadata = {"raw": body, "source": "webhook"}

        metadata.setdefault("source", "webhook")
        metadata.setdefault("path", self.path)

        return [
            Event(
                content=str(content),
                workspace_id=self.workspace_id,
                summary=str(summary)[:200],
                memory_type="experience",
                peer_id=self.peer_id,
                metadata=metadata,
            )
        ]

    def _verify_hmac(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Verify HMAC-SHA256 signature from headers.

        Checks for the signature in any of these header names (first
        match wins):

        - ``X-Hub-Signature-256`` (GitHub-style ``sha256=...``)
        - ``X-Signature-Sha256``
        - ``X-Webhook-Signature``

        Raises:
            ValueError: If the signature is missing or does not match.
        """
        import json

        assert self.secret is not None  # type-narrowing guard

        # Check common header names for the signature
        signature = (
            headers.get("x-hub-signature-256")
            or headers.get("x-signature-sha256")
            or headers.get("x-webhook-signature")
            or ""
        )

        if not signature:
            raise ValueError(
                "HMAC verification failed: no signature header found"
            )

        # Handle both "sha256=..." and raw hex formats
        if signature.startswith("sha256="):
            signature = signature[7:]

        body_bytes = json.dumps(
            body, separators=(",", ":"), sort_keys=True,
        ).encode()
        expected = hmac.new(
            self.secret.encode(),
            body_bytes,
            "sha256",
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            raise ValueError(
                "HMAC verification failed: signature mismatch"
            )


# ── Connector Registry ──────────────────────────────────────────────


class ConnectorRegistry:
    """A registry for managing multiple connectors.

    Usage::

        registry = ConnectorRegistry()
        registry.register("github", github_connector)
        registry.register("rss", rss_connector)
        all_events = registry.poll_all()
    """

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, name: str, connector: Connector) -> None:
        """Register a connector under a human-friendly name."""
        self._connectors[name] = connector

    def unregister(self, name: str) -> None:
        """Remove a registered connector by name."""
        self._connectors.pop(name, None)

    def get(self, name: str) -> Connector | None:
        """Get a registered connector by name."""
        return self._connectors.get(name)

    def list(self) -> dict[str, Connector]:
        """Return a copy of the registered connectors dict."""
        return dict(self._connectors)

    def poll_all(self) -> dict[str, list[Event]]:
        """Call ``poll()`` on every registered connector.

        Errors from individual connectors are caught and logged; they
        do not prevent other connectors from being polled.

        Returns:
            A dict mapping connector names to their event lists.
        """
        results: dict[str, list[Event]] = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = connector.poll()
            except Exception as e:
                print(f"  [registry error] {name}: {e}")
                results[name] = []
        return results
