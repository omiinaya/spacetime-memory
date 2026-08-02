"""Skills/Mods system — Letta-parity reusable agent capabilities.

Skills are reusable capabilities that agents can learn and execute.
Mods extend agent behavior at runtime.

Both skills and mods are stored via the existing memory infrastructure:
- Skills use ``memory_type="skill"``
- Mods use ``memory_type="mod"``

A built-in catalog provides pre-defined skills (search, summarize, classify,
extract, translate, etc.) that agents can use immediately.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ._base import NotFoundError

# ── Constants ─────────────────────────────────────────────────────────────

SKILL_MEMORY_TYPE = "skill"
"""SpacetimeDB ``memory_type`` used for skill entries."""

MOD_MEMORY_TYPE = "mod"
"""SpacetimeDB ``memory_type`` used for mod entries."""


# ── Built-in skill catalog ────────────────────────────────────────────────

BUILTIN_SKILL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "search_memories",
        "description": "Search memories by semantic or keyword query.",
        "code": (
            "def run(client, workspace_id, query, limit=10):\n"
            "    return client.search(workspace_id, query, limit=limit)"
        ),
        "inputs": {"query": "str", "limit": "int"},
        "outputs": {"results": "list[dict]"},
        "category": "memory",
    },
    {
        "name": "summarize",
        "description": "Summarize a block of text into concise bullet points.",
        "code": (
            "def run(client, workspace_id, text, max_length=200):\n"
            '    """Summarize text using the local LLM."""\n'
            "    if client.local_llm:\n"
            '        prompt = f"Summarize the following in at most {max_length} chars:\\n\\n{text}"\n'
            "        return client.local_llm.generate(prompt)\n"
            '    return text[:max_length] + "..." if len(text) > max_length else text'
        ),
        "inputs": {"text": "str", "max_length": "int"},
        "outputs": {"summary": "str"},
        "category": "llm",
    },
    {
        "name": "classify",
        "description": "Classify text into one of the provided categories.",
        "code": (
            "def run(client, workspace_id, text, categories):\n"
            '    """Classify text using the local LLM."""\n'
            "    if client.local_llm:\n"
            '        prompt = f"Classify the following text into one of {categories}:\\n\\n{text}\\n\\nCategory:"\n'
            "        return client.local_llm.generate(prompt)\n"
            "    return categories[0] if categories else \"unknown\""
        ),
        "inputs": {"text": "str", "categories": "list[str]"},
        "outputs": {"category": "str"},
        "category": "llm",
    },
    {
        "name": "extract_entities",
        "description": "Extract named entities from text (people, places, concepts).",
        "code": (
            "def run(client, workspace_id, text):\n"
            '    """Extract entities using KG infrastructure."""\n'
            "    return client.search(workspace_id, text).get(\"entities\", [])"
        ),
        "inputs": {"text": "str"},
        "outputs": {"entities": "list[str]"},
        "category": "memory",
    },
    {
        "name": "translate",
        "description": "Translate text from source_lang to target_lang.",
        "code": (
            "def run(client, workspace_id, text, source_lang, target_lang):\n"
            '    """Translate text using the local LLM."""\n'
            "    if client.local_llm:\n"
            '        prompt = f"Translate the following {source_lang} text to {target_lang}:\\n\\n{text}\\n\\nTranslation:"'
            "        return client.local_llm.generate(prompt)\n"
            "    return text"
        ),
        "inputs": {"text": "str", "source_lang": "str", "target_lang": "str"},
        "outputs": {"translation": "str"},
        "category": "llm",
    },
    {
        "name": "create_note",
        "description": "Create a wiki-style note in the workspace.",
        "code": (
            "def run(client, workspace_id, title, content):\n"
            "    return client.create_note(workspace_id, title, content)"
        ),
        "inputs": {"title": "str", "content": "str"},
        "outputs": {"note_id": "str", "status": "str"},
        "category": "workspace",
    },
    {
        "name": "list_memories",
        "description": "List all memories in a workspace, optionally filtered by type.",
        "code": (
            "def run(client, workspace_id, memory_type=None):\n"
            "    memories = client._query(\"memory\", workspace_id=workspace_id)\n"
            "    if memory_type:\n"
            '        memories = [m for m in memories if m.get("memory_type") == memory_type]\n'
            "    return memories"
        ),
        "inputs": {"memory_type": "str"},
        "outputs": {"memories": "list[dict]"},
        "category": "memory",
    },
    {
        "name": "graph_query",
        "description": "Query the knowledge graph for entities and relationships.",
        "code": (
            "def run(client, workspace_id, query):\n"
            "    return client.query_graph(workspace_id, query)"
        ),
        "inputs": {"query": "str"},
        "outputs": {"results": "list[dict]"},
        "category": "graph",
    },
    {
        "name": "create_entity",
        "description": "Create a new knowledge graph entity node.",
        "code": (
            "def run(client, workspace_id, label, node_type, summary):\n"
            "    return client.create_node(workspace_id, label, node_type, summary)"
        ),
        "inputs": {"label": "str", "node_type": "str", "summary": "str"},
        "outputs": {"node_id": "str", "status": "str"},
        "category": "graph",
    },
    {
        "name": "semantic_search",
        "description": "Perform a semantic (embedding-based) search across all memory types.",
        "code": (
            "def run(client, workspace_id, query, limit=10, threshold=0.5):\n"
            '    """Semantic search returning only results above relevance threshold."""\n'
            "    results = client.search(workspace_id, query, limit=limit)\n"
            '    return [r for r in results if r.get("relevance", 0) >= threshold]'
        ),
        "inputs": {"query": "str", "limit": "int", "threshold": "float"},
        "outputs": {"results": "list[dict]"},
        "category": "memory",
    },
]

BUILTIN_SKILL_MAP: dict[str, dict[str, Any]] = {
    s["name"]: s for s in BUILTIN_SKILL_CATALOG
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _now_seconds() -> int:
    """Return current time in seconds since epoch."""
    return int(time.time())


def _skill_id_from_memory(memory: dict[str, Any]) -> str:
    """Extract the skill ID from a memory dict."""
    return memory.get("id", memory.get("memory_id", ""))


def _make_skill_content(
    name: str,
    description: str,
    code: str,
    inputs: dict[str, str] | None = None,
    outputs: dict[str, str] | None = None,
    category: str = "",
) -> str:
    """Build JSON ``content`` for a skill memory entry.

    Args:
        name: Name of the skill.
        description: Human-readable description.
        code: Executable code/instructions implementing the skill.
        inputs: Dict mapping input parameter names to type hints.
        outputs: Dict mapping output field names to type hints.
        category: Skill category (e.g., 'memory', 'llm', 'graph', 'workspace').

    Returns:
        JSON string suitable for the memory's ``content`` field.
    """
    payload = {
        "name": name,
        "description": description,
        "code": code,
        "inputs": inputs or {},
        "outputs": outputs or {},
        "category": category,
        "created_at": _now_seconds(),
    }
    return json.dumps(payload, separators=(",", ":"))


def _parse_skill_content(content: str) -> dict[str, Any]:
    """Parse skill metadata from a memory content field.

    Args:
        content: Raw ``content`` string from a memory record.

    Returns:
        Dict with skill metadata keys.
    """
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {
            "name": "",
            "description": "",
            "code": "",
            "inputs": {},
            "outputs": {},
            "category": "",
            "created_at": 0,
        }


def _make_mod_content(
    mod_name: str,
    version: str,
    config: dict[str, Any] | None = None,
) -> str:
    """Build JSON ``content`` for a mod memory entry.

    Args:
        mod_name: Name of the mod.
        version: Version string (e.g. '1.0.0').
        config: Optional configuration dict.

    Returns:
        JSON string suitable for the memory's ``content`` field.
    """
    payload = {
        "mod_name": mod_name,
        "version": version,
        "config": config or {},
        "installed_at": _now_seconds(),
    }
    return json.dumps(payload, separators=(",", ":"))


def _parse_mod_content(content: str) -> dict[str, Any]:
    """Parse mod metadata from a memory content field."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {
            "mod_name": "",
            "version": "",
            "config": {},
            "installed_at": 0,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Mixin
