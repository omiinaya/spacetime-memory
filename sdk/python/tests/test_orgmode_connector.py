"""Tests for OrgModeParser connector.

Tests cover:
- parse() with various org-mode constructs (headings, TODO states, tags, lists, code blocks, properties drawers)
- _match_heading() static method for all heading patterns
- _parse_sections() for section splitting
- Error handling (file not found, OSError)
- poll() returns empty list
"""

import os
import tempfile
from unittest.mock import patch

from spacetime_memory.connectors import OrgModeParser


class TestOrgModeParserInit:
    """Constructor and basic attributes."""

    def test_default_peer_id(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        assert p.file_path == "/tmp/test.org"
        assert p.workspace_id == "ws-1"
        assert p.peer_id == "org-parser"

    def test_custom_peer_id(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-2", peer_id="custom-parser")
        assert p.peer_id == "custom-parser"

    def test_poll_returns_empty(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        assert p.poll() == []


class TestMatchHeading:
    """_match_heading() static method tests."""

    def test_not_a_heading(self):
        result = OrgModeParser._match_heading("This is just text")
        assert result is None

    def test_single_star_heading(self):
        result = OrgModeParser._match_heading("* My heading")
        assert result is not None
        assert result["text"] == "My heading"
        assert result["level"] == 1
        assert result["todo_state"] == ""
        assert result["tags"] == []

    def test_nested_heading(self):
        result = OrgModeParser._match_heading("**** Deeply nested")
        assert result["text"] == "Deeply nested"
        assert result["level"] == 4

    def test_todo_heading(self):
        result = OrgModeParser._match_heading("* TODO Write tests")
        assert result["text"] == "Write tests"
        assert result["level"] == 1
        assert result["todo_state"] == "TODO"

    def test_done_heading(self):
        result = OrgModeParser._match_heading("* DONE Finished feature")
        assert result["text"] == "Finished feature"
        assert result["todo_state"] == "DONE"

    def test_in_progress_heading(self):
        result = OrgModeParser._match_heading("** IN-PROGRESS Build feature")
        assert result["level"] == 2
        assert result["todo_state"] == "IN-PROGRESS"
        assert result["text"] == "Build feature"

    def test_blocked_heading(self):
        result = OrgModeParser._match_heading("* BLOCKED Waiting on dep")
        assert result["todo_state"] == "BLOCKED"
        assert result["text"] == "Waiting on dep"

    def test_cancelled_heading(self):
        result = OrgModeParser._match_heading("* CANCELLED Not needed")
        assert result["todo_state"] == "CANCELLED"

    def test_deferred_heading(self):
        result = OrgModeParser._match_heading("* DEFERRED Later")
        assert result["todo_state"] == "DEFERRED"

    def test_waiting_heading(self):
        result = OrgModeParser._match_heading("* WAITING For input")
        assert result["todo_state"] == "WAITING"

    def test_heading_with_tags(self):
        result = OrgModeParser._match_heading("* My task :work:urgent:")
        assert result["text"] == "My task"
        assert result["tags"] == ["work", "urgent"]

    def test_heading_with_single_tag(self):
        result = OrgModeParser._match_heading("** Sub ::tag1:")
        assert result["text"] == "Sub"
        assert result["tags"] == ["tag1"]
        assert result["level"] == 2

    def test_empty_heading(self):
        result = OrgModeParser._match_heading("*")
        assert result is not None
        assert result["text"] == "(empty heading)"
        assert result["level"] == 1

    def test_empty_heading_multiple_stars(self):
        result = OrgModeParser._match_heading("***")
        assert result["level"] == 3
        assert result["text"] == "(empty heading)"

    def test_todo_with_tags(self):
        result = OrgModeParser._match_heading("** TODO Review code :dev:review:")
        assert result["todo_state"] == "TODO"
        assert result["text"] == "Review code"
        assert result["tags"] == ["dev", "review"]
        assert result["level"] == 2


class TestParseSections:
    """_parse_sections() tests."""

    def test_single_section(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = ["* Section One\n", "Body line 1\n", "Body line 2\n"]
        sections = p._parse_sections(lines)
        assert len(sections) == 1
        assert sections[0]["heading"] == "Section One"
        assert sections[0]["level"] == 1
        assert "Body line 1" in sections[0]["body"]
        assert "Body line 2" in sections[0]["body"]

    def test_multiple_sections(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = [
            "* First\n",
            "First body\n",
            "** Second\n",
            "Second body\n",
            "* Third\n",
            "Third body\n",
        ]
        sections = p._parse_sections(lines)
        assert len(sections) == 3
        assert sections[0]["heading"] == "First"
        assert sections[1]["heading"] == "Second"
        assert sections[2]["heading"] == "Third"
        assert sections[1]["level"] == 2

    def test_sections_with_todo(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = [
            "* TODO Do thing\n",
            "Pending work\n",
            "* DONE Done thing\n",
            "Completed\n",
        ]
        sections = p._parse_sections(lines)
        assert sections[0]["todo_state"] == "TODO"
        assert sections[1]["todo_state"] == "DONE"

    def test_sections_with_tags(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = ["* Important thing :urgent:\n", "Details\n"]
        sections = p._parse_sections(lines)
        assert sections[0]["tags"] == ["urgent"]

    def test_skips_source_blocks(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = [
            "* My code\n",
            "#+BEGIN_SRC python\n",
            "def hello():\n",
            "    pass\n",
            "#+END_SRC\n",
            "After block\n",
        ]
        sections = p._parse_sections(lines)
        assert len(sections) == 1
        assert "After block" in sections[0]["body"]
        # Source block content should NOT appear in body
        assert "def hello()" not in sections[0]["body"]

    def test_skips_properties_drawer(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = [
            "* Task\n",
            ":PROPERTIES:\n",
            ":ID: abc-123\n",
            ":END:\n",
            "Real body\n",
        ]
        sections = p._parse_sections(lines)
        assert len(sections) == 1
        assert "Real body" in sections[0]["body"]
        assert ":ID:" not in sections[0]["body"]

    def test_skips_comments(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = [
            "* Heading\n",
            "# This is a comment\n",
            "Real content\n",
        ]
        sections = p._parse_sections(lines)
        assert "# This is a comment" not in sections[0]["body"]
        assert "Real content" in sections[0]["body"]

    def test_empty_file(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        sections = p._parse_sections([])
        assert sections == []

    def test_no_headings(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = ["Just some text\n", "More text\n"]
        sections = p._parse_sections(lines)
        assert sections == []

    def test_heading_with_trailing_content(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        lines = [
            "* Section\n",
            "Body line\n",
            "Still body\n",
            "** Subsection\n",
            "Sub body\n",
        ]
        sections = p._parse_sections(lines)
        assert len(sections) == 2
        assert "Still body" in sections[0]["body"]


class TestParse:
    """parse() method tests using temp files."""

    def _write_org_file(self, content: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".org", delete=False) as f:
            f.write(content)
            return f.name

    def test_parse_simple_file(self):
        content = (
            "* Project Alpha\n"
            "  Some notes about alpha.\n"
            "** TODO Implement feature\n"
            "   Need to add the API endpoint.\n"
            "* DONE Setup CI\n"
            "  CI is running on GitHub Actions.\n"
        )
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-test")
            events = p.parse()
            assert len(events) == 3

            # Event 0: Project Alpha
            assert events[0].content.startswith("Project Alpha")
            assert "Some notes" in events[0].content
            assert events[0].workspace_id == "ws-test"
            assert events[0].memory_type == "experience"
            assert events[0].peer_id == "org-parser"
            assert events[0].metadata["source"] == "org-mode"
            assert events[0].metadata["file"] == path
            assert events[0].metadata["outline_level"] == 1
            assert events[0].metadata["todo_state"] == ""

            # Event 1: TODO Implement feature
            assert events[1].metadata["outline_level"] == 2
            assert events[1].metadata["todo_state"] == "TODO"
            assert "Implement feature" in events[1].content

            # Event 2: DONE Setup CI
            assert events[2].metadata["todo_state"] == "DONE"
            assert "Setup CI" in events[2].summary
        finally:
            os.unlink(path)

    def test_parse_with_tags(self):
        content = "* Review PR #42 :dev:review:\n  Feedback provided.\n"
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-x")
            events = p.parse()
            assert len(events) == 1
            assert events[0].metadata["tags"] == ["dev", "review"]
            assert "Review PR #42" in events[0].content
        finally:
            os.unlink(path)

    def test_parse_with_code_blocks(self):
        content = (
            "* Code snippet\n"
            "  Example:\n"
            "#+BEGIN_SRC python\n"
            "print('hello')\n"
            "#+END_SRC\n"
            "  This is visible after the block.\n"
        )
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-y")
            events = p.parse()
            assert len(events) == 1
            assert "print('hello')" not in events[0].content
            assert "This is visible after the block" in events[0].content
        finally:
            os.unlink(path)

    def test_parse_with_properties(self):
        content = "* Meeting notes\n:PROPERTIES:\n:DATE: 2024-01-15\n:END:\n  Discussed roadmap.\n"
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-z")
            events = p.parse()
            assert len(events) == 1
            assert "Discussed roadmap" in events[0].content
            assert ":DATE:" not in events[0].content
        finally:
            os.unlink(path)

    def test_parse_with_comment_lines(self):
        content = (
            "* Heading\n# This is a comment, should be hidden\n  Visible text\n# Another comment\n"
        )
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-c")
            events = p.parse()
            assert len(events) == 1
            assert "This is a comment" not in events[0].content
            assert "Another comment" not in events[0].content
            assert "Visible text" in events[0].content
        finally:
            os.unlink(path)

    def test_parse_file_not_found(self):
        p = OrgModeParser(file_path="/nonexistent/path/file.org", workspace_id="ws-1")
        events = p.parse()
        assert events == []

    def test_parse_empty_file(self):
        path = self._write_org_file("")
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-e")
            events = p.parse()
            assert events == []
        finally:
            os.unlink(path)

    def test_parse_file_with_only_body_no_headings(self):
        content = "Just some text without any heading.\nMore text.\n"
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-b")
            events = p.parse()
            assert events == []
        finally:
            os.unlink(path)

    def test_parse_summary_truncation(self):
        long_heading = "X" * 300
        content = f"* {long_heading}\nBody\n"
        path = self._write_org_file(content)
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws-t")
            events = p.parse()
            assert len(events) == 1
            assert len(events[0].summary) == 200  # truncated to 200
        finally:
            os.unlink(path)

    def test_parse_oserror(self):
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-1")
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            events = p.parse()
        assert events == []


# ── Hash File ─────────────────────────────────────────────────────────


class TestOrgModeHashFile:
    """_hash_file() computes SHA-256 digest."""

    def test_hash_file_returns_hexdigest(self):
        """_hash_file returns a hex digest for an existing file."""
        content = b"Hello, org-mode world!\n"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            path = f.name
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws")
            digest = p._hash_file()
            assert isinstance(digest, str)
            assert len(digest) == 64  # SHA-256 is 64 hex chars
            assert all(c in "0123456789abcdef" for c in digest)
        finally:
            os.unlink(path)

    def test_hash_file_file_not_found(self):
        """_hash_file raises FileNotFoundError for missing file."""
        p = OrgModeParser(file_path="/nonexistent/org.org", workspace_id="ws")
        try:
            p._hash_file()
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_hash_file_changes_when_content_changes(self):
        """Different content produces different hashes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".org", delete=False) as f:
            f.write("* Original\n")
            path = f.name
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws")
            hash1 = p._hash_file()

            with open(path, "w") as f:
                f.write("* Modified\n")
            hash2 = p._hash_file()

            assert hash1 != hash2
        finally:
            os.unlink(path)


# ── Section to Event ──────────────────────────────────────────────────


class TestOrgModeSectionToEvent:
    """_section_to_event() conversion."""

    def test_basic_section_conversion(self):
        """A basic section dict is converted to an Event."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test")
        section = {"heading": "My Heading", "body": "Body text", "level": 1, "todo_state": "", "tags": []}
        ev = p._section_to_event(section)
        assert ev is not None
        assert ev.content == "My Heading\n\nBody text"
        assert ev.summary == "My Heading"
        assert ev.workspace_id == "ws-test"
        assert ev.metadata["source"] == "org-mode"
        assert ev.metadata["outline_level"] == 1
        assert ev.metadata["todo_state"] == ""
        assert ev.metadata["tags"] == []

    def test_section_no_body(self):
        """Section with no body only uses heading as content."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test")
        section = {"heading": "Empty", "body": "", "level": 1, "todo_state": "", "tags": []}
        ev = p._section_to_event(section)
        assert ev.content == "Empty"

    def test_section_with_todo_state(self):
        """TODO state is forwarded to metadata."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test")
        section = {"heading": "Task", "body": "Details", "level": 2, "todo_state": "TODO", "tags": []}
        ev = p._section_to_event(section)
        assert ev.metadata["todo_state"] == "TODO"
        assert ev.metadata["outline_level"] == 2

    def test_section_with_tags(self):
        """Tags are forwarded to metadata."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test")
        section = {"heading": "Tagged", "body": "", "level": 1, "todo_state": "", "tags": ["work", "urgent"]}
        ev = p._section_to_event(section)
        assert ev.metadata["tags"] == ["work", "urgent"]

    def test_section_untitled_fallback(self):
        """Missing heading falls back to (untitled)."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test")
        section = {"body": "Bare body", "level": 1, "todo_state": "", "tags": []}
        ev = p._section_to_event(section)
        assert "(untitled)" in ev.content

    def test_file_path_in_metadata(self):
        """File path is included in metadata."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test")
        section = {"heading": "X", "body": "", "level": 1, "todo_state": "", "tags": []}
        ev = p._section_to_event(section)
        assert ev.metadata["file"] == "/tmp/test.org"

    def test_peer_id_in_event(self):
        """Peer ID is forwarded from the connector."""
        p = OrgModeParser(file_path="/tmp/test.org", workspace_id="ws-test", peer_id="my-org")
        section = {"heading": "X", "body": "", "level": 1, "todo_state": "", "tags": []}
        ev = p._section_to_event(section)
        assert ev.peer_id == "my-org"


# ── Poll ──────────────────────────────────────────────────────────────


class TestOrgModePoll:
    """poll() change detection."""

    def test_poll_first_call_returns_events(self):
        """First poll parses file and returns events."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".org", delete=False) as f:
            f.write("* Only heading\nContent.\n")
            path = f.name
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws")
            events = p.poll()
            assert len(events) == 1
            assert "Only heading" in events[0].content
        finally:
            os.unlink(path)

    def test_poll_returns_empty_on_no_change(self):
        """Second call returns empty when file hasn't changed."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".org", delete=False) as f:
            f.write("* Static heading\n")
            path = f.name
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws")
            events1 = p.poll()
            assert len(events1) == 1

            events2 = p.poll()
            assert events2 == []
        finally:
            os.unlink(path)

    def test_poll_returns_new_events_after_file_change(self):
        """After modifying file, poll returns new events."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".org", delete=False) as f:
            f.write("* First version\n")
            path = f.name
        try:
            p = OrgModeParser(file_path=path, workspace_id="ws")
            p.poll()  # first poll

            # Modify file
            with open(path, "w") as f:
                f.write("* Second version\n")
            events = p.poll()
            assert len(events) == 1
            assert "Second version" in events[0].content
        finally:
            os.unlink(path)

    def test_poll_nonexistent_file(self):
        """Poll with nonexistent file returns empty (same as init)."""
        p = OrgModeParser(file_path="/nonexistent/file.org", workspace_id="ws")
        events = p.poll()
        assert events == []
