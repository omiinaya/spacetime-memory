"""Edge case tests for spacetime-memory SDK.

Covers edge cases mentioned in ROADMAP section 4.1:

- test_empty_search
- test_special_characters
- test_unicode_in_memory
- test_very_large_content
- test_concurrent_writes
- test_network_partition
"""

from __future__ import annotations

import json
import threading
from unittest.mock import Mock

import httpx
import pytest

from tests.conftest import make_sql_response


# ============================================================================
# Empty / edge-case search queries
# ============================================================================

class TestEmptySearch:
    """Edge case: empty, whitespace-only, and near-empty search queries."""

    @pytest.mark.unit
    def test_empty_query_keyword(self, mock_http_client):
        """Search with an empty string (semantic=False) returns empty list."""
        mock_http_client._tantivy_search = Mock(return_value=[])
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([]),
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query="",
            semantic=False,
        )
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.unit
    def test_none_query(self, mock_http_client):
        """Search with query=None does not crash."""
        mock_http_client._tantivy_search = Mock(return_value=[])
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([]),
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query=None,
            semantic=False,
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_whitespace_only_query(self, mock_http_client, monkeypatch):
        """Search with whitespace-only query is handled gracefully."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            resp = Mock(status_code=200)
            resp.text = make_sql_response([])
            resp.json = lambda: []
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        result = mock_http_client.search(
            workspace_id="ws1",
            query="   \t\n  ",
            semantic=True,
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_search_empty_workspace(self, mock_http_client):
        """Search in a workspace that has no data returns empty list."""
        mock_http_client._tantivy_search = Mock(return_value=[])
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([]),
        )
        result = mock_http_client.search(
            workspace_id="nonexistent-ws",
            query="anything",
            semantic=False,
        )
        assert result == []

    @pytest.mark.unit
    def test_search_single_character(self, mock_http_client):
        """Search with a single character returns valid results."""
        mock_http_client._tantivy_search = Mock(return_value=[])
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([]),
        )
        result = mock_http_client.search(
            workspace_id="ws1", query="a", semantic=False,
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_search_special_regex_chars(self, mock_http_client):
        """Search with regex metacharacters does not crash."""
        mock_http_client._tantivy_search = Mock(return_value=[])
        mock_http_client._keyword_fallback = Mock(return_value=[])
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([]),
        )
        result = mock_http_client.search(
            workspace_id="ws1",
            query=r".*+?^$()[]{}|\\",
            semantic=False,
        )
        assert isinstance(result, list)


# ============================================================================
# Special characters in memory content
# ============================================================================

class TestSpecialCharacters:
    """Edge case: special characters in memory content and queries."""

    @pytest.mark.unit
    def test_quotes_in_content(self, mock_http_client, monkeypatch):
        """Memory content with single and double quotes is stored safely."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "It's a \"test\" with 'quotes' and `backticks`"
        result = mock_http_client.store(
            workspace_id="ws1",
            content=content,
            peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_backslashes_in_content(self, mock_http_client, monkeypatch):
        """Memory content with backslashes is stored safely."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "path\\to\\file\\with\\backslashes\nnew\\line"
        result = mock_http_client.store(
            workspace_id="ws1",
            content=content,
            peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_tabs_and_newlines(self, mock_http_client, monkeypatch):
        """Memory with tabs, newlines, and carriage returns is stored safely."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "line1\nline2\r\nline3\ttabbed\tend"
        result = mock_http_client.store(
            workspace_id="ws1",
            content=content,
            peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_html_in_content(self, mock_http_client, monkeypatch):
        """Memory containing HTML markup is stored safely."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "<script>alert('xss')</script> &amp; <tag attr=\"val\">text</tag>"
        result = mock_http_client.store(
            workspace_id="ws1",
            content=content,
            peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_null_byte_in_content(self, mock_http_client, monkeypatch):
        """Memory containing null bytes is stored safely (may be stripped)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "before\x00after"
        try:
            result = mock_http_client.store(
                workspace_id="ws1",
                content=content,
                peer_id="peer1",
            )
            # Either way, no crash
            assert result["status"] == "ok"
        except (TypeError, ValueError):
            pass  # Some runtimes reject null bytes — acceptable

    @pytest.mark.unit
    def test_sql_injection_attempt(self, mock_http_client, monkeypatch):
        """Content designed to look like SQL injection does not crash."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "'; DROP TABLE memory; --"
        result = mock_http_client.store(
            workspace_id="ws1",
            content=content,
            peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_control_characters(self, mock_http_client, monkeypatch):
        """Memory with ASCII control characters is handled without error."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        # Build content with ASCII control chars (0x01-0x1F) excluding tab/newline/CR
        control_chars = "".join(chr(i) for i in range(0x01, 0x20)
                                if i not in (0x09, 0x0A, 0x0D))
        content = f"before{control_chars}after"
        try:
            result = mock_http_client.store(
                workspace_id="ws1",
                content=content,
                peer_id="peer1",
            )
            assert result["status"] == "ok"
        except (TypeError, ValueError):
            pass  # Some runtimes reject control chars — acceptable


# ============================================================================
# Unicode / multi-language memory content
# ============================================================================

class TestUnicodeMemory:
    """Edge case: unicode, emoji, and multi-language content."""

    @pytest.mark.unit
    def test_emoji_content(self, mock_http_client, monkeypatch):
        """Memory content with emoji characters is stored safely."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "Hello world 🌍🔥🎉  Memorable moment! 😊👋🌟"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_cjk_content(self, mock_http_client, monkeypatch):
        """Memory with CJK (Chinese, Japanese, Korean) characters."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "中文测试：记忆存储系统正常运行"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

        content = "日本語テスト：メモリー保存機能確認"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

        content = "한국어 테스트: 메모리 저장 기능 확인"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_rtl_content(self, mock_http_client, monkeypatch):
        """Memory with right-to-left scripts (Arabic, Hebrew)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "اختبار الذاكرة: نظام تخزين البيانات يعمل بشكل طبيعي"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

        content = "בדיקת זיכרון: מערכת אחסון הנתונים פועלת כשורה"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_mixed_scripts(self, mock_http_client, monkeypatch):
        """Memory mixing Latin, CJK, emoji, and accented chars."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = (
            "Café résumé naïve über cool 🚀 "
            "English 中文 日本語 한국어 العربية עברית "
            "emoji: 🧪📦🔬✅"
        )
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_search_with_unicode_query(self, mock_http_client, monkeypatch):
        """Search with unicode query characters works without error."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            resp = Mock(status_code=200)
            resp.text = make_sql_response([])
            resp.json = lambda: []
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        result = mock_http_client.search(
            workspace_id="ws1",
            query="emoji 😊 test",
            semantic=True,
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_store_unicode_with_embedding(self, mock_http_client, monkeypatch):
        """Unicode content with embedding index path works."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        embed_response = Mock(status_code=200)
        embed_response.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

        def post_side_effect(*args, **kwargs):
            if "/embeddings" in str(args[0]):
                return embed_response
            resp = Mock(status_code=200)
            resp.text = "{}"
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        original_sql = mock_http_client._sql
        def sql_side_effect(query):
            if "SELECT id FROM memory" in query:
                return [{"id": "mem-unicode-1"}]
            return original_sql(query)

        mock_http_client._sql = sql_side_effect

        content = "你好世界！Unicode with embeddings test ⚡"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_surrogate_pairs(self, mock_http_client, monkeypatch):
        """Memory with 4-byte UTF-8 surrogate pairs (astral plane) is stored safely."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        # 𐌰 = Gothic 𐌰 (U+10330), 𓀀 = Egyptian hieroglyph A1 (U+13000)
        content = "Astral plane: 𐌰𐌱𓀀𓁩  𒀭𒈹 Gudea cylinder"
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"


# ============================================================================
# Very large content payloads
# ============================================================================

class TestVeryLargeContent:
    """Edge case: large content payloads and query strings."""

    @pytest.mark.unit
    def test_large_content_store(self, mock_http_client, monkeypatch):
        """Store a large content payload (~100 KB)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "Large content test. " * 5000
        assert len(content) > 80_000

        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_very_large_content_store(self, mock_http_client, monkeypatch):
        """Store a very large content payload (~1 MB)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = ("Very large memory content for stress testing the storage "
                   "system. " * 20_000)
        assert len(content) > 500_000

        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_large_content_with_embedding(self, mock_http_client, monkeypatch):
        """Large content with embedding indexing still works."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        embed_response = Mock(status_code=200)
        embed_response.json.return_value = {"data": [{"embedding": [0.1] * 768}]}

        def post_side_effect(*args, **kwargs):
            if "/embeddings" in str(args[0]):
                return embed_response
            resp = Mock(status_code=200)
            resp.text = "{}"
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        original_sql = mock_http_client._sql

        def sql_side_effect(query):
            if "SELECT id FROM memory" in query:
                return [{"id": "mem-large-1"}]
            return original_sql(query)

        mock_http_client._sql = sql_side_effect

        content = "A" * 100_000
        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"

    @pytest.mark.unit
    def test_very_long_search_query(self, mock_http_client, monkeypatch):
        """Search with a very long query string (>10k chars)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            resp = Mock(status_code=200)
            resp.text = make_sql_response([])
            resp.json = lambda: []
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        long_query = "word " * 5000
        result = mock_http_client.search(
            workspace_id="ws1", query=long_query, semantic=True,
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_content_near_limit(self, mock_http_client, monkeypatch):
        """Store content approaching the ~256 KB SpacetimeDB limit."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        content = "X" * 200_000  # ~200 KB, safely under 256 KB limit
        assert len(content) == 200_000

        result = mock_http_client.store(
            workspace_id="ws1", content=content, peer_id="peer1",
        )
        assert result["status"] == "ok"


# ============================================================================
# Concurrent writes from multiple threads
# ============================================================================

class TestConcurrentWrites:
    """Edge case: concurrent writes from multiple threads."""

    @pytest.mark.unit
    def test_concurrent_store_calls(self, mock_http_client, monkeypatch):
        """Multiple threads calling store() simultaneously all succeed."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        call_lock = threading.Lock()
        call_count = [0]

        def post_side_effect(*args, **kwargs):
            with call_lock:
                call_count[0] += 1
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        errors = []
        lock = threading.Lock()

        def worker(wid: int):
            try:
                mock_http_client.store(
                    workspace_id="ws1",
                    content=f"concurrent memory from worker {wid}",
                    peer_id=f"peer-{wid}",
                )
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Concurrent store errors: {errors}"
        assert call_count[0] >= 20

    @pytest.mark.unit
    def test_concurrent_store_same_content(self, mock_http_client, monkeypatch):
        """Multiple threads storing identical content all succeed."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        errors = []
        lock = threading.Lock()

        def worker():
            try:
                mock_http_client.store(
                    workspace_id="ws1",
                    content="identical content from all workers",
                    peer_id="same-peer",
                )
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Concurrent same-content errors: {errors}"

    @pytest.mark.unit
    def test_concurrent_mixed_operations(self, mock_http_client, monkeypatch):
        """Concurrent store, search, and list operations."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])

        def post_side_effect(*args, **kwargs):
            resp = Mock(status_code=200)
            resp.text = make_sql_response([])
            resp.json = lambda: []
            return resp

        mock_http_client._http.post.side_effect = post_side_effect

        errors = []
        lock = threading.Lock()

        def store_worker(i: int):
            try:
                mock_http_client.store(
                    workspace_id="ws1",
                    content=f"mixed op {i}",
                    peer_id="peer1",
                )
            except Exception as e:
                with lock:
                    errors.append(e)

        def search_worker():
            try:
                mock_http_client.search(
                    workspace_id="ws1", query="test", semantic=False,
                )
            except Exception as e:
                with lock:
                    errors.append(e)

        def list_worker():
            try:
                mock_http_client.list_memories(workspace_id="ws1")
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=store_worker, args=(i,)))
            threads.append(threading.Thread(target=search_worker))
            threads.append(threading.Thread(target=list_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(errors) == 0, f"Mixed op errors: {errors}"

    @pytest.mark.unit
    def test_concurrent_store_and_delete(self, mock_http_client, monkeypatch):
        """Concurrent store and delete operations from multiple threads."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_http_client._embed = Mock(return_value=[])
        mock_http_client._sql = Mock(return_value=[])

        call_count = [0]
        call_lock = threading.Lock()

        def post_side_effect(*args, **kwargs):
            with call_lock:
                call_count[0] += 1
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect

        errors = []
        lock = threading.Lock()

        def store_worker(i: int):
            try:
                mock_http_client.store(
                    workspace_id="ws1",
                    content=f"store-del content {i}",
                    peer_id=f"peer-{i}",
                )
            except Exception as e:
                with lock:
                    errors.append(e)

        def delete_worker():
            try:
                mock_http_client.delete_memory(memory_id="mem-to-delete")
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=store_worker, args=(i,)))
            threads.append(threading.Thread(target=delete_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(errors) == 0, f"Concurrent store/delete errors: {errors}"
        # At least some HTTP calls were made
        assert call_count[0] > 0


# ============================================================================
# Network partition / failure scenarios
# ============================================================================

class TestNetworkPartition:
    """Edge case: network failures, timeouts, and partial responses."""

    @pytest.mark.unit
    def test_connection_refused(self, mock_http_client):
        """search handles connection refused gracefully."""
        mock_http_client.max_retries = 1
        mock_http_client._http.post.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(RuntimeError):
            mock_http_client.search(
                workspace_id="ws1", query="test", semantic=False,
            )

    @pytest.mark.unit
    def test_connection_timeout(self, mock_http_client):
        """search handles connection timeout gracefully."""
        mock_http_client.max_retries = 1
        mock_http_client._http.post.side_effect = httpx.TimeoutException("timed out")
        with pytest.raises(RuntimeError):
            mock_http_client.search(
                workspace_id="ws1", query="test", semantic=False,
            )

    @pytest.mark.unit
    def test_all_retries_exhausted(self, mock_http_client):
        """search raises after exhausting all retries on server errors."""
        mock_http_client.max_retries = 2
        mock_http_client._http.post.return_value = Mock(status_code=502)
        with pytest.raises(RuntimeError, match=r"Request failed|circuit breaker"):
            mock_http_client.search(
                workspace_id="ws1", query="test", semantic=False,
            )

    @pytest.mark.unit
    def test_circuit_breaker_on_consecutive_failures(self, mock_http_client):
        """Circuit breaker trips after consecutive failures."""
        mock_http_client._consecutive_failures = 5
        mock_http_client._circuit_breaker_threshold = 3
        mock_http_client._circuit_open_until = float("inf")
        with pytest.raises(RuntimeError, match=r"circuit breaker"):
            mock_http_client.search(
                workspace_id="ws1", query="test", semantic=False,
            )

    @pytest.mark.unit
    def test_store_with_http_503(self, mock_http_client):
        """store handles HTTP 503 (service unavailable)."""
        mock_http_client._http.post.return_value = Mock(
            status_code=503, text="Service Unavailable",
        )
        with pytest.raises(RuntimeError, match=r"Request failed"):
            mock_http_client.store(
                workspace_id="ws1", content="test", peer_id="peer1",
            )

    @pytest.mark.unit
    def test_store_with_http_500(self, mock_http_client):
        """store handles HTTP 500 (internal server error)."""
        mock_http_client._http.post.return_value = Mock(
            status_code=500, text="Internal Error",
        )
        with pytest.raises(RuntimeError, match=r"Request failed"):
            mock_http_client.store(
                workspace_id="ws1", content="test", peer_id="peer1",
            )

    @pytest.mark.unit
    def test_store_with_http_400(self, mock_http_client):
        """store returns 400 error without retry (client error, not retried)."""
        mock_http_client._http.post.return_value = Mock(
            status_code=400, text="Bad Request",
        )
        with pytest.raises(RuntimeError):
            mock_http_client.store(
                workspace_id="ws1", content="test", peer_id="peer1",
            )

    @pytest.mark.unit
    def test_malformed_response(self, mock_http_client):
        """Client handles malformed JSON response with an appropriate error."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="not valid json {{{",
            json=Mock(side_effect=json.JSONDecodeError("Expecting value", "doc", 0)),
        )
        with pytest.raises(json.JSONDecodeError):
            mock_http_client._sql("SELECT * FROM nothing")

    @pytest.mark.unit
    def test_intermittent_failure(self, mock_http_client):
        """Retry after 503 succeeds — verifies retry logic recovers."""
        mock_http_client.max_retries = 2

        attempt = [0]

        def post_side_effect(*args, **kwargs):
            attempt[0] += 1
            if attempt[0] == 1:
                raise httpx.ConnectError("First attempt fails")
            if attempt[0] == 2:
                return Mock(status_code=503, text="Service Unavailable")
            # Third attempt succeeds
            return Mock(status_code=200, text="{}")

        mock_http_client._http.post.side_effect = post_side_effect
        mock_http_client._http.get.return_value = Mock(status_code=200)

        # The store method with semantic=False hits _sql endpoint.
        # It goes through _call -> _request_with_retry.
        result = mock_http_client.store(
            workspace_id="ws1", content="recovered content", peer_id="peer1",
        )
        assert result["status"] == "ok"
        assert attempt[0] >= 3
