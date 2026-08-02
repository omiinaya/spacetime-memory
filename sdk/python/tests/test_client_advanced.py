"""Tests for the SDK Client — advanced features."""

import json
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from spacetime_memory import Client

# ── Multi-region / Failover ────────────────────────────────────────────


class TestMultiRegionFailover:
    """Fallback between multiple STDB hosts."""

    def test_init_single_host_default(self):
        """Client._hosts defaults to [host:port] when SPACETIMEDB_HOSTS is unset."""
        c = Client(host="myhost", port="3001", database="test-db")
        assert c._hosts == ["myhost:3001"]
        assert c.host == "myhost"
        assert c.port == "3001"
        assert c.sql_url == "http://myhost:3001/v1/database/test-db/sql"

    def test_init_multi_hosts_from_env(self, monkeypatch):
        """Client parses SPACETIMEDB_HOSTS into _hosts list."""
        monkeypatch.setenv("SPACETIMEDB_HOSTS", "host1:3001,host2:4000,host3:5000")
        c = Client(database="test-db")
        assert c._hosts == ["host1:3001", "host2:4000", "host3:5000"]
        assert c.host == "host1"
        assert c.port == "3001"

    def test_try_failover_noop_when_single_host(self):
        """_try_failover returns False when only one host is configured."""
        c = Client(host="h", port="1", database="d")
        assert c._try_failover() is False
        assert c.host == "h"

    def test_try_failover_switches_host(self):
        """_try_failover switches to next host in the list."""
        c = Client(host="host1", port="3001", database="test-db")
        c._hosts = ["host1:3001", "host2:4000"]
        c._current_host_index = 0

        assert c._try_failover() is True
        assert c.host == "host2"
        assert c.port == "4000"
        assert c._current_host_index == 1
        # URL rebuild
        assert "host2" in c.sql_url
        assert "4000" in c.reducer_url
        # Circuit breaker reset
        assert c._consecutive_failures == 0
        assert c._circuit_open_until == 0.0

    def test_request_with_retry_failover_on_connect_error(self, monkeypatch):
        """_request_with_retry fails over to next host on ConnectError."""
        monkeypatch.setenv("SPACETIMEDB_HOSTS", "host1:3001,host2:3001")
        monkeypatch.setenv("STMEM_MAX_RETRIES", "1")  # Min retries to speed test
        c = Client(database="test-db")
        # Track which host each call targets
        call_history: list[str] = []

        def mock_post(url, **kw):
            call_history.append(url[:30])  # Just host prefix
            if "host1" in url:
                raise httpx.ConnectError("Connection refused to host1")
            return Mock(status_code=200, text=json.dumps([]))

        c._http.post = mock_post
        c._http.get = Mock(return_value=Mock(status_code=200, headers={}))

        # This should succeed via failover to host2
        resp = c._request_with_retry("POST", c.sql_url, content="test")
        assert resp.status_code == 200
        # Should have switched to host2
        assert c.host == "host2"
        # First calls went to host1, final call to host2
        assert any("host2" in url for url in call_history)

    def test_ensure_identity_tries_all_hosts(self, monkeypatch):
        """_ensure_identity tries all hosts, pins to first responsive one."""
        monkeypatch.setenv("SPACETIMEDB_HOSTS", "dead:3001,alive:4000")
        c = Client(database="test-db")
        c._identity_established = False
        c._identity_token = None

        call_log = []

        def mock_get(url, **kw):
            call_log.append(url)
            if "dead" in url:
                raise httpx.ConnectError("dead host")
            return Mock(
                status_code=200,
                headers={
                    "spacetime-identity-token": "tok123",
                },
            )

        c._http.get = mock_get

        c._ensure_identity()
        assert c._identity_established is True
        assert c._identity_token == "tok123"
        # Pinned to second host
        assert c.host == "alive"
        assert c.port == "4000"
        assert c._current_host_index == 1


