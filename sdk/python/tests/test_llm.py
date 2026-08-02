"""Tests for spacetime_memory.llm — LLMClient with httpx mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from spacetime_memory.llm import LLMClient

# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


def _make_mock_response(content: str, status_code: int = 200):
    """Build a mock httpx response with .json() and .raise_for_status()."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ═══════════════════════════════════════════════════════════════════
# LLMClient.__init__ and LLMClient.available
# ═══════════════════════════════════════════════════════════════════


class TestLLMClientInit:
    """Tests for LLMClient.__init__ and .available."""

    def test_init_explicit_values(self):
        """All values passed explicitly."""
        client = LLMClient(
            api_key="sk-test",
            base_url="https://custom.example.com/v1",
            model="gpt-5",
        )
        assert client.api_key == "sk-test"
        assert client.base_url == "https://custom.example.com/v1"
        assert client.model == "gpt-5"
        assert client.available is True

    def test_init_api_key_from_env(self, monkeypatch):
        """api_key from OPENAI_API_KEY env var."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        assert client.api_key == "sk-from-env"
        assert client.available is True

    def test_init_api_key_from_litellm_fallback(self, monkeypatch):
        """api_key falls back to LITELLM_MASTER_KEY when OPENAI_API_KEY is empty."""
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-litellm")
        client = LLMClient()
        assert client.api_key == "sk-litellm"
        assert client.available is True

    def test_init_no_api_key_anywhere(self, monkeypatch):
        """No api_key set anywhere -> available is False."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        assert client.api_key == ""
        assert client.available is False

    def test_init_base_url_from_env(self, monkeypatch):
        """base_url from OPENAI_BASE_URL env var."""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://myproxy.com/v1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient()
        assert client.base_url == "https://myproxy.com/v1"

    def test_init_base_url_default(self, monkeypatch):
        """Default base_url when not set in env."""
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient()
        assert client.base_url == "https://api.openai.com/v1"

    def test_init_base_url_strips_trailing_slash(self, monkeypatch):
        """base_url strips trailing slash."""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1/")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient()
        assert client.base_url == "https://api.example.com/v1"

    def test_init_model_from_env(self, monkeypatch):
        """model from LLM_MODEL env var."""
        monkeypatch.setenv("LLM_MODEL", "gpt-4-turbo")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient()
        assert client.model == "gpt-4-turbo"

    def test_init_model_default(self, monkeypatch):
        """Default model when LLM_MODEL not set."""
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient()
        assert client.model == "un-qwen3.6-plus"

    def test_init_explicit_overrides_env(self, monkeypatch):
        """Explicit args override env vars."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example.com/v1")
        monkeypatch.setenv("LLM_MODEL", "env-model")
        client = LLMClient(
            api_key="sk-explicit",
            base_url="https://explicit.example.com/v1",
            model="explicit-model",
        )
        assert client.api_key == "sk-explicit"
        assert client.base_url == "https://explicit.example.com/v1"
        assert client.model == "explicit-model"

    def test_available_with_key(self):
        """available is True when api_key is truthy."""
        client = LLMClient(api_key="sk-xxx")
        assert client.available is True

    def test_available_without_key(self):
        """available is False when api_key is empty string."""
        client = LLMClient.__new__(LLMClient)
        client.api_key = ""
        assert client.available is False


# ═══════════════════════════════════════════════════════════════════
# LLMClient.chat
# ═══════════════════════════════════════════════════════════════════


class TestLLMClientChat:
    """Tests for LLMClient.chat()."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        return LLMClient(api_key="sk-test")

    def test_chat_not_available(self, monkeypatch):
        """Returns None when client is not available."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        result = client.chat([{"role": "user", "content": "hello"}])
        assert result is None

    def test_chat_success(self, client):
        """Successful chat call returns content string."""
        mock_resp = _make_mock_response("Hello, world!")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
            assert result == "Hello, world!"
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["json"]["model"] == client.model
            assert call_args[1]["json"]["messages"] == [{"role": "user", "content": "hi"}]
            assert call_args[1]["json"]["temperature"] == 0.3
            assert call_args[1]["json"]["max_tokens"] == 1024
            assert "response_format" not in call_args[1]["json"]

    def test_chat_with_response_format(self, client):
        """chat() passes response_format when provided."""
        mock_resp = _make_mock_response('{"key": "val"}')
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = client.chat(
                [{"role": "user", "content": "x"}],
                response_format={"type": "json_object"},
            )
            assert result == '{"key": "val"}'
            assert mock_post.call_args[1]["json"]["response_format"] == {"type": "json_object"}

    def test_chat_custom_temperature_and_tokens(self, client):
        """chat() uses custom temperature and max_tokens."""
        mock_resp = _make_mock_response("ok")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.chat(
                [{"role": "user", "content": "x"}],
                temperature=0.7,
                max_tokens=512,
            )
            assert mock_post.call_args[1]["json"]["temperature"] == 0.7
            assert mock_post.call_args[1]["json"]["max_tokens"] == 512

    def test_chat_custom_timeout(self, client):
        """chat() passes timeout to httpx.post."""
        mock_resp = _make_mock_response("ok")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.chat([{"role": "user", "content": "x"}], timeout=30)
            assert mock_post.call_args[1]["timeout"] == 30

    def test_chat_connect_error(self, client):
        """ConnectError returns None."""
        with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
            result = client.chat([{"role": "user", "content": "x"}])
            assert result is None

    def test_chat_timeout_exception(self, client):
        """TimeoutException returns None."""
        with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
            result = client.chat([{"role": "user", "content": "x"}])
            assert result is None

    def test_chat_remote_protocol_error(self, client):
        """RemoteProtocolError returns None."""
        with patch(
            "httpx.post",
            side_effect=httpx.RemoteProtocolError("protocol error"),
        ):
            result = client.chat([{"role": "user", "content": "x"}])
            assert result is None

    def test_chat_http_status_error(self, client):
        """HTTPStatusError returns None."""
        mock_resp = _make_mock_response("", status_code=500)
        with patch("httpx.post", return_value=mock_resp):
            result = client.chat([{"role": "user", "content": "x"}])
            assert result is None

    def test_chat_authorization_header(self, client):
        """Authorization header uses Bearer token."""
        mock_resp = _make_mock_response("ok")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.chat([{"role": "user", "content": "x"}])
            headers = mock_post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer sk-test"
            assert headers["Content-Type"] == "application/json"

    def test_chat_url_constructed_correctly(self, client):
        """URL is base_url + /chat/completions."""
        mock_resp = _make_mock_response("ok")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.chat([{"role": "user", "content": "x"}])
            assert mock_post.call_args[0][0] == f"{client.base_url}/chat/completions"


# ═══════════════════════════════════════════════════════════════════
# LLMClient.summarize
# ═══════════════════════════════════════════════════════════════════


class TestLLMClientSummarize:
    """Tests for LLMClient.summarize()."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        return LLMClient(api_key="sk-test")

    def test_summarize_not_available(self, monkeypatch):
        """Returns None when client is not available."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        result = client.summarize("Some text to summarize")
        assert result is None

    def test_summarize_without_instruction(self, client):
        """Summarize without extra instruction."""
        mock_resp = _make_mock_response("Summary.")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = client.summarize("Long text here")
            assert result == "Summary."
            messages = mock_post.call_args[1]["json"]["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert "precise summarization assistant" in messages[0]["content"]
            assert "Long text here" in messages[1]["content"]

    def test_summarize_with_instruction(self, client):
        """Summarize with extra instruction appended to system prompt."""
        mock_resp = _make_mock_response("Summary.")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = client.summarize("Text", instruction="Be brief.")
            assert result == "Summary."
            system_content = mock_post.call_args[1]["json"]["messages"][0]["content"]
            assert "Be brief." in system_content

    def test_summarize_chat_returns_none(self, client):
        """When chat returns None, summarize returns None."""
        with patch.object(client, "chat", return_value=None):
            result = client.summarize("text")
            assert result is None


# ═══════════════════════════════════════════════════════════════════
# LLMClient.extract_facts
# ═══════════════════════════════════════════════════════════════════


class TestLLMClientExtractFacts:
    """Tests for LLMClient.extract_facts()."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        return LLMClient(api_key="sk-test")

    def test_extract_facts_not_available(self, monkeypatch):
        """Returns None when client is not available."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        result = client.extract_facts("some text")
        assert result is None

    def test_extract_facts_chat_returns_none(self, client):
        """When chat returns None, extract_facts returns None."""
        with patch.object(client, "chat", return_value=None):
            result = client.extract_facts("text")
            assert result is None

    def test_extract_facts_json_array(self, client):
        """Result is a JSON array of strings."""
        json_str = json.dumps(["fact one", "fact two", "fact three"])
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            assert result == ["fact one", "fact two", "fact three"]

    def test_extract_facts_dict_with_facts_key(self, client):
        """Result is a dict with 'facts' key."""
        json_str = json.dumps({"facts": ["fact a", "fact b"]})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            assert result == ["fact a", "fact b"]

    def test_extract_facts_dict_with_fact_key(self, client):
        """Result is a dict with 'fact' key."""
        json_str = json.dumps({"fact": ["single fact"]})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            assert result == ["single fact"]

    def test_extract_facts_dict_with_items_key(self, client):
        """Result is a dict with 'items' key."""
        json_str = json.dumps({"items": ["item 1", "item 2"]})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            assert result == ["item 1", "item 2"]

    def test_extract_facts_dict_with_statements_key(self, client):
        """Result is a dict with 'statements' key."""
        json_str = json.dumps({"statements": ["stmt a", "stmt b"]})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            assert result == ["stmt a", "stmt b"]

    def test_extract_facts_dict_unknown_key_fallback(self, client):
        """Dict with no known keys returns [str(data)] (Python repr, not JSON)."""
        json_str = json.dumps({"random_key": 42})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            # str(data) on a dict produces Python repr: "{'random_key': 42}"
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], str)
            assert "random_key" in result[0]
            assert "42" in result[0]

    def test_extract_facts_dict_non_list_value(self, client):
        """Dict key exists but value is not a list -> falls through to [str(data)]."""
        json_str = json.dumps({"facts": "not-a-list"})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_facts("text")
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], str)

    def test_extract_facts_json_decode_error(self, client):
        """Invalid JSON returns None."""
        with patch.object(client, "chat", return_value="not json at all!!!"):
            result = client.extract_facts("text")
            assert result is None

    def test_extract_facts_type_error(self, client):
        """Chat returns something that json.loads can't handle -> returns None."""
        with patch.object(client, "chat", return_value=42):
            # json.loads(42) raises TypeError
            result = client.extract_facts("text")
            assert result is None

    def test_extract_facts_sends_json_object_response_format(self, client):
        """extract_facts uses response_format={'type': 'json_object'}."""
        mock_resp = _make_mock_response('["fact"]')
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.extract_facts("text")
            assert mock_post.call_args[1]["json"]["response_format"] == {"type": "json_object"}
            assert mock_post.call_args[1]["json"]["temperature"] == 0.1


