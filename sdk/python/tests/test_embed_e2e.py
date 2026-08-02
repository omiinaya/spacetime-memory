"""
Embedding E2E tests — exercise the real embedding path via the OpenAI-compatible proxy.

Requires the spacetime-llm proxy running (or a direct OpenAI-compatible endpoint)
and the following environment variables set:
  - OPENAI_API_KEY
  - OPENAI_BASE_URL (defaults to http://localhost:4000/v1 for the proxy)
  - EMBEDDING_MODEL (defaults to baai/bge-m3)

These tests validate that the embedding pipeline actually returns valid 1024-dim
vectors from NVIDIA NIM through the proxy.  They are NOT mocked — they test the
real infrastructure.
"""

from __future__ import annotations

import os

import pytest

from spacetime_memory import Client


def _embedder_env_set() -> bool:
    """Check whether the required embedder environment variables are configured."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def _embedder_url_reachable(url: str, timeout: float = 3.0) -> bool:
    """Check whether the embedding endpoint is reachable."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 443
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect((host, port))
        return True
    except (ConnectionRefusedError, OSError):
        return False
    finally:
        s.close()


@pytest.mark.embedder
class TestEmbedderE2E:
    """End-to-end tests that exercise the real embedding pipeline."""

    @pytest.fixture(autouse=True)
    def require_embedder(self):
        """Skip all embedder tests if env vars or proxy are not available."""
        if not _embedder_env_set():
            pytest.skip(
                "OPENAI_API_KEY not set — cannot run embedding E2E tests. "
                "Set OPENAI_API_KEY + OPENAI_BASE_URL + EMBEDDING_MODEL."
            )
        base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:4000/v1")
        if not _embedder_url_reachable(base_url):
            pytest.skip(
                f"Embedding endpoint {base_url} not reachable. Make sure the proxy is running."
            )

    @pytest.fixture
    def embed_client(self) -> Client:
        """Create a real Client that talks to the embedding proxy."""
        base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:4000/v1")
        return Client(
            host="localhost",
            port="3001",
            database="spacetime-memory-embed-e2e",
            embedder_url=base_url,
        )

    def test_embed_single_text_returns_vector(self, embed_client: Client):
        """_embed() returns a non-empty list of floats when the proxy responds."""
        result = embed_client._embed("hello world")
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) > 0, "Embedding vector should not be empty"
        assert len(result) == 1024, f"bge-m3 embeddings should be 1024-dim, got {len(result)}"
        assert all(isinstance(v, float) for v in result), "All elements should be floats"
        # Verify it's not all zeros (proxy should return real embeddings)
        non_zero = sum(1 for v in result if abs(v) > 1e-10)
        assert non_zero > 10, (
            f"Expected real (non-zero) embedding values, got only {non_zero} non-zero out of {len(result)}"
        )

    def test_embed_different_texts_produce_different_vectors(self, embed_client: Client):
        """Different inputs produce different embeddings."""
        v1 = embed_client._embed("quantum computing")
        v2 = embed_client._embed("baking cookies")
        assert v1 != v2, "Different texts should produce different embeddings"

    def test_embed_empty_string_graceful(self, embed_client: Client):
        """Empty string gracefully returns [] (API rejects empty input)."""
        result = embed_client._embed("")
        # The proxy/NIM rejects empty strings, client catches and returns []
        assert isinstance(result, list)
        assert len(result) == 0, "Empty string should return [] since APIs reject it"

    def test_embed_batch_returns_correct_count(self, embed_client: Client):
        """_embed_batch() returns the correct number of vectors."""
        texts = [
            "machine learning",
            "deep learning",
            "natural language processing",
        ]
        results = embed_client._embed_batch(texts)
        assert isinstance(results, list), f"Expected list, got {type(results)}"
        assert len(results) == 3, f"Expected 3 vectors, got {len(results)}"
        for i, vec in enumerate(results):
            assert len(vec) == 1024, f"Vector {i} should be 1024-dim, got {len(vec)}"
            assert all(isinstance(v, float) for v in vec), f"Vector {i} elements should be floats"

    def test_embed_batch_single_item(self, embed_client: Client):
        """_embed_batch() with a single text returns one vector."""
        results = embed_client._embed_batch(["single text"])
        assert len(results) == 1
        assert len(results[0]) == 1024

    def test_embed_batch_empty_list(self, embed_client: Client):
        """_embed_batch() with empty list returns empty list."""
        results = embed_client._embed_batch([])
        assert results == []

    def test_embed_unicode_text(self, embed_client: Client):
        """Non-ASCII text should embed correctly (bge-m3 is multilingual)."""
        texts = [
            "你好世界",  # Chinese
            "こんにちは世界",  # Japanese
            "Привет мир",  # Russian
            "Hallo welt",  # German
        ]
        for text in texts:
            result = embed_client._embed(text)
            assert len(result) == 1024, (
                f"Unicode text '{text}' should produce 1024-dim vector, got {len(result)}"
            )
