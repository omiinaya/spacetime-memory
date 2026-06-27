"""Tests for NotionConnector.

Tests cover:
- poll() with mocked httpx.Client (success, pagination, rate limits, errors)
- _extract_title() for various property types
- _extract_body() for property aggregation
- _extract_property_summary() for flat dict extraction
- _get_prop_value() for all supported Notion property types
- Deduplication via _seen set
"""

from unittest.mock import Mock, patch

from spacetime_memory.connectors import NotionConnector, Event


# ── Helpers ──────────────────────────────────────────────────────────


def _make_page(page_id: str, title_text: str, properties: dict, **extra):
    """Build a minimal Notion API page dict."""
    page = {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "created_time": "2024-01-01T00:00:00Z",
        "last_edited_time": "2024-01-02T00:00:00Z",
        "properties": properties,
    }
    page.update(extra)
    return page


def _make_title_prop(text: str):
    return {"type": "title", "title": _rich_text(text)}


def _make_rich_text_prop(text: str):
    return {"type": "rich_text", "rich_text": _rich_text(text)}


def _rich_text(text: str):
    return [{"plain_text": text, "type": "text"}]


def _make_api_response(results: list, has_more=False, next_cursor=None):
    resp = Mock(status_code=200)
    data = {"results": results}
    if has_more:
        data["has_more"] = True
        data["next_cursor"] = next_cursor or "cursor-1"
    resp.json.return_value = data
    return resp


# ── Constructor tests ────────────────────────────────────────────────


class TestNotionConnectorInit:
    def test_default_values(self):
        c = NotionConnector(token="sekrit", database_id="db-1", workspace_id="ws-1")
        assert c.token == "sekrit"
        assert c.database_id == "db-1"
        assert c.workspace_id == "ws-1"
        assert c.peer_id == "notion-bot"
        assert c.max_pages == 100
        assert c._seen == set()

    def test_custom_values(self):
        c = NotionConnector(
            token="tok",
            database_id="db-2",
            workspace_id="ws-2",
            peer_id="my-bot",
            max_pages=50,
        )
        assert c.peer_id == "my-bot"
        assert c.max_pages == 50


# ── _get_prop_value tests ────────────────────────────────────────────


