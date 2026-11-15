"""Proves the testing foundation: isolation and dependency override."""
import pytest
from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from tests.conftest import TEST_DB_URL


def test_db_session_is_usable(db_session):
    assert db_session.execute(text("select 1")).scalar() == 1


def test_get_db_override_injects_test_session(app, client, db_session):
    seen = {}

    @app.get("/_probe")
    def probe(db: Session = Depends(get_db)):
        seen["same"] = db is db_session
        return {"ok": True}

    assert client.get("/_probe").status_code == 200
    assert seen["same"] is True


def test_sessions_are_isolated_between_tests_a(db_session):
    db_session.execute(text("create table if not exists _iso (x int)"))
    db_session.execute(text("insert into _iso values (1)"))
    db_session.commit()


@pytest.mark.skipif(not TEST_DB_URL.startswith("sqlite"), reason="asserts a fresh in-memory SQLite database; server databases are TRUNCATEd instead")
def test_sessions_are_isolated_between_tests_b(db_session):
    # A fresh in-memory database: the table from test_a must not exist.
    rows = db_session.execute(
        text("select name from sqlite_master where name='_iso'")).fetchall()
    assert rows == []
