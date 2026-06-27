import httpx
from .base import Connector, Event


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
            url = f"https://api.twitter.com/2/users/{self.user_id}/tweets"
        else:
            url = f"https://api.twitter.com/2/lists/{self.list_id}/tweets"

        params = {
            "max_results": 30,
            "tweet.fields": "created_at,author_id",
        }

        events: list[Event] = []

        with httpx.Client() as client:
            try:
                resp = client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
            except httpx.RequestError as e:
                print(f"  [Twitter HTTP error] {e}")
                return events

            if resp.status_code == 429:
                print("  [Twitter] Rate limited")
                return events
            if resp.status_code == 401:
                print("  [Twitter] Unauthorized — check bearer token")
                return events
            if resp.status_code != 200:
                print(f"  [Twitter] Unexpected status {resp.status_code}: {resp.text[:200]}")
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

                events.append(
                    Event(
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
                    )
                )

        return events


# ── Webhook Connector ───────────────────────────────────────────────
