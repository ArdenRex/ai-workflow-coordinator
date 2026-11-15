import pytest
from sqlalchemy import select

from app.models.enums import Role
from app.models.identity import Membership, Workspace
from app.models.kernel import SystemEvent
from tests.test_auth_api import PW


def signup(client, email):
    assert client.post("/auth/register", json={"email": email, "password": PW}).status_code == 201
    tok = client.post("/auth/login", json={"email": email, "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def uid(client, h):
    return client.get("/auth/me", headers=h).json()["id"]


def mkws(client, h, name="Acme Corp", **kw):
    r = client.post("/workspaces", json={"name": name, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def team(client):
    """owner + admin + member + viewer + outsider, one workspace."""
    hs = {n: signup(client, f"{n}@x.com") for n in ("owner", "admin", "member", "viewer", "outsider")}
    ws = mkws(client, hs["owner"])
    for n, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
        r = client.post(f"/workspaces/{ws['id']}/members", json={"email": f"{n}@x.com", "role": role},
                        headers=hs["owner"])
        assert r.status_code == 201, r.text
    return hs, ws


def test_create_workspace_makes_creator_owner_and_audits(client, db_session):
    h = signup(client, "a@x.com")
    ws = mkws(client, h, "  Acme Corp ")
    assert ws["role"] == "owner" and ws["slug"] == "acme-corp" and ws["name"] == "Acme Corp"
    ev = db_session.scalars(select(SystemEvent).where(SystemEvent.workspace_id == ws["id"])).all()
    assert [e.event_type for e in ev] == ["workspace.created"] and ev[0].actor == uid(client, h)


def test_slug_rules(client):
    h, h2 = signup(client, "a@x.com"), signup(client, "b@x.com")
    mkws(client, h, slug="acme")
    assert client.post("/workspaces", json={"name": "N", "slug": "acme"}, headers=h2).status_code == 409
    assert client.post("/workspaces", json={"name": "N", "slug": "Bad Slug!"}, headers=h2).status_code == 422
    assert client.post("/workspaces", json={"name": "   "}, headers=h2).status_code == 422
    a, b = mkws(client, h, "Same Name"), mkws(client, h2, "Same Name")      # generated slugs never collide
    assert a["slug"] != b["slug"]
    assert mkws(client, h, "!!!")["slug"].startswith("workspace")


def test_requires_auth(client):
    assert client.post("/workspaces", json={"name": "x"}).status_code == 401
    assert client.get("/workspaces").status_code == 401
    assert client.get("/workspaces/abc").status_code == 401


def test_list_only_my_workspaces(client):
    a, b = signup(client, "a@x.com"), signup(client, "b@x.com")
    wa, _ = mkws(client, a, "A"), mkws(client, b, "B")
    assert [w["id"] for w in client.get("/workspaces", headers=a).json()] == [wa["id"]]


def test_context_shows_role_and_permissions(client, team):
    hs, ws = team
    r = client.get(f"/workspaces/{ws['id']}", headers=hs["viewer"]).json()
    assert r["role"] == "viewer" and "task:write" not in r["permissions"] and "task:read" in r["permissions"]
    assert client.get(f"/workspaces/{ws['id']}", headers=hs["owner"]).json()["permissions"] == ["*"]


def test_non_member_and_unknown_workspace_look_identical(client, team):
    hs, ws = team
    a = client.get(f"/workspaces/{ws['id']}", headers=hs["outsider"])
    b = client.get("/workspaces/does-not-exist", headers=hs["outsider"])
    assert a.status_code == b.status_code == 404 and a.json() == b.json()
    assert client.get(f"/workspaces/{ws['id']}/members", headers=hs["outsider"]).status_code == 404
    assert client.post(f"/workspaces/{ws['id']}/members", json={"email": "outsider@x.com"},
                       headers=hs["outsider"]).status_code == 404


def test_member_management_requires_permission(client, team):
    hs, ws = team
    for who in ("member", "viewer"):
        r = client.post(f"/workspaces/{ws['id']}/members", json={"email": "outsider@x.com"}, headers=hs[who])
        assert r.status_code == 403
    assert client.get(f"/workspaces/{ws['id']}/members", headers=hs["viewer"]).status_code == 200


def test_list_members(client, team):
    hs, ws = team
    rows = client.get(f"/workspaces/{ws['id']}/members", headers=hs["member"]).json()
    assert {r["email"]: r["role"] for r in rows} == {"owner@x.com": "owner", "admin@x.com": "admin",
                                                     "member@x.com": "member", "viewer@x.com": "viewer"}


def test_admin_cannot_grant_owner_or_touch_owner(client, team):
    hs, ws = team
    base = f"/workspaces/{ws['id']}/members"
    assert client.post(base, json={"email": "outsider@x.com", "role": "owner"}, headers=hs["admin"]).status_code == 403
    assert client.patch(f"{base}/{uid(client, hs['member'])}", json={"role": "owner"},
                        headers=hs["admin"]).status_code == 403
    owner_id = uid(client, hs["owner"])
    assert client.patch(f"{base}/{owner_id}", json={"role": "viewer"}, headers=hs["admin"]).status_code == 403
    assert client.delete(f"{base}/{owner_id}", headers=hs["admin"]).status_code == 403
    r = client.post(base, json={"email": "outsider@x.com", "role": "member"}, headers=hs["admin"])
    assert r.status_code == 201 and r.json()["role"] == "member"


def test_last_owner_cannot_leave_or_be_demoted(client, team):
    hs, ws = team
    base, oid = f"/workspaces/{ws['id']}/members", uid(client, hs["owner"])
    assert client.patch(f"{base}/{oid}", json={"role": "admin"}, headers=hs["owner"]).status_code == 409
    assert client.delete(f"{base}/{oid}", headers=hs["owner"]).status_code == 409
    client.patch(f"{base}/{uid(client, hs['admin'])}", json={"role": "owner"}, headers=hs["owner"])
    assert client.patch(f"{base}/{oid}", json={"role": "admin"}, headers=hs["owner"]).status_code == 200


def test_removed_member_loses_access_and_can_be_readded(client, team):
    hs, ws = team
    base, vid = f"/workspaces/{ws['id']}/members", uid(client, hs["viewer"])
    assert client.delete(f"{base}/{vid}", headers=hs["admin"]).status_code == 204
    assert client.get(f"/workspaces/{ws['id']}", headers=hs["viewer"]).status_code == 404
    assert client.delete(f"{base}/{vid}", headers=hs["admin"]).status_code == 404
    r = client.post(base, json={"email": "viewer@x.com", "role": "member"}, headers=hs["owner"])
    assert r.status_code == 201 and r.json()["role"] == "member"
    assert client.get(f"/workspaces/{ws['id']}", headers=hs["viewer"]).json()["role"] == "member"


def test_add_member_errors(client, team):
    hs, ws = team
    base = f"/workspaces/{ws['id']}/members"
    assert client.post(base, json={"email": "member@x.com"}, headers=hs["owner"]).status_code == 409
    assert client.post(base, json={"email": "ghost@x.com"}, headers=hs["owner"]).status_code == 404
    assert client.post(base, json={"email": "outsider@x.com", "role": "superuser"}, headers=hs["owner"]).status_code == 422


def test_membership_in_one_workspace_grants_nothing_in_another(client, team):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other")
    assert client.get(f"/workspaces/{other['id']}", headers=hs["owner"]).status_code == 404
    assert client.get(f"/workspaces/{other['id']}/members", headers=hs["admin"]).status_code == 404
    uid_member = uid(client, hs["member"])
    assert client.patch(f"/workspaces/{other['id']}/members/{uid_member}", json={"role": "admin"},
                        headers=hs["owner"]).status_code == 404


def test_inactive_workspace_is_invisible(client, team, db_session):
    hs, ws = team
    db_session.get(Workspace, ws["id"]).is_active = False
    db_session.commit()
    assert client.get(f"/workspaces/{ws['id']}", headers=hs["owner"]).status_code == 404
    assert client.get("/workspaces", headers=hs["owner"]).json() == []


def test_member_changes_are_audited_without_pii(client, team, db_session):
    hs, ws = team
    types = [e.event_type for e in db_session.scalars(
        select(SystemEvent).where(SystemEvent.workspace_id == ws["id"]).order_by(SystemEvent.created_at))]
    assert types == ["workspace.created"] + ["member.added"] * 3
    assert "@" not in str([e.payload for e in db_session.scalars(select(SystemEvent))])
