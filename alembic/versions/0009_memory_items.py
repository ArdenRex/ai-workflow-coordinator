"""memory items

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('memory_items',
    sa.Column('workspace_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.Enum('short_term', 'operational', 'knowledge', 'preference', name='memorykind', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'superseded', 'deleted', 'expired', name='memorystatus', native_enum=False, length=32), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('content_chars', sa.Integer(), nullable=False),
    sa.Column('content_digest', sa.String(length=64), nullable=False),
    sa.Column('dedupe_key', sa.String(length=160), nullable=True),
    sa.Column('source_kind', sa.Enum('user', 'document', 'connector', 'system', 'agent', name='sourcekind', native_enum=False, length=32), nullable=False),
    sa.Column('source_ref', sa.String(length=200), nullable=False),
    sa.Column('source_label', sa.String(length=120), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_user_id', sa.String(length=36), nullable=True),
    sa.Column('scope_ref', sa.String(length=200), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_by_agent', sa.String(length=32), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('lineage_id', sa.String(length=36), nullable=False),
    sa.Column('supersedes_id', sa.String(length=36), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_by', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(kind = 'preference') = (owner_user_id IS NOT NULL)", name=op.f('ck_memory_items_preference_owner')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_memory_items_version_valid')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_memory_items_created_by_users')),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_memory_items_owner_user_id_users')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_memory_items_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory_items')),
    sa.UniqueConstraint('workspace_id', 'dedupe_key', name='uq_memory_workspace_dedupe')
    )
    with op.batch_alter_table('memory_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_memory_items_lineage_id'), ['lineage_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_items_owner_user_id'), ['owner_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_items_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index('ix_memory_workspace_status_kind', ['workspace_id', 'status', 'kind'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('memory_items', schema=None) as batch_op:
        batch_op.drop_index('ix_memory_workspace_status_kind')
        batch_op.drop_index(batch_op.f('ix_memory_items_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_memory_items_owner_user_id'))
        batch_op.drop_index(batch_op.f('ix_memory_items_lineage_id'))

    op.drop_table('memory_items')