class TestGetPropValue:
    """Static _get_prop_value() — all Notion property types."""

    def test_title(self):
        val = NotionConnector._get_prop_value("title", _make_title_prop("Hello"))
        assert val == "Hello"

    def test_title_empty(self):
        assert NotionConnector._get_prop_value("title", {"type": "title", "title": []}) is None

    def test_rich_text(self):
        val = NotionConnector._get_prop_value("rich_text", _make_rich_text_prop("World"))
        assert val == "World"

    def test_select(self):
        val = NotionConnector._get_prop_value(
            "select", {"type": "select", "select": {"name": "Option A"}}
        )
        assert val == "Option A"

    def test_select_none(self):
        assert NotionConnector._get_prop_value("select", {"type": "select", "select": None}) is None

    def test_multi_select(self):
        val = NotionConnector._get_prop_value(
            "multi_select",
            {
                "type": "multi_select",
                "multi_select": [{"name": "A"}, {"name": "B"}],
            },
        )
        assert val == "A, B"

    def test_multi_select_empty(self):
        val = NotionConnector._get_prop_value(
            "multi_select", {"type": "multi_select", "multi_select": []}
        )
        assert val is None

    def test_status(self):
        val = NotionConnector._get_prop_value(
            "status", {"type": "status", "status": {"name": "In Progress"}}
        )
        assert val == "In Progress"

    def test_status_none(self):
        assert NotionConnector._get_prop_value("status", {"type": "status", "status": None}) is None

    def test_date_start_only(self):
        val = NotionConnector._get_prop_value(
            "date", {"type": "date", "date": {"start": "2024-01-01"}}
        )
        assert val == "2024-01-01"

    def test_date_range(self):
        val = NotionConnector._get_prop_value(
            "date",
            {
                "type": "date",
                "date": {"start": "2024-01-01", "end": "2024-01-10"},
            },
        )
        assert val == "2024-01-01 → 2024-01-10"

    def test_date_none(self):
        assert NotionConnector._get_prop_value("date", {"type": "date", "date": None}) is None

    def test_checkbox_true(self):
        assert (
            NotionConnector._get_prop_value("checkbox", {"type": "checkbox", "checkbox": True})
            is True
        )

    def test_checkbox_false(self):
        assert (
            NotionConnector._get_prop_value("checkbox", {"type": "checkbox", "checkbox": False})
            is False
        )

    def test_number(self):
        assert NotionConnector._get_prop_value("number", {"type": "number", "number": 42}) == 42

    def test_number_zero(self):
        assert NotionConnector._get_prop_value("number", {"type": "number", "number": 0}) == 0

    def test_url(self):
        val = NotionConnector._get_prop_value("url", {"type": "url", "url": "https://example.com"})
        assert val == "https://example.com"

    def test_email(self):
        val = NotionConnector._get_prop_value("email", {"type": "email", "email": "a@b.com"})
        assert val == "a@b.com"

    def test_phone_number(self):
        val = NotionConnector._get_prop_value(
            "phone_number", {"type": "phone_number", "phone_number": "555-1234"}
        )
        assert val == "555-1234"

    def test_unique_id_with_prefix(self):
        val = NotionConnector._get_prop_value(
            "unique_id",
            {
                "type": "unique_id",
                "unique_id": {"prefix": "TASK", "number": 42},
            },
        )
        assert val == "TASK-42"

    def test_unique_id_no_prefix(self):
        val = NotionConnector._get_prop_value(
            "unique_id",
            {
                "type": "unique_id",
                "unique_id": {"prefix": None, "number": 7},
            },
        )
        assert val == "7"

    def test_unique_id_none(self):
        assert (
            NotionConnector._get_prop_value("unique_id", {"type": "unique_id", "unique_id": None})
            is None
        )

    def test_unique_id_prefix_no_number(self):
        """When unique_id has prefix but number is None, returns None."""
        assert (
            NotionConnector._get_prop_value(
                "unique_id",
                {
                    "type": "unique_id",
                    "unique_id": {"prefix": "TASK", "number": None},
                },
            )
            is None
        )

    def test_formula_string(self):
        val = NotionConnector._get_prop_value(
            "formula",
            {
                "type": "formula",
                "formula": {"type": "string", "string": "hello"},
            },
        )
        assert val == "hello"

    def test_formula_number(self):
        val = NotionConnector._get_prop_value(
            "formula",
            {
                "type": "formula",
                "formula": {"type": "number", "number": 3.14},
            },
        )
        assert val == 3.14

    def test_formula_boolean(self):
        val = NotionConnector._get_prop_value(
            "formula",
            {
                "type": "formula",
                "formula": {"type": "boolean", "boolean": True},
            },
        )
        assert val is True

    def test_formula_date(self):
        val = NotionConnector._get_prop_value(
            "formula",
            {
                "type": "formula",
                "formula": {"type": "date", "date": {"start": "2024-06-01"}},
            },
        )
        assert val == "2024-06-01"

    def test_formula_unknown_type(self):
        assert (
            NotionConnector._get_prop_value(
                "formula",
                {
                    "type": "formula",
                    "formula": {"type": "unknown_stuff"},
                },
            )
            is None
        )

    def test_rollup_array(self):
        val = NotionConnector._get_prop_value(
            "rollup",
            {
                "type": "rollup",
                "rollup": {
                    "type": "array",
                    "array": [
                        {"type": "title", "title": _rich_text("Item 1")},
                        {"type": "number", "number": 10},
                    ],
                },
            },
        )
        assert "Item 1" in val
        assert "10" in val

    def test_rollup_number(self):
        val = NotionConnector._get_prop_value(
            "rollup",
            {
                "type": "rollup",
                "rollup": {"type": "number", "number": 99},
            },
        )
        assert val == 99

    def test_rollup_date(self):
        val = NotionConnector._get_prop_value(
            "rollup",
            {
                "type": "rollup",
                "rollup": {"type": "date", "date": {"start": "2024-12-25"}},
            },
        )
        assert val == "2024-12-25"

    def test_rollup_incomplete(self):
        val = NotionConnector._get_prop_value(
            "rollup",
            {
                "type": "rollup",
                "rollup": {"type": "incomplete"},
            },
        )
        assert val == "(incomplete rollup)"

    def test_rollup_unknown_type(self):
        """Rollup with an unrecognised type returns None."""
        assert (
            NotionConnector._get_prop_value(
                "rollup",
                {
                    "type": "rollup",
                    "rollup": {"type": "bogus_rollup"},
                },
            )
            is None
        )

    def test_people(self):
        val = NotionConnector._get_prop_value(
            "people",
            {
                "type": "people",
                "people": [{"name": "Alice"}, {"name": "Bob"}],
            },
        )
        assert val == "Alice, Bob"

    def test_people_fallback_to_id(self):
        val = NotionConnector._get_prop_value(
            "people",
            {
                "type": "people",
                "people": [{"id": "user-1"}, {"name": "Charlie"}],
            },
        )
        assert "user-1" in val
        assert "Charlie" in val

    def test_people_empty(self):
        assert NotionConnector._get_prop_value("people", {"type": "people", "people": []}) is None

    def test_files_with_names_and_urls(self):
        val = NotionConnector._get_prop_value(
            "files",
            {
                "type": "files",
                "files": [
                    {"name": "doc.pdf", "file": {"url": "https://s3/file1"}},
                    {"name": "img.png", "external": {"url": "https://cdn/file2"}},
                ],
            },
        )
        assert "doc.pdf" in val
        assert "img.png" in val
        assert "https://s3/file1" in val
        assert "https://cdn/file2" in val

    def test_files_empty(self):
        assert NotionConnector._get_prop_value("files", {"type": "files", "files": []}) is None

    def test_files_name_only_no_url(self):
        """Files with a name but no URL are still included."""
        val = NotionConnector._get_prop_value(
            "files",
            {
                "type": "files",
                "files": [
                    {"name": "readme.md", "file": {}},
                    {"name": "LICENSE"},
                ],
            },
        )
        assert "readme.md" in val
        assert "LICENSE" in val

    def test_files_url_only_no_name(self):
        """Files with a URL but no name are still included."""
        val = NotionConnector._get_prop_value(
            "files",
            {
                "type": "files",
                "files": [
                    {"file": {"url": "https://s3/bucket/key"}},
                    {"external": {"url": "https://cdn/asset"}},
                ],
            },
        )
        assert "https://s3/bucket/key" in val
        assert "https://cdn/asset" in val

    def test_created_by(self):
        val = NotionConnector._get_prop_value(
            "created_by",
            {
                "type": "created_by",
                "created_by": {"name": "Alice"},
            },
        )
        assert val == "Alice"

    def test_created_time(self):
        val = NotionConnector._get_prop_value(
            "created_time",
            {
                "type": "created_time",
                "created_time": "2024-06-15T10:00:00Z",
            },
        )
        assert val == "2024-06-15T10:00:00Z"

    def test_last_edited_by(self):
        val = NotionConnector._get_prop_value(
            "last_edited_by",
            {
                "type": "last_edited_by",
                "last_edited_by": {"id": "user-2"},
            },
        )
        assert val == "user-2"

    def test_last_edited_time(self):
        val = NotionConnector._get_prop_value(
            "last_edited_time",
            {
                "type": "last_edited_time",
                "last_edited_time": "2024-07-01T12:00:00Z",
            },
        )
        assert val == "2024-07-01T12:00:00Z"

    def test_button(self):
        val = NotionConnector._get_prop_value(
            "button",
            {
                "type": "button",
                "button": {"text": "Click me"},
            },
        )
        assert val == "Click me"

    def test_button_empty(self):
        val = NotionConnector._get_prop_value("button", {"type": "button", "button": {}})
        assert val == "[button]"

    def test_unknown_type(self):
        assert NotionConnector._get_prop_value("bogus_type", {"type": "bogus_type"}) is None


