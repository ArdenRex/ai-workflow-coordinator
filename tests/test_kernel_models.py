import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database import Base, build_engine
from app.models import (Approval, ApprovalStatus, ExecutionStatus, RiskLevel,
                        SystemEvent, ToolExecution)

pytestmark = pytest.mark.usefixtures("seed_workspaces")


def _exec(ws="w1", key=None, **kw):
    return ToolExecution(workspace_id=ws, tool_id="aceden.customer.read", requested_by="u1",
                         risk_level=RiskLevel.LOW, input={"id": 1}, idempotency_key=key, **kw)


def test_execution_roundtrip_defaults(db_session):
    e = _exec()
    db_session.add(e)
    db_session.commit()
    assert e.status == ExecutionStatus.PENDING
    assert e.input == {"id": 1} and e.output is None


def test_approval_and_event_link_to_execution(db_session):
    e = _exec()
    db_session.add(e)
    db_session.flush()
    a = Approval(workspace_id="w1", execution_id=e.id, requested_by="u1")
    ev = SystemEvent(workspace_id="w1", event_type="execution.created", execution_id=e.id,
                     payload={"tool": e.tool_id})
    db_session.add_all([a, ev])
    db_session.commit()
    assert a.status == ApprovalStatus.PENDING
    assert e.approvals[0].id == a.id
    assert ev.created_at is not None


def test_idempotency_key_unique_within_workspace(db_session):
    db_session.add(_exec(key="k1"))
    db_session.commit()
    db_session.add(_exec(key="k1"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_idempotency_key_allowed_across_workspaces(db_session):
    db_session.add_all([_exec(ws="w1", key="k1"), _exec(ws="w2", key="k1")])
    db_session.commit()


def test_invalid_status_string_rejected(db_session):
    e = _exec()
    e.status = "bogus"
    db_session.add(e)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_migrations_match_models_no_drift(tmp_path):
    url = f"sqlite:///{tmp_path/'d.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    eng = build_engine(Settings(app_env="test", database_url=url))
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