class TestGetMemoryHistory:
    """get_memory_history() — returns revision history from memory_revision table."""

    def test_get_memory_history_with_revisions(self, mock_http_client):
        """Returns revision history from memory_revision table, sorted by version."""
        client = mock_http_client
        memory_id = "mem_001"

        # Mock _query to return revision records for memory_revision
        client._query = MagicMock(
            return_value=[
                {
                    "version": 1,
                    "previous_content": "",
                    "previous_summary": "",
                    "previous_confidence": 0.0,
                    "new_content": "original content",
                    "new_summary": "original summary",
                    "new_confidence": 0.8,
                    "changed_at": 1000,
                    "changed_by": "user1",
                },
                {
                    "version": 2,
                    "previous_content": "original content",
                    "previous_summary": "original summary",
                    "previous_confidence": 0.8,
                    "new_content": "updated content",
                    "new_summary": "updated summary",
                    "new_confidence": 0.9,
                    "changed_at": 2000,
                    "changed_by": "user2",
                },
            ]
        )

        # The second _query call (for current memory state) should return the latest
        client._query.side_effect = None  # Reset
        # Make repeated calls return different values based on the table name

        def side_effect(table, **kw):
            if table == "memory_revision":
                return [
                    {
                        "version": 1,
                        "previous_content": "",
                        "previous_summary": "",
                        "previous_confidence": 0.0,
                        "new_content": "original content",
                        "new_summary": "original summary",
                        "new_confidence": 0.8,
                        "changed_at": 1000,
                        "changed_by": "user1",
                    },
                    {
                        "version": 2,
                        "previous_content": "original content",
                        "previous_summary": "original summary",
                        "previous_confidence": 0.8,
                        "new_content": "updated content",
                        "new_summary": "updated summary",
                        "new_confidence": 0.9,
                        "changed_at": 2000,
                        "changed_by": "user2",
                    },
                ]
            if table == "memory":
                return [
                    {
                        "content": "updated content",
                        "summary": "updated summary",
                        "version": 2,
                        "updated_at": 2000,
                        "confidence": 0.9,
                    }
                ]
            return []

        client._query = MagicMock(side_effect=side_effect)

        history = client.get_memory_history(memory_id)

        # Should have 2 revision entries (no duplicate current state since version 2 matches)
        assert len(history) == 2
        assert history[0]["version"] == 1
        assert history[0]["content"] == "original content"
        assert history[0]["previous_content"] == ""
        assert history[1]["version"] == 2
        assert history[1]["content"] == "updated content"
        assert history[1]["previous_content"] == "original content"

    def test_get_memory_history_no_revisions(self, mock_http_client):
        """Returns empty list when memory has no revisions and doesn't exist."""
        client = mock_http_client

        # Both queries return empty
        client._query = MagicMock(return_value=[])

        history = client.get_memory_history("nonexistent")
        assert history == []

    def test_get_memory_history_current_only(self, mock_http_client):
        """Returns current state when memory exists but has no revision history."""
        client = mock_http_client

        def side_effect(table, **kw):
            if table == "memory_revision":
                return []
            if table == "memory":
                return [
                    {
                        "content": "current content",
                        "summary": "current summary",
                        "version": 1,
                        "updated_at": 3000,
                        "confidence": 0.7,
                    }
                ]
            return []

        client._query = MagicMock(side_effect=side_effect)

        history = client.get_memory_history("mem_002")

        assert len(history) == 1
        assert history[0]["version"] == 1
        assert history[0]["content"] == "current content"
        assert history[0]["previous_content"] == ""

    def test_get_memory_history_newer_current_state(self, mock_http_client):
        """When current state has a higher version than last revision, append it."""
        client = mock_http_client

        def side_effect(table, **kw):
            if table == "memory_revision":
                return [
                    {
                        "version": 1,
                        "previous_content": "",
                        "previous_summary": "",
                        "previous_confidence": 0.0,
                        "new_content": "v1 content",
                        "new_summary": "v1 summary",
                        "new_confidence": 0.8,
                        "changed_at": 1000,
                        "changed_by": "user1",
                    },
                ]
            if table == "memory":
                return [
                    {
                        "content": "v2 content",
                        "summary": "v2 summary",
                        "version": 2,
                        "updated_at": 2000,
                        "confidence": 0.9,
                    }
                ]
            return []

        client._query = MagicMock(side_effect=side_effect)

        history = client.get_memory_history("mem_003")

        assert len(history) == 2
        assert history[0]["version"] == 1
        assert history[0]["content"] == "v1 content"
        assert history[1]["version"] == 2
        assert history[1]["content"] == "v2 content"
        assert history[1]["previous_content"] == ""


