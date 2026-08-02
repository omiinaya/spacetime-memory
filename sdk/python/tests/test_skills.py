"""Tests for the SkillsModsMixin — Letta-parity skills and mods.

Unit tests use the ``mock_http_client`` fixture (no SpacetimeDB required).
"""
from __future__ import annotations

import json
import time
from unittest.mock import Mock

import pytest
from conftest import make_sql_response

# ============================================================================
# Helpers
# ============================================================================

def _reducer_resp() -> Mock:
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _sql_resp(rows):
    """Return a mock SQL response."""
    payload = make_sql_response(rows)
    resp = Mock(status_code=200)
    resp.text = payload
    resp.json = lambda: {"result": payload}
    return resp


def _make_skill_memory(
    memory_id: str,
    workspace_id: str = "ws1",
    name: str = "test_skill",
    description: str = "A test skill",
    code: str = "def run(client, workspace_id, **kwargs):\\n    return {\\\"result\\\": \\\"ok\\\"}",
    inputs: dict | None = None,
    outputs: dict | None = None,
    category: str = "test",
) -> dict:
    """Build a memory dict representing a skill entry."""
    state_data = {
        "name": name,
        "description": description,
        "code": code,
        "inputs": inputs or {"param": "str"},
        "outputs": outputs or {"result": "str"},
        "category": category,
        "created_at": int(time.time()),
    }
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "skill",
        "content": json.dumps(state_data, separators=(",", ":")),
        "summary": f"skill:{name}",
        "entities_json": json.dumps({"skill_name": name, "category": category}),
    }


def _make_non_skill_memory(
    memory_id: str,
    workspace_id: str = "ws1",
) -> dict:
    """Build a regular (non-skill) memory dict."""
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "experience",
        "content": "some regular memory",
        "summary": "a regular experience",
        "entities_json": "{}",
    }


def _make_mod_memory(
    memory_id: str,
    workspace_id: str = "ws1",
    mod_name: str = "test_mod",
    version: str = "1.0.0",
    config: dict | None = None,
) -> dict:
    """Build a memory dict representing a mod entry."""
    state_data = {
        "mod_name": mod_name,
        "version": version,
        "config": config or {},
        "installed_at": int(time.time()),
    }
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "mod",
        "content": json.dumps(state_data, separators=(",", ":")),
        "summary": f"mod:{mod_name} v{version}",
        "entities_json": json.dumps({"mod_name": mod_name, "version": version}),
    }


# ============================================================================
# Skill tests
# ============================================================================

