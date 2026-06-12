import json
import hmac
from typing import Any, Optional
from dataclasses import dataclass, field
from .base import Connector, Event
class WebhookConnector(Connector):
    """Receive events via HTTP webhook.

    This connector does **not** poll.  Instead, call ``handle()`` from
    your HTTP handler to process incoming POST data.

    Generic field mapping (first match wins):

    * content ← ``body["content"]`` | ``body["text"]`` | ``body["message"]``
    * summary ← ``body["summary"]`` | ``body["title"]`` | content[:200]
    * metadata ← the full body dict

    If ``secret`` is provided, requests are verified with HMAC-SHA256
    (supports ``X-Hub-Signature-256``, ``X-Signature-Sha256``, and
    ``X-Webhook-Signature`` headers).

    Usage (FastAPI example)::

        connector = WebhookConnector(
            path="/webhook",
            workspace_id="ws-1",
            secret="my-hmac-secret",
        )

        @app.post("/webhook")
        async def webhook(request: Request):
            body = await request.json()
            events = connector.handle(body, dict(request.headers))
            # persist events via client or registry...
    """

    def __init__(
        self,
        path: str,
        workspace_id: str,
        peer_id: str = "webhook",
        secret: str | None = None,
    ):
        self.path = path
        self.workspace_id = workspace_id
        self.peer_id = peer_id
        self.secret = secret

    def poll(self) -> list[Event]:
        """Not applicable for WebhookConnector — returns an empty list."""
        return []

    def handle(
        self,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> list[Event]:
        """Process an incoming webhook payload and return Events.

        Args:
            body: The parsed JSON body of the webhook request.
            headers: Optional HTTP headers (used for HMAC verification).

        Returns:
            A list containing zero or one ``Event`` derived from the body.
        """
        if self.secret:
            self._verify_hmac(body, headers or {})

        # Determine content from common fields
        if isinstance(body, dict):
            content = (
                body.get("content")
                or body.get("text")
                or body.get("message")
                or str(body)
            )
            summary = (
                body.get("summary")
                or body.get("title")
                or str(content)[:200]
            )
            metadata = dict(body)
        else:
            content = str(body)
            summary = content[:200]
            metadata = {"raw": body, "source": "webhook"}

        metadata.setdefault("source", "webhook")
        metadata.setdefault("path", self.path)

        return [
            Event(
                content=str(content),
                workspace_id=self.workspace_id,
                summary=str(summary)[:200],
                memory_type="experience",
                peer_id=self.peer_id,
                metadata=metadata,
            )
        ]

    def _verify_hmac(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Verify HMAC-SHA256 signature from headers.

        Checks for the signature in any of these header names (first
        match wins):

        - ``X-Hub-Signature-256`` (GitHub-style ``sha256=...``)
        - ``X-Signature-Sha256``
        - ``X-Webhook-Signature``

        Raises:
            ValueError: If the signature is missing or does not match.
        """
        import json

        assert self.secret is not None  # type-narrowing guard

        # Check common header names for the signature
        signature = (
            headers.get("x-hub-signature-256")
            or headers.get("x-signature-sha256")
            or headers.get("x-webhook-signature")
            or ""
        )

        if not signature:
            raise ValueError(
                "HMAC verification failed: no signature header found"
            )

        # Handle both "sha256=..." and raw hex formats
        if signature.startswith("sha256="):
            signature = signature[7:]

        body_bytes = json.dumps(
            body, separators=(",", ":"), sort_keys=True,
        ).encode()
        expected = hmac.new(
            self.secret.encode(),
            body_bytes,
            "sha256",
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            raise ValueError(
                "HMAC verification failed: signature mismatch"
            )


# ── Connector Registry ──────────────────────────────────────────────


