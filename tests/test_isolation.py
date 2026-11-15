"""Substep 4.6: workspace-isolation and cross-tenant tests.

Company A must never see, change, use or infer anything about Company B. These tests attack
that property from every layer: HTTP routes, credentials/crypto, the execution kernel and
approvals, connector construction, identity changes, logs and audit payloads.
"""
import json
import logging
import uuid

import pytest
from tests.route_discovery import api_routes
from fastapi.routing import APIRoute
from sqlalchemy import select, update

from app.config import get_settings
from app.connectors import registry as creg
from app.connectors.registry import ConnectorSpec
from app.credentials_service import CredentialService
from app.identity.context import load_context
from app.kernel.approvals import ApprovalService
from app.kernel.errors import ApprovalNotFoundError, ExecutionStateError
from app.kernel.registry import ToolDefinition, ToolRegistry
from app.kernel.service import ToolExecutionService
from app.models import ApprovalStatus, ExecutionStatus, RiskLevel, SystemEvent, ToolExecution
from app.models.credentials import Credential
from app.models.enums import Role
from app.models.identity import Membership, User, Workspace
from app.security.crypto import DecryptionError
from tests.test_aceden_connector import fake_aceden
from tests.test_workspace_connectors import add_cred, principal, public_dns, rig, run  # noqa: F401
from tests.test_workspaces_api import mkws, signup, uid

KEY_A, KEY_B = "secret-key-of-company-A", "secret-key-of-company-B"


@pytest.fixture
def world(client):
    """Company A (owner/admin/member/viewer) and Company B (owner). `dual` is owner of B and
    only a viewer in A."""
    names = ("a_owner", "a_admin", "a_member", "a_viewer", "b_owner", "dual")
    hs = {n: signup(client, f"{n}@x.com") for n in names}
    a = mkws(client, hs["a_owner"], "Company A")
    b = mkws(client, hs["b_owner"], "Company B")
    for n, role in (("a_admin", "admin"), ("a_member", "member"), ("a_viewer", "viewer"), ("dual", "viewer")):
        assert client.post(f"/workspaces/{a['id']}/members", json={"email": f"{n}@x.com", "role": role},
                           headers=hs["a_owner"]).status_code == 201
    assert client.post(f"/workspaces/{b['id']}/members", json={"email": "dual@x.com", "role": "owner"},
                       headers=hs["b_owner"]).status_code == 201
    return hs, a, b


def _workspace_routes(app):
    return api_routes(app, contains="{workspace_id}")


def _call(client, route, method, ws_id, headers):
    path = route.path.replace("{workspace_id}", ws_id)
    for p in route.param_convertors if hasattr(route, "param_convertors") else {}:
        path = path.replace("{" + p + "}", str(uuid.uuid4()))
    return client.request(method, path, headers=headers, json={} if method in ("POST", "PATCH", "PUT") else None)


# ============================================================ HTTP surface
def test_every_workspace_route_hides_workspace_from_outsiders(client, app, world):
    """Auto-discovers every route under {workspace_id}, so a future route can't dodge this."""
    hs, a, b = world
    routes = _workspace_routes(app)
    assert len(routes) >= 11                                  # guard against a vacuous pass
    ghost = str(uuid.uuid4())
    for route in routes:
        for method in route.methods - {"HEAD", "OPTIONS"}:
            theirs = _call(client, route, method, a["id"], hs["b_owner"])      # real, but not theirs
            absent = _call(client, route, method, ghost, hs["b_owner"])        # does not exist
            assert theirs.status_code == 404, (method, route.path, theirs.text)
            assert (theirs.status_code, theirs.json()) == (absent.status_code, absent.json()), route.path
            assert _call(client, route, method, a["id"], {}).status_code == 401, (method, route.path)


def test_outsider_cannot_see_workspace_in_listings(client, world):
    hs, a, b = world
    listed = client.get("/workspaces", headers=hs["b_owner"]).json()
    assert [w["id"] for w in listed] == [b["id"]]


def test_foreign_credential_id_is_not_found_under_own_workspace(client, world):
    hs, a, b = world
    cid = add_cred(client, hs["a_owner"], a)
    base = f"/workspaces/{b['id']}/credentials/{cid}"
    for method, path, body in (("GET", base, None), ("POST", base + "/rotate", {"secret": "hijacked-key"}),
                               ("DELETE", base, None), ("POST", base + "/test", None)):
        r = client.request(method, path, headers=hs["b_owner"], json=body)
        assert r.status_code == 404, (method, r.text)
    ok = client.get(f"/workspaces/{a['id']}/credentials/{cid}", headers=hs["a_owner"]).json()
    assert ok["is_active"] is True and ok["version"] == 1


