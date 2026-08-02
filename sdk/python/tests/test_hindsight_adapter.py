"""Integration tests for Hindsight-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest sdk/python/tests/test_hindsight_adapter.py -v

"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]

from unittest import mock

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
    _HindsightNotImplementedShell,
    _run_async,
)


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture(scope="module")
def db() -> str | None:
    return os.environ.get("SPACETIMEDB_DB", None)


@pytest.fixture(scope="module")
def token() -> str:
    """Generate a JWT token for consistent identity across calls."""
    try:
        from spacetime_memory.auth import generate_token
    except ImportError:
        return ""
    key_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "id_ecdsa_pkcs8.pem"
    if not key_path.exists():
        return ""
    return generate_token(str(key_path))


@pytest.fixture
def hindsight(stdb_client: Client, stdb_session: dict) -> Hindsight:
    """Hindsight adapter backed by the auto-registered test client."""
    h = Hindsight(
        base_url=None,
        stdb_host=stdb_session["host"],
        stdb_port=int(stdb_session["port"]),
        stdb_database=stdb_session["database"],
        api_key=None,
    )
    # Auto-register for auth
    import secrets

    try:
        h._client._call(
            "register", [f"hs_test_{secrets.token_hex(4)}", "Hindsight Test", "testpass"]
        )
    except RuntimeError:
        pass
    my_id = h._client._whoami()
    if my_id:
        try:
            h._client._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass
    return h


def _bid(prefix: str = "hs-test") -> str:
    """Generate a unique bank ID to avoid cross-contamination."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TestHindsightCore:
    """Core Hindsight API operations."""

    def test_retain(self, hindsight: Hindsight) -> None:
        """Retain a single memory unit, verify success."""
        bid = _bid()
        result = hindsight.retain(bank_id=bid, content="Alice loves pizza")
        assert isinstance(result, RetainResponse)
        assert result.success is True
        assert result.bank_id == bid
        assert result.items_count == 1

    def test_retain_batch(self, hindsight: Hindsight) -> None:
        """Retain multiple items, verify count."""
        bid = _bid()
        items = [
            {"content": "Bob enjoys hiking in the mountains"},
            {"content": "Bob prefers tea over coffee"},
            {"content": "Bob works as a software engineer"},
        ]
        result = hindsight.retain_batch(bank_id=bid, items=items)
        assert isinstance(result, RetainResponse)
        assert result.success is True
        assert result.items_count == 3

    def test_recall(self, hindsight: Hindsight) -> None:
        """Recall memories, verify results list."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Charlie likes jazz music")
        hindsight.retain(bank_id=bid, content="Charlie plays the saxophone")

        result = hindsight.recall(bank_id=bid, query="What music does Charlie like?")
        assert isinstance(result, RecallResponse)
        assert isinstance(result.results, list)
        # May or may not find results depending on embedding, but response is valid
        if result.results:
            for r in result.results:
                assert isinstance(r, RecallResult)
                assert r.text

    def test_recall_empty_bank(self, hindsight: Hindsight) -> None:
        """Recall from nonexistent bank returns empty results."""
        bid = _bid("hs-test-noexist")
        result = hindsight.recall(bank_id=bid, query="anything")
        assert isinstance(result, RecallResponse)
        assert isinstance(result.results, list)
        assert len(result.results) == 0

    def test_reflect(self, hindsight: Hindsight) -> None:
        """Reflect on memories, verify response."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Diana's favorite color is blue")
        hindsight.retain(bank_id=bid, content="Diana loves sailing on weekends")

        result = hindsight.reflect(
            bank_id=bid,
            query="What does Diana enjoy doing?",
        )
        assert isinstance(result, ReflectResponse)
        assert result.text
        assert isinstance(result.text, str)

    def test_retain_files(self, hindsight: Hindsight) -> None:
        """Retain file content, verify success."""
        bid = _bid()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("This is test file content for Hindsight adapter.")
            f.flush()
            tmp_path = f.name

        try:
            result = hindsight.retain_files(
                bank_id=bid,
                files=[tmp_path],
                context="Test file upload context",
            )
            assert isinstance(result, FileRetainResponse)
            assert isinstance(result.operation_ids, list)
            assert len(result.operation_ids) == 1
        finally:
            os.unlink(tmp_path)

    def test_close(self, hindsight: Hindsight) -> None:
        """close() is idempotent — multiple calls don't raise."""
        bid = _bid()
        # First call works
        result = hindsight.retain(bank_id=bid, content="Close test 1")
        assert result.success is True

        hindsight.close()
        hindsight.close()  # idempotent — second close should not raise

        # After close, calls should raise RuntimeError
        with pytest.raises(RuntimeError):
            hindsight.retain(bank_id=bid, content="After close")

    def test_context_manager(self, host: str, port: int, stdb_session: dict) -> None:
        """with Hindsight(...) as h: works and closes on exit."""
        bid = _bid()
        with Hindsight(
            base_url=None,
            stdb_host=host,
            stdb_port=port,
            stdb_database=stdb_session["database"],
            api_key=None,
        ) as h:
            # Register for auth so retain/recall work
            import secrets

            try:
                h._client._call(
                    "register", [f"hs_cm_{secrets.token_hex(4)}", "CM Test", "testpass"]
                )
            except RuntimeError:
                pass
            my_id = h._client._whoami()
            if my_id:
                try:
                    h._client._call("set_initial_admin", [my_id])
                except RuntimeError:
                    pass
            result = h.retain(bank_id=bid, content="Context manager test")
            assert result.success is True

        # After exit, client should be closed
        with pytest.raises(RuntimeError):
            h.retain(bank_id=bid, content="After context exit")

    def test_create_bank(self, hindsight: Hindsight) -> None:
        """Create a bank returns valid response."""
        bid = _bid("hs-test-create")
        result = hindsight.create_bank(name=bid, description="Test bank for Hindsight adapter")
        assert isinstance(result, CreateBankResponse)
        assert result.success is True
        assert result.name == bid
        assert result.id

    def test_list_memories(self, hindsight: Hindsight) -> None:
        """List memories in a bank."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Memory A: elephants are large")
        hindsight.retain(bank_id=bid, content="Memory B: penguins cannot fly")

        result = hindsight.list_memories(bank_id=bid, limit=10, offset=0)
        assert isinstance(result, ListMemoryUnitsResponse)
        assert isinstance(result.items, list)
        assert result.limit == 10
        assert result.offset == 0
        # At least the two we stored should be there
        assert result.total >= 2

    def test_list_memories_pagination(self, hindsight: Hindsight) -> None:
        """list_memories with offset pagination."""
        bid = _bid()
        for i in range(5):
            hindsight.retain(bank_id=bid, content=f"Page test memory {i}")

        result = hindsight.list_memories(bank_id=bid, limit=2, offset=1)
        assert isinstance(result, ListMemoryUnitsResponse)
        assert result.limit == 2
        assert result.offset == 1

    def test_delete_bank(self, hindsight: Hindsight) -> None:
        """delete_bank removes a bank."""
        bid = _bid("hs-test-delete-bank")
        hindsight.create_bank(name=bid)
        hindsight.delete_bank(bank_id=bid)
        # Deleting again shouldn't raise
        try:
            hindsight.delete_bank(bank_id=bid)
        except RuntimeError:
            pass  # idempotent behavior

    def test_create_mental_model(self, hindsight: Hindsight) -> None:
        """create_mental_model returns valid response."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Alice is a software engineer")
        hindsight.retain(bank_id=bid, content="Alice enjoys hiking")

        result = hindsight.create_mental_model(
            bank_id=bid,
            name="Alice Profile",
            query="What are Alice's traits?",
        )
        assert isinstance(result, CreateMentalModelResponse)
        assert result.name == "Alice Profile"

    def test_create_directive(self, hindsight: Hindsight) -> None:
        """create_directive returns valid response."""
        bid = _bid()
        result = hindsight.create_directive(
            bank_id=bid,
            name="Test Directive",
            prompt="Always be helpful",
        )
        assert isinstance(result, CreateDirectiveResponse)
        assert result.name == "Test Directive"

    def test_retain_with_all_params(self, hindsight: Hindsight) -> None:
        """retain with metadata, tags, entities."""
        bid = _bid()
        result = hindsight.retain(
            bank_id=bid,
            content="Rich retain test",
            metadata={"source": "test", "version": "1.0"},
            tags=["integration-test", "sdk"],
            entities=[{"name": "Hindsight", "type": "software"}],
            context="Testing all retain parameters",
            document_id="doc-001",
        )
        assert isinstance(result, RetainResponse)
        assert result.success is True

    def test_retain_batch_with_mixed_items(self, hindsight: Hindsight) -> None:
        """retain_batch with items that have various fields."""
        bid = _bid()
        items = [
            {"content": "Item 1", "context": "Context for item 1"},
            {"content": "Item 2"},
            {},  # Empty item should be skipped
        ]
        result = hindsight.retain_batch(bank_id=bid, items=items)
        assert isinstance(result, RetainResponse)
        assert result.success is True

    def test_recall_with_types(self, hindsight: Hindsight) -> None:
        """recall with types filter."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Type test memory")

        result = hindsight.recall(
            bank_id=bid,
            query="test",
            types=["experience"],
            budget="low",
        )
        assert isinstance(result, RecallResponse)

    def test_recall_with_tags(self, hindsight: Hindsight) -> None:
        """recall with tags filter."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Tagged memory", tags=["important"])

        result = hindsight.recall(
            bank_id=bid,
            query="memory",
            tags=["important"],
        )
        assert isinstance(result, RecallResponse)

    def test_reflect_with_response_schema(self, hindsight: Hindsight) -> None:
        """reflect with response_schema for structured output."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Bob's favorite color is blue")

        result = hindsight.reflect(
            bank_id=bid,
            query="What color does Bob like?",
            response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
            include_facts=True,
        )
        assert isinstance(result, ReflectResponse)

    def test_reflect_with_budget_high(self, hindsight: Hindsight) -> None:
        """reflect with high budget."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Budget test memory")

        result = hindsight.reflect(
            bank_id=bid,
            query="Tell me about the budget test",
            budget="high",
        )
        assert isinstance(result, ReflectResponse)

    def test_create_bank_duplicate(self, hindsight: Hindsight) -> None:
        """Creating a bank that already exists returns pre-existing."""
        bid = _bid("hs-test-dup-bank")
        hindsight.create_bank(name=bid, description="First creation")
        r2 = hindsight.create_bank(name=bid, description="Second creation")
        assert r2.success is True
        assert r2.config.get("pre_existing") is True

    def test_low_level_shells(self, hindsight: Hindsight) -> None:
        """Low-level namespaces are backed by real tables (documents/entities/operations)."""
        bid = _bid("hs-shells")
        bank = hindsight.create_bank(name=bid, description="shell test bank")
        ws_id = bank.id  # workspace id generated by create_bank

        # documents — real document table
        docs_result = hindsight.documents.list(bank_id=ws_id)
        assert isinstance(docs_result, dict)
        assert "items" in docs_result and "total" in docs_result

        # entities — real kg_node table
        entities_result = hindsight.entities.list(bank_id=ws_id)
        assert isinstance(entities_result, dict)
        assert "items" in entities_result

        # operations — real change_event table
        ops_result = hindsight.operations.list(bank_id=ws_id)
        assert isinstance(ops_result, dict)
        assert "items" in ops_result

        # unsupported methods raise instead of fabricating success
        import pytest as _pytest
        with _pytest.raises(NotImplementedError):
            hindsight.webhooks.list()

    def test_mental_models_shell(self, hindsight: Hindsight) -> None:
        """mental_models.create() delegates to create_mental_model."""
        bid = _bid()
        hindsight.retain(bank_id=bid, content="Shell test memory")
        result = hindsight.mental_models.create(
            bank_id=bid,
            name="Shell Model",
            query="test",
        )
        assert isinstance(result, CreateMentalModelResponse)

    def test_directives_shell(self, hindsight: Hindsight) -> None:
        """directives.create() delegates to create_directive."""
        bid = _bid()
        result = hindsight.directives.create(
            bank_id=bid,
            name="Shell Directive",
            prompt="Be concise",
        )
        assert isinstance(result, CreateDirectiveResponse)

    def test_files_shell(self, hindsight: Hindsight) -> None:
        """files.upload() delegates to retain_files."""
        import tempfile

        bid = _bid()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Files shell upload test content.")
            f.flush()
            tmp_path = f.name

        try:
            result = hindsight.files.upload(
                bank_id=bid,
                files=[tmp_path],
                context="Upload from files shell",
            )
            assert isinstance(result, FileRetainResponse)
            assert isinstance(result.operation_ids, list)
        finally:
            os.unlink(tmp_path)

    def test_aretain_async(self, hindsight: Hindsight) -> None:
        """aretain async method works (via _run_async)."""
        import asyncio

        bid = _bid()

        async def _test():
            return await hindsight.aretain(bank_id=bid, content="Async retain test")

        result = asyncio.run(_test())
        assert isinstance(result, RetainResponse)
        assert result.success is True


