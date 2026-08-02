import time
from typing import Any

import httpx

from .base import Event, SyncConnector


class GitHubConnector(SyncConnector):
    """Poll GitHub API for public events from a user.

    Queries ``/users/{username}/events`` and supports pagination up to
    30 events per poll.  Deduplicates by event ID.

    Usage::

        connector = GitHubConnector(
            token="ghp_...",
            username="octocat",
            workspace_id="ws-1",
        )
        connector.run(client, interval_secs=600)
    """

    def __init__(
        self,
        token: str,
        username: str,
        workspace_id: str,
        peer_id: str = "github-bot",
        *,
        cursor_dir: str | None = None,
    ):
        super().__init__(cursor_dir=cursor_dir)
        self.token = token
        self.username = username
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self._seen: set[str] = set(self._cursor.get("seen_ids", []))

    def poll(self) -> list[Event]:
        """Fetch user events from the GitHub API and return new Events."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "spacetime-memory-connector",
        }
        url: str | None = f"https://api.github.com/users/{self.username}/events"

        events: list[Event] = []
        fetched = 0

        with httpx.Client() as client:
            while url and fetched < 30:
                try:
                    resp = self._retry_client_call(
                        client,
                        "get",
                        url,
                        headers=headers,
                        timeout=30,
                    )
                except httpx.RequestError as e:
                    self._log.error(
                        "HTTP error after retries: %s",
                        e,
                    )
                    break

                # ── Rate-limit handling ─────────────────────────────
                if resp.status_code == 403:
                    remaining = resp.headers.get("X-RateLimit-Remaining", "")
                    if remaining == "0":
                        reset_epoch = resp.headers.get("X-RateLimit-Reset", "0")
                        try:
                            sleep_secs = max(0, int(reset_epoch) - int(time.time()))
                        except (ValueError, OSError):
                            sleep_secs = 60
                        self._log.warning(
                            "GitHub rate limit exhausted — sleeping %d s until reset (epoch %s)",
                            sleep_secs,
                            reset_epoch,
                        )
                        time.sleep(sleep_secs)
                        continue  # retry after reset
                    self._log.error(
                        "Rate limited or forbidden on %s",
                        url,
                    )
                    break
                if resp.status_code == 404:
                    self._log.error(
                        "User '%s' not found",
                        self.username,
                    )
                    break
                if resp.status_code != 200:
                    self._log.error(
                        "Unexpected status %s on %s",
                        resp.status_code,
                        url,
                    )
                    break

                data = resp.json()
                if not data:
                    break

                for item in data:
                    event_id = str(item.get("id", ""))
                    if event_id in self._seen:
                        continue
                    self._seen.add(event_id)
                    fetched += 1

                    event_type: str = item.get("type", "UnknownEvent")
                    repo_name: str = item.get("repo", {}).get("name", "unknown")
                    actor: str = item.get("actor", {}).get("login", self.username)
                    created_at: str = item.get("created_at", "")
                    payload: dict[str, Any] = item.get("payload", {})

                    content = self._format_event(
                        event_type,
                        actor,
                        repo_name,
                        payload,
                        created_at,
                    )
                    summary = self._summarize_event(event_type, repo_name)

                    events.append(
                        Event(
                            content=content,
                            workspace_id=self.workspace_id,
                            summary=summary,
                            memory_type="experience",
                            peer_id=self.peer_id,
                            metadata={
                                "source": "github",
                                "event_type": event_type,
                                "repo": repo_name,
                            },
                        )
                    )

                # Follow pagination via Link header
                link_header = resp.headers.get("Link", "")
                url = self._parse_next_link(link_header)

        # Persist cursor
        self._cursor["seen_ids"] = list(self._seen)
        self._save_cursor()

        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_next_link(link_header: str) -> str | None:
        """Extract the URL for the next page from a Link header."""
        if not link_header:
            return None
        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                start = part.find("<")
                end = part.find(">")
                if start != -1 and end != -1:
                    return part[start + 1 : end]
        return None

    @staticmethod
    def _format_event(
        event_type: str,
        actor: str,
        repo: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> str:
        """Format a GitHub event into a readable text description."""
        if event_type == "PushEvent":
            commits = payload.get("commits", [])
            ref = payload.get("ref", "").replace("refs/heads/", "")
            lines = [f"{actor} pushed to {ref} in {repo}"]
            for c in commits[:5]:
                msg = c.get("message", "").split("\n")[0]
                lines.append(f"  - {msg}")
            if len(commits) > 5:
                lines.append(f"  ... and {len(commits) - 5} more commits")
            return "\n".join(lines) + f"\nDate: {created_at}"

        elif event_type == "IssuesEvent":
            action = payload.get("action", "opened")
            issue = payload.get("issue", {})
            title = issue.get("title", "")
            number = issue.get("number", "")
            url = issue.get("html_url", "")
            return (
                f"{actor} {action} issue #{number} in {repo}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Date: {created_at}"
            )

        elif event_type == "CreateEvent":
            ref_type = payload.get("ref_type", "unknown")
            ref_name = payload.get("ref", "")
            if ref_type == "branch":
                desc = f"branch '{ref_name}'"
            else:
                desc = ref_type
            return f"{actor} created {desc} in {repo}\nDate: {created_at}"

        elif event_type == "WatchEvent":
            action = payload.get("action", "started")
            return f"{actor} {action} watching {repo}\nDate: {created_at}"

        elif event_type == "ForkEvent":
            forkee = payload.get("forkee", {})
            fork_name = forkee.get("full_name", "unknown")
            return f"{actor} forked {repo} to {fork_name}\nDate: {created_at}"

        elif event_type == "PullRequestEvent":
            action = payload.get("action", "opened")
            pr = payload.get("pull_request", {})
            title = pr.get("title", "")
            number = pr.get("number", "")
            url = pr.get("html_url", "")
            return (
                f"{actor} {action} PR #{number} in {repo}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Date: {created_at}"
            )

        elif event_type == "IssueCommentEvent":
            action = payload.get("action", "created")
            issue = payload.get("issue", {})
            number = issue.get("number", "")
            return f"{actor} {action} comment on issue #{number} in {repo}\nDate: {created_at}"

        else:
            return f"{actor} triggered {event_type} in {repo}\nDate: {created_at}"

    @staticmethod
    def _summarize_event(event_type: str, repo: str) -> str:
        """Generate a short summary line for the event."""
        summaries = {
            "PushEvent": f"Pushed to {repo}",
            "IssuesEvent": f"Issue activity in {repo}",
            "CreateEvent": f"Created reference in {repo}",
            "WatchEvent": f"Starred {repo}",
            "ForkEvent": f"Forked {repo}",
            "PullRequestEvent": f"PR activity in {repo}",
            "IssueCommentEvent": f"Comment on issue in {repo}",
        }
        return summaries.get(event_type, f"Activity in {repo}")


# ── Twitter/X Connector ─────────────────────────────────────────────
