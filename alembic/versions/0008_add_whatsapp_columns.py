"""add whatsapp business connect columns

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29 00:00:00.000000
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_connected BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id VARCHAR(64)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_waba_id VARCHAR(64)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_display_number VARCHAR(32)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_access_token TEXT")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_whatsapp_phone_number_id "
        "ON users (whatsapp_phone_number_id)"
    )
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS whatsapp_message_id VARCHAR(128)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_whatsapp_message_id ON tasks (whatsapp_message_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_whatsapp_message_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS whatsapp_message_id")
    op.execute("DROP INDEX IF EXISTS uq_users_whatsapp_phone_number_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS whatsapp_access_token")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS whatsapp_display_number")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS whatsapp_waba_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS whatsapp_phone_number_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS whatsapp_connected")
