"""Capability catalog: the tools THIS caller could actually use right now.

The model is only ever shown tools the principal is allowed to use (permission, agent scope,
workspace policy all applied through the kernel's own `evaluate`), so it cannot be steered toward
capabilities outside the caller's authority, and one role's catalog never leaks another's tools.
Approval flags come from the registry/policy, never from the model.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.kernel.permissions import Principal
from app.kernel.policy import Outcome, WorkspacePolicy, effective_risk, evaluate
from app.kernel.registry import ToolDefinition, ToolRegistry

MAX_CATALOG = 60
MAX_DESCRIPTION = 200


@dataclass(frozen=True)
class CatalogEntry:
    tool_id: str
    description: str
    risk_level: str
    requires_approval: bool


def build_catalog(registry: ToolRegistry, principal: Principal,
                  policy: Optional[WorkspacePolicy] = None) -> List[CatalogEntry]:
    entries: List[CatalogEntry] = []
    for tool in sorted(registry.list(), key=lambda t: t.id):
        decision = evaluate(tool, principal, principal.workspace_id, policy)
        if decision.outcome == Outcome.DENY:
            continue
        entries.append(CatalogEntry(tool.id, " ".join(tool.description.split())[:MAX_DESCRIPTION],
                                    effective_risk(tool, policy).value, decision.outcome == Outcome.REQUIRE_APPROVAL))
        if len(entries) >= MAX_CATALOG:
            break
    return entries


def index(entries: List[CatalogEntry]) -> Dict[str, CatalogEntry]:
    return {e.tool_id: e for e in entries}
