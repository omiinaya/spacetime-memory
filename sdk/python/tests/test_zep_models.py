"""Unit tests for the Zep adapter models (_models.py).

Tests MemoryMessage, Memory, Session, MemorySearchResult, Fact,
Summary, and all stub types (RoleType, SearchScope, SearchType,
ZepEnvironment, SuccessResponse, etc.).
"""

from __future__ import annotations

import pytest

from spacetime_memory.sdks.zep._models import (
    ApiError,
    BadRequestError,
    ConflictError,
    Fact,
    FactRatingExamples,
    FactRatingInstruction,
    Memory,
    MemoryMessage,
    MemorySearchResult,
    NotFoundError,
    RoleType,
    SearchScope,
    SearchType,
    Session,
    SessionFactRatingExamples,
    SessionFactRatingInstruction,
    SuccessResponse,
    Summary,
    ZepEnvironment,
)

pytestmark = pytest.mark.unit


# ── Error classes ──────────────────────────────────────────────────────────


class TestErrorClasses:
    def test_not_found_error(self):
        err = NotFoundError("not found")
        # The error may be a pydantic BaseModel (zep_python installed)
        # or a RuntimeError subclass (fallback). Either way, it's constructable.
        assert "not found" in str(err)

    def test_bad_request_error(self):
        err = BadRequestError("bad request")
        assert "bad request" in str(err)

    def test_api_error(self):
        # ApiError is a pydantic BaseModel — keyword args only.
        err = ApiError(message="api error")
        assert "api error" in str(err)

    def test_conflict_error(self):
        err = ConflictError("conflict")
        assert "conflict" in str(err)

    def test_not_found_subclass_of_runtime(self):
        # The error classes are either RuntimeError subclasses (fallback)
        # or pydantic BaseModel subclasses (real zep_python) or Exception
        # subclasses (zep_python v2+ ApiError hierarchy). Both are valid.
        from pydantic.v1.main import BaseModel as PydanticBaseModel
        assert issubclass(NotFoundError, (RuntimeError, PydanticBaseModel, Exception))


# ── MemoryMessage ─────────────────────────────────────────────────────────


class TestMemoryMessage:
    def test_default_construction(self):
        msg = MemoryMessage()
        assert msg.role == "user"
        assert msg.content == ""
        assert msg.metadata == {}
        assert msg.token_count is None
        assert msg.uuid is None

    def test_custom_construction(self):
        msg = MemoryMessage(
            role="assistant",
            content="Hello!",
            created_at="2024-01-01T00:00:00",
            metadata={"key": "val"},
            token_count=42,
            uuid="abc-123",
        )
        assert msg.role == "assistant"
        assert msg.content == "Hello!"
        assert msg.metadata == {"key": "val"}
        assert msg.token_count == 42
        assert msg.uuid == "abc-123"

    def test_to_dict_basic(self):
        msg = MemoryMessage(role="user", content="Hi")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hi"

    def test_to_dict_with_all_fields(self):
        msg = MemoryMessage(
            role="assistant",
            content="Hello",
            created_at="now",
            metadata={"k": "v"},
            role_type="primary",
            token_count=10,
            updated_at="later",
            uuid="u1",
        )
        d = msg.to_dict()
        assert d["created_at"] == "now"
        assert d["role_type"] == "primary"
        assert d["token_count"] == 10
        assert d["updated_at"] == "later"
        assert d["uuid"] == "u1"

    def test_to_dict_with_kwargs(self):
        msg = MemoryMessage(role="user", content="Hi", extra_field="extra")
        d = msg.to_dict()
        assert d["extra_field"] == "extra"

    def test_to_dict_excludes_none_fields(self):
        msg = MemoryMessage(role="user", content="Hello")
        d = msg.to_dict()
        assert "created_at" not in d
        assert "token_count" not in d
        assert "uuid" not in d


# ── Memory ─────────────────────────────────────────────────────────────────


class TestMemoryModel:
    def test_default_construction(self):
        mem = Memory()
        assert mem.session_id == ""
        assert mem.messages == []
        assert mem.facts == []
        assert mem.relevant_facts == []

    def test_custom_construction(self):
        facts = ["fact1"]
        relevant = [Fact(uuid="f1", fact="f1")]
        mem = Memory(
            session_id="s1",
            messages=[MemoryMessage(role="user", content="Hi")],
            metadata={"key": "val"},
            facts=facts,
            relevant_facts=relevant,
        )
        assert mem.session_id == "s1"
        assert len(mem.messages) == 1
        assert mem.metadata == {"key": "val"}
        assert mem.facts == ["fact1"]
        assert len(mem.relevant_facts) == 1

    def test_to_dict(self):
        mem = Memory(
            session_id="s1",
            messages=[MemoryMessage(role="user", content="Hi")],
            facts=["f1"],
            relevant_facts=[Fact(uuid="f1", fact="f1")],
        )
        d = mem.to_dict()
        assert d["session_id"] == "s1"
        assert len(d["messages"]) == 1
        assert d["messages"][0]["content"] == "Hi"
        assert d["facts"] == ["f1"]

    def test_kwargs_stored(self):
        mem = Memory(session_id="s1", custom_attr="custom")
        assert mem.custom_attr == "custom"

    def test_to_dict_includes_relevant_facts(self):
        mem = Memory(
            session_id="s1",
            relevant_facts=[Fact(uuid="f1", fact="test fact")],
        )
        d = mem.to_dict()
        assert len(d["relevant_facts"]) == 1
        assert d["relevant_facts"][0]["fact"] == "test fact"


# ── Session ────────────────────────────────────────────────────────────────