class TestEntityAwareBoost:
    """Tests for _boost_with_entity_signal — entity-aware search boosting."""

    def test_boost_no_entities_in_query(self, mock_http_client):
        """No boost when query doesn't match any KG node labels."""
        mock_http_client._query = MagicMock(
            return_value=[
                {
                    "id": "n1",
                    "label": "RLHF",
                    "summary": "Reinforcement learning from human feedback",
                    "node_type": "concept",
                },
            ]
        )

        rows = [
            {"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF is a training method"},
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "Supervised fine-tuning"},
        ]

        result = mock_http_client._boost_with_entity_signal("some unrelated query", rows, "default")
        assert result[0]["fused_score"] == 0.8  # Unchanged
        assert result[1]["fused_score"] == 0.6  # Unchanged

    def test_boost_entity_exact_match(self, mock_http_client):
        """Boost when query exactly matches an entity label."""
        mock_http_client._query = MagicMock(
            return_value=[
                {
                    "id": "n1",
                    "label": "RLHF",
                    "summary": "Reinforcement learning from human feedback",
                    "node_type": "concept",
                },
                {
                    "id": "n2",
                    "label": "LoRA",
                    "summary": "Low-rank adaptation",
                    "node_type": "concept",
                },
            ]
        )

        rows = [
            {
                "entity_id": "m1",
                "fused_score": 0.8,
                "memory_content": "RLHF is a training method for LLMs",
            },
            {
                "entity_id": "m2",
                "fused_score": 0.6,
                "memory_content": "Supervised fine-tuning of base models",
            },
            {
                "entity_id": "m3",
                "fused_score": 0.4,
                "memory_content": "LoRA is a parameter-efficient technique",
            },
        ]

        result = mock_http_client._boost_with_entity_signal(
            "tell me about RLHF", rows, "default", boost_factor=0.15
        )

        # m1 mentions RLHF → gets boosted (because RLHF appears in query + content)
        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8
        assert result[0].get("entity_boost", 0) > 0

        # m3 mentions LoRA but query is about RLHF → not boosted
        assert result[2]["entity_id"] == "m3"
        assert result[2]["fused_score"] == 0.4

        # m2 has no entity match → unchanged
        assert result[1]["entity_id"] == "m2"
        assert result[1]["fused_score"] == 0.6

    def test_boost_multiple_entity_hits(self, mock_http_client):
        """Boost scales with proportion of matched entities in content."""
        mock_http_client._query = MagicMock(
            return_value=[
                {"id": "n1", "label": "RLHF", "summary": "", "node_type": "concept"},
                {"id": "n2", "label": "LoRA", "summary": "", "node_type": "concept"},
            ]
        )

        rows = [
            # Mentions both RLHF and LoRA when both entities match query
            {"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF and LoRA combined"},
            # Mentions only one
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "Only RLHF here"},
        ]

        result = mock_http_client._boost_with_entity_signal(
            "RLHF LoRA comparison", rows, "default", boost_factor=0.15
        )

        # m1 has both entities → proportion = 2/2 = 1.0 → max boost
        # m2 has one entity → proportion = 1/2 = 0.5 → half boost
        assert result[0]["entity_id"] == "m1"
        assert result[1]["entity_id"] == "m2"
        boost_m1 = result[0].get("entity_boost", 0)
        boost_m2 = result[1].get("entity_boost", 0)
        assert boost_m1 > boost_m2
        assert abs(boost_m1 - 0.15) < 0.001  # max boost
        assert abs(boost_m2 - 0.075) < 0.001  # half boost

    def test_boost_word_level_overlap(self, mock_http_client):
        """Boost fires when a word from entity label overlaps query words."""
        mock_http_client._query = MagicMock(
            return_value=[
                {"id": "n1", "label": "Neural Networks", "summary": "", "node_type": "concept"},
            ]
        )

        rows = [
            {
                "entity_id": "m1",
                "fused_score": 0.8,
                "memory_content": "neural networks are powerful",
            },
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "just some text"},
        ]

        result = mock_http_client._boost_with_entity_signal(
            "neural networks in ML", rows, "default", boost_factor=0.15
        )

        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8
        # m2 unchanged
        assert result[1]["entity_id"] == "m2"
        assert result[1]["fused_score"] == 0.6

    def test_boost_summary_match(self, mock_http_client):
        """Boost fires when the query substring appears in entity summary, and result content mentions the entity label."""
        mock_http_client._query = MagicMock(
            return_value=[
                {
                    "id": "n1",
                    "label": "PEFT",
                    "summary": "Parameter-efficient fine-tuning for large models",
                    "node_type": "concept",
                },
            ]
        )

        rows = [
            # Content mentions the entity label "PEFT"
            {
                "entity_id": "m1",
                "fused_score": 0.8,
                "memory_content": "PEFT (parameter efficient fine tuning) is useful",
            },
            # Content doesn't mention the entity label — no boost
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "just some unrelated text"},
        ]

        result = mock_http_client._boost_with_entity_signal(
            "parameter-efficient fine-tuning", rows, "default", boost_factor=0.15
        )

        # m1 mentions PEFT → boosted (entity matched via summary, content mentions label)
        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8
        assert result[0].get("entity_boost", 0) > 0

        # m2 doesn't mention PEFT → unchanged
        assert result[1]["entity_id"] == "m2"
        assert result[1]["fused_score"] == 0.6

    def test_boost_no_nodes_found(self, mock_http_client):
        """No boost when KG has no nodes (graceful degradation)."""
        mock_http_client._query = MagicMock(return_value=[])

        rows = [{"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF content"}]
        result = mock_http_client._boost_with_entity_signal("RLHF", rows, "default")
        assert result[0]["fused_score"] == 0.8

    def test_boost_query_lookup_fails(self, mock_http_client):
        """No boost when KG query raises RuntimeError (graceful degradation)."""
        mock_http_client._query = MagicMock(side_effect=RuntimeError("db error"))

        rows = [{"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF content"}]
        result = mock_http_client._boost_with_entity_signal("RLHF", rows, "default")
        assert result[0]["fused_score"] == 0.8

    def test_boost_empty_rows(self, mock_http_client):
        """No boost when rows list is empty."""
        result = mock_http_client._boost_with_entity_signal("RLHF", [], "default")
        assert result == []

    def test_boost_integrated_in_search_called(self, mock_http_client):
        """Verify _boost_with_entity_signal is called during search()."""
        from unittest.mock import patch

        # Mock _embed to return valid embedding
        mock_http_client._embed = MagicMock(return_value=[0.1, 0.2, 0.3])
        # Mock _call for hybrid_search and query_table
        mock_http_client._call = MagicMock(return_value={"status": "ok"})
        # Mock _sql to return empty results
        mock_http_client._sql = MagicMock(return_value=[])
        # Mock _tantivy_search
        mock_http_client._tantivy_search = MagicMock(return_value=[])
        # Spy on _boost_with_entity_signal
        with patch.object(
            mock_http_client,
            "_boost_with_entity_signal",
            wraps=mock_http_client._boost_with_entity_signal,
        ) as spy:
            mock_http_client.search("default", "RLHF", semantic=True, limit=5)
            spy.assert_called_once()

    # --- Alias-based entity boosting via entity_link ---

    def test_boost_entity_link_alias_in_query(self, mock_http_client):
        """Boost fires when query contains an entity_link alias."""
        # First _query call returns kg_node (empty), second returns entity_link
        mock_http_client._query = MagicMock(
            side_effect=[
                [],  # kg_node: no nodes
                [  # entity_link: one record with aliases
                    {
                        "id": "el1",
                        "entity_name": "RLHF",
                        "aliases_json": '["reinforcement learning from human feedback", "RL from human feedback"]',
                        "entity_type": "concept",
                    }
                ],
            ]
        )

        rows = [
            {"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF is a training method"},
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "Supervised fine-tuning"},
        ]

        result = mock_http_client._boost_with_entity_signal(
            "reinforcement learning from human feedback", rows, "default"
        )

        # m1 has the canonical name "RLHF" in content → boosted
        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8
        assert result[0].get("entity_boost", 0) > 0

        # m2 doesn't mention RLHF → unchanged
        assert result[1]["entity_id"] == "m2"
        assert result[1]["fused_score"] == 0.6

    def test_boost_entity_link_alias_in_content(self, mock_http_client):
        """Boost fires when result content contains an alias, not just canonical name."""
        mock_http_client._query = MagicMock(
            side_effect=[
                [],  # kg_node: empty
                [
                    {
                        "id": "el1",
                        "entity_name": "PEFT",
                        "aliases_json": '["parameter-efficient fine-tuning", "lightweight fine-tuning"]',
                        "entity_type": "concept",
                    }
                ],
            ]
        )

        rows = [
            # Content doesn't mention "PEFT" but mentions the alias
            {
                "entity_id": "m1",
                "fused_score": 0.8,
                "memory_content": "parameter-efficient fine-tuning is useful for LLMs",
            },
            # No alias mention
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "some unrelated content"},
        ]

        result = mock_http_client._boost_with_entity_signal("PEFT methods", rows, "default")

        # m1 mentions the alias "parameter-efficient fine-tuning" → boosted
        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8

        # m2 unchanged
        assert result[1]["entity_id"] == "m2"
        assert result[1]["fused_score"] == 0.6

    def test_boost_entity_link_and_kg_node_combined(self, mock_http_client):
        """Both KG nodes and entity_link aliases contribute to matching."""
        mock_http_client._query = MagicMock(
            side_effect=[
                [  # kg_node
                    {
                        "id": "n1",
                        "label": "RLHF",
                        "summary": "Reinforcement learning from human feedback",
                        "node_type": "concept",
                    },
                ],
                [  # entity_link
                    {
                        "id": "el1",
                        "entity_name": "LoRA",
                        "aliases_json": '["low-rank adaptation"]',
                        "entity_type": "concept",
                    }
                ],
            ]
        )

        rows = [
            {"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF and LoRA combined"},
            {"entity_id": "m2", "fused_score": 0.6, "memory_content": "only RLHF here"},
            {
                "entity_id": "m3",
                "fused_score": 0.4,
                "memory_content": "low-rank adaptation is efficient",
            },
        ]

        result = mock_http_client._boost_with_entity_signal(
            "RLHF and low-rank adaptation", rows, "default", boost_factor=0.15
        )

        # m1 has both RLHF (KG node via label match) and LoRA (entity_link via alias match in content)
        # → proportion = 2/2 = 1.0 → max boost
        assert result[0]["entity_id"] == "m1"
        assert abs(result[0].get("entity_boost", 0) - 0.15) < 0.001

        # m2 only has RLHF → proportion = 1/2 = 0.5 → half boost
        assert result[1]["entity_id"] == "m2"
        assert abs(result[1].get("entity_boost", 0) - 0.075) < 0.001

        # m3 has "low-rank adaptation" (alias of LoRA) in content → matched via entity_link
        assert result[2]["entity_id"] == "m3"
        assert result[2]["fused_score"] > 0.4

    def test_boost_entity_link_table_unavailable(self, mock_http_client):
        """Graceful degradation when entity_link query raises RuntimeError."""
        mock_http_client._query = MagicMock(
            side_effect=[
                [  # kg_node succeeds
                    {"id": "n1", "label": "RLHF", "summary": "", "node_type": "concept"},
                ],
                RuntimeError("no entity_link table"),  # entity_link fails
            ]
        )

        rows = [
            {"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF is great"},
        ]

        # Should not crash — falls back to KG-node-only matching
        result = mock_http_client._boost_with_entity_signal("RLHF", rows, "default")
        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8

    def test_boost_entity_link_empty_aliases_json(self, mock_http_client):
        """entity_link with empty or invalid aliases_json is handled gracefully."""
        mock_http_client._query = MagicMock(
            side_effect=[
                [],
                [
                    {
                        "id": "el1",
                        "entity_name": "RLHF",
                        "aliases_json": "",  # empty aliases field
                        "entity_type": "concept",
                    }
                ],
            ]
        )

        rows = [
            {"entity_id": "m1", "fused_score": 0.8, "memory_content": "RLHF is awesome"},
        ]

        result = mock_http_client._boost_with_entity_signal("RLHF", rows, "default")
        assert result[0]["entity_id"] == "m1"
        assert result[0]["fused_score"] > 0.8  # Still boosted via entity_name


