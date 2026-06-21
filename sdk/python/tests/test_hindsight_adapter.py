"""Integration tests for Hindsight-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest sdk/python/tests/test_hindsight_adapter.py -v

"""

from __future__ import annotations

import os
import uuid
import tempfile
from pathlib import Path

import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]

from spacetime_memory.sdks.hindsight import (
    Hindsight,
    RetainResponse,
    RecallResponse,
    ReflectResponse,
    RecallResult,
    FileRetainResponse,
    ListMemoryUnitsResponse,
    CreateBankResponse,
    CreateMentalModelResponse,
    CreateDirectiveResponse,
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
    key_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "data" / "id_ecdsa_pkcs8.pem"
    )
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
        h._client._call("register", [f"hs_test_{secrets.token_hex(4)}", "Hindsight Test", "testpass"])
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
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
                h._client._call("register", [f"hs_cm_{secrets.token_hex(4)}", "CM Test", "testpass"])
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
        r1 = hindsight.create_bank(name=bid, description="First creation")
        r2 = hindsight.create_bank(name=bid, description="Second creation")
        assert r2.success is True
        assert r2.config.get("pre_existing") is True

    def test_low_level_shells(self, hindsight: Hindsight) -> None:
        """Low-level REST shells return graceful empty responses."""
        # documents shell
        docs_result = hindsight.documents.list()
        assert isinstance(docs_result, dict)
        assert docs_result.get("status") == "ok"

        # entities shell
        entities_result = hindsight.entities.list()
        assert isinstance(entities_result, dict)

        # operations shell
        ops_result = hindsight.operations.list()
        assert isinstance(ops_result, dict)

        # monitoring shell
        mon_result = hindsight.monitoring.status()
        assert isinstance(mon_result, dict)

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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
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
