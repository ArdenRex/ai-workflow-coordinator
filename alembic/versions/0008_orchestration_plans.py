"""orchestration plans and steps

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('orchestration_plans',
    sa.Column('workspace_id', sa.String(length=36), nullable=False),
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('status', sa.Enum('pending', 'running', 'succeeded', 'failed', 'cancelled', name='planstatus', native_enum=False, length=32), nullable=False),
    sa.Column('goal_digest', sa.String(length=64), nullable=False),
    sa.Column('goal_chars', sa.Integer(), nullable=False),
    sa.Column('plan_digest', sa.String(length=64), nullable=False),
    sa.Column('step_count', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('step_count >= 1', name=op.f('ck_orchestration_plans_step_count_valid')),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_orchestration_plans_requested_by_users')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_orchestration_plans_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orchestration_plans')),
    sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_orch_plans_workspace_idem')
    )
    with op.batch_alter_table('orchestration_plans', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_orchestration_plans_requested_by'), ['requested_by'], unique=False)
        batch_op.create_index(batch_op.f('ix_orchestration_plans_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index('ix_orch_plans_workspace_status', ['workspace_id', 'status'], unique=False)

    op.create_table('plan_steps',
    sa.Column('plan_id', sa.String(length=36), nullable=False),
    sa.Column('workspace_id', sa.String(length=36), nullable=False),
    sa.Column('step_key', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(length=32), nullable=False),
    sa.Column('instruction_digest', sa.String(length=64), nullable=False),
    sa.Column('instruction_chars', sa.Integer(), nullable=False),
    sa.Column('depends_on', sa.JSON(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'running', 'waiting_approval', 'succeeded', 'failed', 'skipped', 'cancelled', name='stepstate', native_enum=False, length=32), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('position >= 0', name=op.f('ck_plan_steps_position_valid')),
    sa.ForeignKeyConstraint(['plan_id'], ['orchestration_plans.id'], name=op.f('fk_plan_steps_plan_id_orchestration_plans')),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_plan_steps_run_id_agent_runs')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_plan_steps_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_steps')),
    sa.UniqueConstraint('plan_id', 'step_key', name='uq_plan_steps_key'),
    sa.UniqueConstraint('run_id', name='uq_plan_steps_run')
    )
    with op.batch_alter_table('plan_steps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plan_steps_plan_id'), ['plan_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_plan_steps_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('plan_steps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plan_steps_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_plan_steps_plan_id'))
    op.drop_table('plan_steps')
    with op.batch_alter_table('orchestration_plans', schema=None) as batch_op:
        batch_op.drop_index('ix_orch_plans_workspace_status')
        batch_op.drop_index(batch_op.f('ix_orchestration_plans_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_orchestration_plans_requested_by'))
    op.drop_table('orchestration_plans')
