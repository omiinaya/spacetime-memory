"""Dedicated WebhookConnector tests.

Augments the Webhook tests in test_connectors.py with additional
coverage: HMAC signature verification, header parsing, body format
edge cases, and poll behavior.

All tests use mock httpx — no live endpoints needed.
"""

import hmac
import json

import pytest

from spacetime_memory.connectors import WebhookConnector


class TestWebhookInit:
    """Constructor edge cases."""

    def test_init_minimal(self):
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        assert c.path == "/hook"
        assert c.workspace_id == "ws-1"
        assert c.peer_id == "webhook"
        assert c.secret is None

    def test_init_with_secret(self):
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret="s3kret")
        assert c.secret == "s3kret"

    def test_init_custom_peer_id(self):
        c = WebhookConnector(path="/hook", workspace_id="ws-1", peer_id="my-hook")
        assert c.peer_id == "my-hook"

    def test_path_preserved(self):
        """Path with slashes and special chars preserved."""
        c = WebhookConnector(path="/webhook/v2/data", workspace_id="ws-1")
        assert c.path == "/webhook/v2/data"


class TestWebhookHandle:
    """Webhook handle() method edge cases."""

    def test_handle_empty_dict_body(self):
        """Empty dict body uses str(body) as content."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({})
        assert len(events) == 1
        assert "{}" in events[0].content

    def test_handle_with_content_field(self):
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"content": "hello", "summary": "greeting"})
        assert events[0].content == "hello"
        assert events[0].summary == "greeting"

    def test_handle_with_text_field(self):
        """Falls back to 'text' field."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"text": "fallback text"})
        assert events[0].content == "fallback text"

    def test_handle_with_message_field(self):
        """Falls back to 'message' field."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"message": "msg fallback"})
        assert events[0].content == "msg fallback"

    def test_handle_field_precedence(self):
        """'content' takes priority over 'text' and 'message'."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({
            "content": "primary",
            "text": "secondary",
            "message": "tertiary",
        })
        assert events[0].content == "primary"

    def test_handle_summary_from_title(self):
        """Falls back to 'title' field for summary."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"content": "hello", "title": "S"})
        assert events[0].summary == "S"

    def test_handle_str_body(self):
        """Non-dict body is converted to string."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle("just a string body")
        assert "just a string body" in events[0].content

    def test_handle_int_body(self):
        """Integer body works via str()."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle(42)
        assert "42" in events[0].content

    def test_handle_list_body(self):
        """List body is converted to string."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle([1, 2, 3])
        assert events[0].content is not None

    def test_handle_none_body(self):
        """None body is converted."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle(None)
        assert len(events) == 1

    def test_handle_metadata_includes_path(self):
        """Metadata has 'path' key set to connector path."""
        c = WebhookConnector(path="/my-webhook", workspace_id="ws-1")
        events = c.handle({"content": "test"})
        assert events[0].metadata.get("path") == "/my-webhook"

    def test_handle_metadata_includes_source(self):
        """Metadata has 'source' key set to 'webhook'."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"content": "test"})
        assert events[0].metadata.get("source") == "webhook"

    def test_handle_summary_truncation(self):
        """Long summary is truncated to 200 chars."""
        long_text = "A" * 500
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"content": long_text, "summary": long_text})
        assert len(events[0].summary) == 200

    def test_handle_very_large_body(self):
        """Handle very large body dict."""
        large = {f"key_{i}": f"value_{i}" for i in range(1000)}
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle(large)
        assert len(events) == 1

    def test_handle_poll_returns_empty(self):
        """poll() always returns empty list."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        assert c.poll() == []


class TestWebhookHMAC:
    """HMAC signature verification."""

    def _compute_signature(self, secret: str, body: dict) -> str:
        """Compute HMAC-SHA256 hex digest for body."""
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        return hmac.new(secret.encode(), body_bytes, "sha256").hexdigest()

    def test_hmac_valid_github_style(self):
        """Valid GitHub-style X-Hub-Signature-256 header."""
        secret = "mysecret"
        body = {"content": "hello", "ref": "main"}
        sig = self._compute_signature(secret, body)
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret=secret)
        events = c.handle(body, {"x-hub-signature-256": f"sha256={sig}"})
        assert len(events) == 1
        assert events[0].content == "hello"

    def test_hmac_valid_custom_header(self):
        """Valid X-Webhook-Signature header (no sha256= prefix)."""
        secret = "s3kret"
        body = {"content": "data"}
        sig = self._compute_signature(secret, body)
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret=secret)
        events = c.handle(body, {"x-webhook-signature": sig})
        assert len(events) == 1

    def test_hmac_valid_x_signature_sha256(self):
        """Valid X-Signature-Sha256 header."""
        secret = "abc123"
        body = {"msg": "test"}
        sig = self._compute_signature(secret, body)
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret=secret)
        events = c.handle(body, {"x-signature-sha256": sig})
        assert len(events) == 1

    def test_hmac_invalid_signature(self):
        """Invalid signature raises ValueError."""
        secret = "mysecret"
        body = {"content": "hello"}
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret=secret)
        with pytest.raises(ValueError, match="HMAC verification failed"):
            c.handle(body, {"x-hub-signature-256": "sha256=badbadbad"})

    def test_hmac_missing_header(self):
        """Missing signature header when secret is set raises ValueError."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret="secret")
        with pytest.raises(ValueError, match="no signature header found"):
            c.handle({"content": "test"}, {})

    def test_hmac_no_secret_skips_verification(self):
        """No secret = no HMAC verification."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1")
        events = c.handle({"content": "test"}, {})
        assert len(events) == 1

    def test_hmac_null_secret_is_none(self):
        """Secret=None means no HMAC."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret=None)
        assert c.secret is None

    def test_hmac_empty_secret(self):
        """Empty string secret is still used for HMAC."""
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret="")
        assert c.secret == ""
        with pytest.raises(ValueError, match="no signature header found"):
            c.handle({"content": "test"}, {})

    def test_hmac_header_startswith_sha256(self):
        """sha256= prefix is stripped."""
        secret = "test"
        body = {"key": "value"}
        sig = self._compute_signature(secret, body)
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret=secret)
        # With prefix
        events = c.handle(body, {"x-hub-signature-256": f"sha256={sig}"})
        assert len(events) == 1

    def test_hmac_same_body_different_secret_fails(self):
        """Different secret produces different signature."""
        body = {"content": "test"}
        sig_correct = self._compute_signature("secret1", body)
        c = WebhookConnector(path="/hook", workspace_id="ws-1", secret="secret2")
        with pytest.raises(ValueError, match="signature mismatch"):
            c.handle(body, {"x-hub-signature-256": f"sha256={sig_correct}"})
