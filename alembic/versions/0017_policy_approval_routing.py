"""policy approval routing

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approval_routing', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.drop_column('approval_routing')
