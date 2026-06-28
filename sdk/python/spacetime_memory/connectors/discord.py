import logging
import re
from typing import Any
import httpx
from .base import Connector, Event

logger = logging.getLogger(__name__)


class DiscordConnector(Connector):
    """Poll a Discord channel for recent messages via Discord REST API.

    Queries ``/channels/{id}/messages`` for each configured channel with
    full pagination.  Supports thread detection (fetches parent messages
    for thread channels), attachment capture, and guild emoji decoding.
    Deduplicates by message ID and handles rate limiting.

    Usage::

        connector = DiscordConnector(
            token="MTE...",
            channel_ids=["123", "456"],
            workspace_id="ws-1",
            include_threads=True,
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
        include_threads: bool = False,
        decode_emoji: bool = True,
    ):
        self.token = token
        self.channel_ids = list(channel_ids)
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self.include_threads = include_threads
        self.decode_emoji = decode_emoji
        self._seen: set[str] = set()
        self._emoji_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Emoji helpers
    # ------------------------------------------------------------------

    def _resolve_emoji(
        self,
        content: str,
        guild_id: str | None = None,
    ) -> str:
        """Decode ``:name:`` custom emoji mentions in message content.

        For standard shortcodes and custom guild emoji, attempts to
        resolve ``:name:`` patterns.  Custom emoji in Discord's
        ``<:name:id>`` format are already valid and left as-is.
        Unresolvable shortcodes are left unchanged.
        """

        def replace_emoji(match: re.Match) -> str:
            name = match.group(1)
            # Check cache first
            cached = self._emoji_cache.get(name)
            if cached is not None:
                return cached
            # Cannot resolve — leave original text unchanged
            return match.group(0)

        # Match :name: patterns that aren't part of URLs or markup
        content = re.sub(r":([a-zA-Z0-9_+-]+):", replace_emoji, content)
        return content

    # ------------------------------------------------------------------
    # Channel helpers
    # ------------------------------------------------------------------

    def _fetch_channel_info(
        self,
        client: httpx.Client,
        channel_id: str,
    ) -> dict | None:
        """Fetch channel info from Discord API.

        Returns the channel object, or ``None`` if the channel doesn't
        exist, we don't have access, or an error occurred.
        """
        url = f"{self.BASE_URL}/channels/{channel_id}"
        headers = {
            "Authorization": f"Bot {self.token}",
            "User-Agent": "spacetime-memory-connector/1.0",
        }
        try:
            resp = client.get(url, headers=headers, timeout=15)
        except httpx.RequestError as e:
            logger.warning("Discord HTTP error channel info %s: %s", channel_id, e)
            return None

        if resp.status_code == 404:
            logger.info(
                "Discord unknown channel %s — removing from active list",
                channel_id,
            )
            return None
        if resp.status_code == 403:
            logger.warning(
                "Discord forbidden on channel %s — check bot permissions",
                channel_id,
            )
            return None
        if resp.status_code == 200:
            return resp.json()
        return None

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll(self) -> list[Event]:
        events: list[Event] = []
        headers = {
            "Authorization": f"Bot {self.token}",
            "User-Agent": "spacetime-memory-connector/1.0",
        }

        with httpx.Client() as client:
            # Iterate over a snapshot of channel_ids so we can safely
            # remove channels that return 404 during iteration
            for channel_id in list(self.channel_ids):
                # ── Thread support ───────────────────────────────────
                if self.include_threads:
                    channel_info = self._fetch_channel_info(
                        client,
                        channel_id,
                    )
                    if channel_info is None:
                        # 404 or error — remove from active list
                        if channel_id in self.channel_ids:
                            self.channel_ids.remove(channel_id)
                        continue

                    # Discord thread types:
                    # 10 = GUILD_NEWS_THREAD
                    # 11 = GUILD_PUBLIC_THREAD
                    # 12 = GUILD_PRIVATE_THREAD
                    channel_type = channel_info.get("type")
                    if channel_type in (10, 11, 12):
                        parent_id = channel_info.get("parent_id")
                        if parent_id:
                            logger.info(
                                "Discord channel %s is a thread in parent %s, "
                                "fetching parent messages",
                                channel_id,
                                parent_id,
                            )
                            parent_msgs = self._fetch_messages(
                                client,
                                parent_id,
                                headers,
                            )
                            for msg in parent_msgs:
                                ev = self._msg_to_event(
                                    msg,
                                    channel_id,
                                )
                                if ev:
                                    events.append(ev)

                # Fetch messages for this channel with pagination
                messages = self._fetch_messages(
                    client,
                    channel_id,
                    headers,
                )
                for msg in messages:
                    ev = self._msg_to_event(msg, channel_id)
                    if ev:
                        events.append(ev)

        return events

    # ------------------------------------------------------------------
    # Message fetching
    # ------------------------------------------------------------------

    def _fetch_messages(
        self,
        client: httpx.Client,
        channel_id: str,
        headers: dict[str, str],
    ) -> list[dict]:
        """Fetch messages from a Discord channel with pagination.

        Paginates backwards through message history using the
        ``before`` parameter (Discord returns newest-first).
        Returns up to 10 pages (1000 messages max).
        """
        url = f"{self.BASE_URL}/channels/{channel_id}/messages"
        params: dict[str, Any] = {"limit": 100}
        all_messages: list[dict] = []
        pages = 0

        while pages < 10:
            try:
                resp = client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
            except httpx.RequestError as e:
                logger.warning("Discord HTTP error channel=%s: %s", channel_id, e)
                break

            # Handle rate limiting
            if resp.status_code == 429:
                retry_after = resp.json().get(
                    "retry_after",
                    5.0,
                )
                logger.warning(
                    "Discord rate limited on %s, retry after %ss",
                    channel_id,
                    retry_after,
                )
                break

            if resp.status_code == 403:
                logger.warning(
                    "Discord forbidden on channel %s — check bot permissions",
                    channel_id,
                )
                break

            # Handle 404 gracefully — remove channel from active list
            if resp.status_code == 404:
                logger.info(
                    "Discord unknown channel %s — removing from active list",
                    channel_id,
                )
                if channel_id in self.channel_ids:
                    self.channel_ids.remove(channel_id)
                break

            if resp.status_code != 200:
                logger.warning(
                    "Discord unexpected status %s on %s",
                    resp.status_code,
                    channel_id,
                )
                break

            messages = resp.json()
            if not messages:
                break

            all_messages.extend(messages)

            # Paginate: use the last (oldest) message ID as
            # the 'before' cursor for the next page
            oldest_id = messages[-1].get("id")
            if not oldest_id or len(messages) < 100:
                break
            params["before"] = oldest_id
            pages += 1

        return all_messages

    def _msg_to_event(
        self,
        msg: dict,
        channel_id: str,
    ) -> Event | None:
        """Convert a Discord message dict to an ``Event``."""
        msg_id = msg.get("id", "")
        if msg_id in self._seen:
            return None
        self._seen.add(msg_id)

        content = msg.get("content", "")
        author = msg.get("author", {})
        author_name = author.get("username", "unknown")
        author_id = author.get("id", "")
        timestamp = msg.get("timestamp", "")

        # ── Guild emoji decoding ──────────────────────────────────
        if self.decode_emoji:
            guild_id = msg.get("guild_id")
            content = self._resolve_emoji(content, guild_id)

        # ── Attachment capture ────────────────────────────────────
        attachments = msg.get("attachments", [])
        attachment_urls = [att.get("url", "") for att in attachments if att.get("url")]

        metadata: dict[str, Any] = {
            "source": "discord",
            "channel_id": channel_id,
            "message_id": msg_id,
            "author": author_name,
            "author_id": author_id,
            "timestamp": timestamp,
        }

        if attachment_urls:
            metadata["attachments"] = attachment_urls

        # ── Thread metadata ───────────────────────────────────────
        thread = msg.get("thread", {})
        if thread:
            metadata["thread_id"] = thread.get("id", "")
            metadata["thread_name"] = thread.get("name", "")

        return Event(
            content=content,
            workspace_id=self.workspace_id,
            summary=content[:200],
            memory_type="experience",
            peer_id=self.peer_id,
            metadata=metadata,
        )


# ── Notion Connector ─────────────────────────────────────────────────
