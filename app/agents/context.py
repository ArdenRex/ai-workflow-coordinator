"""Agent context: how an agent acts, without any authority of its own.

- `agent_principal`: the kernel Principal an agent acts as. Same user and workspace as the person it
  works for, permissions = the user's own, `agent_scope` = the agent's scope. The kernel allows an action
  only if BOTH the user and the agent's scope allow it.
- `agent_policy`: the workspace policy plus every tool the agent's rules do not allow (or whose risk is
  above its ceiling) disabled. Enforced by the kernel's own policy hook, so the kernel needs no changes.
  It is recomputed on every kernel call, so a tool registered after the agent was built is denied by
  default (fail closed), never silently allowed.
- `AgentContext`: bundles those so catalogs, understanding, planning and execution all use the same
  restricted view.
"""
import dataclasses
from dataclasses import dataclass
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.agents.definition import AgentDefinition, effective_tools
from app.agents.errors import AgentError
from app.agents.registry import AgentRegistry
from app.intelligence.catalog import CatalogEntry, build_catalog
from app.kernel.permissions import Principal
from app.kernel.policy import WorkspacePolicy
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService


class AgentContextError(AgentError):
    pass


def agent_principal(user: Principal, agent: AgentDefinition) -> Principal:
    if user.agent is not None:
        raise AgentContextError("An agent cannot act on behalf of another agent")
    return Principal(user_id=user.user_id, workspace_id=user.workspace_id, permissions=user.permissions,
                     agent=agent.id, agent_scope=agent.scope_permissions)


def agent_policy(base: WorkspacePolicy, agent: AgentDefinition, tools: ToolRegistry) -> WorkspacePolicy:
    allowed = {t.id for t in effective_tools(agent, tools)}
    blocked = {t.id for t in tools.list() if t.id not in allowed}
    return dataclasses.replace(base, disabled_tools=frozenset(base.disabled_tools | blocked))


@dataclass(frozen=True)
class AgentContext:
    agent: AgentDefinition
    user_principal: Principal
    principal: Principal                                     # the agent principal (what the kernel sees)
    tools: ToolRegistry
    base_policy_provider: Callable[[str], WorkspacePolicy]

    def policy(self, workspace_id: str) -> WorkspacePolicy:
        """Fresh on every call (see module docstring)."""
        return agent_policy(self.base_policy_provider(workspace_id), self.agent, self.tools)

    def catalog(self) -> List[CatalogEntry]:
        return build_catalog(self.tools, self.principal, self.policy(self.principal.workspace_id))

    def execution_service(self, db: Session) -> ToolExecutionService:
        return ToolExecutionService(db, self.tools, policy_provider=self.policy)


def build_agent_context(user_principal: Principal, agent_id: str, agents: AgentRegistry, tools: ToolRegistry, *,
                        base_policy_provider: Optional[Callable[[str], WorkspacePolicy]] = None) -> AgentContext:
    agent = agents.get(agent_id)                             # AgentNotFoundError for unknown ids
    return AgentContext(agent=agent, user_principal=user_principal, principal=agent_principal(user_principal, agent),
                        tools=tools, base_policy_provider=base_policy_provider or (lambda ws: WorkspacePolicy()))
