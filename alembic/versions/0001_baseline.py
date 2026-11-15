"""baseline

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline: establishes the migration chain. Business tables arrive in
    # later steps (execution kernel, tenancy, ...), each as its own revision.
    pass


def downgrade() -> None:
    pass