def test_credential_listing_is_scoped_and_never_returns_secrets(client, db_session, world):
    hs, a, b = world
    add_cred(client, hs["a_owner"], a, key=KEY_A)
    add_cred(client, hs["b_owner"], b, key=KEY_B, url="https://b.test")
    ca = db_session.scalar(select(Credential).where(Credential.workspace_id == a["id"]))
    for h, ws, mine, theirs in ((hs["a_owner"], a, KEY_A, KEY_B), (hs["b_owner"], b, KEY_B, KEY_A)):
        r = client.get(f"/workspaces/{ws['id']}/credentials", headers=h)
        assert len(r.json()) == 1
        assert mine not in r.text and theirs not in r.text and "ciphertext" not in r.text.lower()
    assert ca.secret_ciphertext not in client.get(f"/workspaces/{a['id']}/credentials", headers=hs["a_owner"]).text


def test_member_lists_hide_other_workspaces_people(client, world):
    hs, a, b = world
    emails = {m["email"] for m in client.get(f"/workspaces/{b['id']}/members", headers=hs["b_owner"]).json()}
    assert emails == {"b_owner@x.com", "dual@x.com"}


# ============================================================ credentials / crypto
def test_ciphertext_copied_to_another_workspace_fails_authentication(client, db_session, world):
    hs, a, b = world
    add_cred(client, hs["a_owner"], a, key=KEY_A)
    cb = add_cred(client, hs["b_owner"], b, key=KEY_B, url="https://b.test")
    ca_row = db_session.scalar(select(Credential).where(Credential.workspace_id == a["id"]))
    cb_row = db_session.get(Credential, cb)
    cb_row.secret_ciphertext = ca_row.secret_ciphertext       # attacker with DB write access
    db_session.commit()
    with pytest.raises(DecryptionError):
        CredentialService(db_session, get_settings()).reveal_secret(b["id"], cb)


def test_same_secret_in_two_workspaces_is_stored_differently(client, db_session, world):
    hs, a, b = world
    add_cred(client, hs["a_owner"], a, key="shared-plaintext-key")
    add_cred(client, hs["b_owner"], b, key="shared-plaintext-key", url="https://b.test")
    rows = db_session.scalars(select(Credential)).all()
    assert len({r.secret_ciphertext for r in rows}) == 2
    assert all("shared-plaintext-key" not in r.secret_ciphertext for r in rows)


def test_revoke_in_one_workspace_leaves_the_other_untouched(client, db_session, rig, world):
    hs, a, b = world
    ca = add_cred(client, hs["a_owner"], a)
    add_cred(client, hs["b_owner"], b, url="https://b.test")
    client.delete(f"/workspaces/{a['id']}/credentials/{ca}", headers=hs["a_owner"])
    assert run(rig, "a_owner@x.com", a).status == ExecutionStatus.FAILED
    assert run(rig, "b_owner@x.com", b).status == ExecutionStatus.SUCCEEDED


# ============================================================ connector construction
def test_connectors_are_never_shared_between_workspaces(client, rig, monkeypatch, world):
    hs, a, b = world
    add_cred(client, hs["a_owner"], a, key=KEY_A)
    add_cred(client, hs["b_owner"], b, key=KEY_B, url="https://b.test")
    monkeypatch.setitem(creg.SPECS, "aceden", ConnectorSpec("aceden", lambda config, secret, settings, **kw: creg._aceden(
        config, secret, settings, transport=fake_aceden(rig.logs, key=secret), sleep=lambda s: None)))
    ca, cb = rig.wc.get(a["id"], "aceden"), rig.wc.get(b["id"], "aceden")
    assert ca is not cb
    assert ca.config.auth_token.get_secret_value() == KEY_A and cb.config.auth_token.get_secret_value() == KEY_B
    assert rig.wc.get(a["id"], "aceden") is ca and rig.wc.get(b["id"], "aceden") is cb
    cid = client.get(f"/workspaces/{a['id']}/credentials", headers=hs["a_owner"]).json()[0]["id"]
    client.post(f"/workspaces/{a['id']}/credentials/{cid}/rotate", json={"secret": "a-rotated-key-2"}, headers=hs["a_owner"])
    assert rig.wc.get(a["id"], "aceden") is not ca            # A rebuilt...
    assert rig.wc.get(b["id"], "aceden") is cb                # ...B untouched


def test_non_member_cannot_obtain_a_principal_for_a_workspace(db_session, client, world):
    hs, a, b = world
    user = db_session.scalar(select(User).where(User.email == "b_owner@x.com"))
    assert load_context(db_session, user, a["id"]) is None


