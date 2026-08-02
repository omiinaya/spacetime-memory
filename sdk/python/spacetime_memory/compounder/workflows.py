"""Compounder workflows — combined re-export of all sub-modules."""

from __future__ import annotations

from .workflows_export import CompounderWorkflowsExport
from .workflows_graph import CompounderWorkflowsGraph
from .workflows_knowledge import CompounderWorkflowsKnowledge
from .workflows_ripple import CompounderWorkflowsRipple
from .workflows_search import CompounderWorkflowsSearch


class CompounderWorkflows(
    CompounderWorkflowsSearch,
    CompounderWorkflowsKnowledge,
    CompounderWorkflowsGraph,
    CompounderWorkflowsRipple,
    CompounderWorkflowsExport,
):
    """Mixin holding all public workflow methods of ``Compounder``."""
