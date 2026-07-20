"""add core tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-16 18:08:06.736195

Every statement in this migration is written to be safe to re-run against
a database in an unknown state. Production's `tasks` table predates this
project's Alembic tracking, so some objects here may already exist outside
of what Alembic recorded — and Vercel's serverless cold starts can run
multiple concurrent instances through this migration at once. IF NOT EXISTS
(and DO-block guards for objects Postgres has no IF NOT EXISTS syntax for,
like constraints) mean none of that can produce an error; each statement
either makes its change or is a safe no-op.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_fk_if_missing(constraint_name: str, alter_sql: str) -> None:
    """Add a FOREIGN KEY constraint only if it doesn't already exist.
    Postgres has no ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS, so this
    checks pg_constraint first (same idempotent-guard pattern used for the
    enum types below)."""
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{constraint_name}'
            ) THEN
                {alter_sql}
            END IF;
        END $$;
    """)


def upgrade() -> None:
    # ── Enums ─────────────────────────────────────────────────────────────────
    op.execute("DO $$ BEGIN CREATE TYPE userrole_enum AS ENUM ('architect', 'navigator', 'operator', 'solo'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE feedbacktype_enum AS ENUM ('bug', 'feedback', 'feature_request'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE feedbackstatus_enum AS ENUM ('new', 'in_review', 'resolved'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # ── Tables without circular FK dependencies ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS freelancer_requests (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            approved_at TIMESTAMPTZ
        );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_freelancer_requests_email ON freelancer_requests (email)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS freelancers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            referral_code VARCHAR(32) NOT NULL,
            label VARCHAR(255),
            is_active BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_freelancers_email ON freelancers (email)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_freelancers_referral_code ON freelancers (referral_code)")
    # NOTE: 'slug' column + ix_freelancers_slug are intentionally NOT created here —
    # the add_freelancer_slug migration (which runs immediately after this one)
    # adds that column and backfills it for existing rows.

    # ── users / workspaces: created without their circular FK first ────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255),
            name VARCHAR(255) NOT NULL,
            role userrole_enum NOT NULL DEFAULT 'operator',
            team_name VARCHAR(255),
            workspace_id INTEGER,
            slack_user_id VARCHAR(64) UNIQUE,
            slack_team_id VARCHAR(64),
            language VARCHAR(10),
            timezone VARCHAR(64),
            currency VARCHAR(8),
            trial_ends_at TIMESTAMPTZ,
            subscription_status VARCHAR(32) NOT NULL DEFAULT 'trialing',
            ls_customer_id VARCHAR(128),
            ls_subscription_id VARCHAR(128),
            referred_by_code VARCHAR(32),
            is_active BOOLEAN NOT NULL,
            is_verified BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_referred_by_code ON users (referred_by_code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            invite_code VARCHAR(16) NOT NULL UNIQUE,
            owner_id INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    _add_fk_if_missing(
        'fk_user_workspace',
        "ALTER TABLE users ADD CONSTRAINT fk_user_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id);",
    )
    _add_fk_if_missing(
        'fk_workspace_owner',
        "ALTER TABLE workspaces ADD CONSTRAINT fk_workspace_owner FOREIGN KEY (owner_id) REFERENCES users(id);",
    )

    # ── Tables depending on users / workspaces ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            name VARCHAR(255) NOT NULL,
            key_hash VARCHAR(128) NOT NULL UNIQUE,
            key_prefix VARCHAR(16) NOT NULL,
            created_by INTEGER REFERENCES users(id),
            is_active BOOLEAN NOT NULL,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_workspace_id ON api_keys (workspace_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            type feedbacktype_enum NOT NULL,
            title VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            page_context VARCHAR(128),
            user_id INTEGER REFERENCES users(id),
            user_email VARCHAR(255),
            user_name VARCHAR(255),
            status feedbackstatus_enum NOT NULL DEFAULT 'new',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_status ON feedback (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_type ON feedback (type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_user_id ON feedback (user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS onboarding_progress (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            slack_connected BOOLEAN NOT NULL,
            slack_connected_at TIMESTAMPTZ,
            first_command_sent BOOLEAN NOT NULL,
            first_command_sent_at TIMESTAMPTZ,
            dashboard_viewed BOOLEAN NOT NULL,
            dashboard_viewed_at TIMESTAMPTZ,
            teammate_invited BOOLEAN NOT NULL,
            teammate_invited_at TIMESTAMPTZ,
            is_completed BOOLEAN NOT NULL,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS teams_channels (
            id SERIAL PRIMARY KEY,
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
            channel_id VARCHAR(255) NOT NULL,
            channel_name VARCHAR(255) NOT NULL,
            service_url VARCHAR(512) NOT NULL,
            conversation_id VARCHAR(512) NOT NULL,
            is_active BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_teams_channels_workspace_id ON teams_channels (workspace_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_settings (
            id SERIAL PRIMARY KEY,
            workspace_id INTEGER NOT NULL UNIQUE REFERENCES workspaces(id),
            keyword_rules JSON,
            high_priority_channels JSON,
            drift_alert_hours INTEGER NOT NULL,
            owner_slack_id VARCHAR(64),
            integration_config JSON,
            default_language VARCHAR(10),
            default_timezone VARCHAR(64),
            default_currency VARCHAR(8),
            teams_tenant_id VARCHAR(128),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    # ── tasks table: new columns for ownership/workspace/sharing ───────────────
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS title VARCHAR(500) NOT NULL DEFAULT 'Untitled task'")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee_id VARCHAR(64)")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS share_token VARCHAR(32)")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id INTEGER")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS workspace_id INTEGER")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pinged_at TIMESTAMPTZ")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_pinged_at TIMESTAMPTZ")
    op.execute("ALTER TABLE tasks ALTER COLUMN task_description DROP NOT NULL")
    op.execute("ALTER TABLE tasks ALTER COLUMN source_message DROP NOT NULL")

    op.execute("DROP INDEX IF EXISTS ix_tasks_assignee")
    op.execute("DROP INDEX IF EXISTS ix_tasks_status")
    op.execute("DROP INDEX IF EXISTS ix_tasks_status_created_at")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_owner_id ON tasks (owner_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tasks_share_token ON tasks (share_token)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_workspace_id ON tasks (workspace_id)")

    _add_fk_if_missing(
        'fk_task_owner',
        "ALTER TABLE tasks ADD CONSTRAINT fk_task_owner FOREIGN KEY (owner_id) REFERENCES users(id);",
    )
    _add_fk_if_missing(
        'fk_task_workspace',
        "ALTER TABLE tasks ADD CONSTRAINT fk_task_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id);",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_task_workspace")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_task_owner")
    op.execute("DROP INDEX IF EXISTS ix_tasks_workspace_id")
    op.execute("DROP INDEX IF EXISTS ix_tasks_share_token")
    op.execute("DROP INDEX IF EXISTS ix_tasks_owner_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_status_created_at ON tasks (status, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks (assignee)")
    op.execute("ALTER TABLE tasks ALTER COLUMN source_message SET NOT NULL")
    op.execute("ALTER TABLE tasks ALTER COLUMN task_description SET NOT NULL")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS owner_pinged_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS pinged_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS owner_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS share_token")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS assignee_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS title")

    op.execute("DROP TABLE IF EXISTS workspace_settings")
    op.execute("DROP INDEX IF EXISTS ix_teams_channels_workspace_id")
    op.execute("DROP TABLE IF EXISTS teams_channels")
    op.execute("DROP TABLE IF EXISTS onboarding_progress")
    op.execute("DROP INDEX IF EXISTS ix_feedback_user_id")
    op.execute("DROP INDEX IF EXISTS ix_feedback_type")
    op.execute("DROP INDEX IF EXISTS ix_feedback_status")
    op.execute("DROP TABLE IF EXISTS feedback")
    op.execute("DROP TYPE IF EXISTS feedbacktype_enum")
    op.execute("DROP TYPE IF EXISTS feedbackstatus_enum")
    op.execute("DROP INDEX IF EXISTS ix_api_keys_workspace_id")
    op.execute("DROP TABLE IF EXISTS api_keys")

    op.execute("ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS fk_workspace_owner")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_user_workspace")
    op.execute("DROP TABLE IF EXISTS workspaces")
    op.execute("DROP INDEX IF EXISTS ix_users_referred_by_code")
    op.execute("DROP INDEX IF EXISTS ix_users_email")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TYPE IF EXISTS userrole_enum")

    op.execute("DROP INDEX IF EXISTS ix_freelancers_referral_code")
    op.execute("DROP INDEX IF EXISTS ix_freelancers_email")
    op.execute("DROP TABLE IF EXISTS freelancers")
    op.execute("DROP INDEX IF EXISTS ix_freelancer_requests_email")
    op.execute("DROP TABLE IF EXISTS freelancer_requests")
