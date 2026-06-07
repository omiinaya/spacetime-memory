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


# ── Slack Connector ──────────────────────────────────────────────────


class SlackConnector(Connector):
    """Poll a Slack workspace for recent messages via Slack Web API.

    Queries ``conversations.history`` for each configured channel.
    Deduplicates by message timestamp (``ts``) and handles rate
    limiting via the ``Retry-After`` header.

    Usage::

        connector = SlackConnector(
            token="xoxb-...",
            channel_ids=["C123", "C456"],
            workspace_id="ws-1",
        )
        connector.run(client, interval_secs=60)
    """

    BASE_URL = "https://slack.com/api"

    def __init__(
        self,
        token: str,
        channel_ids: list[str],
        workspace_id: str,
        peer_id: str = "slack-bot",
    ):
        self.token = token
        self.channel_ids = channel_ids
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set()
        self._channel_names: dict[str, str] = {}

    def poll(self) -> list[Event]:
        events: list[Event] = []

        with httpx.Client() as client:
            for channel_id in self.channel_ids:
                channel_name = self._get_channel_name(
                    client, channel_id
                )
                self._channel_names[channel_id] = channel_name

                url = f"{self.BASE_URL}/conversations.history"
                params = {"channel": channel_id, "limit": 30}

                try:
                    resp = client.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.token}",
                        },
                        params=params,
                        timeout=30,
                    )
                except httpx.RequestError as e:
                    print(
                        f"  [Slack HTTP error]"
                        f" channel={channel_id}: {e}"
                    )
                    continue

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = int(
                        resp.headers.get("Retry-After", 5)
                    )
                    print(
                        f"  [Slack] Rate limited on"
                        f" {channel_id}, retry after {retry_after}s"
                    )
                    continue

                if resp.status_code != 200:
                    print(
                        f"  [Slack] Unexpected status"
                        f" {resp.status_code} on {channel_id}"
                    )
                    continue

                data = resp.json()
                if not data.get("ok"):
                    print(
                        f"  [Slack] API error on {channel_id}:"
                        f" {data.get('error', 'unknown')}"
                    )
                    continue

                messages = data.get("messages", [])
                for msg in messages:
                    msg_ts = msg.get("ts", "")
                    if msg_ts in self._seen:
                        continue
                    self._seen.add(msg_ts)

                    text = msg.get("text", "")
                    subtype = msg.get("subtype", "")

                    # Skip bot messages and channel join/leave noise
                    if subtype in ("channel_join", "channel_leave"):
                        continue

                    channel_name = self._channel_names.get(
                        channel_id, channel_id
                    )
                    events.append(Event(
                        content=text,
                        workspace_id=self.workspace_id,
                        summary=text[:200],
                        memory_type="experience",
                        peer_id=self.peer_id,
                        metadata={
                            "source": "slack",
                            "channel": channel_name,
                            "channel_id": channel_id,
                            "ts": msg_ts,
                            "user": msg.get("user", ""),
                            "subtype": subtype,
                        },
                    ))

        return events

    def _get_channel_name(
        self, client: httpx.Client, channel_id: str,
    ) -> str:
        """Look up the human-friendly name for a channel."""
        try:
            resp = client.get(
                f"{self.BASE_URL}/conversations.info",
                headers={
                    "Authorization": f"Bearer {self.token}",
                },
                params={"channel": channel_id},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    channel_info = data.get("channel", {})
                    return channel_info.get("name", channel_id)
        except Exception:
            pass
        return channel_id


# ── Discord Connector ────────────────────────────────────────────────


class DiscordConnector(Connector):
    """Poll a Discord channel for recent messages via Discord REST API.

    Queries ``/channels/{id}/messages`` for each configured channel.
    Deduplicates by message ID and handles rate limiting.

    Usage::

        connector = DiscordConnector(
            token="MTE...",
            channel_ids=["123", "456"],
            workspace_id="ws-1",
        )
        connector.run(client, interval_secs=60)
    """

    BASE_URL = "https://discord.com/api/v10"

    def __init__(
        self,
        token: str,
        channel_ids: list[str],
        workspace_id: str,
        peer_id: str = "discord-bot",
    ):
        self.token = token
        self.channel_ids = channel_ids
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set()

    def poll(self) -> list[Event]:
        events: list[Event] = []
        headers = {
            "Authorization": f"Bot {self.token}",
            "User-Agent": "spacetime-memory-connector/1.0",
        }

        with httpx.Client() as client:
            for channel_id in self.channel_ids:
                url = (
                    f"{self.BASE_URL}"
                    f"/channels/{channel_id}/messages"
                )
                params = {"limit": 50}

                try:
                    resp = client.get(
                        url,
                        headers=headers,
                        params=params,
                        timeout=30,
                    )
                except httpx.RequestError as e:
                    print(
                        f"  [Discord HTTP error]"
                        f" channel={channel_id}: {e}"
                    )
                    continue

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = resp.json().get(
                        "retry_after", 5.0
                    )
                    print(
                        f"  [Discord] Rate limited on"
                        f" {channel_id}, retry after {retry_after}s"
                    )
                    continue

                if resp.status_code == 403:
                    print(
                        f"  [Discord] Forbidden on channel"
                        f" {channel_id} — check bot permissions"
                    )
                    continue

                if resp.status_code != 200:
                    print(
                        f"  [Discord] Unexpected status"
                        f" {resp.status_code} on {channel_id}"
                    )
                    continue

                messages = resp.json()
                for msg in messages:
                    msg_id = msg.get("id", "")
                    if msg_id in self._seen:
                        continue
                    self._seen.add(msg_id)

                    content = msg.get("content", "")
                    author = msg.get("author", {})
                    author_name = author.get("username", "unknown")
                    timestamp = msg.get("timestamp", "")

                    events.append(Event(
                        content=content,
                        workspace_id=self.workspace_id,
                        summary=content[:200],
                        memory_type="experience",
                        peer_id=self.peer_id,
                        metadata={
                            "source": "discord",
                            "channel_id": channel_id,
                            "message_id": msg_id,
                            "author": author_name,
                            "timestamp": timestamp,
                        },
                    ))

        return events


# ── Notion Connector ─────────────────────────────────────────────────


class NotionConnector(Connector):
    """Poll a Notion database for new or updated pages via Notion API.

    Queries ``/databases/{database_id}/query`` (POST) and extracts
    title / content from page properties.  Deduplicates by page ID.

    Usage::

        connector = NotionConnector(
            token="secret_...",
            database_id="abc123",
            workspace_id="ws-1",
        )
        connector.run(client, interval_secs=300)
    """

    BASE_URL = "https://api.notion.com/v1"

    def __init__(
        self,
        token: str,
        database_id: str,
        workspace_id: str,
        peer_id: str = "notion-bot",
    ):
        self.token = token
        self.database_id = database_id
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set()

    def poll(self) -> list[Event]:
        events: list[Event] = []
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
            "User-Agent": "spacetime-memory-connector/1.0",
        }
        url = (
            f"{self.BASE_URL}"
            f"/databases/{self.database_id}/query"
        )
        payload = {"page_size": 50}

        with httpx.Client() as client:
            try:
                resp = client.post(
                    url, headers=headers, json=payload, timeout=30,
                )
            except httpx.RequestError as e:
                print(f"  [Notion HTTP error] {e}")
                return events

            # Handle rate limiting
            if resp.status_code == 429:
                print("  [Notion] Rate limited")
                return events

            if resp.status_code == 401:
                print(
                    "  [Notion] Unauthorised — check integration token"
                )
                return events

            if resp.status_code != 200:
                print(
                    f"  [Notion] Unexpected status {resp.status_code}"
                )
                return events

            data = resp.json()
            results = data.get("results", [])
            for page in results:
                page_id = page.get("id", "")
                if page_id in self._seen:
                    continue
                self._seen.add(page_id)

                props = page.get("properties", {})
                title_text = self._extract_title(props)
                body_text = self._extract_body(props)

                content = title_text
                if body_text:
                    content = f"{title_text}\n\n{body_text}"

                events.append(Event(
                    content=content,
                    workspace_id=self.workspace_id,
                    summary=title_text[:200],
                    memory_type="experience",
                    peer_id=self.peer_id,
                    metadata={
                        "source": "notion",
                        "page_id": page_id,
                        "database_id": self.database_id,
                        "url": page.get("url", ""),
                        "created_time": page.get(
                            "created_time", ""
                        ),
                        "last_edited_time": page.get(
                            "last_edited_time", ""
                        ),
                    },
                ))

        return events

    @staticmethod
    def _extract_title(props: dict) -> str:
        """Extract a title string from Notion page properties."""
        # Try common title property types
        for prop in props.values():
            prop_type = prop.get("type", "")
            if prop_type == "title":
                parts = prop.get("title", [])
                if parts:
                    return "".join(
                        p.get("plain_text", "") for p in parts
                    )
            if prop_type == "rich_text":
                parts = prop.get("rich_text", [])
                if parts:
                    return "".join(
                        p.get("plain_text", "") for p in parts
                    )
        # Fallback: use the first text property we find
        for key, prop in props.items():
            prop_type = prop.get("type", "")
            if prop_type in ("title", "rich_text"):
                parts = prop.get(prop_type, [])
                if parts:
                    return "".join(
                        p.get("plain_text", "") for p in parts
                    )
        return "Untitled"

    @staticmethod
    def _extract_body(props: dict) -> str:
        """Extract body content from Notion page properties (non-title)."""
        parts: list[str] = []
        for key, prop in props.items():
            prop_type = prop.get("type", "")
            if prop_type == "rich_text":
                items = prop.get("rich_text", [])
                text = "".join(
                    p.get("plain_text", "") for p in items
                )
                if text.strip():
                    parts.append(f"{key}: {text}")
            elif prop_type == "select":
                select = prop.get("select")
                if select:
                    parts.append(
                        f"{key}: {select.get('name', '')}"
                    )
            elif prop_type == "multi_select":
                mselects = prop.get("multi_select", [])
                names = [m.get("name", "") for m in mselects]
                if names:
                    parts.append(f"{key}: {', '.join(names)}")
            elif prop_type == "status":
                status = prop.get("status")
                if status:
                    parts.append(
                        f"{key}: {status.get('name', '')}"
                    )
            elif prop_type == "date":
                date = prop.get("date")
                if date:
                    parts.append(
                        f"{key}: {date.get('start', '')}"
                    )
            elif prop_type == "checkbox":
                parts.append(
                    f"{key}: {prop.get('checkbox', False)}"
                )
            elif prop_type == "number":
                val = prop.get("number")
                if val is not None:
                    parts.append(f"{key}: {val}")
            elif prop_type == "url":
                val = prop.get("url")
                if val:
                    parts.append(f"{key}: {val}")
            elif prop_type == "email":
                val = prop.get("email")
                if val:
                    parts.append(f"{key}: {val}")
            elif prop_type == "phone_number":
                val = prop.get("phone_number")
                if val:
                    parts.append(f"{key}: {val}")
        return "\n".join(parts)


