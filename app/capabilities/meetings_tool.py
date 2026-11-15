"""Kernel tool for the meeting briefing (Step 11.5): `insight.meetings.read`.

Same shape as the other composite tools (see composite.py): LOW risk, read-only, no approval, no input, identity rebuilt from the user's
current membership plus the calling agent's scope, nested reads only through the kernel (calendar, CRM), shared concurrency cap. Needs
`insight:read` (admin and owner). Output is `MeetingBriefing`; titles and lead fields are external text and are data only.
"""
import threading
from datetime import datetime, timezone
from typing import Callable, FrozenSet, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.capabilities.composite import MAX_CONCURRENT_COMPOSITES, composite_tool, starter_agent_scope
from app.capabilities.meetings import MeetingBriefing, MeetingService
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition, ToolRegistry

TOOL_ID = "insight.meetings.read"


class MeetingsToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def meetings_tool_definition(
        session_factory: Callable[[], Session], registry_provider: Callable[[], ToolRegistry], *,
        principal_lookup: Optional[Callable[[Session], Callable[[str, str], Optional[Principal]]]] = None,
        agent_scope_for: Callable[[str], Optional[FrozenSet[str]]] = starter_agent_scope,
        policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_concurrent: int = MAX_CONCURRENT_COMPOSITES,
        slots: Optional[threading.BoundedSemaphore] = None) -> ToolDefinition:
    return composite_tool(
        tool_id=TOOL_ID,
        description="Prepare a briefing for tomorrow's (UTC) calendar meetings, with possible related CRM leads matched by title text. "
                    "Read-only; reports whether each source could be read.",
        input_schema=MeetingsToolInput, output_schema=MeetingBriefing, permission="insight:read",
        run=lambda kernel, principal, data: MeetingService(kernel, clock=clock).brief(principal),
        session_factory=session_factory, registry_provider=registry_provider, principal_lookup=principal_lookup,
        agent_scope_for=agent_scope_for, policy_provider=policy_provider, slots=slots, max_concurrent=max_concurrent)
