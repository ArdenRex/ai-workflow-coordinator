import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.credentials_service import CredentialService, CredentialRevokedError
from app.models.credentials import Credential
from app.models.kernel import SystemEvent
from app.security.crypto import DecryptionError
from tests.test_workspaces_api import mkws, signup, uid

SECRET = "sk-super-secret-value-123"


@pytest.fixture
def team(client):
    hs = {n: signup(client, f"{n}@x.com") for n in ("owner", "admin", "member", "viewer", "outsider")}
    ws = mkws(client, hs["owner"])
    for n in ("admin", "member", "viewer"):
        client.post(f"/workspaces/{ws['id']}/members", json={"email": f"{n}@x.com", "role": n}, headers=hs["owner"])
    return hs, ws


def create(client, h, ws, **kw):
    body = {"provider": "aceden", "name": "prod", "secret": SECRET, "config": {"base_url": "https://a.example"}, **kw}
    return client.post(f"/workspaces/{ws['id']}/credentials", json=body, headers=h)


def test_create_never_returns_or_stores_plaintext(client, team, db_session):
    hs, ws = team
    r = create(client, hs["admin"], ws)
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 1 and body["is_active"] and body["config"] == {"base_url": "https://a.example"}
    assert SECRET not in r.text and "ciphertext" not in r.text and "secret" not in body
    row = db_session.get(Credential, body["id"])
    assert SECRET not in row.secret_ciphertext and SECRET not in repr(row)
    dump = " ".join(str(v) for tbl in ("credentials", "system_events") for r_ in
                    db_session.execute(text(f"select * from {tbl}")).all() for v in r_ if "v1." not in str(v))
    assert SECRET not in dump


def test_list_get_never_expose_secret(client, team):
    hs, ws = team
    cid = create(client, hs["owner"], ws).json()["id"]
    for url in (f"/workspaces/{ws['id']}/credentials", f"/workspaces/{ws['id']}/credentials/{cid}"):
        r = client.get(url, headers=hs["admin"])
        assert r.status_code == 200 and SECRET not in r.text and "v1." not in r.text


def test_permissions(client, team):
    hs, ws = team
    for who in ("member", "viewer"):
        assert create(client, hs[who], ws).status_code == 403
        assert client.get(f"/workspaces/{ws['id']}/credentials", headers=hs[who]).status_code == 403
    assert client.get(f"/workspaces/{ws['id']}/credentials", headers=hs["outsider"]).status_code == 404
    assert create(client, hs["outsider"], ws).status_code == 404
    assert client.post(f"/workspaces/{ws['id']}/credentials", json={}).status_code == 401


def test_validation(client, team):
    hs, ws = team
    assert create(client, hs["owner"], ws, provider="Bad Provider!").status_code == 422
    assert create(client, hs["owner"], ws, name="../etc").status_code == 422
    assert create(client, hs["owner"], ws, secret="   ").status_code == 422
    assert create(client, hs["owner"], ws, secret="x" * 5000).status_code == 422
    assert create(client, hs["owner"], ws, config={"api_key": "oops"}).status_code == 422
    assert create(client, hs["owner"], ws, config={"nested": {"a": 1}}).status_code == 422
    assert create(client, hs["owner"], ws, extra="field").status_code == 422


def test_validation_errors_do_not_echo_secret(client, team):
    hs, ws = team
    r = create(client, hs["owner"], ws, provider="Bad Provider!")
    assert SECRET not in r.text


def test_duplicate_name_conflict(client, team):
    hs, ws = team
    assert create(client, hs["owner"], ws).status_code == 201
    assert create(client, hs["owner"], ws).status_code == 409
    assert create(client, hs["owner"], ws, name="staging").status_code == 201


def test_same_name_allowed_in_different_workspaces(client, team):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other")
    assert create(client, hs["owner"], ws).status_code == 201
    assert create(client, hs["outsider"], other).status_code == 201