# ═══════════════════════════════════════════════════════════════════
# LLMClient.summarize_community
# ═══════════════════════════════════════════════════════════════════


class TestLLMClientSummarizeCommunity:
    """Tests for LLMClient.summarize_community()."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        return LLMClient(api_key="sk-test")

    @pytest.fixture
    def sample_nodes(self):
        return [
            {"name": "Alice", "summary": "A software engineer"},
            {"name": "Bob", "summary": "A product manager"},
            {"name": "Charlie"},
        ]

    @pytest.fixture
    def sample_edges(self):
        return [
            {
                "relation": "works_with",
                "fact": "Alice and Bob collaborate on Project X",
                "source_node": "uuid-alice-1234567890",
                "target_node": "uuid-bob-1234567890",
            },
            {
                "relation": "manages",
                "source_node": "uuid-bob-1234567890",
                "target_node": "uuid-charlie-12345678",
            },
        ]

    def test_summarize_community_not_available(self, monkeypatch):
        """Returns None when client is not available."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        result = client.summarize_community("Test", [], [])
        assert result is None

    def test_summarize_community_success(self, client, sample_nodes, sample_edges):
        """Builds prompt and calls summarize."""
        mock_resp = _make_mock_response("A community summary.")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = client.summarize_community("Engineering", sample_nodes, sample_edges)
            assert result == "A community summary."
            # Verify the prompt was constructed
            messages = mock_post.call_args[1]["json"]["messages"]
            user_content = messages[1]["content"]
            assert "## Community: Engineering" in user_content
            assert "### Nodes (3)" in user_content
            assert "### Edges (2)" in user_content
            assert "Alice: A software engineer" in user_content
            assert "Bob: A product manager" in user_content
            assert "- Charlie" in user_content  # no summary
            assert "works_with" in user_content
            assert "manages" in user_content
            assert "Alice and Bob collaborate" in user_content

    def test_summarize_community_nodes_with_label_fallback(self, client):
        """Nodes use 'label' as fallback when 'name' is missing."""
        nodes = [{"label": "NodeLabel", "summary": "desc"}]
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", nodes, [])
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            assert "NodeLabel: desc" in user_content

    def test_summarize_community_nodes_no_name_no_label(self, client):
        """Node without name or label renders '?'."""
        nodes = [{}]
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", nodes, [])
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            assert "- ?" in user_content

    def test_summarize_community_edges_with_name_fallback(self, client):
        """Edges use 'name' fallback for relation."""
        edges = [
            {
                "name": "custom_rel",
                "source_node": "src-uuid-123",
                "target_node": "tgt-uuid-456",
            }
        ]
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", [], edges)
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            assert "[custom_rel]" in user_content

    def test_summarize_community_edges_source_node_uuid_fallback(self, client):
        """Edges use source_node_uuid when source_node is missing."""
        edges = [
            {
                "relation": "test_rel",
                "source_node_uuid": "src-fallback-uuid-here",
                "target_node": "tgt-uuid-456",
            }
        ]
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", [], edges)
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            # truncated to first 12 chars
            assert "src-fallback" in user_content

    def test_summarize_community_edges_target_node_uuid_fallback(self, client):
        """Edges use target_node_uuid when target_node is missing."""
        edges = [
            {
                "relation": "test_rel",
                "source_node": "src-uuid-123",
                "target_node_uuid": "tgt-fallback-uuid",
            }
        ]
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", [], edges)
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            assert "tgt-fallback" in user_content

    def test_summarize_community_edge_no_source_no_target(self, client):
        """Edge missing both source and target renders '?'."""
        edges = [{"relation": "unknown_rel"}]
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", [], edges)
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            # source defaults to "?", target defaults to "?"
            assert "?" in user_content

    def test_summarize_community_empty(self, client):
        """Empty nodes and edges still produces a prompt."""
        mock_resp = _make_mock_response("Empty community.")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = client.summarize_community("Empty", [], [])
            assert result == "Empty community."
            user_content = mock_post.call_args[1]["json"]["messages"][1]["content"]
            assert "### Nodes (0)" in user_content
            assert "### Edges (0)" in user_content

    def test_summarize_community_instruction_included(self, client):
        """summarize_community passes instruction to summarize."""
        mock_resp = _make_mock_response("summary")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.summarize_community("C", [], [])
            system_content = mock_post.call_args[1]["json"]["messages"][0]["content"]
            assert "Be concise. 2-4 sentences." in system_content


