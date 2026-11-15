"""policy level-4 auto-execute tools

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_execute_tools', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.drop_column('auto_execute_tools')