def test_rotate_changes_secret_and_bumps_version(client, team, db_session):
    hs, ws = team
    cid = create(client, hs["owner"], ws).json()["id"]
    svc = CredentialService(db_session)
    old_ct = db_session.get(Credential, cid).secret_ciphertext
    r = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/rotate", json={"secret": "brand-new-secret-9"},
                    headers=hs["admin"])
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["rotated_at"]
    assert "brand-new-secret-9" not in r.text
    db_session.expire_all()
    assert db_session.get(Credential, cid).secret_ciphertext != old_ct
    assert svc.reveal_secret(ws["id"], cid) == "brand-new-secret-9"


def test_revoke_erases_secret_and_blocks_rotation(client, team, db_session):
    hs, ws = team
    cid = create(client, hs["owner"], ws).json()["id"]
    assert client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["admin"]).status_code == 204
    assert client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["admin"]).status_code == 204  # idempotent
    db_session.expire_all()
    row = db_session.get(Credential, cid)
    assert row.secret_ciphertext is None and not row.is_active and row.revoked_at
    assert client.post(f"/workspaces/{ws['id']}/credentials/{cid}/rotate", json={"secret": "another-secret-1"},
                       headers=hs["owner"]).status_code == 409
    with pytest.raises(CredentialRevokedError):
        CredentialService(db_session).reveal_secret(ws["id"], cid)


def test_cross_workspace_access_is_404(client, team):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other")
    cid = create(client, hs["outsider"], other).json()["id"]
    base = f"/workspaces/{ws['id']}/credentials/{cid}"           # my workspace, their credential id
    assert client.get(base, headers=hs["owner"]).status_code == 404
    assert client.post(base + "/rotate", json={"secret": "hijack-attempt-1"}, headers=hs["owner"]).status_code == 404
    assert client.delete(base, headers=hs["owner"]).status_code == 404


def test_ciphertext_moved_to_another_workspace_fails_authentication(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other")
    a = create(client, hs["owner"], ws).json()["id"]
    b = create(client, hs["outsider"], other).json()["id"]
    db_session.get(Credential, b).secret_ciphertext = db_session.get(Credential, a).secret_ciphertext
    db_session.commit()
    with pytest.raises(DecryptionError):
        CredentialService(db_session).reveal_secret(other["id"], b)


def test_reveal_scoped_by_workspace(client, team, db_session):
    hs, ws = team
    cid = create(client, hs["owner"], ws).json()["id"]
    svc = CredentialService(db_session)
    assert svc.reveal_secret(ws["id"], cid) == SECRET
    from app.credentials_service import CredentialNotFoundError
    with pytest.raises(CredentialNotFoundError):
        svc.reveal_secret("some-other-workspace", cid)


def test_audit_events_have_no_secret(client, team, db_session):
    hs, ws = team
    cid = create(client, hs["owner"], ws).json()["id"]
    client.post(f"/workspaces/{ws['id']}/credentials/{cid}/rotate", json={"secret": "rotated-secret-77"}, headers=hs["owner"])
    client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["owner"])
    evs = db_session.scalars(select(SystemEvent).where(SystemEvent.event_type.like("credential.%"))
                             .order_by(SystemEvent.created_at)).all()
    assert [e.event_type for e in evs] == ["credential.created", "credential.rotated", "credential.revoked"]
    assert evs[0].actor == uid(client, hs["owner"])
    flat = str([e.payload for e in evs])
    assert SECRET not in flat and "rotated-secret-77" not in flat and "v1." not in flat


def test_reencrypt_after_root_key_change(client, team, db_session):
    hs, ws = team
    cid = create(client, hs["owner"], ws).json()["id"]
    cur = get_settings()
    new = cur.model_copy(update={"app_secret_key": "new-root-" + "z" * 40, "app_secret_key_previous": cur.app_secret_key})
    svc = CredentialService(db_session, new)
    assert svc.reveal_secret(ws["id"], cid) == SECRET            # still readable via previous key
    assert svc.reencrypt_all() == 1 and svc.reencrypt_all() == 0
    only_new = CredentialService(db_session, new.model_copy(update={"app_secret_key_previous": ""}))
    assert only_new.reveal_secret(ws["id"], cid) == SECRET        # previous key no longer needed