# ── Entity types filter in search() ─────────────────────────────────────


class TestSearchEntityTypes:
    """Tests for the entity_types filter parameter in search()."""

    @pytest.fixture
    def mock_client(self):
        c = Client(host="localhost", port="3000", database="test")
        c._identity_established = True
        c._query_cache = None
        c.event_bus = None
        return c

    def test_entity_types_hybrid_filter(self, mock_client):
        """entity_types filter in hybrid path keeps only matching types."""
        mock_rows = [
            {"entity_id": "m1", "entity_type": "memory", "score": 0.9, "strategy": "semantic"},
            {"entity_id": "n1", "entity_type": "note", "score": 0.8, "strategy": "semantic"},
            {"entity_id": "k1", "entity_type": "node", "score": 0.7, "strategy": "semantic"},
        ]
        with patch.object(mock_client, "_embed", return_value=[0.1, 0.2]):
            with patch.object(mock_client, "_call", return_value={"status": "ok"}):
                with patch.object(mock_client, "_sql", return_value=mock_rows):
                    with patch.object(mock_client, "_tantivy_search", return_value=[]):
                        with patch.object(
                            mock_client, "_fuse_and_deduplicate", return_value=mock_rows
                        ):
                            with patch.object(
                                mock_client, "_enrich_content", return_value=mock_rows
                            ):
                                result = mock_client.search(
                                    "ws1",
                                    "test query",
                                    semantic=True,
                                    limit=20,
                                    entity_types=["memory", "note"],
                                )
        # Should only contain memories and notes
        assert all(r["entity_type"] in ("memory", "note") for r in result)
        assert any(r["entity_type"] == "memory" for r in result)
        assert any(r["entity_type"] == "note" for r in result)
        assert not any(r["entity_type"] == "node" for r in result)

    def test_entity_types_keyword_filter(self, mock_client):
        """entity_types filter in keyword fallback path keeps only matching types."""
        from unittest.mock import patch

        # _keyword_fallback calls _query twice: first for "memory" table,
        # then for "note" table.  Use side_effect to return distinct data.
        mock_memories = [
            {"id": "m1", "content": "hello world", "entity_type": "memory", "created_at": 100},
        ]
        mock_notes = [
            {"id": "n1", "content": "world of notes", "entity_type": "note", "created_at": 90},
        ]
        with patch.object(mock_client, "_call", return_value={"status": "ok"}), patch.object(
            mock_client,
            "_query",
            side_effect=[
                mock_memories,
                mock_notes,
                [],  # _boost_with_entity_signal: kg_node
                [],  # _boost_with_entity_signal: entity_link
            ],
        ):
            result = mock_client.search(
                "ws1",
                "world",
                semantic=False,
                limit=20,
                entity_types=["memory"],
            )
        # Only memories survive (notes are filtered out)
        assert all(r.get("entity_type") == "memory" for r in result)

    def test_entity_types_none_returns_all(self, mock_client):
        """entity_types=None (default) returns all entity types unchanged."""
        mock_rows = [
            {"entity_id": "m1", "entity_type": "memory", "score": 0.9, "strategy": "semantic"},
            {"entity_id": "n1", "entity_type": "note", "score": 0.8, "strategy": "semantic"},
            {"entity_id": "k1", "entity_type": "node", "score": 0.7, "strategy": "semantic"},
        ]
        with patch.object(mock_client, "_embed", return_value=[0.1, 0.2]):
            with patch.object(mock_client, "_call", return_value={"status": "ok"}):
                with patch.object(mock_client, "_sql", return_value=mock_rows):
                    with patch.object(mock_client, "_tantivy_search", return_value=[]):
                        with patch.object(
                            mock_client, "_fuse_and_deduplicate", return_value=mock_rows
                        ):
                            with patch.object(
                                mock_client, "_enrich_content", return_value=mock_rows
                            ):
                                result = mock_client.search(
                                    "ws1",
                                    "test query",
                                    semantic=True,
                                    limit=20,
                                )
        # All types present (no filtering)
        assert len(result) == 3
        types = {r["entity_type"] for r in result}
        assert types == {"memory", "note", "node"}

    def test_entity_types_empty_list_returns_none(self, mock_client):
        """entity_types=[] returns empty results."""
        with patch.object(mock_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_client, "_query", return_value=[]):
            result = mock_client.search(
                "ws1",
                "test",
                semantic=False,
                limit=20,
                entity_types=[],
            )
        assert result == []