# ── Org-mode Parser ──────────────────────────────────────────────────


class OrgModeParser(Connector):
    """Parse Emacs org-mode files and convert to memories / KG nodes.

    This connector is **not a poller** — it has a ``parse()`` method
    instead of ``poll()``.  Call ``parse()`` once to import the file.

    Parsing supports:

    * Headings (``*``, ``**``, …)
    * TODO states (``** TODO``, ``** DONE``)
    * Lists (``- item``)
    * Code blocks (``#+BEGIN_SRC`` / ``#+END_SRC``)
    * Properties drawers (``:PROPERTIES:``)
    * Tags (``:tag1:tag2:`` at end of heading lines)

    Usage::

        parser = OrgModeParser(
            file_path="/path/to/notes.org",
            workspace_id="ws-1",
        )
        events = parser.parse()
        for ev in events:
            client.store(...)
    """

    def __init__(
        self,
        file_path: str,
        workspace_id: str,
        peer_id: str = "org-parser",
    ):
        self.file_path = file_path
        self.workspace_id = workspace_id
        self.peer_id = peer_id

    def poll(self) -> list[Event]:
        """Not applicable for OrgModeParser — returns empty list."""
        return []

    def parse(self) -> list[Event]:
        """Read and parse the org-mode file, returning Events.

        Each top-level heading (``*``) becomes an Event.  Nested
        content under the heading is included in the event body.
        """
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(
                f"  [OrgMode] File not found: {self.file_path}"
            )
            return []
        except OSError as e:
            print(f"  [OrgMode] Error reading file: {e}")
            return []

        events: list[Event] = []
        sections = self._parse_sections(lines)

        for section in sections:
            heading_text = section["heading"]
            body_text = section["body"]
            outline_level = section["level"]
            todo_state = section["todo_state"]
            tags = section["tags"]

            content = heading_text
            if body_text:
                content = f"{heading_text}\n\n{body_text}"

            metadata = {
                "source": "org-mode",
                "file": self.file_path,
                "outline_level": outline_level,
                "tags": tags,
                "todo_state": todo_state,
            }

            events.append(Event(
                content=content,
                workspace_id=self.workspace_id,
                summary=heading_text[:200],
                memory_type="experience",
                peer_id=self.peer_id,
                metadata=metadata,
            ))

        return events

    def _parse_sections(
        self, lines: list[str],
    ) -> list[dict]:
        """Split org-mode lines into heading-anchored sections."""
        sections: list[dict] = []
        current: dict | None = None
        in_src_block = False
        in_props_drawer = False
        body_lines: list[str] = []

        for line in lines:
            stripped = line.rstrip("\n")

            # Track source blocks
            if stripped.startswith("#+BEGIN_SRC"):
                in_src_block = True
                if current is not None:
                    body_lines.append(stripped)
                continue
            if stripped.startswith("#+END_SRC"):
                in_src_block = False
                if current is not None:
                    body_lines.append(stripped)
                continue

            # Track properties drawers
            if stripped == ":PROPERTIES:":
                in_props_drawer = True
                continue
            if stripped == ":END:":
                in_props_drawer = False
                continue

            # Skip content inside source blocks or property drawers
            if in_src_block or in_props_drawer:
                continue

            # Detect heading
            heading_match = self._match_heading(stripped)
            if heading_match:
                # Finalise previous section
                if current is not None:
                    current["body"] = "\n".join(body_lines)
                    sections.append(current)

                # Start new section
                current = {
                    "heading": heading_match["text"],
                    "level": heading_match["level"],
                    "todo_state": heading_match["todo_state"],
                    "tags": heading_match["tags"],
                }
                body_lines = []
            else:
                # Body content line
                if current is not None:
                    # Skip comment lines
                    if stripped.startswith("# "):
                        continue
                    body_lines.append(stripped)

        # Finalise last section
        if current is not None:
            current["body"] = "\n".join(body_lines)
            sections.append(current)

        return sections

    @staticmethod
    def _match_heading(
        line: str,
    ) -> dict | None:
        """Test if a line is an org-mode heading.

        Returns a dict with keys ``text``, ``level``, ``todo_state``,
        ``tags`` if the line is a heading, else ``None``.
        """
        # Headings start with one or more *
        if not line.startswith("*"):
            return None

        # Count leading asterisks
        level = 0
        for ch in line:
            if ch == "*":
                level += 1
            else:
                break

        if level == 0:
            return None

        # Remainder after the asterisks
        rest = line[level:].strip()
        if not rest:
            return {
                "text": "(empty heading)",
                "level": level,
                "todo_state": "",
                "tags": [],
            }

        # Extract tags at end of line, e.g. ``:tag1:tag2:``
        tags: list[str] = []
        if rest.endswith(":"):
            # Tags are colon-surrounded words at end
            space_idx = rest.rfind(" ", 0, -1)
            maybe_tags = rest[space_idx + 1 :] if space_idx >= 0 else rest
            if (
                maybe_tags.startswith(":")
                and maybe_tags.count(":") >= 2
            ):
                tags = [
                    t
                    for t in maybe_tags.strip(":").split(":")
                    if t
                ]
                rest = rest[:space_idx].strip() if space_idx >= 0 else ""

        # Extract TODO state (TODO, DONE, or any known keyword)
        todo_state = ""
        keywords = [
            "TODO",
            "DONE",
            "IN-PROGRESS",
            "BLOCKED",
            "CANCELLED",
            "DEFERRED",
            "WAITING",
        ]
        for kw in keywords:
            if rest.startswith(kw) and (
                len(rest) == len(kw) or rest[len(kw)] in (" ", "\t")
            ):
                todo_state = kw
                rest = rest[len(kw):].strip()
                break

        return {
            "text": rest,
            "level": level,
            "todo_state": todo_state,
            "tags": tags,
        }
