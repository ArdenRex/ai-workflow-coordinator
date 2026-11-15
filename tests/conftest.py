"""Shared test fixtures. Every test gets an isolated in-memory database."""
import os

os.environ["APP_ENV"] = "test"
# TEST_DATABASE_URL (14.2) runs the suite against a real server database, e.g. postgresql+psycopg://postgres@127.0.0.1:5433/aceden_test.
# The database must be empty and disposable: its tables are created once and TRUNCATED after every test.
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:"
os.environ["DATABASE_URL"] = TEST_DB_URL

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (register tables on Base.metadata)
from app.config import Settings
from app.database import Base, build_engine, get_db
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", database_url=TEST_DB_URL, _env_file=None)


@pytest.fixture
def engine(settings):
    eng = build_engine(settings)
    if TEST_DB_URL.startswith("sqlite"):
        Base.metadata.create_all(eng)
        yield eng
        Base.metadata.drop_all(eng)
    else:
        from sqlalchemy import text
        Base.metadata.create_all(eng)                       # checkfirst: a no-op after the first test
        yield eng
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        with eng.begin() as conn:
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Session:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app(settings, db_session):
    application = create_app(settings)
    application.dependency_overrides[get_db] = lambda: db_session
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seed_workspaces(db_session):
    """Kernel tables now FK to workspaces; kernel-level tests use fixed ids w1..w3."""
    from app.models.identity import Workspace
    for i in (1, 2, 3):
        db_session.add(Workspace(id=f"w{i}", name=f"Workspace {i}", slug=f"w-{i}"))
    db_session.commit()
