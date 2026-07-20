"""add slug column to freelancers

Revision ID: add_freelancer_slug
Revises: 0002
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa


# ── Identifiers ───────────────────────────────────────────────────────────────
revision = "add_freelancer_slug"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add slug column (nullable so existing rows don't break) — idempotent,
    # safe to re-run if a concurrent cold-start instance already did this.
    op.execute("ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS slug VARCHAR(255)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_freelancers_slug ON freelancers (slug)")

    # Back-fill slugs for existing freelancers using their name
    op.execute("""
        UPDATE freelancers
        SET slug = LOWER(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(TRIM(name), '[^\\w\\s-]', '', 'g'),
                    '[\\s_]+', '-', 'g'
                ),
                '-+', '-', 'g'
            )
        )
        WHERE slug IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_freelancers_slug")
    op.execute("ALTER TABLE freelancers DROP COLUMN IF EXISTS slug")
