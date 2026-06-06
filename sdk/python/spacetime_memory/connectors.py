"""Connector framework for spacetime-memory.

Connectors poll external data sources and persist them as memories or
KG nodes.  Each connector is a Python class that implements ``poll()``
and is run via a cron job or the CLI.

Built-in connectors:

* ``RssFeedConnector`` — poll an RSS/Atom feed URL, store entries as memories.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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
