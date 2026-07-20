"""initial tasks table

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as pg_ENUM

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every statement below is written to be safe to re-run against a
    # database that already has some/all of these objects — production's
    # `tasks` table predates this migration's tracking, and Vercel's
    # serverless cold starts can race multiple instances through this at
    # once. IF NOT EXISTS everywhere means none of that can produce an error.

    # ── Enums ─────────────────────────────────────────────────────────────────
    op.execute("DO $$ BEGIN CREATE TYPE taskstatus_enum AS ENUM ('pending', 'in_progress', 'completed', 'cancelled'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE priority_enum AS ENUM ('low', 'medium', 'high', 'critical'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # ── Table ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            task_description TEXT NOT NULL,
            assignee VARCHAR(255),
            deadline VARCHAR(100),
            priority priority_enum NOT NULL DEFAULT 'medium',
            source_message TEXT NOT NULL,
            slack_channel_id VARCHAR(64),
            slack_message_ts VARCHAR(64),
            status taskstatus_enum NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    # If tasks already existed from before this migration was tracked, it
    # may be missing columns this migration would otherwise have created.
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS slack_channel_id VARCHAR(64)")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS slack_message_ts VARCHAR(64)")

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_id ON tasks (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks (assignee)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_status_created_at ON tasks (status, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_status_created_at")
    op.execute("DROP INDEX IF EXISTS ix_tasks_assignee")
    op.execute("DROP INDEX IF EXISTS ix_tasks_status")
    op.execute("DROP INDEX IF EXISTS ix_tasks_id")
    op.execute("DROP TABLE IF EXISTS tasks")
    op.execute("DROP TYPE IF EXISTS taskstatus_enum")
    op.execute("DROP TYPE IF EXISTS priority_enum")