# ── _extract_title tests ─────────────────────────────────────────────


class TestExtractTitle:
    def test_title_property_first(self):
        props = {
            "Name": _make_title_prop("My Page"),
        }
        assert NotionConnector._extract_title(props) == "My Page"

    def test_rich_text_fallback(self):
        props = {
            "Notes": _make_rich_text_prop("Fallback title"),
        }
        assert NotionConnector._extract_title(props) == "Fallback title"

    def test_untitled_when_no_text_props(self):
        props = {
            "Status": {"type": "select", "select": {"name": "Done"}},
            "Count": {"type": "number", "number": 5},
        }
        assert NotionConnector._extract_title(props) == "Untitled"


# ── _extract_body tests ──────────────────────────────────────────────


class TestExtractBody:
    def test_extract_body_from_props(self):
        props = {
            "Name": _make_title_prop("My Doc"),
            "Status": {"type": "select", "select": {"name": "Active"}},
            "Priority": {"type": "number", "number": 1},
        }
        body = NotionConnector._extract_body(props)
        assert "Name: My Doc" in body
        assert "Status: Active" in body
        assert "Priority: 1" in body

    def test_skips_empty_values(self):
        props = {
            "Empty": {"type": "rich_text", "rich_text": []},
            "Done": {"type": "checkbox", "checkbox": False},
        }
        body = NotionConnector._extract_body(props)
        # Empty rich_text returns None, False checkbox returns False
        # but "False" != "" so checkbox would appear
        assert body == "Done: False"


