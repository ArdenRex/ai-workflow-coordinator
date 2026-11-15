"""Kernel tool for the weekly changes report (Step 11.4): `insight.changes.read`.

Same shape as the digest and opportunities tools (see composite.py): LOW risk, read-only, no approval, no input, identity rebuilt from
the user's current membership plus the calling agent's scope, nested reads only through the kernel (calendar, project, CRM, email),
shared concurrency cap. Needs `insight:read` (admin and owner). Output is `WeeklyChanges`; email is counts only and every title or
name is external text, returned as data.
"""
import threading
from datetime import datetime, timezone
from typing import Callable, FrozenSet, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.capabilities.changes import ChangesService, WeeklyChanges
from app.capabilities.composite import MAX_CONCURRENT_COMPOSITES, composite_tool, starter_agent_scope
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition, ToolRegistry

TOOL_ID = "insight.changes.read"


class ChangesToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def changes_tool_definition(
        session_factory: Callable[[], Session], registry_provider: Callable[[], ToolRegistry], *,
        principal_lookup: Optional[Callable[[Session], Callable[[str, str], Optional[Principal]]]] = None,
        agent_scope_for: Callable[[str], Optional[FrozenSet[str]]] = starter_agent_scope,
        policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_concurrent: int = MAX_CONCURRENT_COMPOSITES,
        slots: Optional[threading.BoundedSemaphore] = None) -> ToolDefinition:
    return composite_tool(
        tool_id=TOOL_ID,
        description="Summarise what changed in the last 7 days across calendar, project, CRM and email (email as counts only). "
                    "Read-only; reports whether each source could be read.",
        input_schema=ChangesToolInput, output_schema=WeeklyChanges, permission="insight:read",
        run=lambda kernel, principal, data: ChangesService(kernel, clock=clock).report(principal),
        session_factory=session_factory, registry_provider=registry_provider, principal_lookup=principal_lookup,
        agent_scope_for=agent_scope_for, policy_provider=policy_provider, slots=slots, max_concurrent=max_concurrent)
