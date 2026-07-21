"""add missing taskstatus_enum values (to_do, active)

Revision ID: 0005
Revises: add_freelancer_slug
Create Date: 2026-07-21 00:00:00.000000

app/models.py defines TaskStatus with 6 members (to_do, pending, active,
in_progress, completed, cancelled), but migration 0001 only created the
Postgres enum with 4 of them (pending, in_progress, completed, cancelled).
This adds the two that were missing, which is what caused
"invalid input value for enum taskstatus_enum: to_do" in /admin/metrics.
"""
from alembic import op

revision = '0005'
down_revision = 'add_freelancer_slug'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'to_do'")
    op.execute("ALTER TYPE taskstatus_enum ADD VALUE IF NOT EXISTS 'active'")


def downgrade() -> None:
    # Postgres does not support removing enum values directly.
    # A downgrade would require recreating the type and remapping any rows
    # using the two new values, which is out of scope for this migration.
    pass