# ── _extract_property_summary tests ──────────────────────────────────


class TestExtractPropertySummary:
    def test_extracts_all_props(self):
        props = {
            "Name": _make_title_prop("Page"),
            "Count": {"type": "number", "number": 3},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "dev"}]},
        }
        summary = NotionConnector._extract_property_summary(props)
        assert summary["Name"] == "Page"
        assert summary["Count"] == 3
        assert summary["Tags"] == "dev"

    def test_skips_none_values(self):
        props = {
            "Name": _make_title_prop("Page"),
            "Empty": {"type": "select", "select": None},
        }
        summary = NotionConnector._extract_property_summary(props)
        assert "Name" in summary
        assert "Empty" not in summary


# ── poll() tests ─────────────────────────────────────────────────────


class TestNotionPoll:
    def test_poll_success(self):
        """poll() fetches pages and produces Events."""
        page = _make_page(
            "page-1",
            "Test Page",
            {
                "Title": _make_title_prop("Test Page"),
                "Description": _make_rich_text_prop("A test page."),
            },
        )
        mock_resp = _make_api_response([page])

        with patch("httpx.Client") as MockClient:
            mock_cli = MockClient.return_value.__enter__.return_value
            mock_cli.post.return_value = mock_resp

            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert isinstance(events[0], Event)
        assert "Test Page" in events[0].content
        assert events[0].workspace_id == "ws-1"
        assert events[0].peer_id == "notion-bot"
        assert events[0].memory_type == "experience"
        assert events[0].metadata["source"] == "notion"
        assert events[0].metadata["page_id"] == "page-1"
        assert events[0].metadata["database_id"] == "db-1"
        assert events[0].metadata["url"] == "https://notion.so/page-1"

    def test_poll_empty_database(self):
        mock_resp = _make_api_response([])

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_poll_deduplication(self):
        """poll() skips previously seen pages."""
        page = _make_page("dupe-1", "Dupe", {"Title": _make_title_prop("Dupe")})
        mock_resp = _make_api_response([page])

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")

            first = c.poll()
            second = c.poll()

        assert len(first) == 1
        assert len(second) == 0

    def test_poll_pagination(self):
        """poll() follows pagination cursor."""
        page1 = _make_page("p-1", "Page 1", {"Title": _make_title_prop("Page 1")})
        page2 = _make_page("p-2", "Page 2", {"Title": _make_title_prop("Page 2")})

        resp1 = _make_api_response([page1], has_more=True, next_cursor="cursor-1")
        resp2 = _make_api_response([page2], has_more=False)

        with patch("httpx.Client") as MockClient:
            mock_cli = MockClient.return_value.__enter__.return_value
            mock_cli.post.side_effect = [resp1, resp2]

            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 2
        assert events[0].metadata["page_id"] == "p-1"
        assert events[1].metadata["page_id"] == "p-2"
        assert mock_cli.post.call_count == 2

    def test_poll_rate_limit_429(self):
        """poll() retries after 429 with Retry-After."""
        rate_limit_resp = Mock(status_code=429)
        rate_limit_resp.headers = {"Retry-After": "1"}  # 1 second

        success_resp = _make_api_response(
            [_make_page("p-1", "Page", {"Title": _make_title_prop("Page")})]
        )

        with patch("httpx.Client") as MockClient:
            mock_cli = MockClient.return_value.__enter__.return_value
            mock_cli.post.side_effect = [rate_limit_resp, success_resp]

            with patch("time.sleep", return_value=None) as mock_sleep:
                c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
                events = c.poll()

        assert len(events) == 1
        mock_sleep.assert_called_once_with(1)
        assert mock_cli.post.call_count == 2

    def test_poll_rate_limit_default_retry_after(self):
        """429 without Retry-After header defaults to 5 seconds."""
        rate_limit_resp = Mock(status_code=429)
        # Some responses might not include Retry-After
        rate_limit_resp.headers = {}  # no Retry-After

        success_resp = _make_api_response(
            [_make_page("p-1", "Page", {"Title": _make_title_prop("Page")})]
        )

        with patch("httpx.Client") as MockClient:
            mock_cli = MockClient.return_value.__enter__.return_value
            mock_cli.post.side_effect = [rate_limit_resp, success_resp]

            with patch("time.sleep", return_value=None) as mock_sleep:
                c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
                events = c.poll()

        assert len(events) == 1
        mock_sleep.assert_called_once_with(5)

    def test_poll_unauthorized_401(self):
        """poll() breaks on 401."""
        mock_resp = Mock(status_code=401)

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            c = NotionConnector(token="bad-token", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_poll_unexpected_status(self):
        """poll() breaks on non-200/429/401 status."""
        mock_resp = Mock(status_code=500)

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_poll_request_error(self):
        """poll() catches httpx.RequestError and returns empty list."""
        import httpx

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = httpx.RequestError(
                "Connection failed"
            )
            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_poll_metadata_property_merge(self):
        """poll() merges property summary into metadata without overwriting reserved keys."""
        page = _make_page(
            "page-meta",
            "Meta Page",
            {
                "Title": _make_title_prop("Meta Page"),
                # This property key clashes with reserved metadata key "source"
                "source": {"type": "rich_text", "rich_text": _rich_text("should-not-overwrite")},
                "Priority": {"type": "select", "select": {"name": "High"}},
            },
        )
        mock_resp = _make_api_response([page])

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        # Reserved key should not be overwritten
        assert events[0].metadata["source"] == "notion"
        # But the property value should still be accessible somewhere...
        # In the current implementation the body would contain it
        assert "Priority" in events[0].metadata
        assert events[0].metadata["Priority"] == "High"

    def test_poll_max_pages_limit(self):
        """poll() respects max_pages setting."""
        # Create responses that would produce 3 pages if unrestricted
        pages = [
            _make_page(f"p-{i}", f"Page {i}", {"Title": _make_title_prop(f"Page {i}")})
            for i in range(3)
        ]
        resp1 = _make_api_response([pages[0]], has_more=True, next_cursor="c1")
        resp2 = _make_api_response([pages[1]], has_more=True, next_cursor="c2")
        resp3 = _make_api_response([pages[2]], has_more=False)

        with patch("httpx.Client") as MockClient:
            mock_cli = MockClient.return_value.__enter__.return_value
            mock_cli.post.side_effect = [resp1, resp2, resp3]

            c = NotionConnector(token="tok", database_id="db-1", workspace_id="ws-1", max_pages=2)
            events = c.poll()

        # With max_pages=2, the while loop runs pages=0 then pages=1, then pages=2 which is not < 2
        # So it should make exactly 2 API calls
        assert len(events) == 2
        assert mock_cli.post.call_count == 2