# ═══════════════════════════════════════════════════════════════════════════


class SkillsModsMixin:
    """Spacetime-Memory Skills/Mods mixin.

    Provides Letta-parity reusable skill management, built-in skill catalog,
    and behavior mods — all backed by the existing memory store.

    Skills are ``memory_type="skill"`` entries whose ``content`` is a JSON
    blob holding ``name``, ``description``, ``code``, ``inputs``, ``outputs``,
    ``category``, and ``created_at``.

    Mods are ``memory_type="mod"`` entries whose ``content`` is a JSON blob
    holding ``mod_name``, ``version``, ``config``, and ``installed_at``.

    Inherits from ``ClientBase`` for connection infrastructure.
    """

    # ── Skills ────────────────────────────────────────────────────────────

    def create_skill(
        self,
        workspace_id: str,
        name: str,
        description: str,
        code: str,
        inputs: dict[str, str] | None = None,
        outputs: dict[str, str] | None = None,
        category: str = "",
    ) -> dict[str, Any]:
        """Define a new skill in the given workspace.

        Args:
            workspace_id: Target workspace.
            name: Short unique name for the skill (e.g. ``"summarize"``).
            description: Human-readable description of what the skill does.
            code: Executable code/instructions (e.g. a Python function body).
            inputs: Optional dict mapping parameter names to type strings.
            outputs: Optional dict mapping return field names to type strings.
            category: Optional category label (``"memory"``, ``"llm"``,
                ``"graph"``, ``"workspace"``, etc.).

        Returns:
            Reducer status dict with ``skill_id`` in entities_json.
        """
        content = _make_skill_content(
            name, description, code, inputs, outputs, category
        )
        summary = f"skill:{name}"
        entities = json.dumps({"skill_name": name, "category": category})

        result = self._call(
            "store_memory",
            [
                workspace_id,
                "",                           # peer_id
                "",                           # observer_id
                SKILL_MEMORY_TYPE,             # memory_type
                content,
                summary,
                entities,
                0.8,                          # confidence
                "",                           # source_session_id
                "",                           # source_message_id
                "",                           # images_json
            ],
        )

        # Emit event
        self._emit_event(
            "skill.created",
            {
                "name": name,
                "workspace_id": workspace_id,
                "category": category,
            },
            workspace_id=workspace_id,
        )

        # Invalidate query cache
        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        return result

    def get_skill(
        self,
        skill_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a skill definition by its memory ID.

        Args:
            skill_id: The skill's memory ID.

        Returns:
            A skill dict with keys ``skill_id``, ``name``, ``description``,
            ``code``, ``inputs``, ``outputs``, ``category``, ``created_at``,
            ``workspace_id`` — or ``None`` if not found.
        """
        rows = self._query("memory", filter_dict={"id": skill_id})
        if not rows:
            return None
        memory = rows[0]
        if memory.get("memory_type") != SKILL_MEMORY_TYPE:
            return None
        return self._build_skill_dict(memory)

    def list_skills(
        self,
        workspace_id: str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """List available skills in a workspace, optionally filtered by category.

        Args:
            workspace_id: Target workspace.
            category: If provided, only return skills matching this category
                (e.g. ``"memory"``, ``"llm"``, ``"graph"``, ``"workspace"``).

        Returns:
            A list of skill dicts sorted by ``created_at`` descending.
        """
        rows = self._query("memory", workspace_id=workspace_id)
        skills: list[dict[str, Any]] = []
        for row in rows:
            if row.get("memory_type") != SKILL_MEMORY_TYPE:
                continue
            skill_data = _parse_skill_content(row.get("content", ""))
            if category and skill_data.get("category") != category:
                continue
            skills.append(self._build_skill_dict(row))

        skills.sort(key=lambda s: s.get("created_at", 0), reverse=True)
        return skills

    def execute_skill(
        self,
        workspace_id: str,
        skill_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a skill by ID (client-side execution).

        Retrieves the skill definition, then runs its ``code`` as a Python
        function with the provided inputs.

        The skill's code must define a ``run`` function that accepts
        ``(client, workspace_id, **inputs)``.

        Args:
            workspace_id: Target workspace.
            skill_id: The skill's memory ID.
            inputs: Dict of input parameters matching the skill's ``inputs``
                schema.

        Returns:
            Dict with ``status``, ``skill_name``, and ``result`` keys.
            On failure, includes ``error`` with details.

        Raises:
            NotFoundError: If the skill is not found.
            ValueError: If the skill code has no ``run`` function.
        """
        skill = self.get_skill(skill_id)
        if skill is None:
            raise NotFoundError(f"Skill {skill_id!r} not found")

        code = skill.get("code", "")
        name = skill.get("name", "unknown")
        result: Any = None
        error: str | None = None

        try:
            # Create a local namespace and execute the skill code
            namespace: dict[str, Any] = {}
            exec(code, namespace)

            if "run" not in namespace:
                raise ValueError(
                    f"Skill {name!r} code does not define a 'run' function"
                )

            run_fn = namespace["run"]
            inputs = inputs or {}
            result = run_fn(self, workspace_id, **inputs)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        self._emit_event(
            "skill.executed",
            {
                "skill_id": skill_id,
                "skill_name": name,
                "workspace_id": workspace_id,
                "error": error,
            },
            workspace_id=workspace_id,
        )

        return {
            "status": "error" if error else "ok",
            "skill_name": name,
            "result": result,
            "error": error,
        }

    def delete_skill(
        self,
        skill_id: str,
    ) -> dict[str, Any]:
        """Remove a skill by its memory ID.

        Args:
            skill_id: The skill's memory ID.

        Returns:
            Reducer status dict.

        Raises:
            NotFoundError: If the skill does not exist.
        """
        # Verify it exists and is a skill
        rows = self._query("memory", filter_dict={"id": skill_id})
        if not rows:
            raise NotFoundError(f"Skill {skill_id!r} not found")
        if rows[0].get("memory_type") != SKILL_MEMORY_TYPE:
            raise NotFoundError(f"Memory {skill_id!r} is not a skill")

        return self._call("delete_memory", [skill_id])

    # ── Mods ──────────────────────────────────────────────────────────────

    def install_mod(
        self,
        workspace_id: str,
        mod_name: str,
        version: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Install a behavior mod in a workspace.

        Args:
            workspace_id: Target workspace.
            mod_name: Name of the mod (e.g. ``"auto_summarize"``).
            version: Version string (e.g. ``"1.0.0"``).
            config: Optional configuration dict.

        Returns:
            Reducer status dict.
        """
        content = _make_mod_content(mod_name, version, config)
        summary = f"mod:{mod_name} v{version}"
        entities = json.dumps({"mod_name": mod_name, "version": version})

        result = self._call(
            "store_memory",
            [
                workspace_id,
                "",                           # peer_id
                "",                           # observer_id
                MOD_MEMORY_TYPE,               # memory_type
                content,
                summary,
                entities,
                0.9,                          # confidence
                "",                           # source_session_id
                "",                           # source_message_id
                "",                           # images_json
            ],
        )

        self._emit_event(
            "mod.installed",
            {
                "mod_name": mod_name,
                "version": version,
                "workspace_id": workspace_id,
            },
            workspace_id=workspace_id,
        )

        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        return result

    def uninstall_mod(
        self,
        workspace_id: str,
        mod_name: str,
    ) -> dict[str, Any]:
        """Uninstall a behavior mod by name.

        Args:
            workspace_id: Target workspace.
            mod_name: Name of the mod to remove.

        Returns:
            Dict with ``status``, ``removed`` count.

        Raises:
            NotFoundError: If no mod with that name is installed.
        """
        rows = self._query("memory", workspace_id=workspace_id)
        to_delete: list[str] = []
        for row in rows:
            if row.get("memory_type") != MOD_MEMORY_TYPE:
                continue
            content_data = _parse_mod_content(row.get("content", ""))
            if content_data.get("mod_name") == mod_name:
                mid = _skill_id_from_memory(row)
                if mid:
                    to_delete.append(mid)

        if not to_delete:
            raise NotFoundError(
                f"Mod {mod_name!r} not found in workspace {workspace_id!r}"
            )

        for mid in to_delete:
            self._call("delete_memory", [mid])

        self._emit_event(
            "mod.uninstalled",
            {
                "mod_name": mod_name,
                "workspace_id": workspace_id,
                "count": len(to_delete),
            },
            workspace_id=workspace_id,
        )

        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        return {"status": "ok", "removed": len(to_delete)}

    def list_mods(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List installed mods in a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            A list of mod dicts, each with keys ``mod_id``, ``mod_name``,
            ``version``, ``config``, ``installed_at``, ``workspace_id``.
            Sorted by ``installed_at`` descending.
        """
        rows = self._query("memory", workspace_id=workspace_id)
        mods: list[dict[str, Any]] = []
        for row in rows:
            if row.get("memory_type") != MOD_MEMORY_TYPE:
                continue
            mods.append(self._build_mod_dict(row))

        mods.sort(key=lambda m: m.get("installed_at", 0), reverse=True)
        return mods

    def get_mod(
        self,
        mod_name: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Get details of a mod by name.

        Args:
            mod_name: Name of the mod to find.
            workspace_id: Optional workspace to search in. If provided,
                only searches that workspace. If ``None``, searches all
                workspaces.

        Returns:
            A mod dict, or ``None`` if not found.
        """
        if workspace_id:
            return self._get_mod_in_workspace(workspace_id, mod_name)

        # Search across all workspaces
        workspaces = self._query("workspace")
        for ws in workspaces:
            ws_id = ws.get("id", "")
            if not ws_id:
                continue
            mod = self._get_mod_in_workspace(ws_id, mod_name)
            if mod:
                return mod
        return None

    def _get_mod_in_workspace(
        self,
        workspace_id: str,
        mod_name: str,
    ) -> dict[str, Any] | None:
        """Find a mod by name within a specific workspace."""
        rows = self._query("memory", workspace_id=workspace_id)
        for row in rows:
            if row.get("memory_type") != MOD_MEMORY_TYPE:
                continue
            content_data = _parse_mod_content(row.get("content", ""))
            if content_data.get("mod_name") == mod_name:
                return self._build_mod_dict(row)
        return None

    # ── Catalog ───────────────────────────────────────────────────────────

    def get_skills_catalog(
        self,
    ) -> list[dict[str, Any]]:
        """Return the built-in skill catalog with pre-defined skills.

        The catalog includes skills for:
        - ``search_memories`` — semantic/keyword memory search
        - ``summarize`` — text summarization via LLM
        - ``classify`` — text classification via LLM
        - ``extract_entities`` — named entity extraction
        - ``translate`` — text translation via LLM
        - ``create_note`` — wiki-style note creation
        - ``list_memories`` — listing memories by type
        - ``graph_query`` — knowledge graph queries
        - ``create_entity`` — KG entity creation
        - ``semantic_search`` — threshold-filtered semantic search

        Returns:
            A list of skill definition dicts, each with keys ``name``,
            ``description``, ``code``, ``inputs``, ``outputs``, ``category``.
        """
        return list(BUILTIN_SKILL_CATALOG)

    # ── Learn from interaction ────────────────────────────────────────────

    def learn_from_interaction(
        self,
        workspace_id: str,
        interaction_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract a skill from an interaction pattern.

        Analyzes interaction data (queries, actions, responses) and
        creates a skill that captures the observed pattern.

        Args:
            workspace_id: Target workspace.
            interaction_data: Dict containing interaction pattern details.
                Expected keys:
                - ``name`` (str): Suggested skill name.
                - ``description`` (str): What the skill does.
                - ``code`` (str): Inferred implementation code.
                - ``inputs`` (dict, optional): Input parameter schema.
                - ``outputs`` (dict, optional): Output schema.

        Returns:
            The result of :meth:`create_skill`.
        """
        name = interaction_data.get("name", "learned_skill")
        description = interaction_data.get(
            "description", "Skill learned from interaction pattern"
        )
        code = interaction_data.get("code", "")
        inputs = interaction_data.get("inputs")
        outputs = interaction_data.get("outputs")

        return self.create_skill(
            workspace_id=workspace_id,
            name=name,
            description=description,
            code=code,
            inputs=inputs,
            outputs=outputs,
            category="learned",
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _build_skill_dict(
        self,
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a memory record into a structured skill dict.

        Args:
            memory: A raw memory dict from the database.

        Returns:
            A normalised skill dict.
        """
        skill_data = _parse_skill_content(memory.get("content", ""))
        entities_raw = memory.get("entities_json", "{}")
        try:
            json.loads(entities_raw) if entities_raw else {}
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "skill_id": _skill_id_from_memory(memory),
            "workspace_id": memory.get("workspace_id", ""),
            "name": skill_data.get("name", ""),
            "description": skill_data.get("description", ""),
            "code": skill_data.get("code", ""),
            "inputs": skill_data.get("inputs", {}),
            "outputs": skill_data.get("outputs", {}),
            "category": skill_data.get("category", ""),
            "created_at": skill_data.get("created_at", 0),
            "memory_type": SKILL_MEMORY_TYPE,
        }

    def _build_mod_dict(
        self,
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a memory record into a structured mod dict.

        Args:
            memory: A raw memory dict from the database.

        Returns:
            A normalised mod dict.
        """
        mod_data = _parse_mod_content(memory.get("content", ""))

        return {
            "mod_id": _skill_id_from_memory(memory),
            "workspace_id": memory.get("workspace_id", ""),
            "mod_name": mod_data.get("mod_name", ""),
            "version": mod_data.get("version", ""),
            "config": mod_data.get("config", {}),
            "installed_at": mod_data.get("installed_at", 0),
            "memory_type": MOD_MEMORY_TYPE,
        }