class TestSkills:
    """Skills — create, get, list, execute, delete, catalog, learn."""

    # ── create_skill ─────────────────────────────────────────────────────

    def test_create_skill(self, mock_http_client):
        """create_skill calls store_memory with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_skill(
            workspace_id="ws1",
            name="summarize",
            description="Summarize text",
            code="def run(client, ws, text): return text[:100]",
            inputs={"text": "str"},
            outputs={"summary": "str"},
            category="llm",
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/store_memory" in args[0]
        body = json.loads(kwargs["content"])
        assert body[0] == "ws1"
        assert body[3] == "skill"
        # Verify content is valid JSON with expected fields
        skill_data = json.loads(body[4])
        assert skill_data["name"] == "summarize"
        assert skill_data["description"] == "Summarize text"
        assert skill_data["code"] == "def run(client, ws, text): return text[:100]"
        assert skill_data["inputs"] == {"text": "str"}
        assert skill_data["outputs"] == {"summary": "str"}
        assert skill_data["category"] == "llm"
        assert "created_at" in skill_data
        # entities_json should contain skill_name and category
        entities = json.loads(body[6])
        assert entities["skill_name"] == "summarize"
        assert entities["category"] == "llm"

    def test_create_skill_minimal(self, mock_http_client):
        """create_skill with minimal args uses sensible defaults."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_skill(
            workspace_id="ws1",
            name="minimal_skill",
            description="Minimal",
            code="def run(client, ws): pass",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        skill_data = json.loads(body[4])
        assert skill_data["name"] == "minimal_skill"
        assert skill_data["inputs"] == {}
        assert skill_data["outputs"] == {}
        assert skill_data["category"] == ""
        assert skill_data["code"] == "def run(client, ws): pass"

    def test_create_skill_emits_event(self, mock_http_client):
        """create_skill emits a skill.created event (should not crash)."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_skill(
            workspace_id="ws1",
            name="event_skill",
            description="Event test",
            code="def run(client, ws): pass",
        )

        assert result["status"] == "ok"

    # ── get_skill ────────────────────────────────────────────────────────

    def test_get_skill(self, mock_http_client):
        """get_skill returns the skill when found."""
        memory = _make_skill_memory("skill-1")
        mock_http_client._http.post.return_value = _sql_resp([memory])

        skill = mock_http_client.get_skill("skill-1")

        assert skill is not None
        assert skill["skill_id"] == "skill-1"
        assert skill["name"] == "test_skill"
        assert skill["description"] == "A test skill"
        assert "def run(client, workspace_id, **kwargs)" in skill["code"]
        assert skill["inputs"] == {"param": "str"}
        assert skill["outputs"] == {"result": "str"}
        assert skill["category"] == "test"
        assert skill["memory_type"] == "skill"

    def test_get_skill_not_found(self, mock_http_client):
        """get_skill returns None when not found."""
        mock_http_client._http.post.return_value = _sql_resp([])

        skill = mock_http_client.get_skill("missing-skill")

        assert skill is None

    def test_get_skill_wrong_type(self, mock_http_client):
        """get_skill returns None when the memory is not a skill."""
        non_skill = _make_non_skill_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([non_skill])

        skill = mock_http_client.get_skill("mem-1")

        assert skill is None

    # ── list_skills ──────────────────────────────────────────────────────

    def test_list_skills(self, mock_http_client):
        """list_skills returns all skills in a workspace."""
        s1 = _make_skill_memory("s-1", name="skill_a")
        s2 = _make_skill_memory("s-2", name="skill_b")
        nonskill = _make_non_skill_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([s1, s2, nonskill])

        skills = mock_http_client.list_skills(workspace_id="ws1")

        assert len(skills) == 2
        assert {s["name"] for s in skills} == {"skill_a", "skill_b"}

    def test_list_skills_filters_by_category(self, mock_http_client):
        """list_skills filters by category when provided."""
        s_mem = _make_skill_memory("s-1", name="search", category="memory")
        s_llm = _make_skill_memory("s-2", name="summarize", category="llm")
        mock_http_client._http.post.return_value = _sql_resp([s_mem, s_llm])

        memory_skills = mock_http_client.list_skills(workspace_id="ws1", category="memory")
        llm_skills = mock_http_client.list_skills(workspace_id="ws1", category="llm")

        assert len(memory_skills) == 1
        assert memory_skills[0]["name"] == "search"
        assert len(llm_skills) == 1
        assert llm_skills[0]["name"] == "summarize"

    def test_list_skills_empty(self, mock_http_client):
        """list_skills returns empty list when no skills exist."""
        mock_http_client._http.post.return_value = _sql_resp([])

        skills = mock_http_client.list_skills(workspace_id="ws1")

        assert skills == []

    def test_list_skills_filters_non_skill(self, mock_http_client):
        """list_skills ignores non-skill memories."""
        nonskill = _make_non_skill_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([nonskill])

        skills = mock_http_client.list_skills(workspace_id="ws1")

        assert skills == []

    # ── execute_skill ────────────────────────────────────────────────────

    def test_execute_skill_basic(self, mock_http_client):
        """execute_skill runs the skill's code and returns the result."""
        memory = _make_skill_memory(
            "s-exec",
            name="echo",
            code=(
                "def run(client, workspace_id, message):\n"
                '    return {"echo": message}'
            ),
        )
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.execute_skill(
            workspace_id="ws1",
            skill_id="s-exec",
            inputs={"message": "hello world"},
        )

        assert result["status"] == "ok"
        assert result["skill_name"] == "echo"
        assert result["result"] == {"echo": "hello world"}
        assert result["error"] is None

    def test_execute_skill_no_inputs(self, mock_http_client):
        """execute_skill works with no inputs."""
        memory = _make_skill_memory(
            "s-no-input",
            name="no_input",
            code=(
                "def run(client, workspace_id):\n"
                '    return {"status": "ok"}'
            ),
            inputs={},
        )
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.execute_skill(
            workspace_id="ws1",
            skill_id="s-no-input",
        )

        assert result["status"] == "ok"
        assert result["result"] == {"status": "ok"}

    def test_execute_skill_not_found(self, mock_http_client):
        """execute_skill raises NotFoundError for missing skill."""
        mock_http_client._http.post.return_value = _sql_resp([])

        with pytest.raises(Exception, match="not found"):
            mock_http_client.execute_skill(
                workspace_id="ws1",
                skill_id="missing",
            )

    def test_execute_skill_code_has_no_run_function(self, mock_http_client):
        """execute_skill returns error when code has no 'run' function."""
        memory = _make_skill_memory(
            "s-no-fn",
            name="no_fn",
            code="# just a comment, no run function",
        )
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.execute_skill(
            workspace_id="ws1",
            skill_id="s-no-fn",
        )

        assert result["status"] == "error"
        assert "does not define a 'run' function" in result["error"]

    def test_execute_skill_code_raises_exception(self, mock_http_client):
        """execute_skill gracefully handles exceptions in skill code."""
        memory = _make_skill_memory(
            "s-crash",
            name="crash",
            code=(
                "def run(client, workspace_id):\n"
                '    raise ValueError("intentional crash")'
            ),
        )
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.execute_skill(
            workspace_id="ws1",
            skill_id="s-crash",
        )

        assert result["status"] == "error"
        assert "ValueError" in result["error"]

    # ── delete_skill ─────────────────────────────────────────────────────

    def test_delete_skill(self, mock_http_client):
        """delete_skill calls delete_memory for a valid skill."""
        memory = _make_skill_memory("skill-1")
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.delete_skill("skill-1")

        assert result["status"] == "ok"
        calls = mock_http_client._http.post.call_args_list
        delete_calls = [
            c for c in calls
            if "/call/delete_memory" in str(c)
        ]
        assert len(delete_calls) >= 1

    def test_delete_skill_not_found(self, mock_http_client):
        """delete_skill raises NotFoundError for missing skill."""
        mock_http_client._http.post.return_value = _sql_resp([])

        with pytest.raises(Exception, match="not found"):
            mock_http_client.delete_skill("missing")

    def test_delete_skill_wrong_type(self, mock_http_client):
        """delete_skill raises NotFoundError if memory is not a skill."""
        non_skill = _make_non_skill_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([non_skill])

        with pytest.raises(Exception, match="not a skill|not found"):
            mock_http_client.delete_skill("mem-1")


