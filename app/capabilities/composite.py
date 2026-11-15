"""Factory for capability kernel tools (Step 11.2+): a read-only composite tool whose handler reads only through the kernel.

Every composite tool shares the same safety shape:
- LOW risk, no approval, strict input, one audited execution for the tool plus one per nested read.
- The handler rebuilds the acting identity from the execution context: the user's CURRENT membership permissions (removed or
  deactivated => `DigestIdentityError`, no reads), plus the calling agent's scope when an agent called it. A nested read therefore
  needs the user's rights AND the agent's scope.
- A composite tool holds one of the kernel's pool workers while its nested reads queue behind it, so concurrent composite calls are
  capped by ONE shared semaphore (default 4 of 8 workers) across all composite tools. Extra callers fail fast with
  `DigestBusyError`. The slot is always released. (The error names come from the first capability; all composites share them.)
"""
import threading
from typing import Callable, FrozenSet, Optional, Type

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolDefinition, ToolRegistry
from app.kernel.service import ExecutionContext, ToolExecutionService
from app.models.enums import RiskLevel

MAX_CONCURRENT_COMPOSITES = 4


class DigestBusyError(Exception):
    """Too many composite tools running at once (fixed text; stored on the execution as the type name only)."""


class DigestIdentityError(Exception):
    """The caller is no longer an active member, or the agent is unknown (fail closed)."""


def new_slots(size: int = MAX_CONCURRENT_COMPOSITES) -> threading.BoundedSemaphore:
    return threading.BoundedSemaphore(size)


def starter_agent_scope(agent_id: str) -> Optional[FrozenSet[str]]:
    from app.agents.starter import STARTER_AGENTS          # local import: agents depend on the tool registry
    for agent in STARTER_AGENTS:
        if agent.id == agent_id:
            return agent.scope_permissions
    return None


def composite_tool(*, tool_id: str, description: str, input_schema: Type[BaseModel], output_schema: Type[BaseModel],
                   permission: str, run: Callable[[ToolExecutionService, Principal, BaseModel], BaseModel],
                   session_factory: Callable[[], Session], registry_provider: Callable[[], ToolRegistry],
                   principal_lookup: Optional[Callable[[Session], Callable[[str, str], Optional[Principal]]]] = None,
                   agent_scope_for: Callable[[str], Optional[FrozenSet[str]]] = starter_agent_scope,
                   policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None,
                   slots: Optional[threading.BoundedSemaphore] = None, max_concurrent: int = MAX_CONCURRENT_COMPOSITES,
                   timeout_seconds: int = 120) -> ToolDefinition:
    if principal_lookup is None:
        from app.workflows.scheduler import principal_from_membership
        principal_lookup = principal_from_membership
    slots = slots or new_slots(max_concurrent)

    def handler(ctx: ExecutionContext, data: BaseModel) -> dict:
        if not slots.acquire(blocking=False):
            raise DigestBusyError()
        db = session_factory()
        try:
            user = principal_lookup(db)(ctx.workspace_id, ctx.user_id)
            if user is None:
                raise DigestIdentityError()
            if ctx.agent is not None:
                scope = agent_scope_for(ctx.agent)
                if scope is None:
                    raise DigestIdentityError()
                user = Principal(user_id=user.user_id, workspace_id=user.workspace_id, permissions=user.permissions,
                                 agent=ctx.agent, agent_scope=scope)
            kernel = ToolExecutionService(db, registry_provider(), policy_provider=policy_provider)
            return run(kernel, user, data).model_dump(mode="json")
        finally:
            db.close()
            slots.release()

    return ToolDefinition(id=tool_id, description=description, input_schema=input_schema, output_schema=output_schema,
                          required_permission=permission, risk_level=RiskLevel.LOW, timeout_seconds=timeout_seconds,
                          handler=handler)