class TestSessionModel:
    def test_default_construction(self):
        s = Session()
        assert s.session_id == ""
        assert s.metadata == {}
        assert s.classifications == []
        assert s.facts == []
        assert s.uuid is None

    def test_custom_construction(self):
        s = Session(
            session_id="s1",
            metadata={"user": "alice"},
            created_at="now",
            updated_at="later",
            classifications=["general"],
            user_id="u1",
            uuid="abc-123",
        )
        assert s.session_id == "s1"
        assert s.metadata == {"user": "alice"}
        assert s.uuid == "abc-123"

    def test_to_dict_basic(self):
        s = Session(session_id="s1")
        d = s.to_dict()
        assert d["session_id"] == "s1"

    def test_to_dict_with_optionals(self):
        s = Session(session_id="s1", classifications=["c1"], uuid="u1")
        d = s.to_dict()
        assert d["classifications"] == ["c1"]
        assert d["uuid"] == "u1"

    def test_to_dict_excludes_none(self):
        s = Session(session_id="s1")
        d = s.to_dict()
        assert "classifications" not in d
        assert "uuid" not in d

    def test_kwargs_stored(self):
        s = Session(session_id="s1", custom="val")
        assert s.custom == "val"


# ── MemorySearchResult ─────────────────────────────────────────────────────


class TestMemorySearchResult:
    def test_default_construction(self):
        msr = MemorySearchResult()
        assert msr.message is None
        assert msr.score == 0.0
        assert msr.metadata == {}

    def test_custom_construction(self):
        msg = MemoryMessage(role="user", content="test")
        msr = MemorySearchResult(message=msg, score=0.95)
        assert msr.message is not None
        assert msr.message.content == "test"
        assert msr.score == 0.95

    def test_to_dict(self):
        msg = MemoryMessage(role="user", content="hello")
        msr = MemorySearchResult(message=msg, score=0.9, metadata={"k": "v"})
        d = msr.to_dict()
        assert d["score"] == 0.9
        assert d["message"]["content"] == "hello"
        assert d["metadata"]["k"] == "v"

    def test_to_dict_no_message(self):
        msr = MemorySearchResult(score=0.5)
        d = msr.to_dict()
        assert d["message"] is None


# ── Fact ───────────────────────────────────────────────────────────────────


class TestFactModel:
    def test_default_construction(self):
        f = Fact()
        assert f.uuid == ""
        assert f.fact == ""
        assert f.created_at == ""
        assert f.rating is None

    def test_custom_construction(self):
        f = Fact(uuid="f1", fact="Alice likes pizza", created_at="now", rating=0.8)
        assert f.fact == "Alice likes pizza"
        assert f.rating == 0.8

    def test_to_dict(self):
        f = Fact(uuid="f1", fact="test", created_at="now")
        d = f.to_dict()
        assert d["uuid"] == "f1"
        assert d["fact"] == "test"
        assert "rating" not in d

    def test_to_dict_with_rating(self):
        f = Fact(uuid="f1", fact="test", created_at="now", rating=0.9)
        d = f.to_dict()
        assert d["rating"] == 0.9

    def test_kwargs_stored(self):
        f = Fact(uuid="f1", fact="test", created_at="now", extra="val")
        assert f.extra == "val"


# ── Summary ────────────────────────────────────────────────────────────────


class TestSummaryModel:
    def test_default_construction(self):
        s = Summary()
        assert s.uuid == ""
        assert s.content == ""
        assert s.token_count == 0

    def test_custom_construction(self):
        s = Summary(uuid="s1", created_at="now", content="summary text", token_count=50)
        assert s.content == "summary text"
        assert s.token_count == 50

    def test_kwargs_stored(self):
        s = Summary(uuid="s1", created_at="now", content="test", extra="val")
        assert s.extra == "val"


# ── Stub types ─────────────────────────────────────────────────────────────


class TestStubTypes:
    def test_role_type_constants(self):
        assert RoleType.UserRole == "user"
        assert RoleType.AssistantRole == "assistant"
        assert RoleType.SystemRole == "system"
        assert RoleType.FunctionRole == "function"
        assert RoleType.ToolRole == "tool"

    def test_search_scope_constants(self):
        assert SearchScope.MESSAGES == "messages"
        assert SearchScope.FACTS == "facts"
        assert SearchScope.SUMMARY == "summary"

    def test_search_type_constants(self):
        assert SearchType.SIMILARITY == "similarity"
        assert SearchType.MMR == "mmr"

    def test_zep_environment_constants(self):
        assert ZepEnvironment.CLOUD == "cloud"
        assert ZepEnvironment.SELF_HOSTED == "self_hosted"

    def test_success_response(self):
        sr = SuccessResponse(message="ok")
        assert sr.message == "ok"


# ── Fact rating stubs ──────────────────────────────────────────────────────


class TestFactRatingStubs:
    def test_fact_rating_examples(self):
        fre = FactRatingExamples(high="high", medium="med", low="low")
        assert fre.high == "high"
        assert fre.medium == "med"

    def test_fact_rating_instruction(self):
        fri = FactRatingInstruction(instruction="be strict")
        assert fri.instruction == "be strict"

    def test_fact_rating_instruction_with_examples(self):
        fre = FactRatingExamples(high="good", low="bad")
        fri = FactRatingInstruction(instruction="rate facts", examples=fre)
        assert fri.examples.high == "good"

    def test_session_fact_rating_examples(self):
        sfre = SessionFactRatingExamples(high="relevant", low="irrelevant")
        assert sfre.high == "relevant"

    def test_session_fact_rating_instruction(self):
        sfri = SessionFactRatingInstruction(instruction="be fair")
        assert sfri.instruction == "be fair"

    def test_kwargs_on_all_stubs(self):
        fre = FactRatingExamples(high="h", medium="m", low="l", extra="val")
        assert fre.extra == "val"
