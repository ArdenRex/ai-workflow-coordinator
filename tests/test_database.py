from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import Settings
from app.database import Base, build_engine, check_database
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


def _engine():
    return build_engine(Settings(app_env="test", database_url="sqlite:///:memory:"))


def test_engine_connects():
    assert check_database(_engine()) is True


def test_check_database_false_on_bad_engine():
    from sqlalchemy import create_engine
    assert check_database(create_engine("sqlite:////nonexistent_dir/x.db")) is False


def test_mixins_populate_id_and_timestamps():
    from sqlalchemy.orm import Session

    class Thing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
        __tablename__ = "_test_things"
        name: Mapped[str] = mapped_column()

    eng = _engine()
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        t = Thing(name="a")
        s.add(t)
        s.commit()
        assert len(t.id) == 36 and t.created_at and t.updated_at
    Base.metadata.drop_all(eng)
    Base.metadata.remove(Thing.__table__)


def test_alembic_single_head_and_upgrade_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path/'m.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
    command.upgrade(cfg, "head")
    eng = build_engine(Settings(app_env="test", database_url=url))
    assert "alembic_version" in inspect(eng).get_table_names()
    with eng.connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == "0020"
    command.downgrade(cfg, "base")


def test_ready_endpoint(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["database"] is True