# ============================================================ kernel + approvals
@pytest.fixture
def kernel(db_session):
    from pydantic import BaseModel, ConfigDict

    class In(BaseModel):
        model_config = ConfigDict(extra="forbid")
        n: int = 1

    class Out(BaseModel):
        value: int

    class K:
        calls = []
    reg = ToolRegistry()
    reg.register(ToolDefinition(id="aceden.customer.update", description="d", input_schema=In, output_schema=Out,
                                required_permission="customer:update", risk_level=RiskLevel.HIGH,
                                handler=lambda ctx, d: (K.calls.append(ctx.workspace_id) or {"value": d.n})))
    K.svc, K.db = ToolExecutionService(db_session, reg), db_session
    K.calls.clear()
    return K


def test_executions_approvals_and_audit_are_invisible_across_workspaces(client, kernel, world):
    hs, a, b = world
    pa = principal(kernel.db, "a_owner@x.com", a["id"])
    pb = principal(kernel.db, "b_owner@x.com", b["id"])
    ex = kernel.svc.submit(pa, "aceden.customer.update", {"n": 7})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL
    approval = kernel.db.scalar(select(ToolExecution).where(ToolExecution.id == ex.id)).approvals[0]

    with pytest.raises(ExecutionStateError):
        kernel.svc.get(ex.id, b["id"])
    with pytest.raises(ExecutionStateError):
        kernel.svc.audit_trail(ex.id, b["id"])
    with pytest.raises(ApprovalNotFoundError):
        ApprovalService(kernel.db).get(approval.id, b["id"])
    with pytest.raises(ApprovalNotFoundError):                # B's owner cannot approve A's request
        ApprovalService(kernel.db).decide(approval.id, pb, approve=True)
    with pytest.raises(ExecutionStateError):
        kernel.svc.execute_approved(pb, ex.id)
    assert kernel.calls == []

    decider = principal(kernel.db, "a_admin@x.com", a["id"])
    ApprovalService(kernel.db).decide(approval.id, decider, approve=True)
    with pytest.raises(ExecutionStateError):                  # approved, yet still not B's to run
        kernel.svc.execute_approved(pb, ex.id)
    assert kernel.calls == []
    assert kernel.svc.execute_approved(pa, ex.id).status == ExecutionStatus.SUCCEEDED
    assert kernel.calls == [a["id"]]


def test_audit_events_stay_inside_their_workspace_and_hold_no_secrets(client, kernel, world):
    hs, a, b = world
    add_cred(client, hs["a_owner"], a, key=KEY_A)
    kernel.svc.submit(principal(kernel.db, "a_owner@x.com", a["id"]), "aceden.customer.update", {"n": 1})
    kernel.svc.submit(principal(kernel.db, "b_owner@x.com", b["id"]), "aceden.customer.update", {"n": 2})
    events = kernel.db.scalars(select(SystemEvent)).all()
    by_ws = {a["id"]: [], b["id"]: []}
    for e in events:
        by_ws[e.workspace_id].append(e)
        if e.execution_id:
            assert kernel.db.get(ToolExecution, e.execution_id).workspace_id == e.workspace_id
    assert by_ws[a["id"]] and by_ws[b["id"]]
    blob = json.dumps([e.payload for e in events], default=str)
    assert KEY_A not in blob and "@x.com" not in blob


def test_same_idempotency_key_in_two_workspaces_does_not_collide(client, kernel, world):
    hs, a, b = world
    ea = kernel.svc.submit(principal(kernel.db, "a_owner@x.com", a["id"]), "aceden.customer.update", {"n": 1},
                           idempotency_key="same-key")
    eb = kernel.svc.submit(principal(kernel.db, "b_owner@x.com", b["id"]), "aceden.customer.update", {"n": 9},
                           idempotency_key="same-key")
    assert ea.id != eb.id and ea.workspace_id == a["id"] and eb.workspace_id == b["id"] and eb.input == {"n": 9}


# ============================================================ identity edge cases
def test_same_user_has_independent_roles_per_workspace(client, world):
    hs, a, b = world
    in_a = client.get(f"/workspaces/{a['id']}", headers=hs["dual"]).json()
    in_b = client.get(f"/workspaces/{b['id']}", headers=hs["dual"]).json()
    assert (in_a["role"], in_b["role"]) == ("viewer", "owner")
    assert "connection:write" not in in_a["permissions"] and "*" in in_b["permissions"]
    body = {"provider": "aceden", "name": "x", "secret": "dual-user-key-1", "config": {"base_url": "https://aceden.test"}}
    assert client.post(f"/workspaces/{a['id']}/credentials", json=body, headers=hs["dual"]).status_code == 403
    assert client.post(f"/workspaces/{b['id']}/credentials", json=body, headers=hs["dual"]).status_code == 201
    assert {w["id"]: w["role"] for w in client.get("/workspaces", headers=hs["dual"]).json()} == {a["id"]: "viewer", b["id"]: "owner"}


