"""Tests for TelegramConnector — mock-based HTTP tests.

Covers: poll(), _message_to_event, _callback_to_event, _get_chat_name,
cursor persistence, error handling, deduplication, attachments.
"""

from __future__ import annotations

import os as _os
import shutil as _shutil
from unittest.mock import Mock, patch

import pytest

_conn_cursor_dir = _os.path.expanduser("~/.spacetime-memory/connectors")
if _os.path.exists(_conn_cursor_dir):
    _shutil.rmtree(_conn_cursor_dir, ignore_errors=True)

from spacetime_memory.connectors import TelegramConnector


@pytest.fixture(autouse=True)
def _isolate_all_cursors(tmp_path, monkeypatch):
    """Isolate the default connector cursor dir for every test.

    Any TelegramConnector constructed WITHOUT an explicit ``cursor_dir``
    falls back to ``~/.spacetime-memory/connectors`` — a shared path that
    leaks dedup state between tests and xdist workers. Redirect it to a
    per-test tmp dir so each test starts with a fresh cursor.
    """
    test_cursor_dir = str(tmp_path / "connectors")
    monkeypatch.setattr(
        "spacetime_memory.connectors._base.os.path.expanduser",
        lambda _path: test_cursor_dir,
    )
    yield test_cursor_dir

# ── Helpers ──────────────────────────────────────────────────────────


