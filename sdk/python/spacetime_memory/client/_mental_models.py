"""Mental models / directives mixin — Hindsight parity.

Mental models are structured directives that define how an agent should
think about a domain. They extend the Directive concept (from the
Rust ``directive`` module) with:

- **MentalModel** — a named thinking pattern with rules, constraints, and heuristics
- **Disposition** — a persistent behavioural tendency (optimistic, skeptical, etc.)
- **Directive templates** — reusable directive patterns

All data is stored via the existing ``directive`` table using the
``create_directive`` reducer with ``category='mental_model'`` etc.
Client-side logic provides the enhanced processing (``apply_mental_model``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ._base import logger

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MentalModel:
    """A structured thinking pattern that guides agent reasoning.

    Attributes:
        id: Unique identifier.
        workspace_id: The workspace this model belongs to.
        name: Human-readable name (e.g. "Customer Empathy Lens").
        rules: List of prescriptive rules the agent must follow.
        constraints: List of boundaries or limitations.
        heuristics: List of mental shortcuts / thinking patterns.
        description: Free-text description of when/how to apply.
        tags: Categorisation tags.
        status: "active" or "inactive".
        priority: Priority level (1–5).
        created_at: Unix micros timestamp.
        updated_at: Unix micros timestamp.
    """
    id: str = ""
    workspace_id: str = ""
    name: str = ""
    rules: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    heuristics: list[str] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    priority: int = 3
    created_at: int = 0
    updated_at: int = 0

    @classmethod
    def from_directive(cls, row: dict[str, Any]) -> MentalModel:
        """Parse a MentalModel from a directive table row."""
        desc = row.get("description", "{}")
        try:
            parsed = json.loads(desc) if isinstance(desc, str) else desc
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        rules_in = parsed.get("rules", []) if isinstance(parsed, dict) else []
        constraints_in = parsed.get("constraints", []) if isinstance(parsed, dict) else []
        heuristics_in = parsed.get("heuristics", []) if isinstance(parsed, dict) else []
        description = parsed.get("description", "") if isinstance(parsed, dict) else str(parsed)

        tags_raw = row.get("tags_json", "[]")
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags = []
        elif isinstance(tags_raw, list):
            tags = tags_raw
        else:
            tags = []

        return cls(
            id=row.get("id", ""),
            workspace_id=row.get("workspace_id", ""),
            name=row.get("title", ""),
            rules=rules_in if isinstance(rules_in, list) else [],
            constraints=constraints_in if isinstance(constraints_in, list) else [],
            heuristics=heuristics_in if isinstance(heuristics_in, list) else [],
            description=description,
            tags=tags if isinstance(tags, list) else [],
            status=row.get("status", "active"),
            priority=int(row.get("priority", 3)),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )

    def to_directive_args(self) -> dict[str, Any]:
        """Build the description JSON for storing as a directive."""
        desc_payload = {
            "rules": self.rules,
            "constraints": self.constraints,
            "heuristics": self.heuristics,
            "description": self.description,
        }
        return {
            "title": self.name,
            "description": json.dumps(desc_payload),
            "category": "mental_model",
            "tags_json": json.dumps(self.tags),
            "priority": min(max(self.priority, 1), 5),
        }


@dataclass
class Disposition:
    """A persistent behavioural tendency for an agent.

    Attributes:
        id: The directive ID (populated after storage).
        workspace_id: The workspace this disposition belongs to.
        disposition_type: One of "optimistic", "skeptical", "neutral",
            "cautious", "creative", "analytical", "empathetic".
        intensity: Strength of the disposition (1–5).
        description: Free-text elaboration.
        active: Whether this disposition is currently applied.
        created_at: Unix micros timestamp.
    """
    id: str = ""
    workspace_id: str = ""
    disposition_type: str = "neutral"
    intensity: int = 3
    description: str = ""
    active: bool = True
    created_at: int = 0

    @classmethod
    def from_directive(cls, row: dict[str, Any]) -> Disposition:
        """Parse a Disposition from a directive table row."""
        desc = row.get("description", "{}")
        try:
            parsed = json.loads(desc) if isinstance(desc, str) else desc
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        return cls(
            workspace_id=row.get("workspace_id", ""),
            disposition_type=parsed.get("type", "neutral") if isinstance(parsed, dict) else "neutral",
            intensity=int(parsed.get("intensity", 3)) if isinstance(parsed, dict) else 3,
            description=parsed.get("description", "") if isinstance(parsed, dict) else str(parsed),
            active=row.get("status", "active") == "active",
            created_at=int(row.get("created_at", 0)),
        )

    def to_directive_args(self, title: str = "") -> dict[str, Any]:
        """Build the description JSON for storing as a directive."""
        desc_payload = {
            "type": self.disposition_type,
            "intensity": min(max(self.intensity, 1), 5),
            "description": self.description,
        }
        return {
            "title": title or f"disposition:{self.disposition_type}",
            "description": json.dumps(desc_payload),
            "category": "disposition",
            "tags_json": "[]",
            "priority": min(max(self.intensity, 1), 5),
        }


# ---------------------------------------------------------------------------
# Directive template helpers
# ---------------------------------------------------------------------------

DIRECTIVE_TEMPLATES: dict[str, dict[str, Any]] = {
    "analysis": {
        "title": "Analysis Lens",
        "description": json.dumps({
            "rules": [
                "Break complex problems into smaller components",
                "Evaluate evidence for each claim",
                "Consider multiple perspectives before concluding",
            ],
            "constraints": [
                "Stay within the defined scope of analysis",
                "Do not make claims unsupported by evidence",
            ],
            "heuristics": [
                "Use first-principles thinking for novel problems",
                "Apply Occam's razor when choosing between explanations",
            ],
            "description": "Apply systematic analytical reasoning to evaluate information.",
        }),
        "category": "mental_model",
        "priority": 3,
    },
    "creative": {
        "title": "Creative Exploration",
        "description": json.dumps({
            "rules": [
                "Generate diverse ideas before evaluating",
                "Build on existing concepts with novel combinations",
                "Suspend judgment during ideation",
            ],
            "constraints": [
                "Ideas must be feasible within given constraints",
                "Avoid repeating the same pattern",
            ],
            "heuristics": [
                "Use analogical thinking from unrelated domains",
                "Apply constraint removal to overcome fixation",
            ],
            "description": "Explore creative possibilities and generate novel solutions.",
        }),
        "category": "mental_model",
        "priority": 3,
    },
    "critical": {
        "title": "Critical Review",
        "description": json.dumps({
            "rules": [
                "Identify assumptions underlying each claim",
                "Evaluate the quality and relevance of evidence",
                "Consider alternative explanations",
            ],
            "constraints": [
                "Do not accept claims at face value",
                "Distinguish correlation from causation",
            ],
            "heuristics": [
                "Apply the 'so what?' test to evaluate significance",
                "Use devil's advocate to stress-test conclusions",
            ],
            "description": "Apply critical thinking to evaluate claims and reasoning.",
        }),
        "category": "mental_model",
        "priority": 3,
    },
    "empathetic": {
        "title": "Empathetic Understanding",
        "description": json.dumps({
            "rules": [
                "Consider the emotional state and perspective of stakeholders",
                "Acknowledge feelings before problem-solving",
                "Use inclusive and respectful language",
            ],
            "constraints": [
                "Do not dismiss or invalidate emotional responses",
                "Avoid purely transactional framing",
            ],
            "heuristics": [
                "Put yourself in the other person's situation",
                "Listen actively before responding",
            ],
            "description": "Understand and incorporate the emotional and human dimensions.",
        }),
        "category": "mental_model",
        "priority": 3,
    },
}


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class MentalModelMixin:
    """Client mixin that provides mental model, disposition, and directive
    template operations on top of the existing ``directive`` table.

    All persistent storage uses the ``create_directive`` / ``list_directives``
    reducers; client-side logic provides the ``apply_mental_model`` enrichment.
    """

    # ------------------------------------------------------------------
    # Mental model CRUD
    # ------------------------------------------------------------------

    def create_mental_model(
        self,
        workspace_id: str,
        name: str,
        rules: list[str] | None = None,
        constraints: list[str] | None = None,
        heuristics: list[str] | None = None,
        tags: list[str] | None = None,
        description: str = "",
        priority: int = 3,
    ) -> dict[str, Any]:
        """Create a named mental model for a workspace.

        The model is stored as a directive with ``category='mental_model'``.
        The structured fields (rules, constraints, heuristics) are encoded
        in the JSON description field.

        Args:
            workspace_id: Target workspace.
            name: Human-readable name for the model.
            rules: Prescriptive rules the agent should follow.
            constraints: Boundaries and limitations.
            heuristics: Mental shortcuts / thinking patterns.
            tags: Categorisation tags.
            description: Free-text elaboration.
            priority: Importance level (1–5, default 3).

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        model = MentalModel(
            workspace_id=workspace_id,
            name=name,
            rules=rules or [],
            constraints=constraints or [],
            heuristics=heuristics or [],
            tags=tags or [],
            description=description,
            priority=priority,
        )
        args = model.to_directive_args()

        result = self._call("create_directive", [
            workspace_id,
            args["title"],
            args["description"],
            args["priority"],
            "",              # assigned_to — let the system assign
            args["category"],
            args["tags_json"],
            "",              # parent_id — no parent
            0,               # deadline — no deadline
        ])
        if result.get("status") == "ok":
            # Resolve the model ID by querying for the most recent
            rows = self._query(
                "directive",
                workspace_id=workspace_id,
                filter_dict={"category": "mental_model"},
                columns=["id", "title", "created_at"],
            )
            if rows:
                # Most recent match wins
                rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
                model.id = rows[0]["id"]
                result["id"] = model.id
        return result

    def create_mental_model_from_template(
        self,
        workspace_id: str,
        template_name: str,
        **overrides: Any,
    ) -> dict[str, Any]:
        """Create a mental model from a built-in template.

        Args:
            workspace_id: Target workspace.
            template_name: One of ``"analysis"``, ``"creative"``,
                ``"critical"``, ``"empathetic"``.
            **overrides: Override fields (e.g. ``name=...``).

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        template = DIRECTIVE_TEMPLATES.get(template_name)
        if template is None:
            valid = list(DIRECTIVE_TEMPLATES.keys())
            raise ValueError(
                f"Unknown template {template_name!r}. Valid: {valid}"
            )

        title = overrides.pop("title", template["title"])
        desc_str = template["description"]
        try:
            desc = json.loads(desc_str)
        except (json.JSONDecodeError, TypeError):
            desc = {}

        rules = overrides.pop("rules", desc.get("rules", []))
        constraints = overrides.pop("constraints", desc.get("constraints", []))
        heuristics = overrides.pop("heuristics", desc.get("heuristics", []))
        description = overrides.pop("description", desc.get("description", ""))
        priority = overrides.pop("priority", template.get("priority", 3))

        return self.create_mental_model(
            workspace_id=workspace_id,
            name=title,
            rules=rules,
            constraints=constraints,
            heuristics=heuristics,
            description=description,
            priority=priority,
            **overrides,
        )

    def get_mental_model(self, model_id: str) -> MentalModel | None:
        """Retrieve a single mental model by its directive ID.

        Args:
            model_id: The directive ID.

        Returns:
            A ``MentalModel`` instance, or ``None`` if not found.
        """
        rows = self._query("directive", filter_dict={"id": model_id})
        if not rows:
            return None
        row = rows[0]
        # Verify it's actually a mental model
        if row.get("category", "") != "mental_model":
            logger.warning(
                "Directive %s has category %r, expected 'mental_model'",
                model_id, row.get("category", ""),
            )
            return None
        return MentalModel.from_directive(row)

    def list_mental_models(
        self,
        workspace_id: str,
        status: str = "",
    ) -> list[MentalModel]:
        """List mental models in a workspace.

        Args:
            workspace_id: Target workspace.
            status: Optional filter — ``"active"`` or ``"inactive"``.

        Returns:
            List of ``MentalModel`` instances.
        """
        # Call the list_directives reducer to get all directives,
        # then filter client-side for category='mental_model'.
        try:
            self._call("list_directives", [workspace_id, "", ""])
        except RuntimeError:
            pass  # may fail if no results table exists yet

        rows = self._query(
            "directive",
            workspace_id=workspace_id,
            filter_dict={"category": "mental_model"},
        )
        models = [MentalModel.from_directive(r) for r in rows]
        # Also try direct query for the directive table
        try:
            sql_rows = self._query(
                "directive",
                workspace_id=workspace_id,
                filter_dict={"category": "mental_model"},
            )
            seen = {m.id for m in models}
            for r in sql_rows:
                if r.get("id", "") not in seen:
                    models.append(MentalModel.from_directive(r))
                    seen.add(r["id"])
        except RuntimeError:
            pass

        if status:
            models = [m for m in models if m.status == status]
        return models

    def update_mental_model(
        self,
        model_id: str,
        name: str | None = None,
        rules: list[str] | None = None,
        constraints: list[str] | None = None,
        heuristics: list[str] | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing mental model's fields.

        Args:
            model_id: The directive ID.
            name: New name (title).
            rules: New rules list.
            constraints: New constraints list.
            heuristics: New heuristics list.
            tags: New tags list.
            description: New description.
            priority: New priority (1–5).

        Returns:
            Reducer status dict.
        """
        existing = self.get_mental_model(model_id)
        if existing is None:
            return {"status": "error", "error": "Mental model not found"}

        if name is not None:
            existing.name = name
        if rules is not None:
            existing.rules = rules
        if constraints is not None:
            existing.constraints = constraints
        if heuristics is not None:
            existing.heuristics = heuristics
        if tags is not None:
            existing.tags = tags
        if description is not None:
            existing.description = description
        if priority is not None:
            existing.priority = min(max(priority, 1), 5)

        args = existing.to_directive_args()
        # Update via directive progress + status (we re-use the directive
        # update pathway for the description).
        return self._call("update_directive_status", [
            model_id,
            existing.status,
            args["description"],
        ])

    def delete_mental_model(self, model_id: str) -> dict[str, Any]:
        """Delete (abandon) a mental model.

        Args:
            model_id: The directive ID.

        Returns:
            Reducer status dict.
        """
        return self._call("update_directive_status", [
            model_id,
            "abandoned",
            "Mental model deleted by user.",
        ])

    # ------------------------------------------------------------------
    # Apply mental model — enrich a context dict
    # ------------------------------------------------------------------

    def apply_mental_model(
        self,
        workspace_id: str,
        model_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply a mental model to a context dict, returning an enhanced copy.

        This is a **client-side** enrichment: it reads the mental model,
        then merges the model's rules, constraints, and heuristics into
        the context under a ``mental_model`` key.  No LLM call or reducer
        is involved.

        Args:
            workspace_id: Target workspace (used for lookup fallback).
            model_id: The mental model directive ID.
            context: Optional base context dict to enhance.  If ``None``,
                starts with an empty dict.

        Returns:
            Enhanced context dict with a ``mental_model`` key containing
            the model's structured fields.
        """
        model = self.get_mental_model(model_id)
        if model is None:
            raise ValueError(
                f"Mental model {model_id!r} not found in workspace {workspace_id!r}"
            )

        ctx = dict(context or {})
        ctx["mental_model"] = {
            "id": model.id,
            "name": model.name,
            "rules": model.rules,
            "constraints": model.constraints,
            "heuristics": model.heuristics,
            "description": model.description,
            "tags": model.tags,
        }
        # Also add a flat concatenation for easy prompt injection
        ctx["mental_model_prompt"] = _build_mental_model_prompt(model)
        return ctx

    # ------------------------------------------------------------------
    # Disposition management
    # ------------------------------------------------------------------

    def set_disposition(
        self,
        workspace_id: str,
        disposition_type: str,
        intensity: int = 3,
        description: str = "",
    ) -> dict[str, Any]:
        """Set the agent's disposition for a workspace.

        The disposition is stored as a directive with
        ``category='disposition'``.  Setting a new disposition replaces
        any existing active one (marks the old one as inactive).

        Args:
            workspace_id: Target workspace.
            disposition_type: One of ``"optimistic"``, ``"skeptical"``,
                ``"neutral"``, ``"cautious"``, ``"creative"``,
                ``"analytical"``, ``"empathetic"``.
            intensity: Strength 1–5 (default 3).
            description: Optional elaboration.

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        valid_types = {
            "optimistic", "skeptical", "neutral", "cautious",
            "creative", "analytical", "empathetic",
        }
        if disposition_type not in valid_types:
            raise ValueError(
                f"Invalid disposition_type {disposition_type!r}. "
                f"Must be one of: {sorted(valid_types)}"
            )

        # Mark any existing active disposition as inactive
        existing = self.get_disposition(workspace_id)
        if existing is not None and existing.active:
            try:
                self._call("update_directive_status", [
                    existing.id, "inactive",
                    "Replaced by new disposition.",
                ])
            except RuntimeError:
                pass

        disp = Disposition(
            workspace_id=workspace_id,
            disposition_type=disposition_type,
            intensity=intensity,
            description=description,
            active=True,
        )
        args = disp.to_directive_args()

        result = self._call("create_directive", [
            workspace_id,
            args["title"],
            args["description"],
            args["priority"],
            "",
            args["category"],
            args["tags_json"],
            "",
            0,
        ])

        # Resolve ID from latest directive
        disp_id = ""
        if result.get("status") == "ok":
            rows = self._query(
                "directive",
                workspace_id=workspace_id,
                filter_dict={"category": "disposition"},
                columns=["id", "created_at"],
            )
            if rows:
                rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
                disp_id = rows[0]["id"]
            result["id"] = disp_id
        return result

    def get_disposition(self, workspace_id: str) -> Disposition | None:
        """Get the currently active disposition for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            A ``Disposition`` instance, or ``None`` if none is set.
        """
        try:
            self._call("list_directives", [workspace_id, "active", ""])
        except RuntimeError:
            pass

        rows = self._query(
            "directive",
            workspace_id=workspace_id,
            filter_dict={"category": "disposition", "status": "active"},
        )
        if rows:
            # Take the most recent
            rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
            d = Disposition.from_directive(rows[0])
            d.id = rows[0].get("id", "")
            return d

        # Fallback: try query
        try:
            sql_rows = self._query(
                "directive",
                workspace_id=workspace_id,
                filter_dict={"category": "disposition", "status": "active"},
            )
            if sql_rows:
                sql_rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
                sql_rows = sql_rows[:1]
            if sql_rows:
                d = Disposition.from_directive(sql_rows[0])
                d.id = sql_rows[0].get("id", "")
                return d
        except RuntimeError:
            pass

        return None

    def clear_disposition(self, workspace_id: str) -> dict[str, Any]:
        """Clear (deactivate) the current disposition for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            Reducer status dict.
        """
        disp = self.get_disposition(workspace_id)
        if disp is None or not hasattr(disp, "id") or not disp.id:
            return {"status": "ok", "note": "No active disposition to clear"}
        return self._call("update_directive_status", [
            disp.id,
            "inactive",
            "Cleared by user.",
        ])

    # ------------------------------------------------------------------
    # Directive template listing
    # ------------------------------------------------------------------

    def list_directive_templates(self) -> dict[str, dict[str, Any]]:
        """List available built-in directive templates.

        Returns:
            Dict mapping template name to its metadata (title, rules,
            constraints, heuristics).
        """
        result: dict[str, dict[str, Any]] = {}
        for name, tmpl in DIRECTIVE_TEMPLATES.items():
            desc_str = tmpl.get("description", "{}")
            try:
                desc = json.loads(desc_str) if isinstance(desc_str, str) else desc_str
            except (json.JSONDecodeError, TypeError):
                desc = {}
            result[name] = {
                "title": tmpl.get("title", name),
                "rules": desc.get("rules", []),
                "constraints": desc.get("constraints", []),
                "heuristics": desc.get("heuristics", []),
                "description": desc.get("description", ""),
            }
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_mental_model_prompt(model: MentalModel) -> str:
    """Build a flat prompt string from a mental model for easy injection."""
    parts: list[str] = []
    parts.append(f"## Mental Model: {model.name}")
    if model.description:
        parts.append(f"\n{model.description}")
    if model.rules:
        parts.append("\n### Rules")
        for r in model.rules:
            parts.append(f"- {r}")
    if model.constraints:
        parts.append("\n### Constraints")
        for c in model.constraints:
            parts.append(f"- {c}")
    if model.heuristics:
        parts.append("\n### Heuristics")
        for h in model.heuristics:
            parts.append(f"- {h}")
    return "\n".join(parts)