# ============================================================================
# Mod tests
# ============================================================================

class TestMods:
    """Mods — install, uninstall, list, get."""

    # ── install_mod ──────────────────────────────────────────────────────

    def test_install_mod(self, mock_http_client):
        """install_mod calls store_memory with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.install_mod(
            workspace_id="ws1",
            mod_name="auto_summarize",
            version="2.1.0",
            config={"max_length": 200},
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/store_memory" in args[0]
        body = json.loads(kwargs["content"])
        assert body[0] == "ws1"
        assert body[3] == "mod"
        mod_data = json.loads(body[4])
        assert mod_data["mod_name"] == "auto_summarize"
        assert mod_data["version"] == "2.1.0"
        assert mod_data["config"] == {"max_length": 200}
        assert "installed_at" in mod_data
        entities = json.loads(body[6])
        assert entities["mod_name"] == "auto_summarize"
        assert entities["version"] == "2.1.0"

    def test_install_mod_no_config(self, mock_http_client):
        """install_mod works with no config."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.install_mod(
            workspace_id="ws1",
            mod_name="minimal_mod",
            version="1.0.0",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        mod_data = json.loads(body[4])
        assert mod_data["mod_name"] == "minimal_mod"
        assert mod_data["config"] == {}

    # ── list_mods ────────────────────────────────────────────────────────

    def test_list_mods(self, mock_http_client):
        """list_mods returns all installed mods in a workspace."""
        m1 = _make_mod_memory("mod-1", mod_name="mod_a")
        m2 = _make_mod_memory("mod-2", mod_name="mod_b")
        mock_http_client._http.post.return_value = _sql_resp([m1, m2])

        mods = mock_http_client.list_mods(workspace_id="ws1")

        assert len(mods) == 2
        assert {m["mod_name"] for m in mods} == {"mod_a", "mod_b"}

    def test_list_mods_empty(self, mock_http_client):
        """list_mods returns empty list when no mods installed."""
        mock_http_client._http.post.return_value = _sql_resp([])

        mods = mock_http_client.list_mods(workspace_id="ws1")

        assert mods == []

    def test_list_mods_filters_non_mod(self, mock_http_client):
        """list_mods ignores non-mod memories."""
        nonskill = _make_non_skill_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([nonskill])

        mods = mock_http_client.list_mods(workspace_id="ws1")

        assert mods == []

    # ── get_mod ──────────────────────────────────────────────────────────

    def test_get_mod_with_workspace(self, mock_http_client):
        """get_mod returns a mod by name in a specific workspace."""
        mod = _make_mod_memory("mod-1", workspace_id="ws1", mod_name="my_mod")
        # _query("memory", workspace_id="ws1") makes 2 HTTP calls:
        # 1. _call("query_table", ...) → /call/query_table
        # 2. _sql(...) → /sql
        mock_http_client._http.post.side_effect = [
            _reducer_resp(),  # _call to query_table
            _sql_resp([mod]),  # _sql to read query_result
        ]

        result = mock_http_client.get_mod("my_mod", workspace_id="ws1")

        assert result is not None
        assert result["mod_name"] == "my_mod"
        assert result["version"] == "1.0.0"
        assert result["workspace_id"] == "ws1"

    def test_get_mod_not_found_in_workspace(self, mock_http_client):
        """get_mod returns None when mod not found in specified workspace."""
        mock_http_client._http.post.side_effect = [
            _reducer_resp(),  # _call to query_table
            _sql_resp([]),    # _sql to read query_result (no mods)
        ]

        result = mock_http_client.get_mod("nonexistent_mod", workspace_id="ws1")

        assert result is None

    def test_get_mod_in_workspace(self, mock_http_client):
        """_get_mod_in_workspace finds a mod within a workspace."""
        mod = _make_mod_memory("mod-1", workspace_id="ws1", mod_name="specific_mod")
        mock_http_client._http.post.return_value = _sql_resp([mod])

        result = mock_http_client._get_mod_in_workspace("ws1", "specific_mod")

        assert result is not None
        assert result["mod_name"] == "specific_mod"
        assert result["mod_id"] == "mod-1"

    # ── uninstall_mod ────────────────────────────────────────────────────

    def test_uninstall_mod(self, mock_http_client):
        """uninstall_mod removes a mod by name."""
        mod = _make_mod_memory("mod-1", mod_name="remove_me")
        # _query("memory", workspace_id="ws1") makes 2 HTTP calls:
        # 1. _call("query_table", ...) → /call/query_table
        # 2. _sql(...) → /sql (reads query_result)
        # Then delete_memory is a third call
        mock_http_client._http.post.side_effect = [
            _reducer_resp(),  # _call to query_table
            _sql_resp([mod]),  # _sql to read query_result (finds the mod)
            _reducer_resp(),    # delete_memory
        ]

        result = mock_http_client.uninstall_mod(
            workspace_id="ws1",
            mod_name="remove_me",
        )

        assert result["status"] == "ok"
        assert result["removed"] == 1

    def test_uninstall_mod_not_found(self, mock_http_client):
        """uninstall_mod raises NotFoundError when mod not found."""
        # _query("memory", workspace_id="ws1") makes 2 calls
        mock_http_client._http.post.side_effect = [
            _reducer_resp(),   # _call to query_table
            _sql_resp([]),     # _sql reads empty query_result
        ]

        with pytest.raises(Exception, match="not found"):
            mock_http_client.uninstall_mod(
                workspace_id="ws1",
                mod_name="missing_mod",
            )


