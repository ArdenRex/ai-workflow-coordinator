"""Process-wide wiring: the one tool registry the API uses (built-in + workspace connector tools)."""
from app.config import Settings
from app.connectors.workspace import WorkspaceConnectors, register_workspace_tools
from app.database import get_session_factory
from app.capabilities.attention_tool import attention_tool_definition
from app.capabilities.changes_tool import changes_tool_definition
from app.capabilities.composite import new_slots
from app.capabilities.meetings_tool import meetings_tool_definition
from app.capabilities.opportunities_tool import opportunity_tool_definition
from app.kernel.builtin_tools import build_default_registry
from app.kernel.policy import WorkspacePolicy
from app.kernel.policy_store import db_policy_provider, session_policy_provider
from app.database import get_db
from fastapi import Depends
from sqlalchemy.orm import Session
from typing import Callable


def get_policy_provider() -> Callable[[str], WorkspacePolicy]:
    """The ONE policy provider every kernel in the running app uses (12.2). Reads the store per call; fails closed on error."""
    return db_policy_provider(lambda: get_session_factory()())


def request_policy_provider(db: Session = Depends(get_db)) -> Callable[[str], WorkspacePolicy]:
    """FastAPI dependency (12.2): the stored policy, read on the request's own session so routes and policy see one database."""
    return session_policy_provider(db)


def build_runtime(settings: Settings):
    """Returns (registry, connectors). Connector sessions are created lazily, per call."""
    connectors = WorkspaceConnectors(lambda: get_session_factory()(), settings)
    registry = register_workspace_tools(build_default_registry(), connectors)
    sessions, slots, policy = (lambda: get_session_factory()()), new_slots(), get_policy_provider()        # ONE worker cap shared by every composite tool
    registry.register(attention_tool_definition(sessions, lambda: registry, slots=slots, policy_provider=policy))             # 11.2
    registry.register(opportunity_tool_definition(sessions, lambda: registry, slots=slots, policy_provider=policy))           # 11.3
    registry.register(changes_tool_definition(sessions, lambda: registry, slots=slots, policy_provider=policy))               # 11.4
    registry.register(meetings_tool_definition(sessions, lambda: registry, slots=slots, policy_provider=policy))              # 11.5
    return registry, connectors