class TestListSpaceMembers:
    """Tests for list_space_members SDK method."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_list_space_members_calls_reducer(self, client):
        """list_space_members calls list_space_members reducer then queries result table."""
        client.list_space_members("ws-1")
        client._call.assert_called_with("list_space_members", ["ws-1"])
        client._query.assert_called_with("space_member_result")

    def test_list_space_members_returns_sorted(self, client):
        """list_space_members returns rows sorted by created_at."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(
            return_value=[
                {"peer_id": "p2", "permission": "owner", "created_at": 200},
                {"peer_id": "p1", "permission": "viewer", "created_at": 100},
            ]
        )
        rows = c.list_space_members("ws-1")
        assert rows[0]["peer_id"] == "p1"
        assert rows[1]["peer_id"] == "p2"


class TestGetSessionSteps:
    """Tests for get_session_steps SDK method."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_get_session_steps_calls_reducer(self, client):
        """get_session_steps calls the reducer then queries result table with steps: hash."""
        client.get_session_steps("session-1")
        client._call.assert_called_with("get_session_steps", ["session-1"])
        client._query.assert_called_with(
            "session_step_result",
            filter_dict={"query_hash": "steps:session-1"},
        )

    def test_get_session_steps_returns_sorted(self, client):
        """get_session_steps returns rows sorted by created_at."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(
            return_value=[
                {"id": "step-2", "content": "second", "created_at": 200},
                {"id": "step-1", "content": "first", "created_at": 100},
            ]
        )
        rows = c.get_session_steps("session-1")
        assert rows[0]["id"] == "step-1"
        assert rows[1]["id"] == "step-2"


