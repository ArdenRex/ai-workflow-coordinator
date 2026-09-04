"""add password reset token fields to users

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-04 00:00:00.000000

Adds:
  - users.reset_token          → random URL-safe token emailed to the user
  - users.reset_token_expires  → token expiry (1 hour from issue)

Used by POST /auth/forgot-password and POST /auth/reset-password.
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('reset_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('reset_token_expires', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_users_reset_token', 'users', ['reset_token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_reset_token', table_name='users')
    op.drop_column('users', 'reset_token_expires')
    op.drop_column('users', 'reset_token')
