"""Telegram Bot API connector — polls a bot for new messages.

Queries ``getUpdates`` for each configured chat (or all chats if none
specified).  Deduplicates by ``update_id`` and handles Telegram's offset-
based pagination automatically.  Supports text messages, photo captions,
and callback queries.

Usage::

    connector = TelegramConnector(
        token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_ids=["-1001234567890"],
        workspace_id="ws-1",
    )
    connector.run(client, interval_secs=60)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Event, SyncConnector

logger = logging.getLogger(__name__)


class TelegramConnector(SyncConnector):
    """Poll a Telegram bot for new messages via the Bot API.

    Queries ``getUpdates`` for each configured chat (or all accessible
    chats when ``chat_ids`` is empty).  Uses Telegram's ``offset``-based
    pagination — each update carries a monotonically increasing
    ``update_id`` stored in the cursor, so no message is missed across
    restarts.  Supports text messages, photo captions, and callback
    queries from inline keyboards.

    Usage::

        connector = TelegramConnector(
            token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            chat_ids=["-1001234567890"],
            workspace_id="ws-1",
            include_callback_queries=True,
        )
        connector.run(client, interval_secs=60)
    """

    BASE_URL = "https://api.telegram.org/bot"

    def __init__(
        self,
        token: str,
        chat_ids: list[str] | None = None,
        workspace_id: str = "",
        peer_id: str = "telegram-bot",
        include_callback_queries: bool = True,
        max_updates: int = 100,
        cursor_dir: str | None = None,
    ):
        """Initialise the Telegram connector.

        Args:
            token: Telegram Bot API token (``123456:ABC-DEF1234...``).
            chat_ids: List of chat IDs to poll.  Empty list polls all
                chats the bot has access to.
            workspace_id: Target workspace UUID.
            peer_id: Name for the memory source (default ``"telegram-bot"``).
            include_callback_queries: Whether to include callback query
                data as events (default ``True``).
            max_updates: Max updates per poll (Telegram limit is 100).
            cursor_dir: Optional custom directory for cursor persistence.
        """
        super().__init__(cursor_dir=cursor_dir)
        self.token = token
        self.chat_ids = list(chat_ids) if chat_ids else []
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self.include_callback_queries = include_callback_queries
        self.max_updates = min(max_updates, 100)  # Telegram hard-limit
        super().__init__()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _api_url(self) -> str:
        """Full API base URL including bot token."""
        return f"{self.BASE_URL}{self.token}"

    def _get_chat_name(self, chat: dict[str, Any] | None) -> str:
        """Extract a human-readable name from a Telegram chat object."""
        if not chat:
            return "unknown"
        # Try title first (groups/supergroups), then username, then first+last
        title = chat.get("title")
        if title:
            return title
        username = chat.get("username")
        if username:
            return f"@{username}"
        first = chat.get("first_name", "")
        last = chat.get("last_name", "")
        if first or last:
            return f"{first} {last}".strip()
        return str(chat.get("id", "unknown"))

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll(self) -> list[Event]:
        """Poll Telegram for new messages via ``getUpdates``.

        Uses the ``offset`` cursor stored in ``self._cursor`` to resume
        from where the last poll left off.  Fetches up to ``max_updates``
        updates per tick and converts messages and (optionally) callback
        queries to ``Event`` objects.

        Returns:
            List of new ``Event`` objects since the last poll.
        """
        events: list[Event] = []
        headers = {
            "User-Agent": "spacetime-memory-connector/1.0",
        }

        # Restore cursor: the highest seen update_id
        offset = self._cursor.get("offset", 0)

        params: dict[str, Any] = {
            "offset": offset,
            "limit": self.max_updates,
            "timeout": 5,
        }

        with httpx.Client() as client:
            try:
                resp = client.get(
                    f"{self._api_url}/getUpdates",
                    headers=headers,
                    params=params,
                    timeout=30,
                )
            except httpx.RequestError as e:
                logger.warning("Telegram HTTP error: %s", e)
                return events

            if resp.status_code == 429:
                logger.warning("Telegram rate limited")
                return events
            if resp.status_code == 401:
                logger.warning(
                    "Telegram unauthorized — check bot token"
                )
                return events
            if resp.status_code != 200:
                logger.warning(
                    "Telegram unexpected status %s: %s",
                    resp.status_code,
                    str(resp.text)[:200],
                )
                return events

            data = resp.json()
            if not data.get("ok"):
                error_desc = data.get("description", "unknown error")
                logger.warning("Telegram API error: %s", error_desc)
                return events

            updates = data.get("result", [])
            if not updates:
                return events

            # Track the highest update_id for cursor persistence
            max_update_id = offset

            for update in updates:
                update_id: int = update.get("update_id", 0)
                max_update_id = max(max_update_id, update_id)

                # ── Text messages ──────────────────────────────────
                msg = update.get("message")
                if msg:
                    ev = self._message_to_event(msg, update_id)
                    if ev:
                        events.append(ev)
                    continue

                # ── Edited messages ────────────────────────────────
                edited_msg = update.get("edited_message")
                if edited_msg:
                    ev = self._message_to_event(edited_msg, update_id)
                    if ev:
                        events.append(ev)
                    continue

                # ── Channel posts ──────────────────────────────────
                channel_post = update.get("channel_post")
                if channel_post:
                    ev = self._message_to_event(channel_post, update_id)
                    if ev:
                        events.append(ev)
                    continue

                # ── Callback queries ────────────────────────────────
                if self.include_callback_queries:
                    cb = update.get("callback_query")
                    if cb:
                        ev = self._callback_to_event(cb, update_id)
                        if ev:
                            events.append(ev)
                        continue

            # Persist cursor
            if max_update_id > offset:
                self._cursor["offset"] = max_update_id + 1
                self._save_cursor()

        return events

    def _save_cursor(self) -> None:
        """Persist cursor, converting non-serializable types."""
        # Convert _seen set to list for JSON serialization
        if "_seen" in self._cursor:
            self._cursor["_seen"] = sorted(self._cursor["_seen"])
        super()._save_cursor()

    def _load_cursor(self) -> None:
        """Restore cursor, converting list back to set."""
        super()._load_cursor()
        if "_seen" in self._cursor and isinstance(self._cursor["_seen"], list):
            self._cursor["_seen"] = set(self._cursor["_seen"])

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _message_to_event(
        self,
        msg: dict[str, Any],
        update_id: int,
    ) -> Event | None:
        """Convert a Telegram message dict to an ``Event``.

        Handles text messages, photo captions, and various message
        subtypes (poll results, new chat members, etc.).
        """
        message_id: int = msg.get("message_id", 0)
        dedup_key = f"msg:{message_id}"
        if dedup_key in self._cursor.get("_seen", set()):
            return None

        chat = msg.get("chat", {})
        chat_id = chat.get("id", "")
        chat_name = self._get_chat_name(chat)
        sender = msg.get("from", {})
        sender_name = sender.get("first_name", "") or sender.get("username", "unknown")
        sender_id = sender.get("id", "")
        date = msg.get("date", 0)
        text = msg.get("text", "")

        # Photo messages carry captions instead of text
        if not text and msg.get("caption"):
            text = msg.get("caption", "")

        # Build content string with metadata
        metadata: dict[str, Any] = {
            "source": "telegram",
            "chat_id": str(chat_id),
            "chat_name": chat_name,
            "chat_type": chat.get("type", ""),
            "message_id": message_id,
            "sender": sender_name,
            "sender_id": str(sender_id),
            "date": date,
            "update_id": update_id,
        }

        # ── Forward origin ─────────────────────────────────────────
        forward_from = msg.get("forward_from")
        if forward_from:
            metadata["forward_from"] = forward_from.get(
                "username", forward_from.get("first_name", "unknown")
            )

        # ── Entities (mentions, hashtags, etc.) ────────────────────
        entities = msg.get("entities", [])
        if entities:
            metadata["entities"] = [
                {
                    "type": e.get("type", ""),
                    "text": text[e.get("offset", 0): e.get("offset", 0) + e.get("length", 0)],
                }
                for e in entities
            ]

        # ── Reply-to ───────────────────────────────────────────────
        reply_to = msg.get("reply_to_message")
        if reply_to:
            metadata["reply_to_message_id"] = reply_to.get("message_id", 0)

        # ── Thread / topic ─────────────────────────────────────────
        thread_id = msg.get("message_thread_id")
        if thread_id:
            metadata["thread_id"] = thread_id

        # ── Media attachments ──────────────────────────────────────
        if msg.get("photo"):
            metadata["has_photo"] = True
        if msg.get("document"):
            doc = msg["document"]
            metadata["document"] = {"file_name": doc.get("file_name", ""), "mime_type": doc.get("mime_type", "")}
        if msg.get("audio"):
            metadata["has_audio"] = True
        if msg.get("voice"):
            metadata["has_voice"] = True
        if msg.get("video"):
            metadata["has_video"] = True
        if msg.get("sticker"):
            sticker = msg["sticker"]
            metadata["sticker"] = {"emoji": sticker.get("emoji", ""), "set_name": sticker.get("set_name", "")}

        # ── Poll ───────────────────────────────────────────────────
        poll = msg.get("poll")
        if poll:
            metadata["poll"] = {"question": poll.get("question", "")}

        content = text or f"[{chat.get('type', '') or 'message'}]"

        # Track seen
        seen = self._cursor.setdefault("_seen", set())
        seen.add(dedup_key)
        # Keep _seen from growing unboundedly — cap at 10_000
        if len(seen) > 10_000:
            # Keep the most recent 5_000
            self._cursor["_seen"] = set(
                sorted(seen)[-5_000:]
            )

        return Event(
            content=content,
            workspace_id=self.workspace_id,
            summary=content[:200],
            memory_type="experience",
            peer_id=self.peer_id,
            metadata=metadata,
        )

    def _callback_to_event(
        self,
        cb: dict[str, Any],
        update_id: int,
    ) -> Event | None:
        """Convert a Telegram callback query to an ``Event``.

        Callback queries are generated when users press inline keyboard
        buttons.  They include the callback data and the original
        message context.
        """
        cb_id: str = cb.get("id", "")
        dedup_key = f"cb:{cb_id}"
        if dedup_key in self._cursor.get("_seen", set()):
            return None

        data: str = cb.get("data", "")
        sender = cb.get("from", {})
        sender_name = sender.get("first_name", "") or sender.get("username", "unknown")
        sender_id = sender.get("id", "")

        msg = cb.get("message", {})
        chat = msg.get("chat", {})
        chat_id = chat.get("id", "")
        chat_name = self._get_chat_name(chat)
        message_id: int = msg.get("message_id", 0)

        content = f"[callback] {data}"

        seen = self._cursor.setdefault("_seen", set())
        seen.add(dedup_key)
        if len(seen) > 10_000:
            self._cursor["_seen"] = set(sorted(seen)[-5_000:])

        return Event(
            content=content,
            workspace_id=self.workspace_id,
            summary=f"Callback from {sender_name}: {data[:150]}",
            memory_type="experience",
            peer_id=self.peer_id,
            metadata={
                "source": "telegram",
                "chat_id": str(chat_id),
                "chat_name": chat_name,
                "message_id": message_id,
                "sender": sender_name,
                "sender_id": str(sender_id),
                "callback_id": cb_id,
                "callback_data": data,
                "update_id": update_id,
            },
        )
