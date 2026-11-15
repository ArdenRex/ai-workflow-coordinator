"""Kernel tool for qualified opportunities (Step 11.3): `sales.opportunity.list`.

Same shape as the digest tool (see composite.py): LOW risk, read-only, no approval, no input, identity rebuilt from the user's current
membership plus the calling agent's scope, nested read only through the kernel (`crm.lead.list`), shared concurrency cap. Needs
`sales:read` (admin and owner). Output is the `OpportunityList`; names and companies are external text and are data only.
"""
import threading
from datetime import datetime, timezone
from typing import Callable, FrozenSet, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.capabilities.composite import (MAX_CONCURRENT_COMPOSITES, composite_tool, starter_agent_scope)
from app.capabilities.opportunities import OpportunityList, OpportunityService
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition, ToolRegistry

TOOL_ID = "sales.opportunity.list"


class OpportunityToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def opportunity_tool_definition(
        session_factory: Callable[[], Session], registry_provider: Callable[[], ToolRegistry], *,
        principal_lookup: Optional[Callable[[Session], Callable[[str, str], Optional[Principal]]]] = None,
        agent_scope_for: Callable[[str], Optional[FrozenSet[str]]] = starter_agent_scope,
        policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_concurrent: int = MAX_CONCURRENT_COMPOSITES,
        slots: Optional[threading.BoundedSemaphore] = None) -> ToolDefinition:
    return composite_tool(
        tool_id=TOOL_ID,
        description="List qualified sales opportunities from the connected CRM, ranked by stage and recent activity. "
                    "Read-only; reports whether the CRM could be read.",
        input_schema=OpportunityToolInput, output_schema=OpportunityList, permission="sales:read",
        run=lambda kernel, principal, data: OpportunityService(kernel, clock=clock).list(principal),
        session_factory=session_factory, registry_provider=registry_provider, principal_lookup=principal_lookup,
        agent_scope_for=agent_scope_for, policy_provider=policy_provider, slots=slots, max_concurrent=max_concurrent)
