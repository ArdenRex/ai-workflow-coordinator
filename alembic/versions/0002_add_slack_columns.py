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
    op.add_column('tasks', sa.Column('slack_channel_id', sa.String(length=64), nullable=True))
    op.add_column('tasks', sa.Column('slack_message_ts', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'slack_message_ts')
    op.drop_column('tasks', 'slack_channel_id')
