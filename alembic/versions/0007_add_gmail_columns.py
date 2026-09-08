"""add gmail connect columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_connected BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_email VARCHAR(255)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_access_token TEXT")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_refresh_token TEXT")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_token_expires_at TIMESTAMPTZ")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gmail_last_checked_at TIMESTAMPTZ")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS gmail_message_id VARCHAR(128)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_gmail_message_id ON tasks (gmail_message_id)")


def downgrade() -> None:
    op.drop_index('ix_tasks_gmail_message_id', table_name='tasks')
    op.drop_column('tasks', 'gmail_message_id')
    op.drop_column('users', 'gmail_last_checked_at')
    op.drop_column('users', 'gmail_token_expires_at')
    op.drop_column('users', 'gmail_refresh_token')
    op.drop_column('users', 'gmail_access_token')
    op.drop_column('users', 'gmail_email')
    op.drop_column('users', 'gmail_connected')
