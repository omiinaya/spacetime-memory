import logging
import time
from typing import Any

import httpx

from .base import Event, SyncConnector

logger = logging.getLogger(__name__)


class NotionConnector(SyncConnector):
    """Poll a Notion database for new or updated pages via Notion API.

    Queries ``/databases/{database_id}/query`` (POST) with full
    pagination (up to 100 pages).  Extracts title and body content
    from all supported property types (title, rich_text, select,
    multi_select, status, date, checkbox, number, url, email,
    phone_number, unique_id, formula, rollup, created_by,
    created_time, last_edited_by, last_edited_time, people, files,
    button).  Deduplicates by page ID and handles rate limits by
    honouring the ``Retry-After`` header.

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
        max_pages: int = 100,
    ):
        """Initialise the Notion connector.

        Args:
            token: Notion integration token (``secret_...``).
            database_id: Notion database ID to poll.
            workspace_id: Target workspace UUID.
            peer_id: Name for the memory source (default ``"notion-bot"``).
            max_pages: Maximum pages to fetch per poll (default ``100``).
        """
        self.token = token
        self.database_id = database_id
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self.max_pages = max_pages
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll(self) -> list[Event]:
        """Poll a Notion database for new or updated pages.

        Queries the database with cursor-based pagination (up to
        ``max_pages`` pages of 100 results each).  Extracts title,
        body, and all property values from each page.  Skips pages
        already seen (deduplication by page ID).  Handles rate
        limits by honouring the ``Retry-After`` header.

        Returns:
            List of new ``Event`` objects since the last poll.
        """
        events: list[Event] = []
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
            "User-Agent": "spacetime-memory-connector/1.0",
        }
        url = f"{self.BASE_URL}/databases/{self.database_id}/query"
        payload: dict[str, Any] = {"page_size": 100}

        with httpx.Client() as client:
            pages = 0
            while pages < self.max_pages:
                try:
                    resp = client.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=30,
                    )
                except httpx.RequestError as e:
                    logger.warning("Notion HTTP error: %s", e)
                    break

                # ── Rate-limit handling with Retry-After ──────────
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning("Notion rate limited, waiting %ss ...", retry_after)
                    time.sleep(retry_after)
                    continue  # retry the same page

                if resp.status_code == 401:
                    logger.warning("Notion unauthorised — check integration token")
                    break

                if resp.status_code != 200:
                    logger.warning("Notion unexpected status %s", resp.status_code)
                    break

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

                    # Collect all property values into metadata
                    prop_summary = self._extract_property_summary(
                        props,
                    )

                    metadata: dict[str, Any] = {
                        "source": "notion",
                        "page_id": page_id,
                        "database_id": self.database_id,
                        "url": page.get("url", ""),
                        "created_time": page.get(
                            "created_time",
                            "",
                        ),
                        "last_edited_time": page.get(
                            "last_edited_time",
                            "",
                        ),
                    }
                    # Merge property summary (avoids overwriting
                    # the reserved keys above)
                    for k, v in prop_summary.items():
                        if k not in metadata:
                            metadata[k] = v

                    events.append(
                        Event(
                            content=content,
                            workspace_id=self.workspace_id,
                            summary=title_text[:200],
                            memory_type="experience",
                            peer_id=self.peer_id,
                            metadata=metadata,
                        )
                    )

                # ── Pagination ────────────────────────────────────
                next_cursor = data.get("next_cursor")
                has_more = data.get("has_more", False)
                if not has_more or not next_cursor:
                    break

                payload["start_cursor"] = next_cursor
                pages += 1

        return events

    # ------------------------------------------------------------------
    # Property extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(props: dict) -> str:
        """Extract a title string from Notion page properties."""
        for prop in props.values():
            prop_type = prop.get("type", "")
            if prop_type == "title":
                parts = prop.get("title", [])
                if parts:
                    return "".join(p.get("plain_text", "") for p in parts)
            if prop_type == "rich_text":
                parts = prop.get("rich_text", [])
                if parts:
                    return "".join(p.get("plain_text", "") for p in parts)
        return "Untitled"

    @staticmethod
    def _extract_body(props: dict) -> str:
        """Extract body content from Notion page properties (non-title)."""
        parts: list[str] = []
        for key, prop in props.items():
            prop_type = prop.get("type", "")
            val = NotionConnector._get_prop_value(prop_type, prop)
            if val is not None and val != "":
                parts.append(f"{key}: {val}")
        return "\n".join(parts)

    @staticmethod
    def _extract_property_summary(props: dict) -> dict[str, Any]:
        """Extract all property values into a flat dict for metadata."""
        summary: dict[str, Any] = {}
        for key, prop in props.items():
            prop_type = prop.get("type", "")
            val = NotionConnector._get_prop_value(prop_type, prop)
            if val is not None:
                summary[key] = val
        return summary

    @staticmethod
    def _get_prop_value(
        prop_type: str,
        prop: dict,
    ) -> Any:
        """Get the display value for a Notion property by its type.

        Supports all standard Notion property types.
        """
        # ── Text / Title ──────────────────────────────────────────
        if prop_type == "title":
            parts = prop.get("title", [])
            if not parts:
                return None
            return "".join(p.get("plain_text", "") for p in parts)

        if prop_type == "rich_text":
            parts = prop.get("rich_text", [])
            if not parts:
                return None
            return "".join(p.get("plain_text", "") for p in parts)

        # ── Selects ───────────────────────────────────────────────
        if prop_type == "select":
            select = prop.get("select")
            if not select:
                return None
            return select.get("name", "")

        if prop_type == "multi_select":
            mselects = prop.get("multi_select", [])
            if not mselects:
                return None
            return ", ".join(m.get("name", "") for m in mselects)

        if prop_type == "status":
            status = prop.get("status")
            if not status:
                return None
            return status.get("name", "")

        # ── Date ──────────────────────────────────────────────────
        if prop_type == "date":
            date = prop.get("date")
            if not date:
                return None
            start = date.get("start", "")
            end = date.get("end")
            if end:
                return f"{start} \u2192 {end}"
            return start

        # ── Primitives ────────────────────────────────────────────
        if prop_type == "checkbox":
            return prop.get("checkbox", False)

        if prop_type == "number":
            return prop.get("number")

        if prop_type == "url":
            return prop.get("url")

        if prop_type == "email":
            return prop.get("email")

        if prop_type == "phone_number":
            return prop.get("phone_number")

        # ── Unique ID ─────────────────────────────────────────────
        if prop_type == "unique_id":
            uid = prop.get("unique_id")
            if not uid:
                return None
            prefix = uid.get("prefix", "")
            number = uid.get("number")
            if prefix and number is not None:
                return f"{prefix}-{number}"
            if number is not None:
                return str(number)
            return None

        # ── Formula ───────────────────────────────────────────────
        if prop_type == "formula":
            formula = prop.get("formula", {})
            formula_type = formula.get("type", "")
            if formula_type == "string":
                return formula.get("string")
            if formula_type == "number":
                return formula.get("number")
            if formula_type == "boolean":
                return formula.get("boolean")
            if formula_type == "date":
                date_val = formula.get("date")
                if date_val:
                    return date_val.get("start", "")
            return None

        # ── Rollup ────────────────────────────────────────────────
        if prop_type == "rollup":
            rollup = prop.get("rollup", {})
            rollup_type = rollup.get("type", "")
            if rollup_type == "array":
                arr = rollup.get("array", [])
                display = []
                for item in arr:
                    item_type = item.get("type", "")
                    val = NotionConnector._get_prop_value(
                        item_type,
                        item,
                    )
                    if val is not None:
                        display.append(str(val))
                return ", ".join(display)
            if rollup_type == "number":
                return rollup.get("number")
            if rollup_type == "date":
                date_val = rollup.get("date")
                if date_val:
                    return date_val.get("start", "")
            if rollup_type == "incomplete":
                return "(incomplete rollup)"
            return None

        # ── People (user references) ──────────────────────────────
        if prop_type == "people":
            people = prop.get("people", [])
            if not people:
                return None
            return ", ".join(p.get("name", p.get("id", "?")) for p in people)

        # ── Files ─────────────────────────────────────────────────
        if prop_type == "files":
            files = prop.get("files", [])
            if not files:
                return None
            urls = []
            for f in files:
                name = f.get("name", "")
                file_data = f.get("file") or f.get("external", {})
                url_val = file_data.get("url", "")
                if name and url_val:
                    urls.append(f"{name}: {url_val}")
                elif url_val:
                    urls.append(url_val)
                elif name:
                    urls.append(name)
            return ", ".join(urls)

        # ── Created / Edited metadata ─────────────────────────────
        if prop_type == "created_by":
            user = prop.get("created_by", {})
            return user.get("name", user.get("id", ""))

        if prop_type == "created_time":
            return prop.get("created_time")

        if prop_type == "last_edited_by":
            user = prop.get("last_edited_by", {})
            return user.get("name", user.get("id", ""))

        if prop_type == "last_edited_time":
            return prop.get("last_edited_time")

        # ── Button (Notion button property — typically no value) ──
        if prop_type == "button":
            button = prop.get("button", {})
            if button:
                return button.get("text", "[button]")
            return "[button]"

        # ── Fallback for unknown types ────────────────────────────
        return None


# ── Org-mode Parser ──────────────────────────────────────────────────
