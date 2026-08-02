import hashlib
import logging

from .base import Event, SyncConnector

logger = logging.getLogger(__name__)


class OrgModeParser(SyncConnector):
    """Parse Emacs org-mode files and convert to memories / KG nodes.

    You can use this connector in two ways:

    **One-shot** — call ``parse()`` to import a file immediately::

        parser = OrgModeParser(
            file_path="/path/to/notes.org",
            workspace_id="ws-1",
        )
        events = parser.parse()
        for ev in events:
            client.store(...)

    **Polling (daemon)** — register with a ``ConnectorRegistry`` and the
    framework calls ``poll()`` automatically.  Files are re-parsed only
    when their content hash changes (tracked via the base-class cursor)::

        parser = OrgModeParser(
            file_path="/path/to/notes.org",
            workspace_id="ws-1",
        )
        registry.register("my-org", parser)
        # daemon.poll_all() → parser.poll() returns new events
        #                      only when the file changes

    Parsing supports:

    * Headings (``*``, ``**``, …)
    * TODO states (``** TODO``, ``** DONE``)
    * Lists (``- item``)
    * Code blocks (``#+BEGIN_SRC`` / ``#+END_SRC``)
    * Properties drawers (``:PROPERTIES:``)
    * Tags (``:tag1:tag2:`` at end of heading lines)
    """

    def __init__(
        self,
        file_path: str,
        workspace_id: str,
        peer_id: str = "org-parser",
        *,
        memory_type: str = "experience",
        cursor_dir: str | None = None,
    ):
        """Initialise the org-mode parser.

        Args:
            file_path: Path to the ``.org`` file.
            workspace_id: Target workspace UUID.
            peer_id: Name for the memory source (default ``"org-parser"``).
            memory_type: Default memory type to assign (default ``"experience"``).
            cursor_dir: Optional directory for cursor persistence.
        """
        super().__init__(cursor_dir=cursor_dir)
        self.file_path = file_path
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._memory_type = memory_type
        # Load last known file hash from cursor for cross-session dedup.
        # This ensures restarted processes don't re-process unchanged files.
        self._last_file_hash: str = self._cursor.get("file_hash", "")

    def poll(self) -> list[Event]:
        """Poll the org-mode file for changes and return new events.

        Re-parses the file only when its content hash has changed since
        the last call.  Returns the parsed events once; subsequent calls
        return an empty list until the file changes again.

        Returns:
            A list of ``Event`` objects, or ``[]`` if unchanged.
        """
        # Compute current file hash
        try:
            file_hash = self._hash_file()
        except (OSError, FileNotFoundError) as e:
            logger.warning("OrgMode poll error reading %s: %s", self.file_path, e)
            return []

        # Check if file changed since last poll
        cursor_hash = self._cursor.get("file_hash", "")
        if file_hash == cursor_hash:
            return []  # unchanged — already processed this version

        # Dedup within this session: if we already returned events for this
        # hash, avoid returning them again (cursor save may have failed on
        # the first pass, causing a stale cursor on disk but valid in-memory
        # tracking).
        if file_hash == self._last_file_hash:
            # Re-save cursor so on-disk state catches up
            self._cursor["file_hash"] = file_hash
            self._save_cursor()
            return []

        # File changed — parse and cache
        events = self.parse()
        if events:
            self._log.info(
                "OrgMode poll — %s changed, %d events",
                self.file_path,
                len(events),
            )

        # Update tracking.  Cursor persists the hash to disk for cross-session
        # dedup; _last_file_hash prevents re-processing within a session when
        # the disk write fails temporarily.
        self._last_file_hash = file_hash
        self._cursor["file_hash"] = file_hash
        self._save_cursor()
        return events

    def _hash_file(self) -> str:
        """Return SHA-256 hex digest of the file contents."""
        h = hashlib.sha256()
        with open(self.file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def parse(self) -> list[Event]:
        """Read and parse the org-mode file, returning Events.

        Each top-level heading (``*``) becomes an Event.  Nested
        content under the heading is included in the event body.

        Returns:
            A list of ``Event`` objects.  Returns ``[]`` on error.
        """
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            self._log.warning("OrgMode file not found: %s", self.file_path)
            return []
        except OSError as e:
            self._log.error("OrgMode error reading file: %s", e)
            return []

        events: list[Event] = []
        sections = self._parse_sections(lines)

        for section in sections:
            events.append(self._section_to_event(section))

        return events

    def _section_to_event(self, section: dict) -> Event:
        """Convert a parsed section dict into an Event."""
        heading_text = section.get("heading", "(untitled)")
        body_text = section.get("body", "")
        outline_level = section.get("level", 1)
        todo_state = section.get("todo_state", "")
        tags = section.get("tags", [])

        content = heading_text
        if body_text:
            content = f"{heading_text}\n\n{body_text}"

        metadata = {
            "source": "org-mode",
            "file": self.file_path,
            "outline_level": outline_level,
            "tags": tags,
            "todo_state": todo_state,
        }

        return Event(
            content=content,
            workspace_id=self.workspace_id,
            summary=heading_text[:200],
            memory_type=self._memory_type,
            peer_id=self.peer_id,
            metadata=metadata,
        )

    def _parse_sections(
        self,
        lines: list[str],
    ) -> list[dict]:
        """Split org-mode lines into heading-anchored sections."""
        sections: list[dict] = []
        current: dict | None = None
        in_src_block = False
        in_props_drawer = False
        body_lines: list[str] = []

        for line in lines:
            stripped = line.rstrip("\n")

            # Track source blocks
            if stripped.startswith("#+BEGIN_SRC"):
                in_src_block = True
                if current is not None:
                    body_lines.append(stripped)
                continue
            if stripped.startswith("#+END_SRC"):
                in_src_block = False
                if current is not None:
                    body_lines.append(stripped)
                continue

            # Track properties drawers
            if stripped == ":PROPERTIES:":
                in_props_drawer = True
                continue
            if stripped == ":END:":
                in_props_drawer = False
                continue

            # Skip content inside source blocks or property drawers
            if in_src_block or in_props_drawer:
                continue

            # Detect heading
            heading_match = self._match_heading(stripped)
            if heading_match:
                # Finalise previous section
                if current is not None:
                    current["body"] = "\n".join(body_lines)
                    sections.append(current)

                # Start new section
                current = {
                    "heading": heading_match["text"],
                    "level": heading_match["level"],
                    "todo_state": heading_match["todo_state"],
                    "tags": heading_match["tags"],
                }
                body_lines = []
            else:
                # Body content line
                if current is not None:
                    # Skip comment lines
                    if stripped.startswith("# "):
                        continue
                    body_lines.append(stripped)

        # Finalise last section
        if current is not None:
            current["body"] = "\n".join(body_lines)
            sections.append(current)

        return sections

    @staticmethod
    def _match_heading(
        line: str,
    ) -> dict | None:
        """Test if a line is an org-mode heading.

        Returns a dict with keys ``text``, ``level``, ``todo_state``,
        ``tags`` if the line is a heading, else ``None``.
        """
        # Headings start with one or more *
        if not line.startswith("*"):
            return None

        # Count leading asterisks
        level = 0
        for ch in line:
            if ch == "*":
                level += 1
            else:
                break

        # Remainder after the asterisks
        rest = line[level:].strip()
        if not rest:
            return {
                "text": "(empty heading)",
                "level": level,
                "todo_state": "",
                "tags": [],
            }

        # Extract tags at end of line, e.g. ``:tag1:tag2:``
        tags: list[str] = []
        if rest.endswith(":"):
            # Tags are colon-surrounded words at end
            space_idx = rest.rfind(" ", 0, -1)
            maybe_tags = rest[space_idx + 1 :] if space_idx >= 0 else rest
            if maybe_tags.startswith(":") and maybe_tags.count(":") >= 2:
                tags = [t for t in maybe_tags.strip(":").split(":") if t]
                rest = rest[:space_idx].strip() if space_idx >= 0 else ""

        # Extract TODO state (TODO, DONE, or any known keyword)
        todo_state = ""
        keywords = [
            "TODO",
            "DONE",
            "IN-PROGRESS",
            "BLOCKED",
            "CANCELLED",
            "DEFERRED",
            "WAITING",
        ]
        for kw in keywords:
            if rest.startswith(kw) and (
                len(rest) == len(kw) or rest[len(kw)] in (" ", "\t")
            ):
                todo_state = kw
                rest = rest[len(kw) :].strip()
                break

        return {
            "text": rest,
            "level": level,
            "todo_state": todo_state,
            "tags": tags,
        }


# ── SyncConnector Daemon ────────────────────────────────────────────
