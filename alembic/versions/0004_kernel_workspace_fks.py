"""kernel tables -> workspaces foreign keys

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

TABLES = ("tool_executions", "approvals", "system_events")


def _fk(table: str) -> str:
    return f"fk_{table}_workspace_id_workspaces"


def upgrade() -> None:
    bind = op.get_bind()
    for t in TABLES:   # fail loudly (with a clear message) rather than half-apply on legacy rows
        orphans = bind.execute(sa.text(
            f"SELECT count(*) FROM {t} WHERE workspace_id NOT IN (SELECT id FROM workspaces)")).scalar()
        if orphans:
            raise RuntimeError(f"{t} has {orphans} row(s) whose workspace_id matches no workspace; "
                               "create the workspaces or remove the rows before migrating")
    for t in TABLES:
        with op.batch_alter_table(t) as batch_op:
            batch_op.alter_column("workspace_id", existing_type=sa.String(64), type_=sa.String(36),
                                  existing_nullable=False)
            batch_op.create_foreign_key(op.f(_fk(t)), "workspaces", ["workspace_id"], ["id"])


def downgrade() -> None:
    for t in TABLES:
        with op.batch_alter_table(t) as batch_op:
            batch_op.drop_constraint(op.f(_fk(t)), type_="foreignkey")
            batch_op.alter_column("workspace_id", existing_type=sa.String(36), type_=sa.String(64),
                                  existing_nullable=False)
