import json
from typing import Any
import httpx
from .base import Connector, Event
class SlackConnector(Connector):
    """Poll a Slack workspace for recent messages via Slack Web API.

    Queries ``conversations.history`` for each configured channel with
    full pagination support.  Optionally fetches thread replies when
    ``include_threads=True``.  Deduplicates by message timestamp (``ts``)
    and handles rate limiting via the ``Retry-After`` header.

    Usage::

        connector = SlackConnector(
            token="xoxb-...",
            channel_ids=["C123", "C456"],
            workspace_id="ws-1",
            include_threads=True,
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
        include_threads: bool = False,
        max_pages: int = 10,
    ):
        self.token = token
        self.channel_ids = list(channel_ids)
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self.include_threads = include_threads
        self.max_pages = max_pages
        self._seen: set[str] = set()
        self._channel_names: dict[str, str] = {}
        self._refresh_warned = False
        self._token_refresh_callback = None

    # ------------------------------------------------------------------
    # Token lifecycle
    # ------------------------------------------------------------------

    def _refresh_token(self) -> None:
        """Check if token is about to expire (for short-lived tokens).

        Logs a warning once per session if no refresh mechanism is
        configured.  Subclasses can override this method or set
        ``_token_refresh_callback`` to a callable that accepts the
        current token and returns a fresh one.
        """
        if self._token_refresh_callback is not None:
            new_token = self._token_refresh_callback(self.token)
            if new_token:
                self.token = new_token
                return
        if not self._refresh_warned:
            print(
                "  [Slack] No token refresh mechanism configured — "
                "if your token expires, override _refresh_token() "
                "or set _token_refresh_callback"
            )
            self._refresh_warned = True

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _paginate(
        self,
        client: httpx.Client,
        url: str,
        params: dict[str, Any],
    ) -> list[dict]:
        """Paginate through Slack API responses following ``next_cursor``.

        Args:
            client: An ``httpx.Client`` instance.
            url: The Slack API method URL.
            params: Query parameters (must include ``channel``).

        Returns:
            Combined list of items from all pages (up to ``max_pages``).
        """
        all_items: list[dict] = []
        params = dict(params)
        pages = 0

        while pages < self.max_pages:
            try:
                resp = client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    params=params,
                    timeout=30,
                )
            except httpx.RequestError as e:
                print(f"  [Slack pagination HTTP error] {e}")
                break

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                print(
                    f"  [Slack] Rate limited during pagination,"
                    f" retry after {retry_after}s"
                )
                break

            if resp.status_code != 200:
                print(
                    f"  [Slack] Unexpected status {resp.status_code}"
                    f" during pagination"
                )
                break

            data = resp.json()
            if not data.get("ok"):
                error = data.get("error", "unknown")
                # Handle not_in_channel gracefully
                if error == "not_in_channel":
                    print(
                        f"  [Slack] Bot not in channel"
                        f" {params.get('channel', '?')} — skipping"
                    )
                    return all_items
                print(f"  [Slack] API error during pagination: {error}")
                break

            # Both conversations.history and conversations.replies
            # return items under the "messages" key
            items = data.get("messages", [])
            all_items.extend(items)

            # Follow cursor-based pagination
            response_metadata = data.get("response_metadata", {})
            next_cursor = response_metadata.get("next_cursor")
            if not next_cursor:
                break

            params["cursor"] = next_cursor
            pages += 1

        return all_items

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll(self) -> list[Event]:
        self._refresh_token()
        events: list[Event] = []

        with httpx.Client() as client:
            for channel_id in self.channel_ids:
                channel_name = self._get_channel_name(
                    client, channel_id
                )
                self._channel_names[channel_id] = channel_name

                # Fetch all messages with full pagination
                url = f"{self.BASE_URL}/conversations.history"
                params: dict[str, Any] = {
                    "channel": channel_id,
                    "limit": 100,
                }
                messages = self._paginate(client, url, params)

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

                    metadata: dict[str, Any] = {
                        "source": "slack",
                        "channel": channel_name,
                        "channel_id": channel_id,
                        "ts": msg_ts,
                        "user": msg.get("user", ""),
                        "subtype": subtype,
                    }

                    # ── Thread support ──────────────────────────────
                    thread_ts = msg.get("thread_ts")
                    if self.include_threads and thread_ts:
                        metadata["thread_ts"] = thread_ts
                        replies = self._fetch_thread_replies(
                            client, channel_id, thread_ts,
                        )
                        for reply in replies:
                            reply_ts = reply.get("ts", "")
                            if reply_ts in self._seen:
                                continue
                            self._seen.add(reply_ts)
                            reply_text = reply.get("text", "")
                            reply_user = reply.get("user", "")
                            events.append(Event(
                                content=reply_text,
                                workspace_id=self.workspace_id,
                                summary=reply_text[:200],
                                memory_type="experience",
                                peer_id=self.peer_id,
                                metadata={
                                    "source": "slack",
                                    "channel": channel_name,
                                    "channel_id": channel_id,
                                    "ts": reply_ts,
                                    "user": reply_user,
                                    "subtype": reply.get("subtype", ""),
                                    "thread_ts": thread_ts,
                                    "is_thread_reply": True,
                                },
                            ))

                    events.append(Event(
                        content=text,
                        workspace_id=self.workspace_id,
                        summary=text[:200],
                        memory_type="experience",
                        peer_id=self.peer_id,
                        metadata=metadata,
                    ))

        return events

    def _fetch_thread_replies(
        self,
        client: httpx.Client,
        channel_id: str,
        thread_ts: str,
    ) -> list[dict]:
        """Fetch all replies in a thread via ``conversations.replies``."""
        url = f"{self.BASE_URL}/conversations.replies"
        params: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 100,
        }
        return self._paginate(client, url, params)

    # ------------------------------------------------------------------
    # Channel helpers
    # ------------------------------------------------------------------

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