class TestMakeSnippet:
    """Tests for the _make_snippet() pure function (word-boundary text truncation)."""

    def test_short_text_no_truncation(self):
        """Text shorter than max_chars is returned unchanged."""
        from spacetime_memory.client import _make_snippet

        text = "Hello world"
        result = _make_snippet(text, max_chars=200)
        assert result == "Hello world"

    def test_exact_boundary_no_truncation(self):
        """Text exactly at max_chars is returned without '...'."""
        from spacetime_memory.client import _make_snippet

        text = "A" * 200
        result = _make_snippet(text, max_chars=200)
        assert result == "A" * 200
        assert len(result) == 200

    def test_truncate_at_word_boundary(self):
        """Long text is truncated at the last space within the first max_chars."""
        from spacetime_memory.client import _make_snippet

        # "quick brown fox..." — first 20 chars: "quick brown fox jump"
        # last space within those 20 is after "fox" (pos 15)
        text = "quick brown fox jumped over the lazy dog"
        result = _make_snippet(text, max_chars=20)
        assert result == "quick brown fox..."

    def test_truncate_no_good_boundary_uses_hard_cut(self):
        """When no suitable word boundary (space before max_chars//2), use hard cut at max_chars."""
        from spacetime_memory.client import _make_snippet

        # "abcdefghijklmnopqrstuvwxyz" — 26 chars, max_chars=10, no space at all
        text = "abcdefghijklmnopqrstuvwxyz"
        result = _make_snippet(text, max_chars=10)
        assert result == "abcdefghij..."

    def test_empty_string_returns_empty(self):
        """Empty string returns empty string."""
        from spacetime_memory.client import _make_snippet

        assert _make_snippet("") == ""

    def test_none_falsy_returns_empty(self):
        """Falsy input (None, empty) returns empty string."""
        from spacetime_memory.client import _make_snippet

        assert _make_snippet(None) == ""  # type: ignore[arg-type]
        assert _make_snippet("") == ""
        assert _make_snippet("   ".strip()[:0]) == ""

    def test_custom_max_chars(self):
        """max_chars parameter controls truncation length."""
        from spacetime_memory.client import _make_snippet

        text = "this is a test of the emergency broadcast system"
        result = _make_snippet(text, max_chars=10)
        # First 10 chars: "this is a " — last space at pos 9 ("this is a")
        assert result == "this is a..."

    def test_very_long_text(self):
        """Very long text (multi-KB) truncates correctly."""
        from spacetime_memory.client import _make_snippet

        text = "hello world " * 500  # ~6000 chars
        result = _make_snippet(text, max_chars=200)
        assert result.endswith("...")
        assert len(result) <= 200 + 3  # 200 max + "..." suffix
        assert " " not in result[:-3].lstrip("...") or result[:-3].endswith(" ") is False
        # Ensure word-boundary was respected
        assert result.rstrip(".")  # non-empty

    def test_single_word_no_space(self):
        """A single unbroken word longer than max_chars uses hard cut."""
        from spacetime_memory.client import _make_snippet

        text = "Supercalifragilisticexpialidocious"
        result = _make_snippet(text, max_chars=10)
        assert result == "Supercalif..."  # Hard cut at 10 + "..."

    def test_rstrip_trailing_spaces(self):
        """Trailing whitespace before '...' is stripped."""
        from spacetime_memory.client import _make_snippet

        # First 20 chars: "hello world      a" with lots of trailing spaces
        text = "hello world" + " " * 20 + "this part is after the boundary"
        result = _make_snippet(text, max_chars=20)
        # The space at pos 10 is the last space within first 20 chars
        assert result == "hello world..."


class TestGrantRevokeSpaceAccess:
    """Tests for grant_space_access and revoke_space_access SDK methods."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_grant_space_access_calls_reducer(self, client):
        """grant_space_access calls the grant_space_access reducer."""
        client.grant_space_access("ws-1", "peer-1", "editor")
        client._call.assert_called_once_with(
            "grant_space_access", ["ws-1", "peer-1", "editor"]
        )

    def test_grant_space_access_returns_status(self, client):
        """grant_space_access returns the reducer result dict."""
        client._call.return_value = {"status": "ok"}
        result = client.grant_space_access("ws-1", "peer-2", "viewer")
        assert result == {"status": "ok"}

    def test_revoke_space_access_calls_reducer(self, client):
        """revoke_space_access calls the revoke_space_access reducer."""
        client.revoke_space_access("ws-1", "peer-1")
        client._call.assert_called_once_with(
            "revoke_space_access", ["ws-1", "peer-1"]
        )

    def test_revoke_space_access_returns_status(self, client):
        """revoke_space_access returns the reducer result dict."""
        client._call.return_value = {"status": "ok"}
        result = client.revoke_space_access("ws-1", "peer-2")
        assert result == {"status": "ok"}
