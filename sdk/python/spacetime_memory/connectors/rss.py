import feedparser
from .base import Connector, Event
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
        *,
        cursor_dir: str | None = None,
    ):
        super().__init__(cursor_dir=cursor_dir)
        self.feed_url = feed_url
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set(
            self._cursor.get("seen_ids", [])
        )

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

        # Persist cursor
        self._cursor["seen_ids"] = list(self._seen)
        self._save_cursor()

        return events


# ── GitHub Connector ────────────────────────────────────────────────


