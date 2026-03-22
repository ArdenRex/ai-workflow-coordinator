import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Supabase / Render emit postgres:// — SQLAlchemy 2.x only accepts postgresql://
_raw_url: str = str(settings.database_url)
_db_url: str = _raw_url.replace("postgres://", "postgresql://", 1)

# ── Engine ────────────────────────────────────────────────────────────────────
# NullPool is used when DATABASE_URL points at a connection pooler (e.g. PgBouncer,
# Supabase pooler) that manages its own pool — double-pooling causes "prepared
# statement already exists" errors with pgBouncer in transaction mode.
# For direct connections, swap NullPool for the defaults below.
_pool_kwargs: dict = (
    {"poolclass": NullPool}
    if "pgbouncer" in _db_url or settings.app_env == "production"
    else {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_recycle": 1800,   # recycle connections after 30 min
    }
)

engine = create_engine(
    _db_url,
    pool_pre_ping=True,     # validates connection before checkout
    **_pool_kwargs,
)


# ── Connection health logging ─────────────────────────────────────────────────
@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, connection_record):
    logger.debug("DB connection established: %s", connection_record)


@event.listens_for(engine, "checkout")
def _on_checkout(dbapi_conn, connection_record, connection_proxy):
    logger.debug("DB connection checked out from pool.")


# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,   # avoids lazy-load errors after commit in async contexts
)


# ── ORM base ─────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────
def get_db():
    """
    FastAPI dependency: yields a transactional DB session.
    Rolls back on unhandled exceptions; always closes the session.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Connectivity check (called from lifespan if needed) ───────────────────────
def check_db_connection() -> None:
    """Raises OperationalError if the database is unreachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connectivity check passed.")
    except OperationalError as exc:
        logger.critical("Database connectivity check FAILED: %s", exc)
        raise
