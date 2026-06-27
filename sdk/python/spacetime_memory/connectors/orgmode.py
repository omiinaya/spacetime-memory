from .base import Connector, Event


class OrgModeParser(Connector):
    """Parse Emacs org-mode files and convert to memories / KG nodes.

    This connector is **not a poller** — it has a ``parse()`` method
    instead of ``poll()``.  Call ``parse()`` once to import the file.

    Parsing supports:

    * Headings (``*``, ``**``, …)
    * TODO states (``** TODO``, ``** DONE``)
    * Lists (``- item``)
    * Code blocks (``#+BEGIN_SRC`` / ``#+END_SRC``)
    * Properties drawers (``:PROPERTIES:``)
    * Tags (``:tag1:tag2:`` at end of heading lines)

    Usage::

        parser = OrgModeParser(
            file_path="/path/to/notes.org",
            workspace_id="ws-1",
        )
        events = parser.parse()
        for ev in events:
            client.store(...)
    """

    def __init__(
        self,
        file_path: str,
        workspace_id: str,
        peer_id: str = "org-parser",
    ):
        self.file_path = file_path
        self.workspace_id = workspace_id
        self.peer_id = peer_id

    def poll(self) -> list[Event]:
        """Not applicable for OrgModeParser — returns empty list."""
        return []

    def parse(self) -> list[Event]:
        """Read and parse the org-mode file, returning Events.

        Each top-level heading (``*``) becomes an Event.  Nested
        content under the heading is included in the event body.
        """
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"  [OrgMode] File not found: {self.file_path}")
            return []
        except OSError as e:
            print(f"  [OrgMode] Error reading file: {e}")
            return []

        events: list[Event] = []
        sections = self._parse_sections(lines)

        for section in sections:
            heading_text = section["heading"]
            body_text = section["body"]
            outline_level = section["level"]
            todo_state = section["todo_state"]
            tags = section["tags"]

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

            events.append(
                Event(
                    content=content,
                    workspace_id=self.workspace_id,
                    summary=heading_text[:200],
                    memory_type="experience",
                    peer_id=self.peer_id,
                    metadata=metadata,
                )
            )

        return events

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
            if rest.startswith(kw) and (len(rest) == len(kw) or rest[len(kw)] in (" ", "\t")):
                todo_state = kw
                rest = rest[len(kw) :].strip()
                break

        return {
            "text": rest,
            "level": level,
            "todo_state": todo_state,
            "tags": tags,
        }


# ── Connector Daemon ────────────────────────────────────────────
