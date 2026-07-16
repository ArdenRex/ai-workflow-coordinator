import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Load .env so DATABASE_URL is available even when running alembic directly
from dotenv import load_dotenv
load_dotenv()

# Import your models so Alembic can detect them
from app.database import Base
from app import models  # noqa: F401 — ensures models are registered

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False is required here: this file runs
    # in-process inside the FastAPI lifespan on every cold start
    # (see app/main.py's _run_alembic_upgrade). fileConfig() defaults to
    # disable_existing_loggers=True, which silently sets .disabled = True
    # on every already-created logger not listed in alembic.ini's
    # [loggers] section — including app.main, app.crud, app.database,
    # etc. That killed all app logging (even exc_info=True error logs)
    # for the rest of the process's life after the first startup.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Migrations need a direct/session-mode Postgres connection, not a transaction-
# mode pooler. Supabase's transaction pooler (port 6543, used by DATABASE_URL
# for normal app traffic) is documented as unsuitable for schema migrations —
# other tools (e.g. Prisma) have reported migrations hanging indefinitely over
# it. If DIRECT_DATABASE_URL is set (Supabase dashboard → Project Settings →
# Database → "Direct connection", port 5432), migrations use that instead.
# Falls back to DATABASE_URL so local/dev setups without a separate pooler
# keep working unchanged.
db_url = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
if db_url:
    # Supabase/Render use postgres:// — SQLAlchemy 2.x requires postgresql://
    db_url = db_url.replace("postgres://", "postgresql://", 1)
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
