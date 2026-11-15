import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Membership, Role, User, Workspace


def user(db, email="a@x.com"):
    u = User(email=email, password_hash="h")
    db.add(u)
    db.flush()
    return u


def ws(db, slug="acme", name="Acme", by=None):
    w = Workspace(name=name, slug=slug, created_by=by)
    db.add(w)
    db.flush()
    return w


def test_user_roundtrip_and_defaults(db_session):
    u = user(db_session)
    db_session.commit()
    assert len(u.id) == 36 and u.is_active is True and u.created_at and u.last_login_at is None


def test_email_normalized_and_case_insensitive_unique(db_session):
    u = user(db_session, "  Boss@Example.COM ")
    assert u.email == "boss@example.com"
    db_session.add(User(email="BOSS@example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("bad", ["", "nope", "a@b", "a b@c.com", "@x.com"])
def test_invalid_emails_rejected(bad):
    with pytest.raises(ValueError):
        User(email=bad)


def test_db_check_blocks_uppercase_email_bypassing_validator(db_session):
    with pytest.raises(IntegrityError):
        db_session.execute(text("insert into users (id,email,is_active,created_at,updated_at) "
                                "values ('x','UP@X.COM',true,'2026-01-01','2026-01-01')"))
    db_session.rollback()


@pytest.mark.parametrize("bad", ["", "a", "-bad", "Has Space", "a/b", "x" * 80])
def test_invalid_slugs_rejected(bad):
    with pytest.raises(ValueError):
        Workspace(name="n", slug=bad)


def test_workspace_slug_unique_and_name_required(db_session):
    ws(db_session)
    db_session.add(Workspace(name="Other", slug="acme"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    with pytest.raises(ValueError):
        Workspace(name="  ", slug="ok-slug")


def test_membership_links_and_default_role(db_session):
    u, w = user(db_session), None
    w = ws(db_session, by=u.id)
    m = Membership(workspace_id=w.id, user_id=u.id)
    db_session.add(m)
    db_session.commit()
    assert m.role == Role.MEMBER and m.is_active and w.memberships[0].user.email == "a@x.com"


def test_one_membership_per_user_per_workspace(db_session):
    u, w = user(db_session), None
    w = ws(db_session)
    db_session.add(Membership(workspace_id=w.id, user_id=u.id, role=Role.OWNER))
    db_session.flush()
    db_session.add(Membership(workspace_id=w.id, user_id=u.id, role=Role.ADMIN))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_same_user_can_join_multiple_workspaces(db_session):
    u = user(db_session)
    for slug in ("one", "two"):
        db_session.add(Membership(workspace_id=ws(db_session, slug=slug).id, user_id=u.id))
    db_session.commit()
    assert len(u.memberships) == 2


def test_foreign_keys_enforced_and_no_cascade_delete(db_session):
    db_session.add(Membership(workspace_id="nope", user_id="nope"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    u = user(db_session)
    w = ws(db_session)
    db_session.add(Membership(workspace_id=w.id, user_id=u.id))
    db_session.commit()
    db_session.delete(u)
    with pytest.raises(IntegrityError):         # deactivate users, never delete them
        db_session.commit()
    db_session.rollback()


def test_invalid_role_rejected(db_session):
    u, w = user(db_session), None
    w = ws(db_session)
    db_session.add(Membership(workspace_id=w.id, user_id=u.id, role="superadmin"))
    with pytest.raises(Exception):
        db_session.flush()
    db_session.rollback()