# ============================================================================
# Catalog tests
# ============================================================================

class TestSkillsCatalog:
    """Skills catalog — built-in skill definitions."""

    def test_get_skills_catalog_returns_list(self, mock_http_client):
        """get_skills_catalog returns a non-empty list."""
        catalog = mock_http_client.get_skills_catalog()

        assert isinstance(catalog, list)
        assert len(catalog) >= 10  # at least 10 built-in skills

    def test_get_skills_catalog_contains_expected_skills(self, mock_http_client):
        """get_skills_catalog includes expected skill names."""
        catalog = mock_http_client.get_skills_catalog()
        names = {s["name"] for s in catalog}

        assert "search_memories" in names
        assert "summarize" in names
        assert "classify" in names
        assert "extract_entities" in names
        assert "translate" in names
        assert "create_note" in names
        assert "list_memories" in names
        assert "graph_query" in names
        assert "create_entity" in names
        assert "semantic_search" in names

    def test_get_skills_catalog_entries_have_required_keys(self, mock_http_client):
        """Each catalog entry has name, description, code, inputs, outputs, category."""
        catalog = mock_http_client.get_skills_catalog()
        required = {"name", "description", "code", "inputs", "outputs", "category"}

        for entry in catalog:
            missing = required - set(entry.keys())
            assert not missing, f"Entry {entry.get('name')} missing keys: {missing}"

    def test_get_skills_catalog_categories(self, mock_http_client):
        """get_skills_catalog entries have valid categories."""
        catalog = mock_http_client.get_skills_catalog()
        valid = {"memory", "llm", "graph", "workspace"}

        for entry in catalog:
            cat = entry.get("category", "")
            assert cat in valid, f"Entry {entry.get('name')} has invalid category {cat!r}"


