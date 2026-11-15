"""Role -> Principal -> kernel: the whole point of 4.3."""
import pytest
from sqlalchemy import select

from app.identity.context import load_context
from app.kernel.errors import PolicyDeniedError
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService
from app.kernel.builtin_tools import build_default_registry
from app.models.identity import Membership, User
from tests.test_workspaces_api import mkws, signup
from sqlalchemy.exc import IntegrityError
from app.models import ToolExecution, RiskLevel


def ctx_for(db, client, email, ws_id):
    user = db.scalar(select(User).where(User.email == email))
    return load_context(db, user, ws_id)


def test_principal_is_built_from_membership_not_input(client, db_session):
    h = signup(client, "o@x.com")
    ws = mkws(client, h)
    ctx = ctx_for(db_session, client, "o@x.com", ws["id"])
    p = ctx.principal()
    assert p.workspace_id == ws["id"] and p.user_id == ctx.user.id and p.can("anything") and p.agent is None


def test_agent_principal_requires_scope_and_narrows(client, db_session):
    h = signup(client, "o@x.com")
    ws = mkws(client, h)
    ctx = ctx_for(db_session, client, "o@x.com", ws["id"])
    with pytest.raises(ValueError):
        ctx.principal(agent="sales")
    p = ctx.principal(agent="sales", agent_scope=frozenset({"task:read"}))
    assert p.can("task:read") and not p.can("task:write")


def test_viewer_principal_is_denied_writes_by_kernel(client, db_session):
    o, v = signup(client, "o@x.com"), signup(client, "v@x.com")
    ws = mkws(client, o)
    client.post(f"/workspaces/{ws['id']}/members", json={"email": "v@x.com", "role": "viewer"}, headers=o)
    reg = build_default_registry()
    svc = ToolExecutionService(db_session, reg)
    viewer = ctx_for(db_session, client, "v@x.com", ws["id"]).principal()
    assert svc.submit(viewer, "system.ping", {"message": "hi"}).status.value == "succeeded"   # system:read ok
    assert viewer.can("approval:decide") is False


def test_kernel_rows_cannot_reference_missing_workspace(db_session):
    db_session.add(ToolExecution(workspace_id="ghost", tool_id="t.x", requested_by="u",
                                 risk_level=RiskLevel.LOW, input={}))
    with pytest.raises(IntegrityError):
        db_session.commit()
