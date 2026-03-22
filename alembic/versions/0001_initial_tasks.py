"""initial tasks table

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enums ─────────────────────────────────────────────────────────────────
    # Create enums explicitly so downgrade can drop them cleanly.
    # checkfirst=True makes re-runs idempotent.
    taskstatus_enum = sa.Enum(
        'pending', 'in_progress', 'completed', 'cancelled',
        name='taskstatus_enum',
    )
    taskstatus_enum.create(op.get_bind(), checkfirst=True)

    priority_enum = sa.Enum(
        'low', 'medium', 'high', 'critical',
        name='priority_enum',
    )
    priority_enum.create(op.get_bind(), checkfirst=True)

    # ── Table ─────────────────────────────────────────────────────────────────
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('task_description', sa.Text(), nullable=False),
        sa.Column('assignee', sa.String(length=255), nullable=True),
        sa.Column('deadline', sa.String(length=100), nullable=True),
        sa.Column(
            'priority',
            sa.Enum('low', 'medium', 'high', 'critical', name='priority_enum'),
            server_default='medium',
            nullable=False,
        ),
        sa.Column('source_message', sa.Text(), nullable=False),
        # Slack traceability — used for deduplication of event retries
        sa.Column('slack_channel_id', sa.String(length=64), nullable=True),
        sa.Column('slack_message_ts', sa.String(length=64), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'in_progress', 'completed', 'cancelled', name='taskstatus_enum'),
            server_default='pending',
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index(op.f('ix_tasks_id'), 'tasks', ['id'], unique=False)
    op.create_index('ix_tasks_status', 'tasks', ['status'], unique=False)
    op.create_index('ix_tasks_assignee', 'tasks', ['assignee'], unique=False)
    op.create_index('ix_tasks_status_created_at', 'tasks', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_tasks_status_created_at', table_name='tasks')
    op.drop_index('ix_tasks_assignee', table_name='tasks')
    op.drop_index('ix_tasks_status', table_name='tasks')
    op.drop_index(op.f('ix_tasks_id'), table_name='tasks')
    op.drop_table('tasks')
    op.execute("DROP TYPE IF EXISTS taskstatus_enum")
    op.execute("DROP TYPE IF EXISTS priority_enum")
