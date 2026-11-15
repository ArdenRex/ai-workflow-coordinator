"""Kernel tool for the operations digest (Step 11.2): `insight.attention.read`.

Makes the 11.1 digest available to agents, plans and workflows through the ordinary run -> scope -> kernel -> audit path, with no new
authority. The safety shape (identity rebuilt from the user's current membership plus the agent's scope, nested reads only through
the kernel, shared concurrency cap) lives in `app/capabilities/composite.py`. Needs `insight:read` (admin and owner).

Output is the 11.1 `AttentionDigest`. Titles are external text (flagged `external_text`) and are data only. Agent runs never feed
tool output back to a model (6.4); anything that later does must treat these titles as untrusted.
"""
import threading
from datetime import datetime, timezone
from typing import Callable, FrozenSet, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.capabilities.attention import AttentionDigest, AttentionService
from app.capabilities.composite import (MAX_CONCURRENT_COMPOSITES as MAX_CONCURRENT_DIGESTS, DigestBusyError,  # noqa: F401
                                        DigestIdentityError, composite_tool, starter_agent_scope)
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition, ToolRegistry

TOOL_ID = "insight.attention.read"


class AttentionToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def attention_tool_definition(
        session_factory: Callable[[], Session], registry_provider: Callable[[], ToolRegistry], *,
        principal_lookup: Optional[Callable[[Session], Callable[[str, str], Optional[Principal]]]] = None,
        agent_scope_for: Callable[[str], Optional[FrozenSet[str]]] = starter_agent_scope,
        policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_concurrent: int = MAX_CONCURRENT_DIGESTS,
        slots: Optional[threading.BoundedSemaphore] = None) -> ToolDefinition:
    return composite_tool(
        tool_id=TOOL_ID,
        description="Summarise what requires attention across connected calendar, project, CRM and email systems. "
                    "Read-only; reports which sources were unavailable.",
        input_schema=AttentionToolInput, output_schema=AttentionDigest, permission="insight:read",
        run=lambda kernel, principal, data: AttentionService(kernel, clock=clock).digest(principal),
        session_factory=session_factory, registry_provider=registry_provider, principal_lookup=principal_lookup,
        agent_scope_for=agent_scope_for, policy_provider=policy_provider, slots=slots, max_concurrent=max_concurrent)
