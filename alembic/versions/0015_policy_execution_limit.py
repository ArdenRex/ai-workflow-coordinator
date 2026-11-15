"""policy execution limit

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('execution_limit', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.drop_column('execution_limit')
