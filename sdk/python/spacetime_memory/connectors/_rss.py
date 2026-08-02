"""RSS/Atom feed connector for spacetime-memory.

``connectors._rss`` provides ``RssFeedConnector``, a sync connector that
polls an RSS or Atom feed URL and stores entries as memories.
"""

from __future__ import annotations

import feedparser

from ._base import SyncConnector
from ._types import Event


class RssFeedConnector(SyncConnector):
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
        *,
        cursor_dir: str | None = None,
    ):
        """Initialise the RSS/Atom feed connector.

        Args:
            feed_url: URL of the RSS or Atom feed to poll.
            workspace_id: Target workspace UUID.
            peer_id: Name for the memory source (default ``\"rss-bot\"``).
            cursor_dir: Optional directory for cursor persistence.
        """
        super().__init__(cursor_dir=cursor_dir)
        self.feed_url = feed_url
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set(self._cursor.get("seen_ids", []))

    def poll(self) -> list[Event]:
        """Fetch the feed and return new (unseen) entries as Events."""

        try:
            parsed = feedparser.parse(self.feed_url)
        except Exception:
            self._log.exception("Failed to parse feed %s", self.feed_url)
            return []

        # feedparser v6.x never raises exceptions; errors set bozo=True
        if getattr(parsed, "bozo", False) or not getattr(parsed, "entries", None):
            self._log.warning("Feed parse error (bozo): %s", getattr(parsed, "bozo_exception", None))
            return []

        entries = parsed.entries
        events: list[Event] = []

        for entry in entries[:10]:  # max 10 per poll
            entry_id = entry.get("id") or entry.get("link", "")
            if entry_id in self._seen:
                continue
            self._seen.add(entry_id)

            title = entry.get("title", "")
            content = entry.get("summary", entry.get("description", ""))
            link = entry.get("link", "")

            full = f"{title}\n\n{content}\n\nSource: {link}"
            events.append(
                Event(
                    content=full,
                    workspace_id=self.workspace_id,
                    summary=title,
                    memory_type="experience",
                    peer_id=self.peer_id,
                )
            )

        # Persist cursor
        self._cursor["seen_ids"] = list(self._seen)
        self._save_cursor()

        return events