# ═══════════════════════════════════════════════════════════════════
# LLMClient.extract_entities_llm
# ═══════════════════════════════════════════════════════════════════


class TestLLMClientExtractEntitiesLLM:
    """Tests for LLMClient.extract_entities_llm()."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        return LLMClient(api_key="sk-test")

    def test_extract_entities_not_available(self, monkeypatch):
        """Returns None when client is not available."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        client = LLMClient()
        result = client.extract_entities_llm("text")
        assert result is None

    def test_extract_entities_chat_returns_none(self, client):
        """When chat returns None, extract_entities_llm returns None."""
        with patch.object(client, "chat", return_value=None):
            result = client.extract_entities_llm("text")
            assert result is None

    def test_extract_entities_with_entities_key(self, client):
        """Result has 'entities' key with list."""
        json_str = json.dumps(
            {
                "entities": [
                    {
                        "name": "Alice",
                        "entity_type": "person",
                        "aliases": ["Al"],
                        "description": "Engineer",
                    },
                    {"name": "Acme Corp", "entity_type": "company"},
                ]
            }
        )
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_entities_llm("text")
            assert len(result) == 2
            assert result[0]["name"] == "Alice"
            assert result[0]["entity_type"] == "person"
            assert result[1]["name"] == "Acme Corp"

    def test_extract_entities_with_items_key(self, client):
        """Result has 'items' key instead of 'entities'."""
        json_str = json.dumps(
            {
                "items": [
                    {"name": "Bob", "entity_type": "person"},
                ]
            }
        )
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_entities_llm("text")
            assert len(result) == 1
            assert result[0]["name"] == "Bob"

    def test_extract_entities_neither_key_returns_empty(self, client):
        """Dict without 'entities' or 'items' returns empty list."""
        json_str = json.dumps({"something_else": [1, 2, 3]})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_entities_llm("text")
            assert result == []

    def test_extract_entities_json_decode_error(self, client):
        """Invalid JSON returns None."""
        with patch.object(client, "chat", return_value="garbage json!!!"):
            result = client.extract_entities_llm("text")
            assert result is None

    def test_extract_entities_type_error(self, client):
        """chat returns non-string -> TypeError -> returns None."""
        with patch.object(client, "chat", return_value=12345):
            result = client.extract_entities_llm("text")
            assert result is None

    def test_extract_entities_non_list_entities_value(self, client):
        """'entities' key exists but value is not a list -> returns [] (isinstance check)."""
        json_str = json.dumps({"entities": "not-a-list"})
        with patch.object(client, "chat", return_value=json_str):
            result = client.extract_entities_llm("text")
            assert result == []

    def test_extract_entities_sends_json_object_format(self, client):
        """extract_entities_llm passes response_format and temperature."""
        mock_resp = _make_mock_response('{"entities": []}')
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            client.extract_entities_llm("text")
            assert mock_post.call_args[1]["json"]["response_format"] == {"type": "json_object"}
            assert mock_post.call_args[1]["json"]["temperature"] == 0.1
