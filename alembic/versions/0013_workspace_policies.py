"""workspace policies

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('workspace_policies',
    sa.Column('workspace_id', sa.String(length=36), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('autonomy_level', sa.Integer(), nullable=False),
    sa.Column('disabled_tools', sa.JSON(), nullable=False),
    sa.Column('approval_required_tools', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('autonomy_level >= 1 AND autonomy_level <= 5', name=op.f('ck_workspace_policies_autonomy_level_valid')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_workspace_policies_version_valid')),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_workspace_policies_updated_by_users')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workspace_policies_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspace_policies')),
    sa.UniqueConstraint('workspace_id', name='uq_workspace_policies_workspace')
    )
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspace_policies_updated_by'), ['updated_by'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('workspace_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspace_policies_updated_by'))
    op.drop_table('workspace_policies')