def _make_update(
    update_id: int,
    message_id: int = 1,
    text: str = "hello",
    chat_id: int = -1001234567890,
    chat_type: str = "supergroup",
    chat_title: str = "Test Group",
    sender_name: str = "Alice",
    sender_id: int = 12345,
    date: int = 1700000000,
) -> dict:
    """Build a Telegram update dict with a text message."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "from": {
                "id": sender_id,
                "is_bot": False,
                "first_name": sender_name,
            },
            "chat": {
                "id": chat_id,
                "type": chat_type,
                "title": chat_title,
            },
            "date": date,
            "text": text,
        },
    }


def _make_callback_update(
    update_id: int,
    cb_id: str = "cb-1",
    cb_data: str = "button_click",
    message_id: int = 1,
    chat_id: int = -1001234567890,
    chat_title: str = "Test Group",
    sender_name: str = "Bob",
    sender_id: int = 67890,
) -> dict:
    """Build a Telegram update dict with a callback query."""
    return {
        "update_id": update_id,
        "callback_query": {
            "id": cb_id,
            "from": {
                "id": sender_id,
                "is_bot": False,
                "first_name": sender_name,
            },
            "message": {
                "message_id": message_id,
                "chat": {
                    "id": chat_id,
                    "type": "supergroup",
                    "title": chat_title,
                },
                "date": 1700000000,
            },
            "data": cb_data,
        },
    }


def _make_api_response(ok: bool = True, result: list | None = None) -> dict:
    """Build a Telegram API response dict."""
    return {
        "ok": ok,
        "result": result or [],
    }


# ── Chat name ────────────────────────────────────────────────────────


class TestTelegramGetChatName:
    """_get_chat_name extraction from different chat types."""

    def test_group_title(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        name = connector._get_chat_name(
            {"id": -100, "type": "supergroup", "title": "My Group"}
        )
        assert name == "My Group"

    def test_private_chat_username(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        name = connector._get_chat_name(
            {
                "id": 123,
                "type": "private",
                "username": "testuser",
                "first_name": "Test",
            }
        )
        assert name == "@testuser"

    def test_private_chat_first_last(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        name = connector._get_chat_name(
            {"id": 123, "type": "private", "first_name": "John", "last_name": "Doe"}
        )
        assert name == "John Doe"

    def test_private_chat_first_only(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        name = connector._get_chat_name(
            {"id": 123, "type": "private", "first_name": "Jane"}
        )
        assert name == "Jane"

    def test_none_chat(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        name = connector._get_chat_name(None)
        assert name == "unknown"

    def test_empty_chat(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        name = connector._get_chat_name({})
        assert name == "unknown"


# ── Message to Event ─────────────────────────────────────────────────


class TestTelegramMsgToEvent:
    """_message_to_event conversion and edge cases."""

    @pytest.fixture(autouse=True)
    def _isolate_cursor(self, tmp_path):
        """Use an isolated cursor dir so dedup state never leaks between tests.

        Without this, tests in the same xdist worker share
        ``~/.spacetime-memory/connectors/TelegramConnector_cursor.json``
        and a prior test that saw the same message_id would make later
        tests get ``None`` from ``_message_to_event``.
        """
        self.cursor_dir = str(tmp_path / "connectors")

    def _connector(self):
        return TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws",
            cursor_dir=self.cursor_dir,
        )

    def test_basic_text_message(self):
        connector = self._connector()
        update = _make_update(1, message_id=101, text="Hello world")
        msg = update["message"]
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.content == "Hello world"
        assert ev.metadata["source"] == "telegram"
        assert ev.metadata["chat_name"] == "Test Group"
        assert ev.metadata["sender"] == "Alice"

    def test_deduplication(self):
        connector = self._connector()
        msg = _make_update(1)["message"]
        ev1 = connector._message_to_event(msg, 1)
        assert ev1 is not None
        ev2 = connector._message_to_event(msg, 1)
        assert ev2 is None  # dedup

    def test_photo_caption(self):
        connector = self._connector()
        msg = _make_update(1, text="")["message"]
        msg["caption"] = "A lovely photo"
        msg["photo"] = [{"file_id": "abc", "width": 100, "height": 100}]
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.content == "A lovely photo"
        assert ev.metadata.get("has_photo") is True

    def test_no_text_or_caption(self):
        connector = self._connector()
        msg = _make_update(1, text="")["message"]
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.content is not None

    def test_sticker(self):
        connector = self._connector()
        msg = _make_update(1, text="")["message"]
        msg["sticker"] = {"emoji": "\U0001f44d", "set_name": "Nice"}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("sticker") == {"emoji": "\U0001f44d", "set_name": "Nice"}

    def test_poll(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, text="")["message"]
        msg["poll"] = {"question": "Yes or no?"}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("poll") == {"question": "Yes or no?"}

    def test_entities(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, text="Hello @user")["message"]
        msg["entities"] = [
            {"type": "mention", "offset": 6, "length": 5}
        ]
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert "entities" in ev.metadata
        assert ev.metadata["entities"][0]["type"] == "mention"

    def test_reply_to(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1)["message"]
        msg["reply_to_message"] = {
            "message_id": 42,
            "text": "original",
            "from": {"id": 99, "first_name": "Bot"},
        }
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("reply_to_message_id") == 42

    def test_thread_id(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1)["message"]
        msg["message_thread_id"] = 999
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("thread_id") == 999


# ── Callback to Event ────────────────────────────────────────────────


class TestTelegramCallbackToEvent:
    """_callback_to_event conversion."""

    @pytest.fixture(autouse=True)
    def _isolate_cursor(self, tmp_path):
        """Use an isolated cursor dir so dedup state never leaks between tests."""
        self.cursor_dir = str(tmp_path / "connectors")

    def test_basic_callback(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws",
            cursor_dir=self.cursor_dir,
        )
        update = _make_callback_update(2)
        cb = update["callback_query"]
        ev = connector._callback_to_event(cb, 2)
        assert ev is not None
        assert "button_click" in ev.content
        assert ev.metadata["callback_data"] == "button_click"
        assert ev.metadata["source"] == "telegram"

    def test_deduplication(self):
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws",
            cursor_dir=self.cursor_dir,
        )
        cb = _make_callback_update(1)["callback_query"]
        ev1 = connector._callback_to_event(cb, 1)
        assert ev1 is not None
        ev2 = connector._callback_to_event(cb, 1)
        assert ev2 is None


# ── Poll ─────────────────────────────────────────────────────────────


class TestTelegramPoll:
    """poll() integration with mocked HTTP."""

    def test_simple_poll(self):
        """Basic poll with one message update."""
        api_resp = _make_api_response(
            result=[_make_update(1, message_id=1, text="hello")]
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "hello"

    def test_poll_with_callback(self):
        """Poll includes callback queries when enabled."""
        api_resp = _make_api_response(
            result=[
                _make_callback_update(1),
            ]
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok",
                chat_ids=[],
                workspace_id="ws",
                include_callback_queries=True,
            )
            events = connector.poll()

        assert len(events) == 1
        assert "button_click" in events[0].content

    def test_poll_excludes_callbacks_when_disabled(self):
        """Callback queries are skipped when include_callback_queries=False."""
        api_resp = _make_api_response(
            result=[
                _make_callback_update(1),
            ]
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok",
                chat_ids=[],
                workspace_id="ws",
                include_callback_queries=False,
            )
            events = connector.poll()

        assert len(events) == 0

    def test_empty_result(self):
        """Empty result from API returns no events."""
        api_resp = _make_api_response(result=[])

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert events == []

    def test_rate_limited_429(self):
        """429 rate limited returns no events."""
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=429)
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert events == []

    def test_unauthorized_401(self):
        """401 unauthorized returns no events."""
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=401)
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert events == []

    def test_api_error(self):
        """API returning ok=False returns no events."""
        api_resp = {"ok": False, "description": "Conflict: terminated by other getUpdates request"}

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert events == []

    def test_unexpected_status(self):
        """Non-200/401/429 status returns no events."""
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=500)
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert events == []

    def test_request_error(self):
        """httpx.RequestError returns no events."""
        import httpx

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = httpx.RequestError("connection failed")

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert events == []

    def test_cursor_persistence(self):
        """Cursor is updated with highest update_id + 1."""
        api_resp = _make_api_response(
            result=[
                _make_update(10, message_id=1, text="a"),
                _make_update(20, message_id=2, text="b"),
            ]
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            connector._cursor = {}  # fresh cursor
            connector._save_cursor = Mock()  # don't actually write

            events = connector.poll()

        assert len(events) == 2
        # Cursor should be max update_id + 1
        assert connector._cursor.get("offset") == 21

    def test_multiple_update_types(self):
        """Mixed message types all produce events."""
        api_resp = _make_api_response(
            result=[
                _make_update(1, message_id=10, text="text msg"),
                _make_callback_update(2, cb_id="c1", cb_data="btn1"),
                _make_callback_update(3, cb_id="c2", cb_data="btn2"),
            ]
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert len(events) == 3

    def test_edited_message(self):
        """edited_message updates are processed."""
        update = {
            "update_id": 1,
            "edited_message": {
                "message_id": 5,
                "from": {"id": 1, "first_name": "Alice"},
                "chat": {"id": -100, "type": "supergroup", "title": "G"},
                "date": 1700000000,
                "text": "edited text",
            },
        }
        api_resp = _make_api_response(result=[update])

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "edited text"

    def test_channel_post(self):
        """channel_post updates are processed."""
        update = {
            "update_id": 1,
            "channel_post": {
                "message_id": 100,
                "chat": {"id": -200, "type": "channel", "title": "News"},
                "date": 1700000000,
                "text": "channel post",
            },
        }
        api_resp = _make_api_response(result=[update])

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            resp = Mock(status_code=200)
            resp.json.return_value = api_resp
            mock_client.get.return_value = resp

            connector = TelegramConnector(
                token="tok", chat_ids=[], workspace_id="ws"
            )
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "channel post"


# ── Message to Event — extended media metadata ────────────────────────


class TestTelegramMsgToEventExtended:
    """_message_to_event edge cases for media/documents/forwarding."""

    def test_forward_from_username(self):
        """forward_from with username appears in metadata."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=101, text="forwarded msg")["message"]
        msg["forward_from"] = {"id": 999, "username": "original_user", "first_name": "Original"}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("forward_from") == "original_user"

    def test_forward_from_fallback_first_name(self):
        """forward_from falls back to first_name when no username."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=102, text="forwarded")["message"]
        msg["forward_from"] = {"id": 999, "first_name": "OriginalSender"}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("forward_from") == "OriginalSender"

    def test_document_metadata(self):
        """Document metadata includes file_name and mime_type."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=103, text="")["message"]
        msg["document"] = {"file_name": "report.pdf", "mime_type": "application/pdf"}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("document") == {"file_name": "report.pdf", "mime_type": "application/pdf"}

    def test_audio_metadata(self):
        """Audio messages have has_audio flag in metadata."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=104, text="")["message"]
        msg["audio"] = {"file_id": "abc123", "duration": 120}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("has_audio") is True

    def test_voice_metadata(self):
        """Voice messages have has_voice flag in metadata."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=105, text="")["message"]
        msg["voice"] = {"file_id": "def456", "duration": 30}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("has_voice") is True

    def test_video_metadata(self):
        """Video messages have has_video flag in metadata."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=106, text="")["message"]
        msg["video"] = {"file_id": "ghi789", "width": 640, "height": 480}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata.get("has_video") is True

    def test_sender_name_from_username(self):
        """Sender name falls back to username when first_name is missing."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        msg = _make_update(1, message_id=107, text="test", sender_name="")["message"]
        msg["from"] = {"id": 12345, "is_bot": False, "username": "testuser"}
        ev = connector._message_to_event(msg, 1)
        assert ev is not None
        assert ev.metadata["sender"] == "testuser"


# ── API URL ──────────────────────────────────────────────────────────


class TestTelegramApiUrl:
    """_api_url property."""

    def test_api_url_construction(self):
        """_api_url combines BASE_URL with bot token."""
        connector = TelegramConnector(
            token="123456:ABC-DEF1234", chat_ids=[], workspace_id="ws"
        )
        assert connector._api_url == "https://api.telegram.org/bot123456:ABC-DEF1234"


# ── Cursor / Seen Set ───────────────────────────────────────────────


class TestTelegramSeenCap:
    """_seen set capping at 10k entries."""

    def test_seen_set_caps_at_threshold(self):
        """_seen set is capped to 5k when it exceeds 10k entries."""
        connector = TelegramConnector(
            token="tok", chat_ids=[], workspace_id="ws"
        )
        # Pre-fill _seen with 10_001 entries — one above the cap
        connector._cursor["_seen"] = set(f"msg:{i}" for i in range(10001))
        msg = _make_update(1, message_id=99999, text="a")["message"]
        connector._message_to_event(msg, 1)
        # After cap: should only keep the last 5k + the new entry was added before cap triggered
        assert len(connector._cursor["_seen"]) <= 5001  # 5000 kept + 1 new = 5001 max