def test_removed_member_loses_only_that_workspace_immediately(client, world):
    hs, a, b = world
    admin_id = uid(client, hs["a_admin"])
    assert client.get(f"/workspaces/{a['id']}", headers=hs["a_admin"]).status_code == 200
    assert client.delete(f"/workspaces/{a['id']}/members/{admin_id}", headers=hs["a_owner"]).status_code == 204
    assert client.get(f"/workspaces/{a['id']}", headers=hs["a_admin"]).status_code == 404
    assert client.get(f"/workspaces/{a['id']}/credentials", headers=hs["a_admin"]).status_code == 404
    assert client.get(f"/workspaces/{b['id']}", headers=hs["dual"]).status_code == 200


def test_deactivated_workspace_and_user_are_cut_off(client, db_session, world):
    hs, a, b = world
    db_session.execute(update(Workspace).where(Workspace.id == a["id"]).values(is_active=False))
    db_session.commit()
    assert client.get(f"/workspaces/{a['id']}", headers=hs["a_owner"]).status_code == 404
    assert client.get(f"/workspaces/{b['id']}", headers=hs["b_owner"]).status_code == 200
    db_session.execute(update(User).where(User.email == "b_owner@x.com").values(is_active=False))
    db_session.commit()
    assert client.get(f"/workspaces/{b['id']}", headers=hs["b_owner"]).status_code == 401


def test_role_escalation_attempts_fail_and_change_nothing(client, db_session, world):
    hs, a, b = world
    member_id, admin_id = uid(client, hs["a_member"]), uid(client, hs["a_admin"])
    owner_id = uid(client, hs["a_owner"])
    attempts = (("a_member", member_id, "owner"), ("a_member", member_id, "admin"),
                ("a_admin", member_id, "owner"), ("a_admin", owner_id, "viewer"), ("a_admin", admin_id, "owner"))
    for who, target, role in attempts:
        r = client.patch(f"/workspaces/{a['id']}/members/{target}", json={"role": role}, headers=hs[who])
        assert r.status_code in (403, 409, 422), (who, role, r.text)
    roles = {m.user_id: m.role for m in db_session.scalars(select(Membership).where(Membership.workspace_id == a["id"]))}
    assert roles[member_id] == Role.MEMBER and roles[admin_id] == Role.ADMIN and roles[owner_id] == Role.OWNER
    assert client.delete(f"/workspaces/{a['id']}/members/{owner_id}", headers=hs["a_admin"]).status_code in (403, 409)


def test_user_in_only_one_workspace_cannot_touch_the_other_via_membership_calls(client, db_session, world):
    hs, a, b = world
    outsider_id = uid(client, hs["b_owner"])
    r = client.post(f"/workspaces/{a['id']}/members", json={"email": "b_owner@x.com", "role": "owner"}, headers=hs["b_owner"])
    assert r.status_code == 404
    assert db_session.scalar(select(Membership).where(Membership.workspace_id == a["id"], Membership.user_id == outsider_id)) is None


# ============================================================ secrets never leak
def test_secrets_never_reach_logs_or_error_bodies(client, caplog, rig, world):
    hs, a, b = world
    caplog.set_level(logging.DEBUG)
    cid = add_cred(client, hs["a_owner"], a, key=KEY_A)
    client.post(f"/workspaces/{a['id']}/credentials/{cid}/test", headers=hs["a_owner"])
    rot = client.post(f"/workspaces/{a['id']}/credentials/{cid}/rotate", json={"secret": "rotated-secret-key-A2"}, headers=hs["a_owner"])
    run(rig, "a_owner@x.com", a)
    bad = client.post(f"/workspaces/{b['id']}/credentials/{cid}/rotate", json={"secret": "attacker-secret-key"}, headers=hs["b_owner"])
    client.delete(f"/workspaces/{a['id']}/credentials/{cid}", headers=hs["a_owner"])
    run(rig, "a_owner@x.com", a)
    for needle in (KEY_A, "rotated-secret-key-A2", "attacker-secret-key"):
        assert needle not in caplog.text, needle
        assert needle not in rot.text and needle not in bad.text