# ============================================================================
# Learn from interaction tests
# ============================================================================

class TestLearnFromInteraction:
    """Learn from interaction — skill extraction from patterns."""

    def test_learn_from_interaction_basic(self, mock_http_client):
        """learn_from_interaction creates a skill from interaction data."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.learn_from_interaction(
            workspace_id="ws1",
            interaction_data={
                "name": "my_pattern_skill",
                "description": "Learned from repeated pattern",
                "code": "def run(client, ws, x): return x * 2",
                "inputs": {"x": "int"},
                "outputs": {"result": "int"},
            },
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        skill_data = json.loads(body[4])
        assert skill_data["name"] == "my_pattern_skill"
        assert skill_data["category"] == "learned"

    def test_learn_from_interaction_minimal(self, mock_http_client):
        """learn_from_interaction uses defaults when data is minimal."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.learn_from_interaction(
            workspace_id="ws1",
            interaction_data={
                "name": "empty_skill",
            },
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        skill_data = json.loads(body[4])
        assert skill_data["name"] == "empty_skill"
        # Should have default description
        assert "learned from interaction" in skill_data["description"].lower()


# ============================================================================
# Edge case tests
# ============================================================================

class TestSkillsEdgeCases:
    """Skills and Mods — edge cases."""

    def test_malformed_skill_content(self, mock_http_client):
        """Skills with malformed content should not crash."""
        memory = {
            "id": "bad-skill",
            "workspace_id": "ws1",
            "memory_type": "skill",
            "content": "not valid json at all {{{",
            "summary": "skill:bad",
            "entities_json": "{}",
        }
        mock_http_client._http.post.return_value = _sql_resp([memory])

        skill = mock_http_client.get_skill("bad-skill")

        assert skill is not None
        # Should return empty defaults for missing data
        assert skill["name"] == ""
        assert skill["description"] == ""
        assert skill["code"] == ""
        assert skill["inputs"] == {}
        assert skill["outputs"] == {}

    def test_malformed_mod_content(self, mock_http_client):
        """Mods with malformed content should not crash."""
        memory = {
            "id": "bad-mod",
            "workspace_id": "ws1",
            "memory_type": "mod",
            "content": "{{{ broken json",
            "summary": "mod:bad",
            "entities_json": "{}",
        }
        mock_http_client._http.post.side_effect = [
            _reducer_resp(),   # _call to query_table
            _sql_resp([memory]),  # _sql to read query_result
        ]

        # Use get_mod with workspace_id to avoid listing all workspaces first
        result = mock_http_client.get_mod("bad-mod", workspace_id="ws1")

        # Should not crash — mod_name from broken JSON is empty, so name won't match
        assert result is None

    def test_malformed_entities_json(self, mock_http_client):
        """Malformed entities_json should not crash get_skill."""
        memory = _make_skill_memory("s-1")
        memory["entities_json"] = "{{{ broken"
        mock_http_client._http.post.return_value = _sql_resp([memory])

        skill = mock_http_client.get_skill("s-1")

        assert skill is not None
        assert skill["name"] == "test_skill"

    def test_execute_skill_with_client_methods(self, mock_http_client):
        """execute_skill can call client methods within skill code."""
        # Skill that uses client._query internally
        memory = _make_skill_memory(
            "s-use-client",
            name="count_memories",
            code=(
                "def run(client, workspace_id):\n"
                "    memories = client._query('memory', workspace_id=workspace_id)\n"
                '    return {"count": len(memories)}'
            ),
        )

        # Mock: first call is for get_skill (sql query), second is for the
        # skill's internal _query call
        def side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "call/query_table" in str(url):
                # Internal skill _query call
                inner_mem = _make_skill_memory("s-inner")
                return _sql_resp([inner_mem])
            return _sql_resp([memory])

        mock_http_client._http.post.side_effect = side_effect

        result = mock_http_client.execute_skill(
            workspace_id="ws1",
            skill_id="s-use-client",
        )

        assert result["status"] == "ok"
        # The result count depends on internal mock - verify it ran
        assert "count" in result["result"]

    def test_skill_with_empty_code(self, mock_http_client):
        """Skill with empty code should not crash execute_skill."""
        memory = _make_skill_memory("s-empty", code="")
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.execute_skill(
            workspace_id="ws1",
            skill_id="s-empty",
        )

        assert result["status"] == "error"
        assert "does not define a 'run' function" in result["error"]

    def test_list_skills_single_category_no_match(self, mock_http_client):
        """list_skills with non-matching category returns empty list."""
        mem = _make_skill_memory("s-1", category="memory")
        mock_http_client._http.post.return_value = _sql_resp([mem])

        skills = mock_http_client.list_skills(workspace_id="ws1", category="nonexistent")

        assert skills == []

    def test_uninstall_mod_multiple_versions(self, mock_http_client):
        """uninstall_mod removes all versions of a mod by name."""
        mod_v1 = _make_mod_memory("mod-v1", mod_name="my_mod", version="1.0.0")
        mod_v2 = _make_mod_memory("mod-v2", mod_name="my_mod", version="2.0.0")
        # _query makes 2 calls (_call + _sql), then 2 delete calls
        mock_http_client._http.post.side_effect = [
            _reducer_resp(),               # _call to query_table
            _sql_resp([mod_v1, mod_v2]),   # _sql returns both mods
            _reducer_resp(),               # delete v1
            _reducer_resp(),               # delete v2
        ]

        result = mock_http_client.uninstall_mod(
            workspace_id="ws1",
            mod_name="my_mod",
        )

        assert result["status"] == "ok"
        assert result["removed"] == 2
