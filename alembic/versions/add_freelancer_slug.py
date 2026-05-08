"""add slug column to freelancers

Revision ID: add_freelancer_slug
Revises: (set to your latest revision id)
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa


# ── Identifiers ───────────────────────────────────────────────────────────────
revision = "add_freelancer_slug"
down_revision = None   # ← replace with your current head revision id
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add slug column (nullable so existing rows don't break)
    op.add_column(
        "freelancers",
        sa.Column("slug", sa.String(255), nullable=True),
    )
    # Create unique index
    op.create_index(
        "ix_freelancers_slug",
        "freelancers",
        ["slug"],
        unique=True,
    )

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
    op.drop_index("ix_freelancers_slug", table_name="freelancers")
    op.drop_column("freelancers", "slug")
