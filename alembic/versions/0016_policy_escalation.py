"""policy escalation rule

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('escalation', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.drop_column('escalation')