class TestCoverageGaps:
    """Tests targeting specific uncovered lines in hindsight.py."""

    # ------------------------------------------------------------------
    # Simple property / shell calls (lines 279, 395, 400, 430, 480)
    # ------------------------------------------------------------------

    def test_memory_property_returns_self(self, hindsight: Hindsight) -> None:
        """hindsight.memory returns self (line 395)."""
        assert hindsight.memory is hindsight

    def test_banks_property_returns_self(self, hindsight: Hindsight) -> None:
        """hindsight.banks returns self (line 400)."""
        assert hindsight.banks is hindsight

    def test_webhooks_shell(self, hindsight: Hindsight) -> None:
        """hindsight.webhooks raises NotImplementedError (no fabricated success)."""
        import pytest as _pytest
        wh = hindsight.webhooks
        assert isinstance(wh, _HindsightNotImplementedShell)
        with _pytest.raises(NotImplementedError):
            wh("arg1", key="val")

    def test_not_implemented_shell_call(self) -> None:
        """_HindsightNotImplementedShell raises on call and attribute access."""
        import pytest as _pytest
        shell = _HindsightNotImplementedShell("test_shell")
        with _pytest.raises(NotImplementedError) as exc_info:
            shell("pos_arg", key="val")
        assert "test_shell" in str(exc_info.value)
        with _pytest.raises(NotImplementedError):
            shell.anything()

    def test_monitoring_health_real(self, hindsight: Hindsight) -> None:
        """monitoring.health() returns real sidecar health data."""
        result = hindsight.monitoring.health()
        assert isinstance(result, dict)
        assert "embedder" in result and "tantivy" in result
        assert "ok" in result

    def test_aclose(self, hindsight: Hindsight) -> None:
        """aclose sets _closed = True (line 480)."""
        import asyncio

        assert hindsight._closed is False
        asyncio.run(hindsight.aclose())
        assert hindsight._closed is True

    # ------------------------------------------------------------------
    # _run_async from async context (line 245)
    # ------------------------------------------------------------------

    def test_sync_wrapper_from_async_context_raises(self, hindsight: Hindsight) -> None:
        """Calling sync wrapper from inside running event loop raises RuntimeError (line 245)."""
        import asyncio

        bid = _bid()

        async def _call_sync_from_async():
            # This should raise because we're inside a running event loop
            with pytest.raises(RuntimeError, match="Cannot call sync wrapper"):
                hindsight.retain(bank_id=bid, content="test")

        asyncio.run(_call_sync_from_async())

    # ------------------------------------------------------------------
    # _ensure_bank cache hit (lines 458-459)
    # ------------------------------------------------------------------

    def test_ensure_bank_cache_hit(self, hindsight: Hindsight) -> None:
        """Second call to same bank hits workspace cache (lines 458-459)."""
        bid = _bid("hs-cache-test")
        # First call creates workspace and populates cache
        ws1 = hindsight._ensure_bank(bid)
        assert ws1
        assert bid in hindsight._ws_cache
        # Second call should hit cache
        ws2 = hindsight._ensure_bank(bid)
        assert ws2 == ws1

    # ------------------------------------------------------------------
    # aretain with timestamp (line 651)
    # ------------------------------------------------------------------

    def test_aretain_with_timestamp(self, hindsight: Hindsight) -> None:
        """aretain with datetime timestamp (line 651)."""
        import asyncio
        import datetime

        bid = _bid("hs-ts")
        ts = datetime.datetime(2024, 1, 15, 10, 30, 0)

        async def _test():
            return await hindsight.aretain(
                bank_id=bid,
                content="Timestamped memory",
                timestamp=ts,
            )

        result = asyncio.run(_test())
        assert isinstance(result, RetainResponse)
        assert result.success is True
        assert result.bank_id == bid

    # ------------------------------------------------------------------
    # aretain error path — store raises RuntimeError (lines 662-663)
    # ------------------------------------------------------------------

    def test_aretain_store_error_returns_failure(self, hindsight: Hindsight) -> None:
        """When store raises RuntimeError, aretain returns RetainResponse(success=False) (lines 662-663)."""
        import asyncio

        bid = _bid("hs-err")

        async def _test():
            # Mock store to raise RuntimeError
            with mock.patch.object(
                hindsight._client, "store", side_effect=RuntimeError("store failed")
            ):
                return await hindsight.aretain(bank_id=bid, content="error test")

        result = asyncio.run(_test())
        assert isinstance(result, RetainResponse)
        assert result.success is False
        assert result.bank_id == bid
        assert result.items_count == 0

    # ------------------------------------------------------------------
    # aretain_batch closed check (line 679)
    # ------------------------------------------------------------------

    def test_aretain_batch_closed_raises(self, hindsight: Hindsight) -> None:
        """aretain_batch raises RuntimeError when client is closed (line 679)."""
        import asyncio

        bid = _bid("hs-closed-batch")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.aretain_batch(bank_id=bid, items=[{"content": "test"}])

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # aretain_batch error handling (lines 693-694)
    # ------------------------------------------------------------------

    def test_aretain_batch_store_error(self, hindsight: Hindsight) -> None:
        """aretain_batch handles store RuntimeError gracefully (lines 693-694)."""
        import asyncio

        bid = _bid("hs-batch-err")

        async def _test():
            with mock.patch.object(
                hindsight._client, "store", side_effect=RuntimeError("store fail")
            ):
                return await hindsight.aretain_batch(
                    bank_id=bid,
                    items=[{"content": "item1"}, {"content": "item2"}],
                )

        result = asyncio.run(_test())
        assert isinstance(result, RetainResponse)
        assert result.success is True
        assert result.items_count == 0  # both failed

    # ------------------------------------------------------------------
    # arecall closed check (line 723)
    # ------------------------------------------------------------------

    def test_arecall_closed_raises(self, hindsight: Hindsight) -> None:
        """arecall raises RuntimeError when closed (line 723)."""
        import asyncio

        bid = _bid("hs-closed-recall")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.arecall(bank_id=bid, query="test")

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # arecall error handling (lines 732-734)
    # ------------------------------------------------------------------

    def test_arecall_search_error(self, hindsight: Hindsight) -> None:
        """arecall handles search RuntimeError gracefully (lines 732-734)."""
        import asyncio

        bid = _bid("hs-recall-err")

        async def _test():
            with mock.patch.object(
                hindsight._client, "search", side_effect=RuntimeError("search fail")
            ):
                return await hindsight.arecall(bank_id=bid, query="test")

        result = asyncio.run(_test())
        assert isinstance(result, RecallResponse)
        assert result.results == []

    # ------------------------------------------------------------------
    # areflect closed check (line 774)
    # ------------------------------------------------------------------

    def test_areflect_closed_raises(self, hindsight: Hindsight) -> None:
        """areflect raises RuntimeError when closed (line 774)."""
        import asyncio

        bid = _bid("hs-closed-reflect")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.areflect(bank_id=bid, query="test")

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # areflect search error (lines 781-783)
    # ------------------------------------------------------------------

    def test_areflect_search_error(self, hindsight: Hindsight) -> None:
        """areflect handles search failure (lines 781-783)."""
        import asyncio

        bid = _bid("hs-reflect-err")

        async def _test():
            # Make store work (for creating bank) but search fail
            with mock.patch.object(
                hindsight._client, "search", side_effect=RuntimeError("search fail")
            ):
                return await hindsight.areflect(bank_id=bid, query="test")

        result = asyncio.run(_test())
        assert isinstance(result, ReflectResponse)
        assert result.text  # should have fallback text

    # ------------------------------------------------------------------
    # areflect LLM insight success (line 801)
    # ------------------------------------------------------------------

    def test_areflect_insight_success(self, hindsight: Hindsight) -> None:
        """areflect when create_insight returns a valid response (line 801)."""
        import asyncio

        bid = _bid("hs-insight")

        async def _test():
            # Mock search to return some memories, mock _call for create_insight
            mock_memories = [
                {"id": "1", "memory_content": "Alice likes pizza", "entity_type": "experience"},
            ]
            with mock.patch.object(hindsight._client, "search", return_value=mock_memories):
                with mock.patch.object(
                    hindsight._client,
                    "_call",
                    return_value={"insight": "Alice enjoys Italian food"},
                ):
                    return await hindsight.areflect(
                        bank_id=bid, query="What does Alice like?", include_facts=True
                    )

        result = asyncio.run(_test())
        assert isinstance(result, ReflectResponse)
        assert "Alice" in result.text
        # Check based_on is populated when include_facts=True with memories
        assert result.based_on is not None
        assert result.based_on.memories is not None
        assert len(result.based_on.memories) > 0

    # ------------------------------------------------------------------
    # alist_memories closed check (line 858)
    # ------------------------------------------------------------------

    def test_alist_memories_closed_raises(self, hindsight: Hindsight) -> None:
        """alist_memories raises RuntimeError when closed (line 858)."""
        import asyncio

        bid = _bid("hs-closed-list")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.alist_memories(bank_id=bid)

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # alist_memories search error (lines 866-868)
    # ------------------------------------------------------------------

    def test_alist_memories_search_error(self, hindsight: Hindsight) -> None:
        """alist_memories handles search error (lines 866-868)."""
        import asyncio

        bid = _bid("hs-list-err")

        async def _test():
            with mock.patch.object(
                hindsight._client, "search", side_effect=RuntimeError("search fail")
            ):
                return await hindsight.alist_memories(bank_id=bid)

        result = asyncio.run(_test())
        assert isinstance(result, ListMemoryUnitsResponse)
        assert result.items == []
        assert result.total == 0

    # ------------------------------------------------------------------
    # adelete_bank closed check (line 899)
    # ------------------------------------------------------------------

    def test_adelete_bank_closed_raises(self, hindsight: Hindsight) -> None:
        """adelete_bank raises RuntimeError when closed (line 899)."""
        import asyncio

        bid = _bid("hs-closed-del")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.adelete_bank(bank_id=bid)

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # acreate_bank closed check (line 939)
    # ------------------------------------------------------------------

    def test_acreate_bank_closed_raises(self, hindsight: Hindsight) -> None:
        """acreate_bank raises RuntimeError when closed (line 939)."""
        import asyncio

        bid = _bid("hs-closed-create-bank")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.acreate_bank(name=bid)

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # acreate_bank default name (line 943)
    # ------------------------------------------------------------------

    def test_acreate_bank_default_name(self, hindsight: Hindsight) -> None:
        """acreate_bank with name=None falls back to 'default' (line 943)."""
        import asyncio

        async def _test():
            return await hindsight.acreate_bank(name=None, description="default name test")

        result = asyncio.run(_test())
        assert isinstance(result, CreateBankResponse)
        assert result.name == "default"
        assert result.success is True

    # ------------------------------------------------------------------
    # acreate_bank LLM config paths (lines 983-997)
    # ------------------------------------------------------------------

    def test_acreate_bank_llm_unavailable_fallback(self, hindsight: Hindsight) -> None:
        """When LLM is not available, falls back to default config (lines 990-994)."""
        import asyncio

        bid = _bid("hs-bank-no-llm")

        async def _test():
            # Ensure LLM is unavailable by removing api_key
            with mock.patch.object(hindsight, "_get_llm") as mock_get_llm:
                mock_llm = mock.MagicMock()
                mock_llm.available = False
                mock_get_llm.return_value = mock_llm
                return await hindsight.acreate_bank(name=bid, description="test bank")

        result = asyncio.run(_test())
        assert isinstance(result, CreateBankResponse)
        assert result.name == bid
        # Should have default disposition
        assert "disposition" in result.config

    def test_acreate_bank_llm_returns_valid_json(self, hindsight: Hindsight) -> None:
        """When LLM returns valid JSON config, it's merged (lines 984-986)."""
        import asyncio

        bid = _bid("hs-bank-json")

        async def _test():
            with mock.patch.object(hindsight, "_get_llm") as mock_get_llm:
                mock_llm = mock.MagicMock()
                mock_llm.available = True
                mock_llm.chat.return_value = '{"disposition": {"skepticism": 2, "literalism": 3, "empathy": 4}, "mission": "custom mission"}'
                mock_get_llm.return_value = mock_llm
                return await hindsight.acreate_bank(name=bid)

        result = asyncio.run(_test())
        assert isinstance(result, CreateBankResponse)
        assert result.config.get("mission") == "custom mission"
        assert result.config.get("disposition", {}).get("skepticism") == 2

    def test_acreate_bank_llm_returns_bad_json(self, hindsight: Hindsight) -> None:
        """When LLM returns invalid JSON, stored as _llm_raw (line 988)."""
        import asyncio

        bid = _bid("hs-bank-bad-json")

        async def _test():
            with mock.patch.object(hindsight, "_get_llm") as mock_get_llm:
                mock_llm = mock.MagicMock()
                mock_llm.available = True
                mock_llm.chat.return_value = "not valid json!!!"
                mock_get_llm.return_value = mock_llm
                return await hindsight.acreate_bank(name=bid)

        result = asyncio.run(_test())
        assert isinstance(result, CreateBankResponse)
        assert result.config.get("_llm_raw") == "not valid json!!!"

    def test_acreate_bank_llm_raises_runtime_error(self, hindsight: Hindsight) -> None:
        """When LLM.chat raises RuntimeError, falls back to default (lines 995-997)."""
        import asyncio

        bid = _bid("hs-bank-llm-err")

        async def _test():
            with mock.patch.object(hindsight, "_get_llm") as mock_get_llm:
                mock_llm = mock.MagicMock()
                mock_llm.available = True
                mock_llm.chat.side_effect = RuntimeError("LLM crash")
                mock_get_llm.return_value = mock_llm
                return await hindsight.acreate_bank(name=bid)

        result = asyncio.run(_test())
        assert isinstance(result, CreateBankResponse)
        assert result.success is True
        # Should fall back to default config
        assert "disposition" in result.config

    # ------------------------------------------------------------------
    # retain_files error handling (lines 548-549)
    # ------------------------------------------------------------------

    def test_retain_files_store_error(self, hindsight: Hindsight) -> None:
        """retain_files handles store RuntimeError gracefully (lines 548-549)."""
        import tempfile

        bid = _bid("hs-files-err")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Error test content")
            f.flush()
            tmp_path = f.name
        try:
            with mock.patch.object(
                hindsight._client, "store", side_effect=RuntimeError("store fail")
            ):
                result = hindsight.retain_files(bank_id=bid, files=[tmp_path])
            assert isinstance(result, FileRetainResponse)
            assert isinstance(result.operation_ids, list)
            # Still returns operation IDs even on error
            assert len(result.operation_ids) == 1
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # acreate_mental_model closed check (line 1050)
    # ------------------------------------------------------------------

    def test_acreate_mental_model_closed_raises(self, hindsight: Hindsight) -> None:
        """acreate_mental_model raises RuntimeError when closed (line 1050)."""
        import asyncio

        bid = _bid("hs-closed-mm")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.acreate_mental_model(bank_id=bid, name="Test")

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # acreate_mental_model search error (lines 1061-1062)
    # ------------------------------------------------------------------

    def test_acreate_mental_model_search_error(self, hindsight: Hindsight) -> None:
        """acreate_mental_model handles search error (lines 1061-1062)."""
        import asyncio

        bid = _bid("hs-mm-err")

        async def _test():
            with mock.patch.object(
                hindsight._client, "search", side_effect=RuntimeError("search fail")
            ):
                return await hindsight.acreate_mental_model(bank_id=bid, name="Test Model")

        result = asyncio.run(_test())
        assert isinstance(result, CreateMentalModelResponse)
        assert result.name == "Test Model"

    # ------------------------------------------------------------------
    # acreate_mental_model LLM fallback (lines 1089-1094)
    # ------------------------------------------------------------------

    def test_acreate_mental_model_llm_unavailable_fallback(self, hindsight: Hindsight) -> None:
        """When LLM unavailable, joins memory contents (lines 1089-1094)."""
        import asyncio

        bid = _bid("hs-mm-no-llm")

        async def _test():
            mock_memories = [
                {"id": "1", "memory_content": "Memory A", "entity_type": "test"},
                {"id": "2", "memory_content": "Memory B", "entity_type": "test"},
            ]
            with mock.patch.object(hindsight._client, "search", return_value=mock_memories):
                with mock.patch.object(hindsight, "_get_llm") as mock_get_llm:
                    mock_llm = mock.MagicMock()
                    mock_llm.available = False
                    mock_get_llm.return_value = mock_llm
                    return await hindsight.acreate_mental_model(
                        bank_id=bid, name="Test Model", query="memory"
                    )

        result = asyncio.run(_test())
        assert isinstance(result, CreateMentalModelResponse)
        # Content should be from memory join fallback
        assert "Memory A" in result.content or "Memory B" in result.content

    def test_acreate_mental_model_llm_raises_with_memories(self, hindsight: Hindsight) -> None:
        """When LLM raises RuntimeError but memories exist, fallback (lines 1096-1099)."""
        import asyncio

        bid = _bid("hs-mm-llm-err")

        async def _test():
            mock_memories = [
                {"id": "1", "memory_content": "Fallback A", "entity_type": "test"},
            ]
            with mock.patch.object(hindsight._client, "search", return_value=mock_memories):
                with mock.patch.object(hindsight, "_get_llm") as mock_get_llm:
                    mock_llm = mock.MagicMock()
                    mock_llm.available = True
                    mock_llm.chat.side_effect = RuntimeError("LLM fail")
                    mock_get_llm.return_value = mock_llm
                    return await hindsight.acreate_mental_model(
                        bank_id=bid, name="Test Model", query="fallback"
                    )

        result = asyncio.run(_test())
        assert isinstance(result, CreateMentalModelResponse)
        assert "Fallback A" in result.content

    # ------------------------------------------------------------------
    # acreate_mental_model store error (lines 1117-1119)
    # ------------------------------------------------------------------

    def test_acreate_mental_model_store_error(self, hindsight: Hindsight) -> None:
        """acreate_mental_model handles store error (lines 1117-1119)."""
        import asyncio

        bid = _bid("hs-mm-store-err")

        async def _test():
            # Make search work but store fail
            mock_memories = [
                {"id": "1", "memory_content": "Store test", "entity_type": "test"},
            ]
            with mock.patch.object(hindsight._client, "search", return_value=mock_memories):
                with mock.patch.object(
                    hindsight._client, "store", side_effect=RuntimeError("store fail")
                ):
                    return await hindsight.acreate_mental_model(
                        bank_id=bid, name="Store Err Model", query="store"
                    )

        result = asyncio.run(_test())
        assert isinstance(result, CreateMentalModelResponse)
        assert result.name == "Store Err Model"

    # ------------------------------------------------------------------
    # acreate_directive closed check (line 1166)
    # ------------------------------------------------------------------

    def test_acreate_directive_closed_raises(self, hindsight: Hindsight) -> None:
        """acreate_directive raises RuntimeError when closed (line 1166)."""
        import asyncio

        bid = _bid("hs-closed-dir")
        hindsight.close()

        async def _test():
            with pytest.raises(RuntimeError, match="closed"):
                await hindsight.acreate_directive(bank_id=bid, name="Test", prompt="Be helpful")

        asyncio.run(_test())

    # ------------------------------------------------------------------
    # acreate_directive store error (lines 1179-1181)
    # ------------------------------------------------------------------

    def test_acreate_directive_store_error(self, hindsight: Hindsight) -> None:
        """acreate_directive handles store error (lines 1179-1181)."""
        import asyncio

        bid = _bid("hs-dir-err")

        async def _test():
            with mock.patch.object(
                hindsight._client, "store", side_effect=RuntimeError("store fail")
            ):
                return await hindsight.acreate_directive(
                    bank_id=bid, name="Err Dir", prompt="Be nice"
                )

        result = asyncio.run(_test())
        assert isinstance(result, CreateDirectiveResponse)
        assert result.name == "Err Dir"
        assert result.success is True

    # ------------------------------------------------------------------
    # _run_async direct coverage (line 240-244, non-error path)
    # ------------------------------------------------------------------

    def test_run_async_direct(self) -> None:
        """Verify _run_async works directly without event loop."""

        async def _coro():
            return 42

        result = _run_async(_coro())
        assert result == 42

    # ------------------------------------------------------------------
    # retain_files with files_metadata (line 534)
    # ------------------------------------------------------------------

    def test_retain_files_with_metadata(self, hindsight: Hindsight) -> None:
        """retain_files with custom files_metadata list."""
        import tempfile

        bid = _bid("hs-files-meta")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Metadata test content")
            f.flush()
            tmp_path = f.name
        try:
            result = hindsight.retain_files(
                bank_id=bid,
                files=[tmp_path],
                files_metadata=[
                    {"document_id": "custom-doc", "context": "Custom metadata context"}
                ],
            )
            assert isinstance(result, FileRetainResponse)
            assert len(result.operation_ids) == 1
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # _ensure_bank finds pre-existing workspace server-side (lines 458-459)
    # ------------------------------------------------------------------

    def test_ensure_bank_finds_existing_workspace(
        self, hindsight: Hindsight, stdb_client: Client, stdb_session: dict
    ) -> None:
        """_ensure_bank finds workspace via list_workspaces when not in cache (lines 458-459)."""
        import secrets

        # Create a workspace directly via client (not through Hindsight)
        bank_name = _bid("hs-existing-ws")
        ws_result = stdb_client.create_workspace(name=bank_name)
        ws_id = ws_result.get("id") if isinstance(ws_result, dict) else ws_result

        # Now create a fresh Hindsight with empty cache
        h2 = Hindsight(
            base_url=None,
            stdb_host=stdb_session["host"],
            stdb_port=int(stdb_session["port"]),
            stdb_database=stdb_session["database"],
            api_key=None,
        )
        # Register so _ensure_bank can list workspaces
        try:
            h2._client._call(
                "register", [f"hs_existws_{secrets.token_hex(4)}", "ExistWS Test", "testpass"]
            )
        except RuntimeError:
            pass
        my_id = h2._client._whoami()
        if my_id:
            try:
                h2._client._call("set_initial_admin", [my_id])
            except RuntimeError:
                pass

        # Cache should be empty
        assert bank_name not in h2._ws_cache

        # _ensure_bank should find it via list_workspaces
        found_ws_id = h2._ensure_bank(bank_name)
        assert found_ws_id == ws_id

    # ------------------------------------------------------------------
    # acreate_bank with empty string name (line 943)
    # ------------------------------------------------------------------

    def test_acreate_bank_empty_string_name(self, hindsight: Hindsight) -> None:
        """acreate_bank with name='' falls back to 'default' (line 943)."""
        import asyncio

        async def _test():
            return await hindsight.acreate_bank(name="", description="empty name test")

        result = asyncio.run(_test())
        assert isinstance(result, CreateBankResponse)
        assert result.name == "default"
        assert result.success is True
