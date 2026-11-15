"""auth_events: account activity (register, login, logout, password change)

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auth_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_auth_events_user_id'), 'auth_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_auth_events_created_at'), 'auth_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_events_created_at'), table_name='auth_events')
    op.drop_index(op.f('ix_auth_events_user_id'), table_name='auth_events')
    op.drop_table('auth_events')
