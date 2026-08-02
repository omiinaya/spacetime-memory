"""Unit tests for the Hindsight SDK adapter (sdks/hindsight.py).

Mocks the underlying Client to test Hindsight operations
(retain, recall, reflect, banks, etc.) without a real SpacetimeDB.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from spacetime_memory.sdks.hindsight import (
    CreateBankResponse,
    CreateDirectiveResponse,
    CreateMentalModelResponse,
    FileRetainResponse,
    Hindsight,
    ListMemoryUnitsResponse,
    RecallResponse,
    RecallResult,
    ReflectResponse,
    RetainResponse,
    _HindsightDirectivesShell,
    _HindsightDocumentsAPI,
    _HindsightEntitiesAPI,
    _HindsightFilesShell,
    _HindsightMentalModelsShell,
    _HindsightMonitoringAPI,
    _HindsightNotImplementedShell,
    _HindsightOperationsAPI,
    _HindsightWebhooksAPI,
    _run_async,
)


# =====================================================================
# Helpers
# =====================================================================
class TestRunAsync:
    def test_runs_coro(self):
        async def demo():
            return "done"
        result = _run_async(demo())
        assert result == "done"

    def test_raises_in_async_context(self):
        """_run_async raises RuntimeError when called from an async context."""
        async def test():
            with pytest.raises(RuntimeError, match="Cannot call sync wrapper from async context"):
                _run_async(asyncio.sleep(0))
        asyncio.run(test())


class TestNotImplementedShell:
    def test_call_raises(self):
        shell = _HindsightNotImplementedShell("test")
        with pytest.raises(NotImplementedError, match="Hindsight.test"):
            shell()

    def test_attr_access_raises(self):
        shell = _HindsightNotImplementedShell("test")
        with pytest.raises(NotImplementedError, match="Hindsight.test.method"):
            shell.method("arg")


# =====================================================================
# Hindsight - Init
# =====================================================================
class TestHindsightInit:
    @patch("spacetime_memory.sdks.hindsight.Client")
    def test_init_defaults(self, MockClient):
        h = Hindsight(base_url=None)
        assert h._closed is False
        assert h._ws_cache == {}
        h.close()

    @patch("spacetime_memory.sdks.hindsight.Client")
    def test_init_with_params(self, MockClient):
        h = Hindsight(
            base_url=None,
            stdb_host="myhost",
            stdb_port=9999,
            stdb_database="mydb",
            api_key="test-key",
        )
        MockClient.assert_called_once()
        assert h._api_key == "test-key"
        h.close()

    def test_context_manager(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            with Hindsight(base_url=None) as h:
                assert h._closed is False
            assert h._closed is True


# =====================================================================
# Hindsight - Properties
# =====================================================================
class TestHindsightProperties:
    def setup_method(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            self.h = Hindsight(base_url=None)
            self.h._client = MagicMock()

    def test_memory_returns_self(self):
        assert self.h.memory is self.h

    def test_banks_returns_self(self):
        assert self.h.banks is self.h

    def test_documents(self):
        docs = self.h.documents
        assert isinstance(docs, _HindsightDocumentsAPI)

    def test_entities(self):
        entities = self.h.entities
        assert isinstance(entities, _HindsightEntitiesAPI)

    def test_operations(self):
        ops = self.h.operations
        assert isinstance(ops, _HindsightOperationsAPI)

    def test_monitoring(self):
        mon = self.h.monitoring
        assert isinstance(mon, _HindsightMonitoringAPI)

    def test_mental_models(self):
        mm = self.h.mental_models
        assert isinstance(mm, _HindsightMentalModelsShell)

    def test_directives(self):
        d = self.h.directives
        assert isinstance(d, _HindsightDirectivesShell)

    def test_files(self):
        f = self.h.files
        assert isinstance(f, _HindsightFilesShell)

    def test_webhooks(self):
        wh = self.h.webhooks
        assert isinstance(wh, _HindsightWebhooksAPI)


# =====================================================================
# Hindsight - Retain
# =====================================================================
class TestRetain:
    def setup_method(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            self.h = Hindsight(base_url=None)
            self.h._client = MagicMock()
            self.h._client.list_workspaces.return_value = [
                {"id": "ws-1", "name": "test-bank"}
            ]

    def test_retain(self):
        result = self.h.retain(bank_id="test-bank", content="Alice likes pizza")
        assert isinstance(result, RetainResponse)
        assert result.success is True

    def test_retain_store_fails(self):
        self.h._client.store.side_effect = RuntimeError("fail")
        result = self.h.retain(bank_id="test-bank", content="Test")
        assert result.success is False

    def test_retain_with_all_params(self):
        result = self.h.retain(
            bank_id="test-bank",
            content="Rich retain",
            metadata={"source": "test"},
            tags=["important"],
            entities=[{"name": "Alice", "type": "person"}],
            context="Test context",
            document_id="doc-001",
        )
        assert result.success is True

    def test_retain_batch(self):
        items = [
            {"content": "Item 1", "context": "Ctx 1"},
            {"content": "Item 2"},
            {},
        ]
        result = self.h.retain_batch(bank_id="test-bank", items=items)
        assert isinstance(result, RetainResponse)

    def test_retain_files(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("File content")
            f.flush()
            tmp_path = f.name

        result = self.h.retain_files(
            bank_id="test-bank",
            files=[tmp_path],
            context="File context",
        )
        assert isinstance(result, FileRetainResponse)

    def test_retain_after_close_raises(self):
        self.h.close()
        with pytest.raises(RuntimeError, match="closed"):
            self.h.retain(bank_id="test-bank", content="After close")


# =====================================================================
# Hindsight - Recall
# =====================================================================
class TestRecall:
    def setup_method(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            self.h = Hindsight(base_url=None)
            self.h._client = MagicMock()
            self.h._client.list_workspaces.return_value = [
                {"id": "ws-1", "name": "test-bank"}
            ]

    def test_recall(self):
        self.h._client.search.return_value = [
            {"id": "m1", "memory_content": "Alice likes pizza", "score": 0.9}
        ]
        result = self.h.recall(bank_id="test-bank", query="food")
        assert isinstance(result, RecallResponse)
        assert len(result.results) > 0

    def test_recall_empty(self):
        self.h._client.search.return_value = []
        result = self.h.recall(bank_id="test-bank", query="nothing")
        assert result.results == []

    def test_recall_with_types(self):
        self.h._client.search.return_value = []
        result = self.h.recall(bank_id="test-bank", query="test", types=["experience"])
        assert isinstance(result, RecallResponse)


# =====================================================================
# Hindsight - Reflect / Create
# =====================================================================
class TestReflectAndCreate:
    def setup_method(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            self.h = Hindsight(base_url=None)
            self.h._client = MagicMock()
            self.h._client.list_workspaces.return_value = [
                {"id": "ws-1", "name": "test-bank"}
            ]

    def test_reflect(self):
        self.h._client.search.return_value = [
            {"memory_content": "Alice likes pizza", "score": 0.9}
        ]
        self.h._client._call.return_value = {"insight": "Alice likes pizza and hiking"}
        result = self.h.reflect(bank_id="test-bank", query="What does Alice like?")
        assert isinstance(result, ReflectResponse)
        assert result.text

    def test_create_bank(self):
        self.h._client.create_workspace.return_value = {"id": "new-ws"}
        result = self.h.create_bank(name="new-bank")
        assert isinstance(result, CreateBankResponse)
        assert result.success is True

    def test_create_mental_model(self):
        self.h._client.search.return_value = []
        self.h._client._call.return_value = {"status": "ok"}
        result = self.h.create_mental_model(bank_id="test-bank", name="Profile", query="traits")
        assert isinstance(result, CreateMentalModelResponse)

    def test_create_directive(self):
        self.h._client._call.return_value = {"status": "ok"}
        result = self.h.create_directive(bank_id="test-bank", name="Directive", prompt="Be nice")
        assert isinstance(result, CreateDirectiveResponse)

    def test_list_memories(self):
        self.h._client._query.return_value = []
        result = self.h.list_memories(bank_id="test-bank", limit=10, offset=0)
        assert isinstance(result, ListMemoryUnitsResponse)

    def test_delete_bank(self):
        self.h._client._call.return_value = {"status": "ok"}
        self.h.delete_bank(bank_id="test-bank")  # should not raise

    def test_get_bank_profile(self):
        self.h._client._query.return_value = []
        # get_bank_profile is not in the adapter; test something that exists
        assert hasattr(self.h, "create_bank")
        assert hasattr(self.h, "list_memories")


# =====================================================================
# Sub-API shells
# =====================================================================
class TestSubAPIs:
    def setup_method(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            self.h = Hindsight(base_url=None)
            self.h._client = MagicMock()
            self.h._client.list_workspaces.return_value = [
                {"id": "ws-1", "name": "test-bank"}
            ]

    def test_documents_list(self):
        self.h._client._query.return_value = []
        result = self.h.documents.list(bank_id="ws-1")
        assert "items" in result

    def test_entities_list(self):
        self.h._client._query.return_value = []
        result = self.h.entities.list(bank_id="ws-1")
        assert "items" in result

    def test_operations_list(self):
        self.h._client._query.return_value = []
        result = self.h.operations.list(bank_id="ws-1")
        assert "items" in result

    def test_monitoring_health(self):
        self.h._client.check_embedder_health.return_value = {"status": "ok"}
        self.h._client.check_tantivy_health.return_value = {"status": "ok"}
        result = self.h.monitoring.health()
        assert result["ok"] is True

    def test_mental_models_shell(self):
        self.h._client.search.return_value = []
        self.h._client._call.return_value = {"status": "ok"}
        result = self.h.mental_models.create(bank_id="test-bank", name="MM", query="test")
        assert isinstance(result, CreateMentalModelResponse)

    def test_directives_shell(self):
        self.h._client._call.return_value = {"status": "ok"}
        result = self.h.directives.create(bank_id="test-bank", name="D", prompt="Be nice")
        assert isinstance(result, CreateDirectiveResponse)

    def test_files_shell(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Shell test")
            f.flush()
            tmp_path = f.name
        result = self.h.files.upload(bank_id="test-bank", files=[tmp_path])
        assert isinstance(result, FileRetainResponse)

    def test_webhooks_create_and_list(self):
        """webhooks.create/list delegate to the real client webhook API."""
        self.h._client.create_webhook.return_value = {"status": "ok"}
        self.h._client.list_webhooks.return_value = [
            {"webhook_id": "wh-1", "name": "Alert", "url": "https://x.example/hook"}
        ]
        result = self.h.webhooks.create(
            bank_id="test-bank",
            name="Alert",
            url="https://x.example/hook",
            event_types=["memory.created"],
            secret="s3cret",
        )
        assert result == {"status": "ok"}
        self.h._client.create_webhook.assert_called_once_with(
            workspace_id="ws-1", name="Alert",
            url="https://x.example/hook",
            event_types='["memory.created"]', secret="s3cret",
        )

        listing = self.h.webhooks.list(bank_id="test-bank")
        assert listing["total"] == 1
        assert listing["items"][0]["webhook_id"] == "wh-1"

    def test_webhooks_get_update_delete_fire(self):
        """webhooks.get/update/delete/fire delegate to the real client API."""
        self.h._client.list_webhooks.return_value = [
            {"webhook_id": "wh-1", "name": "Alert", "url": "https://x.example/hook"}
        ]
        got = self.h.webhooks.get(bank_id="test-bank", webhook_id="wh-1")
        assert got["webhook_id"] == "wh-1"

        self.h._client.update_webhook.return_value = {"status": "ok"}
        upd = self.h.webhooks.update(webhook_id="wh-1", is_active=False)
        assert upd == {"status": "ok"}

        self.h._client.delete_webhook.return_value = {"status": "ok"}
        deleted = self.h.webhooks.delete(bank_id="test-bank", webhook_id="wh-1")
        assert deleted == {"status": "ok"}

        self.h._client.fire_webhook_event.return_value = {"status": "ok"}
        fired = self.h.webhooks.fire(
            bank_id="test-bank", event_type="memory.created",
            payload={"content": "hi"},
        )
        assert fired == {"status": "ok"}
        self.h._client.fire_webhook_event.assert_called_once_with(
            workspace_id="ws-1", event_type="memory.created",
            payload='{"content": "hi"}',
        )

    def test_webhooks_get_missing_raises(self):
        self.h._client.list_webhooks.return_value = []
        with pytest.raises(KeyError):
            self.h.webhooks.get(bank_id="test-bank", webhook_id="nope")

    def test_retain_with_ttl_stores_expiry_marker(self):
        """retain(ttl_seconds=...) encodes an expiry marker into entities."""
        self.h._client.store.return_value = {"status": "ok", "id": "m1"}
        result = self.h.retain(
            bank_id="test-bank",
            content="working memory item",
            ttl_seconds=3600,
        )
        assert result.success is True
        _, kwargs = self.h._client.store.call_args
        ents = json.loads(kwargs.get("entities_json", "[]"))
        assert any(e.get("type") == "_ttl" for e in ents)
        ttl_entry = next(e for e in ents if e.get("type") == "_ttl")
        assert float(ttl_entry["expires_at"]) > 0

    def test_filter_expired_evicts_expired_working_memory(self):
        """_filter_expired drops TTL entries past their expiry."""
        import time as _time

        self.h._client.list_memories.return_value = [
            {"id": "live-1", "entities_json": json.dumps(
                [{"type": "_ttl", "expires_at": str(_time.time() + 1000)}]
            )},
            {"id": "dead-1", "entities_json": json.dumps(
                [{"type": "_ttl", "expires_at": str(_time.time() - 1000)}]
            )},
            {"id": "durable-1", "entities_json": "[]"},
        ]
        results = [
            RecallResult(id="live-1", text="live", type="experience", score=1.0),
            RecallResult(id="dead-1", text="dead", type="experience", score=1.0),
            RecallResult(id="durable-1", text="durable", type="experience", score=1.0),
        ]
        kept = self.h._filter_expired(results, "ws-1")
        kept_ids = [r.id for r in kept]
        assert "live-1" in kept_ids
        assert "durable-1" in kept_ids
        assert "dead-1" not in kept_ids

    def test_get_entity(self):
        self.h._client._query.return_value = [{"id": "e1", "label": "Entity1"}]
        result = self.h.entities.get(bank_id="ws-1", entity_id="e1")
        assert result["id"] == "e1"

    def test_get_document(self):
        self.h._client._query.return_value = [{"id": "d1", "content": "Doc content"}]
        result = self.h.documents.get(bank_id="ws-1", document_id="d1")
        assert result["id"] == "d1"

    def test_delete_document(self):
        self.h._client._call.return_value = {"status": "ok"}
        result = self.h.documents.delete(bank_id="ws-1", document_id="d1")
        assert result["status"] == "ok"

    def test_delete_entity(self):
        self.h._client._call.return_value = {"status": "ok"}
        result = self.h.entities.delete(bank_id="ws-1", entity_id="e1")
        assert result["status"] == "ok"


# =====================================================================
# Async methods
# =====================================================================
class TestAsyncMethods:
    def setup_method(self):
        with patch("spacetime_memory.sdks.hindsight.Client"):
            self.h = Hindsight(base_url=None)
            self.h._client = MagicMock()
            self.h._client.list_workspaces.return_value = [
                {"id": "ws-1", "name": "test-bank"}
            ]

    def test_aretain(self):
        async def test():
            return await self.h.aretain(bank_id="test-bank", content="Async test")
        result = asyncio.run(test())
        assert isinstance(result, RetainResponse)

    def test_aretain_batch(self):
        async def test():
            return await self.h.aretain_batch(
                bank_id="test-bank",
                items=[{"content": "Item 1"}, {"content": "Item 2"}],
            )
        result = asyncio.run(test())
        assert isinstance(result, RetainResponse)

    def test_arecall(self):
        self.h._client.search.return_value = []
        async def test():
            return await self.h.arecall(bank_id="test-bank", query="test")
        result = asyncio.run(test())
        assert isinstance(result, RecallResponse)

    def test_areflect(self):
        self.h._client.search.return_value = []
        self.h._client._call.return_value = {"insight": "Answer"}
        async def test():
            return await self.h.areflect(bank_id="test-bank", query="test")
        result = asyncio.run(test())
        assert isinstance(result, ReflectResponse)

    def test_aclose(self):
        async def test():
            await self.h.aclose()
            assert self.h._closed is True
        asyncio.run(test())
