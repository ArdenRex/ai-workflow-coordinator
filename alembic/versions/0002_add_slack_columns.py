"""add slack columns

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS slack_channel_id VARCHAR(64)")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS slack_message_ts VARCHAR(64)")


def downgrade() -> None:
    op.drop_column('tasks', 'slack_message_ts')
    op.drop_column('tasks', 'slack_channel_id')
